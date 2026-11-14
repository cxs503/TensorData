"""Profile-driven deterministic checks for CSV-exported physics datasets.

This is an initial, deliberately bounded adapter: it validates CSV field tables.
It does not claim to read arbitrary NetCDF/HDF5/VTK files or prove a simulation
physically correct. Unsupported required checks are reported as inconclusive.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

SUPPORTED_CHECKS = {
    "finite_values",
    "monotonic_axis",
    "unit_consistency",
    "physical_bounds",
    "split_leakage",
}
KNOWN_PLACEHOLDERS = {"", "unknown", "required", "tbd", "n/a", "unspecified"}


class PhysicsProfileError(ValueError):
    """Invalid or unsupported physics validation profile."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _number(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _validate_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise PhysicsProfileError("profile root must be a JSON object")
    for key in ("profile_id", "version", "domain", "variables", "checks", "rights_policy"):
        if key not in profile:
            raise PhysicsProfileError(f"profile.{key} is required")
    if not isinstance(profile["variables"], list) or not profile["variables"]:
        raise PhysicsProfileError("profile.variables must be a non-empty array")
    if not isinstance(profile["checks"], list):
        raise PhysicsProfileError("profile.checks must be an array")
    names: set[str] = set()
    for item in profile["variables"]:
        if not isinstance(item, dict) or not all(k in item for k in ("name", "role", "unit")):
            raise PhysicsProfileError("each variable requires name, role and unit")
        if item["name"] in names:
            raise PhysicsProfileError(f"duplicate variable: {item['name']}")
        names.add(item["name"])
        if "valid_range" in item:
            bounds = item["valid_range"]
            if (not isinstance(bounds, list) or len(bounds) != 2
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(float(v)) for v in bounds)
                    or bounds[0] >= bounds[1]):
                raise PhysicsProfileError(
                    f"variable {item['name']} valid_range must be two finite increasing numbers"
                )
    check_ids: set[str] = set()
    for check in profile["checks"]:
        if not isinstance(check, dict) or not all(
            key in check for key in ("check_id", "kind", "required", "applicability")
        ):
            raise PhysicsProfileError("each check requires check_id, kind, required and applicability")
        if not isinstance(check["check_id"], str) or not check["check_id"].strip():
            raise PhysicsProfileError("check_id must be a non-empty string")
        if check["check_id"] in check_ids:
            raise PhysicsProfileError(f"duplicate check_id: {check['check_id']}")
        check_ids.add(check["check_id"])
        if not isinstance(check["required"], bool):
            raise PhysicsProfileError(f"check {check['check_id']} required must be boolean")
        selected = check.get("variables", [])
        if not isinstance(selected, list) or any(name not in names for name in selected):
            raise PhysicsProfileError(f"check {check['check_id']} references unknown variables")
        if check["kind"] not in SUPPORTED_CHECKS | {
            "boundary_condition", "initial_condition", "conservation",
            "multimodal_alignment",
        }:
            raise PhysicsProfileError(f"unsupported check kind: {check['kind']}")
    if profile["rights_policy"] not in {
        "require_cleared", "allow_internal_restricted", "metadata_only"
    }:
        raise PhysicsProfileError("unsupported rights_policy")
    return profile


