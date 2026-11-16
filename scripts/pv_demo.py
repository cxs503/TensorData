#!/usr/bin/env python3
"""One-command demo of the Physics Dataset Validator (PROD-PV).

This is the *product* entry point, not the mission pilot. It runs the shipped
library surface only:

    tensordata.quality.fields        column/field/unit identification
    tensordata.quality.physics_csv   CSV adapter (+ SI unit resolution)
    tensordata.quality.engine        structure/quality rules

and prints one verdict per CSV plus the measurements the product claims
(identification coverage, review load, baseline comparison, injected-defect
detection, wall clock, deterministic result digest).

Default input is the bundled synthetic fixture ``examples/pv-demo/`` so a third
party can run it with no private data. ``--input-dir`` points it at real data:

    python3 scripts/pv_demo.py
    python3 scripts/pv_demo.py --input-dir path/to/csvs --out-dir artifacts/pv-demo/run

Exit code: 0 = every input file passed, 1 = at least one did not.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tensordata.quality.fields import (  # noqa: E402
    UNKNOWN_RATE_LIMIT,
    build_profile,
    monotonic_axis_within_groups,
    profile_columns_from_file,
)
from tensordata.quality.physics_csv import validate_physics_csv  # noqa: E402
from tensordata.quality.units import get_unit, normalize_unit  # noqa: E402
from tensordata.quality.version import IDENTITY  # noqa: E402

DEFAULT_INPUT_DIR = REPO_ROOT / "examples" / "pv-demo"
AXIS_HINTS = ("Fn", "Fr", "Vs", "V", "Re")


# --------------------------------------------------------------------- helpers
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def suffix_unit(name: str) -> str | None:
    """``Rt_kN`` -> ``kN``; ``V_ms`` -> ``ms``; ``Fn`` -> ``None``."""
    if "_" not in name:
        return None
    tail = name.rsplit("_", 1)[1]
    return tail if tail and not tail.isdigit() else None


def baseline_unit(name: str) -> tuple[str | None, str | None]:
    """The unit a first-cut, case-insensitive suffix lookup resolves to.

    This is the pre-PV-arm behaviour: ``normalize_unit`` lower-cases, so the
    knot suffix ``_kn`` collapses onto the kilonewton key ``kn``.
    """
    suffix = suffix_unit(name)
    if suffix is None:
        return None, None
    key = normalize_unit(suffix)
    unit = get_unit(key)
    return (key, unit.dimension if unit else None)


def detect_group_column(column_report: dict[str, Any], rows: list[dict[str, str]]) -> str | None:
    """A categorical column that repeats down the file (variant-major export)."""
    for entry in column_report["columns"]:
        if entry.get("status") != "not_numeric":
            continue
        distinct = {row.get(entry["column"], "") for row in rows}
        if 1 < len(distinct) < len(rows):
            return entry["column"]
    return None


def detect_axis_column(column_report: dict[str, Any], headers: list[str]) -> str | None:
    numeric = [entry["column"] for entry in column_report["columns"] if entry["kind"] == "numeric"]
    for hint in AXIS_HINTS:
        if hint in numeric:
            return hint
    return numeric[0] if numeric else None


def closure_checks(
    headers: list[str],
    rows: list[dict[str, str]],
    column_report: dict[str, Any],
    density_window: tuple[float, float] = (900.0, 1100.0),
) -> dict[str, Any]:
    """Independent physics identities, computed from the SI-converted columns."""
    factors = {e["column"]: e.get("si_scale") for e in column_report["columns"]
               if e.get("status") == "identified"}

    def series(name: str) -> list[float] | None:
        if name not in factors or factors[name] is None:
            return None
        scale = factors[name]
        out = []
        for row in rows:
            try:
                out.append(float(row[name]) * scale)
            except (TypeError, ValueError):
                return None
        return out

    result: dict[str, Any] = {}
    rt, ct, area, speed = series("Rt_kN") or series("Rt_N"), series("Ct"), series("S"), series("V_ms")
    if speed is None:
        speed = series("V_kn")
    if rt and ct and area and speed:
        densities = [r / (0.5 * c * s * v * v) for r, c, s, v in zip(rt, ct, area, speed)
                     if c and s and v]
        if densities:
            mean = statistics.fmean(densities)
            spread = (max(densities) - min(densities)) / mean if mean else float("inf")
            result["implied_density_kg_m3"] = {
                "mean": mean,
                "relative_spread": spread,
                "inside_window": density_window[0] <= mean <= density_window[1],
            }
    pe = series("Pe_kW")
    if pe and rt and speed:
        deviations = [abs(p - r * v) / abs(p) for p, r, v in zip(pe, rt, speed) if p]
        if deviations:
            result["power_identity_relative_deviation"] = max(deviations)
    v_ms, v_kn = series("V_ms"), series("V_kn")
    if v_ms and v_kn:
        deviations = [abs(a - b) / abs(a) for a, b in zip(v_kn, v_ms) if a]
        if deviations:
            result["speed_cross_column_relative_deviation"] = max(deviations)
    return result


def check_states(report: dict[str, Any]) -> list[dict[str, str]]:
    return [{"check_id": c["check_id"], "state": c["state"], "required": c["required"]}
            for c in report["checks"]]


# ------------------------------------------------------------------ one dataset
def analyse(path: Path, work_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    headers, rows = read_table(path)
    column_report = profile_columns_from_file(path)
    identify_seconds = time.perf_counter() - started

    group = detect_group_column(column_report, rows)
    axis = detect_axis_column(column_report, headers)
    axis_columns = [axis] if axis and not group else []
    profile = build_profile(
        column_report,
        profile_id=f"pv-demo-{path.stem}",
        version=IDENTITY.product_version,
        axis_columns=axis_columns,
    )
    profile_path = work_dir / f"{path.stem}.profile.json"
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    validate_started = time.perf_counter()
    report = validate_physics_csv(path, profile_path)
    validate_seconds = time.perf_counter() - validate_started

    grouped_axis = None
    file_level_axis = None
    verdict = report["overall_status"]
    if axis:
        values = [float(row[axis]) for row in rows]
        file_level_axis = all(b > a for a, b in zip(values, values[1:]))
    if group and axis:
        # A variant-major export restarts the axis per variant, so whole-file
        # monotonicity is the wrong property (PV-EX1 pilot finding). The engine
        # check is therefore evaluated inside each group and recorded explicitly.
        grouped_axis = monotonic_axis_within_groups(rows, axis, group)
        report["checks"].append({
            "check_id": f"dataset.axis_monotonic_within_groups.{axis}",
            "version": profile["version"],
            "method": "deterministic_rule",
            "state": "passed" if grouped_axis["monotonic_within_groups"] else "failed",
            "required": True,
            "details": f"axis {axis} strictly increasing inside each {group} group; "
                       f"whole-file monotonic={file_level_axis}",
        })
        if not grouped_axis["monotonic_within_groups"]:
            verdict = "failed"

    numeric = [e for e in column_report["columns"] if e["kind"] == "numeric"]
    review_required = [e["column"] for e in numeric if e.get("confidence") != "high"]
    baseline = baseline_comparison(column_report, profile, path, work_dir)
    closures = closure_checks(headers, rows, column_report)
    elapsed = time.perf_counter() - started

    return {
        "file": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": len(rows),
        "columns": headers,
        "numeric_columns": len(numeric),
        "identified_columns": column_report["identified_columns"],
        "unknown_columns": column_report["unknown_columns"],
        "unknown_rate": column_report["unknown_rate"],
        "unknown_rate_limit": UNKNOWN_RATE_LIMIT,
        "meets_unknown_limit": column_report["meets_unknown_limit"],
        "group_column": group,
        "axis_column": axis,
        "grouped_axis_monotonic": grouped_axis["monotonic_within_groups"] if grouped_axis else None,
        "file_level_axis_monotonic": file_level_axis,
        "overall_status": report["overall_status"],
        "verdict": verdict,
        "verdict_notes": (
            [f"unknown_columns_present:{','.join(column_report['unknown_columns'])}"
             f" (rate {column_report['unknown_rate']:.4f} <= limit "
             f"{UNKNOWN_RATE_LIMIT}, so the dataset verdict is unchanged; the columns are "
             f"listed in the profile notes and were not range-checked)"]
            if column_report["unknown_columns"] else []),
        "checks": check_states(report),
        "columns_report": [
            {key: e.get(key) for key in ("column", "status", "field", "source_unit",
                                         "canonical_unit", "si_scale", "confidence", "basis")}
            for e in column_report["columns"]
        ],
        "review_required_columns": review_required,
        "automation_rate": (1.0 - len(review_required) / len(numeric)) if numeric else None,
        "closures": closures,
        "baseline": baseline,
        "profile": profile,
        "report": report,
        "timing_seconds": {
            "identify": identify_seconds,
            "validate": validate_seconds,
            "total": elapsed,
        },
    }


def baseline_comparison(column_report: dict[str, Any], profile: dict[str, Any], path: Path,
                        work_dir: Path) -> dict[str, Any]:
    """Compare against the first-cut, case-insensitive suffix lookup."""
    mismatches: list[dict[str, Any]] = []
    baseline_profile = json.loads(json.dumps(profile))
    for entry in column_report["columns"]:
        if entry["kind"] != "numeric" or entry["status"] != "identified":
            continue
        key, dimension = baseline_unit(entry["column"])
        if key is None:
            continue
        pv_dimension = (get_unit(entry["source_unit"]).dimension
                        if get_unit(entry["source_unit"]) else None)
        if dimension != pv_dimension:
            mismatches.append({
                "column": entry["column"],
                "pv_source_unit": entry["source_unit"],
                "pv_dimension": pv_dimension,
                "baseline_unit": key,
                "baseline_dimension": dimension,
            })
    for variable in baseline_profile["variables"]:
        for mismatch in mismatches:
            if variable["name"] == mismatch["column"]:
                variable["source_unit"] = mismatch["baseline_unit"]
    baseline_profile_path = work_dir / f"{path.stem}.baseline.profile.json"
    baseline_profile_path.write_text(json.dumps(baseline_profile, indent=2), encoding="utf-8")
    baseline_report = validate_physics_csv(path, baseline_profile_path)
    return {
        "arm": "case_insensitive_suffix_lookup",
        "mismatched_columns": mismatches,
        "mismatch_count": len(mismatches),
        "verdict": baseline_report["overall_status"],
        "failed_checks": [c["check_id"] for c in baseline_report["checks"] if c["state"] == "failed"],
        "hand_written_profile_fields": 2 * len(profile["variables"]),
        "generated_profile_fields": 0,
    }


# ------------------------------------------------------------------- injections
def run_injections(dataset: dict[str, Any], source: Path, work_dir: Path) -> list[dict[str, Any]]:
    headers, rows = read_table(source)
    profile = dataset["profile"]
    inject_dir = work_dir / "injections"
    inject_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []

    def write_rows(name: str, new_headers: list[str], new_rows: list[dict[str, str]]) -> Path:
        target = inject_dir / name
        with target.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=new_headers)
            writer.writeheader()
            writer.writerows(new_rows)
        return target

    base_profile_path = inject_dir / "base.profile.json"
    base_profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def write_profile(name: str, payload: dict[str, Any]) -> Path:
        target = inject_dir / name
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def evaluate(case: dict[str, Any], dataset_path: Path, profile_path: Path,
                 channel: str) -> None:
        report = validate_physics_csv(dataset_path, profile_path)
        case["verdict"] = report["overall_status"]
        case["detected"] = report["overall_status"] == "failed"
        case["channel"] = channel
        case["failed_checks"] = [c["check_id"] for c in report["checks"] if c["state"] == "failed"]
        cases.append(case)

    # 1. physical range violation (x100) and scale sensitivity (x10)
    target = next((name for name in headers if name.startswith("Rt")), None)
    if target:
        for factor, label in ((100.0, "out_of_range_value"), (10.0, "moderate_scale_error")):
            wide = [{**row, target: f"{float(row[target]) * factor:.6f}"} for row in rows]
            path = write_rows(f"{label}.csv", headers, wide)
            case: dict[str, Any] = {"case": label,
                                    "injection": f"{target} x{factor:g}"}
            evaluate(case, path, base_profile_path, "dataset.physical_bounds")
            closure = closure_checks(headers, read_table(path)[1],
                                     profile_columns_from_file(path))
            density = closure.get("implied_density_kg_m3")
            case["closure_implied_density"] = density
            case["closure_detected"] = bool(density) and not density["inside_window"]
    # 2. unit mislabel inside the profile (force unit on a velocity column)
    mislabelled = json.loads(json.dumps(profile))
    speed_column = next((name for name in headers if name.startswith("V_")), None)
    if speed_column:
        for variable in mislabelled["variables"]:
            if variable["name"] == speed_column:
                variable["source_unit"] = "kn"
        path = write_profile("mislabel.profile.json", mislabelled)
        evaluate({"case": "unit_mislabel_in_profile", "injection": f"{speed_column} -> kn"},
                 source, path, "dataset.units_resolvable")
    # 3. unknown column: rename one identified column so identification must fail
    victim = next((name for name in headers if name.startswith("CF")), None)
    if victim:
        renamed_headers = ["XX_mystery" if name == victim else name for name in headers]
        renamed = [{"XX_mystery" if k == victim else k: v for k, v in row.items()} for row in rows]
        path = write_rows("unknown_column.csv", renamed_headers, renamed)
        report = profile_columns_from_file(path)
        cases.append({
            "case": "unknown_column_gate",
            "injection": f"{victim} -> XX_mystery",
            "verdict": "failed" if not report["meets_unknown_limit"] else "passed",
            "detected": not report["meets_unknown_limit"],
            "channel": "unknown_rate_gate",
            "unknown_rate": report["unknown_rate"],
            "unknown_rate_limit": report["unknown_rate_limit"],
        })
    # 4. non-finite cell
    number_column = next((name for name in headers if name.startswith("Ct")), None)
    if number_column and len(rows) > 1:
        broken = [dict(row) for row in rows]
        broken[0][number_column] = ""
        path = write_rows("missing_cell.csv", headers, broken)
        evaluate({"case": "non_finite_cell", "injection": f"{number_column} row 1 blank"}, path,
                 base_profile_path, "dataset.finite_values")
    return cases


# ------------------------------------------------------------------------ main
def markdown_tables(evidence: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"<!-- generated by scripts/pv_demo.py from {evidence['out_dir']}; do not edit -->")
    lines.append(f"Product: `{evidence['product']['product_id']} "
                 f"{evidence['product']['product_version']}`\n")
    lines.append("### Per-file verdict and identification\n")
    lines.append("| file | rows | numeric cols | identified | unknown | verdict | baseline verdict |")
    lines.append("|---|---|---|---|---|---|---|")
    for item in evidence["datasets"]:
        lines.append(f"| `{item['file']}` | {item['rows']} | {item['numeric_columns']} | "
                     f"{item['identified_columns']} | {len(item['unknown_columns'])} | "
                     f"**{item['verdict']}** | {item['baseline']['verdict']} |")
    lines.append("\n### Physics closures (independent of the profile)\n")
    lines.append("| file | implied density kg/m3 | relative spread | Pe=Rt*V max rel dev | "
                 "V_kn vs V_ms max rel dev |")
    lines.append("|---|---|---|---|---|")
    for item in evidence["datasets"]:
        c = item["closures"]
        density = c.get("implied_density_kg_m3")
        lines.append(
            f"| `{item['file']}` | "
            f"{density['mean']:.4f}" if density else "| `%s` | n/a" % item["file"])
        lines[-1] += (f" | {density['relative_spread']:.3e}" if density else " | n/a")
        lines[-1] += (f" | {c['power_identity_relative_deviation']:.3e}"
                      if "power_identity_relative_deviation" in c else " | n/a")
        lines[-1] += (f" | {c['speed_cross_column_relative_deviation']:.3e} |"
                      if "speed_cross_column_relative_deviation" in c else " | n/a |")
    lines.append("\n### Injected defects\n")
    lines.append("| case | injection | detected | channel | verdict |")
    lines.append("|---|---|---|---|---|")
    for case in evidence["injections"]:
        lines.append(f"| {case['case']} | `{case['injection']}` | **{case['detected']}** | "
                     f"{case['channel']} | {case['verdict']} |")
    lines.append("\n### Latency (seconds, repeated runs)\n")
    lines.append("| repeat | wall total | identify | validate |")
    lines.append("|---|---|---|---|")
    for run in evidence["timing"]["repeats"]:
        lines.append(f"| {run['repeat']} | {run['wall_total']:.3f} | {run['identify']:.3f} | "
                     f"{run['validate']:.3f} |")
    t = evidence["timing"]
    lines.append(f"\nmedian wall = **{t['wall_median']:.3f} s** "
                 f"(min {t['wall_min']:.3f} / max {t['wall_max']:.3f}, "
                 f"n={len(t['repeats'])}), result digest `{evidence['result_digest'][:16]}`\n")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Physics Dataset Validator demo")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--evidence", type=Path, default=None,
                        help="write the six-dimension evidence JSON here")
    parser.add_argument("--tables", type=Path, default=None,
                        help="write generated markdown tables here")
    parser.add_argument("--input-label", default=None,
                        help="label stored in the evidence file instead of the absolute input path "
                             "(use it when the input is not redistributable)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if not args.input_dir.is_dir():
        print(f"error: input dir not found: {args.input_dir}", file=sys.stderr)
        return 2
    csv_files = sorted(args.input_dir.glob("*.csv"))
    if not csv_files:
        print(f"error: no CSV files in {args.input_dir}", file=sys.stderr)
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (REPO_ROOT / "artifacts" / "pv-demo" / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    datasets: list[dict[str, Any]] = []
    injections: list[dict[str, Any]] = []
    repeats: list[dict[str, Any]] = []
    for repeat in range(max(1, args.repeat)):
        run_dir = out_dir / f"repeat{repeat + 1}"
        run_dir.mkdir(parents=True, exist_ok=True)
        wall_start = time.perf_counter()
        for path in csv_files:
            item = analyse(path, run_dir)
            if repeat == 0:
                datasets.append(item)
                if not injections:
                    injections = run_injections(item, path, run_dir)
            (run_dir / f"{path.stem}.report.json").write_text(
                json.dumps(item["report"], indent=2), encoding="utf-8")
        repeats.append({
            "repeat": repeat + 1,
            "wall_total": time.perf_counter() - wall_start,
            "identify": sum(d["timing_seconds"]["identify"] for d in datasets),
            "validate": sum(d["timing_seconds"]["validate"] for d in datasets),
        })

    digest_payload = {
        "product": IDENTITY.as_dict(),
        "datasets": [
            {
                "file": d["file"],
                "sha256": d["sha256"],
                "numeric_columns": d["numeric_columns"],
                "identified_columns": d["identified_columns"],
                "unknown_columns": d["unknown_columns"],
                "verdict": d["verdict"],
                "checks": d["checks"],
                "si_scales": {e["column"]: e["si_scale"] for e in d["columns_report"]
                              if e.get("si_scale") is not None},
                "closures": d["closures"],
            }
            for d in datasets
        ],
        "injections": [{"case": c["case"], "detected": c["detected"]} for c in injections],
    }
    walls = [item["wall_total"] for item in repeats]
    evidence: dict[str, Any] = {
        "product": IDENTITY.as_dict(),
        "input_dir": args.input_label or str(args.input_dir.resolve()),
        "input_class": "bundled_demo_fixture" if args.input_dir.resolve() == DEFAULT_INPUT_DIR.resolve()
                       else "caller_supplied",
        "out_dir": str(out_dir),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "datasets": datasets,
        "injections": injections,
        "timing": {
            "repeats": repeats,
            "wall_median": statistics.median(walls),
            "wall_min": min(walls),
            "wall_max": max(walls),
            "files": len(csv_files),
        },
        "automation": {
            "numeric_columns": sum(d["numeric_columns"] for d in datasets),
            "identified_columns": sum(d["identified_columns"] for d in datasets),
            "review_required_columns": sum(len(d["review_required_columns"]) for d in datasets),
            "cli_interventions_required": 0,
            "manual_profile_fields_written": 0,
        },
        "result_digest": canonical_sha256(digest_payload),
        "command": "python3 scripts/pv_demo.py" + (
            "" if args.input_dir == DEFAULT_INPUT_DIR else f" --input-dir {args.input_dir}"),
    }
    (out_dir / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    tables = markdown_tables(evidence)
    if args.tables:
        args.tables.parent.mkdir(parents=True, exist_ok=True)
        args.tables.write_text(tables, encoding="utf-8")

    if not args.quiet:
        print(f"{IDENTITY.describe()}")
        for item in datasets:
            flag = "*" if item["verdict_notes"] else " "
            print(f"  {item['file']:<28} verdict={item['verdict']:<12}{flag}"
                  f"identified={item['identified_columns']}/{item['numeric_columns']} "
                  f"unknown={len(item['unknown_columns'])} "
                  f"baseline={item['baseline']['verdict']}")
        print(f"  injections detected: {sum(1 for c in injections if c['detected'])}/{len(injections)}")
        print(f"  wall median {evidence['timing']['wall_median']:.3f}s over "
              f"{len(repeats)} run(s); digest {evidence['result_digest'][:16]}")
        print(f"  artifacts: {out_dir}")
    failed = [d["file"] for d in datasets if d["verdict"] != "passed"]
    if failed:
        print(f"FAIL: {', '.join(failed)}", file=sys.stderr)
    print(f"[pv-demo] wall={time.perf_counter() - started:.3f}s")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())