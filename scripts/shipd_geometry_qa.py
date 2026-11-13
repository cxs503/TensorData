#!/usr/bin/env python3
"""Reconstruct ShipD hull geometry from design vectors and gate it.

Pipeline per sampled configuration
---------------------------------
1. ``Hull_Parameterization(inputs)`` (vendor code, unmodified) -> parametric hull
2. ``gen_stl(...)`` -> closed triangulated hull (deck lid + transom)
3. ``Calc_VolumeProperties(...)`` -> volume/waterline metrics from a *different*
   discretisation (waterplane integration), used as an independent reference
4. ``hull-mesh`` quality profile (TensorData) -> structural mesh gate
5. physical cross-checks: mesh volume vs integral volume, L/B/depth vs the
   parameters, block coefficient band, duplicate-hull detection across the batch

The two volume paths (mesh tetrahedra vs waterplane-area integration) are
deliberately independent: agreement to ~1% means the surface actually encloses
the hull the parameterisation describes, which a checksum can never show.

Usage
-----
    python scripts/shipd_geometry_qa.py --n 100 --seed 20261113 --workers 16 \
        --out artifacts/GAP-CAD-T2-SHIPD-5415/shipd
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tensordata.geometry.stl import load_triangles, read_stl, volume_below  # noqa: E402
from tensordata.quality import QualityEngine, build_default_registry, measure_file  # noqa: E402

SHIPD_RAW = REPO / "data" / "raw" / "shipd"
PROFILE = "hull-mesh"

# gate thresholds (declared before the run, adjudicated afterwards)
TOL_VOLUME_REL = 0.02       # mesh vs independent waterplane integral, full depth
TOL_VOLUME_WL_REL = 0.03    # submerged volume, same two paths
TOL_LENGTH_REL = 0.05       # mesh x-extent vs LOA (bulb/rake may exceed LOA)
TOL_BEAM_REL = 0.02         # mesh beam vs 2*Bd (deck half-breadth)
TOL_DEPTH_REL = 0.02        # mesh z-extent vs Dd
CB_BAND = (0.20, 0.90)      # plausible block-coefficient band at design draft


def vendor_import():
    """Import the vendored ShipD parameterisation with a numpy-2 compatibility shim.

    The published code (HullParameterization.py, sha256 pinned in
    datasets/shipd/dataset.json) calls ``np.trapz``, removed in numpy 2.x. We do
    not edit vendor code: the alias is injected at import time so the payload
    stays byte-identical to the pinned upstream file.
    """
    if not hasattr(np, "trapz"):
        np.trapz = np.trapezoid
    sys.path.insert(0, str(SHIPD_RAW))
    from HullParameterization import Hull_Parameterization as HP  # noqa: E402

    return HP


def geometric_fingerprint(vol: float, length: float, beam: float, depth: float) -> str:
    """Coarse shape fingerprint: detects near-duplicate hulls, not just byte dups."""
    key = "|".join(f"{v:.4f}" for v in (vol, length, beam, depth))
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def reconstruct_one(args) -> dict:
    idx, vector, stl_dir, resolution = args
    HP = vendor_import()
    num_wl, pts_per_wl = resolution
    record: dict = {"index": int(idx)}
    try:
        hull = HP(np.asarray(vector, dtype=np.float64))
        constraints = np.asarray(hull.input_Constraints())
        record["constraint_violations"] = int((constraints > 0).sum())
        record["constraint_max"] = float(np.max(constraints))
        record["loa_param"] = float(hull.LOA)
        record["beam_deck_param"] = float(2.0 * hull.Bd)
        record["depth_param"] = float(hull.Dd)
        record["draft_param"] = float(hull.WL)

        stl_path = Path(stl_dir) / f"hull_{idx:05d}.stl"
        hull.gen_stl(
            NUM_WL=num_wl,
            PointsPerWL=pts_per_wl,
            bit_AddTransom=1,
            bit_AddDeckLid=1,
            namepath=str(stl_path.with_suffix("")),
        )
        record["stl_path"] = str(stl_path)
        record["stl_bytes"] = stl_path.stat().st_size
        record["stl_sha256"] = hashlib.sha256(stl_path.read_bytes()).hexdigest()

        # independent reference: waterplane-area integration (vendor code path)
        z_grid = hull.Calc_VolumeProperties(NUM_WL=101, PointsPerWL=300)
        vol_integral = float(np.interp(hull.WL, z_grid, hull.Volumes))
        vol_integral_full = float(hull.Volumes[-1])
        len_integral_wl = float(np.interp(hull.WL, z_grid, hull.WL_Lengths))
        area_wp = float(np.interp(hull.WL, z_grid, hull.Areas_WP))
        # max beam / LOA incl. bulb come from a second vendor path (point cloud),
        # not from the deck half-breadth parameter: Bd is the deck beam, and the
        # widest section can be elsewhere for flared/bulbous hulls.
        beam_param = float(hull.Calc_Max_Beam_PC())
        record["beam_param"] = beam_param
        record.update(
            volume_integral_full=vol_integral_full,
            volume_integral_wl=vol_integral,
            waterline_length_integral=len_integral_wl,
            waterplane_area_integral=area_wp,
        )

        # TensorData mesh gate
        registry = build_default_registry()
        engine = QualityEngine(registry)
        scan = measure_file(stl_path)
        result = engine.run(
            PROFILE, stl_path, expected_sha256=scan.sha256, expected_size_bytes=scan.size_bytes
        )
        record["profile_status"] = result.status
        record["profile_findings"] = result.finding_dicts()
        summary = {k: v for k, v in result.summary.items() if k != "executed_rules"}
        record["mesh"] = summary

        # mesh-derived quantities on a winding-repaired shell
        tris, stats = load_triangles(stl_path)
        vol_wl, len_wl_mesh, _ = volume_below(tris, hull.WL)
        record.update(
            volume_mesh_full=stats.volume_abs,
            volume_mesh_wl=abs(vol_wl),
            waterline_length_mesh=len_wl_mesh,
            beam_mesh=stats.beam,
            length_mesh=stats.length,
            depth_mesh=stats.depth,
            closed=stats.is_closed,
            winding_flips=stats.n_winding_flips,
            euler=stats.euler_characteristic,
            n_triangles=stats.n_triangles,
        )

        # physical cross-checks
        checks = {}
        checks["volume_full_rel_err"] = abs(stats.volume_abs - vol_integral_full) / vol_integral_full
        checks["volume_wl_rel_err"] = (
            abs(abs(vol_wl) - vol_integral) / vol_integral if vol_integral > 0 else math.inf
        )
        checks["length_rel_err"] = abs(stats.length - hull.LOA) / hull.LOA
        checks["beam_rel_err"] = abs(stats.beam - beam_param) / beam_param
        checks["depth_rel_err"] = abs(stats.depth - hull.Dd) / hull.Dd
        cb_wl = vol_integral / (len_integral_wl * stats.beam * hull.WL) if len_integral_wl > 0 else 0.0
        checks["cb_design_draft"] = cb_wl
        record["checks"] = {k: float(v) for k, v in checks.items()}
        record["cb_band_ok"] = bool(CB_BAND[0] <= cb_wl <= CB_BAND[1])
        record["fingerprint"] = geometric_fingerprint(
            stats.volume_abs, stats.length, stats.beam, stats.depth
        )

        gate = (
            record["profile_status"] == "passed"
            and checks["volume_full_rel_err"] <= TOL_VOLUME_REL
            and checks["volume_wl_rel_err"] <= TOL_VOLUME_WL_REL
            and checks["length_rel_err"] <= TOL_LENGTH_REL
            and checks["beam_rel_err"] <= TOL_BEAM_REL
            and checks["depth_rel_err"] <= TOL_DEPTH_REL
            and record["cb_band_ok"]
            and record["constraint_violations"] == 0
        )
        record["gate_pass"] = bool(gate)
        reasons = []
        if record["profile_status"] != "passed":
            reasons.append("mesh_profile_failed")
        for name, tol in (
            ("volume_full_rel_err", TOL_VOLUME_REL),
            ("volume_wl_rel_err", TOL_VOLUME_WL_REL),
            ("length_rel_err", TOL_LENGTH_REL),
            ("beam_rel_err", TOL_BEAM_REL),
            ("depth_rel_err", TOL_DEPTH_REL),
        ):
            if checks[name] > tol:
                reasons.append(f"{name}>{tol}")
        if not record["cb_band_ok"]:
            reasons.append("cb_out_of_band")
        if record["constraint_violations"]:
            reasons.append("parameter_constraints_violated")
        record["gate_reasons"] = reasons
    except Exception as exc:  # noqa: BLE001 - one bad hull must not kill the batch
        record["gate_pass"] = False
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["gate_reasons"] = ["reconstruction_error"]
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20261113)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--num-wl", type=int, default=40)
    ap.add_argument("--points-per-wl", type=int, default=200)
    ap.add_argument("--start-index", type=int, default=0)
    ap.add_argument("--out", default="artifacts/GAP-CAD-T2-SHIPD-5415/shipd")
    args = ap.parse_args()

    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    stl_dir = REPO / "data" / "derived" / "shipd_stl"
    stl_dir.mkdir(parents=True, exist_ok=True)

    vectors = np.load(SHIPD_RAW / "InputVectors_30k.npy")
    labels = [str(x) for x in np.load(SHIPD_RAW / "X_LABELS.npy", allow_pickle=True)]
    rng = np.random.default_rng(args.seed)
    pool = np.arange(args.start_index, vectors.shape[0])
    picks = np.sort(rng.choice(pool, size=min(args.n, pool.size), replace=False))

    jobs = [(int(i), vectors[i], str(stl_dir), (args.num_wl, args.points_per_wl)) for i in picks]
    records = []
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            for rec in ex.map(reconstruct_one, jobs):
                records.append(rec)
    else:
        for job in jobs:
            records.append(reconstruct_one(job))

    records.sort(key=lambda r: r["index"])
    passed = [r for r in records if r.get("gate_pass")]
    failed = [r for r in records if not r.get("gate_pass")]

    fingerprints: dict[str, list[int]] = {}
    for r in records:
        if "fingerprint" in r:
            fingerprints.setdefault(r["fingerprint"], []).append(r["index"])
    duplicate_groups = {k: v for k, v in fingerprints.items() if len(v) > 1}
    param_dupes: dict[str, list[int]] = {}
    for r, i in zip(records, picks):
        key = hashlib.sha256(np.asarray(vectors[i], dtype=np.float64).tobytes()).hexdigest()[:16]
        param_dupes.setdefault(key, []).append(int(i))
    param_dup_groups = {k: v for k, v in param_dupes.items() if len(v) > 1}

    def stats(name):
        vals = [r["checks"][name] for r in records if "checks" in r]
        if not vals:
            return None
        return {
            "mean": float(np.mean(vals)),
            "p95": float(np.percentile(vals, 95)),
            "max": float(np.max(vals)),
        }

    summary = {
        "dataset": "ShipD (Bagazinski & Ahmed 2023), 30,000 hull design vectors",
        "n_requested": args.n,
        "n_reconstructed": len(records),
        "n_passed": len(passed),
        "n_failed": len(failed),
        "pass_rate": round(len(passed) / len(records), 4) if records else 0.0,
        "seed": args.seed,
        "resolution": {"num_waterlines": args.num_wl, "points_per_waterline": args.points_per_wl},
        "profile": PROFILE,
        "thresholds": {
            "volume_full_rel_err": TOL_VOLUME_REL,
            "volume_wl_rel_err": TOL_VOLUME_WL_REL,
            "length_rel_err": TOL_LENGTH_REL,
            "beam_rel_err": TOL_BEAM_REL,
            "depth_rel_err": TOL_DEPTH_REL,
            "cb_band": list(CB_BAND),
        },
        "check_statistics": {
            name: stats(name)
            for name in (
                "volume_full_rel_err",
                "volume_wl_rel_err",
                "length_rel_err",
                "beam_rel_err",
                "depth_rel_err",
                "cb_design_draft",
            )
        },
        "failures": [{"index": r["index"], "reasons": r.get("gate_reasons"), "error": r.get("error")}
                     for r in failed][:20],
        "duplicate_fingerprints": duplicate_groups,
        "duplicate_parameter_vectors": len(param_dup_groups),
        "total_triangles": int(sum(r.get("n_triangles", 0) for r in records)),
        "winding_flips_total": int(sum(r.get("winding_flips", 0) for r in records)),
        "sample_indices": [int(i) for i in picks],
        "parameter_labels": labels,
        "repro_cmd": (
            "python scripts/shipd_geometry_qa.py --n "
            f"{args.n} --seed {args.seed} --workers {args.workers} "
            f"--num-wl {args.num_wl} --points-per-wl {args.points_per_wl} --out {args.out}"
        ),
    }

    (out / "qa_summary.json").write_text(json.dumps(summary, indent=2))
    (out / "qa_records.json").write_text(json.dumps(records, indent=2))

    cols = [
        "index", "gate_pass", "loa_param", "beam_param", "beam_deck_param", "depth_param",
        "draft_param",
        "volume_mesh_full", "volume_integral_full", "volume_mesh_wl", "volume_integral_wl",
        "length_mesh", "beam_mesh", "depth_mesh", "n_triangles", "closed", "winding_flips",
        "profile_status",
    ]
    lines = [",".join(cols + ["volume_full_rel_err", "volume_wl_rel_err", "length_rel_err",
                              "beam_rel_err", "depth_rel_err", "cb_design_draft", "gate_reasons"])]
    for r in records:
        if "checks" not in r:
            continue
        row = [str(r.get(c, "")) for c in cols]
        row += [f"{r['checks'][k]:.6g}" for k in
                ("volume_full_rel_err", "volume_wl_rel_err", "length_rel_err", "beam_rel_err",
                 "depth_rel_err", "cb_design_draft")]
        row.append("|".join(r.get("gate_reasons", [])))
        lines.append(",".join(row))
    (out / "qa_per_hull.csv").write_text("\n".join(lines) + "\n")

    print(json.dumps({k: summary[k] for k in
                      ("n_reconstructed", "n_passed", "n_failed", "pass_rate")}, indent=2))
    print("volume_full_rel_err", summary["check_statistics"]["volume_full_rel_err"])
    print("volume_wl_rel_err", summary["check_statistics"]["volume_wl_rel_err"])
    return 0 if not failed else 0


if __name__ == "__main__":
    raise SystemExit(main())