def validate_physics_csv(
    csv_path: str | Path,
    profile_path: str | Path,
    *,
    rights_status: str = "unknown",
) -> dict[str, Any]:
    """Validate a CSV field table and return a TensorBench-compatible report."""
    source = Path(csv_path)
    profile_file = Path(profile_path)
    try:
        profile = _validate_profile(json.loads(profile_file.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhysicsProfileError(f"cannot read profile {profile_file}: {exc}") from exc

    digest = _sha256(source)
    evidence_ref = f"file:sha256:{digest}"
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    findings: list[dict[str, Any]] = []
    checks_out: list[dict[str, Any]] = []

    def record(check: dict[str, Any], state: str, detail: str, *, severity: str = "medium") -> None:
        checks_out.append({
            "check_id": check["check_id"],
            "version": profile["version"],
            "method": "deterministic_rule",
            "state": state,
            "required": bool(check["required"]),
            "details": detail,
        })
        if state in {"failed", "inconclusive"}:
            findings.append({
                "finding_id": f"{check['check_id']}:{len(findings) + 1}",
                "check_id": check["check_id"],
                "status": "confirmed" if state == "failed" else "inconclusive",
                "severity": severity if state == "failed" else "info",
                "summary": detail,
                "rationale": detail,
                        "review_state": "unreviewed",
                "limitations": [],
            })

    try:
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise PhysicsProfileError(f"cannot parse dataset CSV: {exc}") from exc
    if not headers or not rows:
        raise PhysicsProfileError("dataset CSV must contain a header and at least one data row")

    declared = {item["name"]: item for item in profile["variables"]}
    missing = [name for name, spec in declared.items() if spec.get("required", True) and name not in headers]
    if missing:
        check = {
            "check_id": "dataset.required_variables",
            "required": True,
        }
        record(check, "failed", f"Required variables missing from CSV: {', '.join(missing)}", severity="high")

    # Every check is explicit. Unsupported physics operations never become a pass.
    for check in profile["checks"]:
        kind = check["kind"]
        variables = check.get("variables") or list(declared)
        applicable = [name for name in variables if name in headers]
        if kind not in SUPPORTED_CHECKS:
            record(check, "inconclusive", f"{kind} is not implemented by the CSV adapter; {check['applicability']}")
            continue
        if kind == "unit_consistency":
            unknown = [
                name for name in variables
                if name not in declared
                or str(declared[name].get("unit", "")).strip().lower() in KNOWN_PLACEHOLDERS
                or str(declared[name].get("unit", "")).strip().lower().startswith("required")
            ]
            if unknown:
                record(check, "inconclusive", f"Units are missing or unresolved for: {', '.join(unknown)}")
            else:
                record(check, "passed", "All selected variables have explicit unit declarations in the profile.")
            continue
        if not applicable:
            record(check, "inconclusive", f"No applicable CSV columns found for {kind}: {variables}")
            continue

        if kind == "finite_values":
            bad: list[str] = []
            for name in applicable:
                for row_number, row in enumerate(rows, start=2):
                    value = row.get(name, "")
                    if _number(value) is None:
                        bad.append(f"{name}@row{row_number}={value!r}")
                        if len(bad) >= 10:
                            break
                if len(bad) >= 10:
                    break
            record(check, "failed" if bad else "passed",
                   "Non-finite or non-numeric values: " + "; ".join(bad) if bad else
                   f"All {len(rows)} rows contain finite numeric values for {applicable}.",
                   severity="high")
        elif kind == "monotonic_axis":
            name = applicable[0]
            values = [_number(row.get(name, "")) for row in rows]
            if any(value is None for value in values):
                record(check, "failed", f"Axis {name} contains non-numeric or non-finite values.", severity="high")
            else:
                # Repeated coordinates are allowed; only decreases violate ordering.
                unique_consecutive = [v for i, v in enumerate(values) if i == 0 or v != values[i - 1]]
                monotonic = all(b > a for a, b in pairwise(unique_consecutive))
                record(check, "passed" if monotonic else "failed",
                       f"Axis {name} is strictly increasing after collapsing adjacent repeats."
                       if monotonic else f"Axis {name} decreases or is not strictly increasing.",
                       severity="high")
        elif kind == "physical_bounds":
            violations: list[str] = []
            for name in applicable:
                bounds = declared.get(name, {}).get("valid_range")
                if not bounds or len(bounds) != 2:
                    continue
                low, high = bounds
                for row_number, row in enumerate(rows, start=2):
                    value = _number(row.get(name, ""))
                    if value is not None and not low <= value <= high:
                        violations.append(f"{name}@row{row_number}={value} outside [{low}, {high}]")
                        if len(violations) >= 10:
                            break
            if not any(declared.get(name, {}).get("valid_range") for name in applicable):
                record(check, "inconclusive", "No valid_range declared for selected variables.")
            else:
                record(check, "failed" if violations else "passed",
                       "; ".join(violations) if violations else "All selected values satisfy declared valid_range.",
                       severity="high")
        elif kind == "split_leakage":
            entity_col = check.get("parameters", {}).get("entity_column", "entity_id")
            split_col = check.get("parameters", {}).get("split_column", "split")
            if entity_col not in headers or split_col not in headers:
                record(check, "inconclusive", f"Leakage check requires columns {entity_col!r} and {split_col!r}.")
            else:
                entity_splits: dict[str, set[str]] = {}
                for row in rows:
                    entity_splits.setdefault(row[entity_col], set()).add(row[split_col])
                leaked = [entity for entity, splits in entity_splits.items() if len(splits) > 1]
                record(check, "failed" if leaked else "passed",
                       f"Entities cross dataset splits: {leaked[:10]}" if leaked else "No entity appears in multiple splits.",
                       severity="high")

    if profile["rights_policy"] == "require_cleared" and rights_status != "cleared":
        record({"check_id": "dataset.rights_cleared", "required": True}, "failed",
               f"Dataset rights_status is {rights_status!r}; profile requires 'cleared'.", severity="critical")

    required_failed = any(c["required"] and c["state"] == "failed" for c in checks_out)
    required_unresolved = any(c["required"] and c["state"] in {"inconclusive", "not_measured"} for c in checks_out)
    overall = "failed" if required_failed else "inconclusive" if required_unresolved else "passed"
    return {
        "schema_version": "0.1.0",
        "product_id": "physics-dataset-validator",
        "product_version": "0.1.0",
        "run_id": f"pdv-{digest[:16]}",
        "created_at": now,
        "input_refs": [str(source.resolve()), str(profile_file.resolve())],
        "input_fingerprints": {"dataset_sha256": digest, "profile_sha256": _sha256(profile_file)},
        "checks": checks_out,
        "findings": findings,
        "evidence_refs": [evidence_ref],
        "overall_status": overall,
        "summary": {"row_count": len(rows), "columns": headers, "rights_status": rights_status},
        "provenance": {
            "input_fingerprints": {"dataset_sha256": digest, "profile_sha256": _sha256(profile_file)},
        },
    }
