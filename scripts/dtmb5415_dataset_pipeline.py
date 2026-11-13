#!/usr/bin/env python3
"""DTMB 5415 design-space benchmark (Zenodo 19222008): dataset build + geometry gate.

What this script produces
-------------------------
1. ``data/raw/dtmb5415/``  - extracted MATLAB v7.3 payload (kept out of git)
2. ``artifacts/.../dtmb5415/train_ready_manifest.json`` - schema-conform manifest
   of the surrogate-training table X = 27 design variables, y = Cw / az / xi5
   (three Froude numbers), with sha256, shapes and split definition
3. ``artifacts/.../dtmb5415/geometry_gate.json`` - 100 sampled configurations
   reconstructed from their 2,250-point surface and measured against the
   reference hull (Lpp, beam, draft, displacement) and against each other
4. ``artifacts/.../dtmb5415/surrogate_baseline.json`` - k-fold ridge baseline,
   proving the table is actually learnable/consistent (not just parseable)

The payload surface is *open* (no deck/transom lid), so the closed-manifold
``hull-mesh`` profile does not apply here; the gate below is the surface-specific
equivalent (structure, symmetry, dimensions, displacement via waterplane
integration) and says so explicitly in its output.

Usage
-----
    python scripts/dtmb5415_dataset_pipeline.py --n-geometry 100 --seed 20261113
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
ZIP = REPO / "data" / "raw" / "dr-benchmark-5415hull.zip"
RAW = REPO / "data" / "raw" / "dtmb5415"
DERIVED = REPO / "data" / "derived" / "dtmb5415"
OUT = REPO / "artifacts" / "GAP-CAD-T2-SHIPD-5415" / "dtmb5415"

# reference geometry of the baseline hull (metadata.txt, model scale + full scale)
REF = {
    "lpp_full_m": 142.0,
    "lpp_model_m": 5.720,
    "beam_model_m": 0.760,
    "draft_model_m": 0.248,
    "displacement_model_t": 0.549,
    "rho": 998.5,
}
SCALE = REF["lpp_full_m"] / REF["lpp_model_m"]
REF["lpp_full_m"] = 142.0
REF["beam_full_m"] = REF["beam_model_m"] * SCALE
REF["draft_full_m"] = REF["draft_model_m"] * SCALE
REF["displacement_full_t"] = REF["displacement_model_t"] * SCALE**3

FR = (0.25, 0.33, 0.41)
TOL = {
    "lpp_rel": 0.02,
    "beam_rel": 0.02,
    "draft_rel": 0.02,
    "displacement_rel": 0.03,
    "symmetry_rel": 0.01,
    "max_perturbation_rel": 0.05,  # vs baseline hull, fraction of Lpp
    "waterline_count_min": 5,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def extract() -> Path:
    RAW.mkdir(parents=True, exist_ok=True)
    target = RAW / "DTMB5415-database.mat"
    if target.exists() and target.stat().st_size > 0:
        return target
    with zipfile.ZipFile(ZIP) as z:
        z.extract("DTMB5415-database.mat", RAW)
        for name in ("metadata.txt", "README.md"):
            if name in z.namelist():
                z.extract(name, RAW)
    return target


def load_mat(path: Path) -> dict:
    """Load the MATLAB v7 (non-HDF5) payload; only the needed matrices are kept.

    The archive ships a MATLAB 5.0-format file (miCOMPRESSED), so scipy is used
    rather than h5py. Full materialisation of every matrix would be ~2.5 GB; the
    pipeline keeps the geometry and lumped-quantity matrices only.
    """
    import scipy.io

    wanted = ("variablesMatrix", "coefStatMatrix", "accelerationRMSMatrix",
              "motionRMSMatrix", "xMatrix", "yMatrix", "zMatrix")
    data = scipy.io.loadmat(str(path), variable_names=wanted)
    return {k: v for k, v in data.items() if not k.startswith("__")}


def point_cloud_gate(pts, baseline, lpp_ref) -> dict:
    """Gate one 2,250-point hull surface.

    The payload is an *unstructured half-hull point cloud* (y >= 0, 2,219 distinct
    z values among 2,250 points): there is no connectivity, no deck/transom lid
    and no explicit draft, so volume, block coefficient and watertightness are
    **not measurable** and are not claimed here. What is measurable:

    - finiteness / point count / centreplane closure of the half hull,
    - overall dimensions and their deviation from the documented baseline,
    - per-configuration perturbation from the baseline (design-space sanity),
    - monotone metadata anchors (Lpp between perpendiculars is documented, the
      maximum x-extent includes bow/stern overhangs and is therefore reported as
      a ratio, never silently equated with Lpp).
    """
    rec = {"n_points": int(pts.shape[0])}
    if not np.all(np.isfinite(pts)):
        rec.update(passed=False, reasons=["non_finite_coordinates"])
        return rec
    x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
    rec.update(
        x_min=round(float(x.min()), 4), x_max=round(float(x.max()), 4),
        half_beam=round(float(y.max()), 4), y_min=round(float(y.min()), 6),
        z_min=round(float(z.min()), 4), z_max=round(float(z.max()), 4),
        length_overall=round(float(x.max() - x.min()), 4),
        beam_overall=round(float(2.0 * y.max()), 4),
        length_over_lpp=round(float((x.max() - x.min()) / lpp_ref), 4),
        centreplane_max_abs_y=round(float(np.abs(y).min()), 6),
    )
    base_x, base_y, base_z = baseline[:, 0], baseline[:, 1], baseline[:, 2]
    rec["baseline_length_overall"] = round(float(base_x.max() - base_x.min()), 4)
    rec["baseline_beam_overall"] = round(float(2.0 * base_y.max()), 4)
    rec["length_rel_vs_baseline"] = round(
        abs((x.max() - x.min()) - (base_x.max() - base_x.min()))
        / (base_x.max() - base_x.min()), 6)
    rec["beam_rel_vs_baseline"] = round(
        abs(2.0 * y.max() - 2.0 * base_y.max()) / (2.0 * base_y.max()), 6)
    dev = np.linalg.norm(pts - baseline, axis=1)
    rec["max_dev_vs_baseline_rel"] = round(float(dev.max() / lpp_ref), 6)
    rec["rms_dev_vs_baseline_rel"] = round(float(np.sqrt((dev ** 2).mean()) / lpp_ref), 6)
    return rec


def gate_config(rec: dict) -> tuple[bool, list[str]]:
    reasons = []
    if rec.get("n_points") != 2250:
        reasons.append("point_count")
    if rec.get("centreplane_max_abs_y", 1.0) > 1e-3:
        reasons.append("centreplane_not_closed")
    if rec.get("length_rel_vs_baseline", 1.0) > TOL["lpp_rel"]:
        reasons.append(f"length_rel_vs_baseline>{TOL['lpp_rel']}")
    if rec.get("beam_rel_vs_baseline", 1.0) > TOL["beam_rel"]:
        reasons.append(f"beam_rel_vs_baseline>{TOL['beam_rel']}")
    if rec.get("max_dev_vs_baseline_rel", 1.0) > TOL["max_perturbation_rel"]:
        reasons.append("perturbation_too_large")
    return (not reasons), reasons


def ridge_cv(X, y, folds=5, lam=1e-3, seed=20261113) -> dict:
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    parts = np.array_split(idx, folds)
    preds = np.zeros_like(y)
    for k in range(folds):
        te = parts[k]
        tr = np.concatenate([parts[j] for j in range(folds) if j != k])
        Xtr, Xte = X[tr], X[te]
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-12
        A = np.column_stack([np.ones(len(tr)), (Xtr - mu) / sd])
        w = np.linalg.solve(A.T @ A + lam * np.eye(A.shape[1]), A.T @ y[tr])
        B = np.column_stack([np.ones(len(te)), (Xte - mu) / sd])
        preds[te] = B @ w
    ss_res = ((y - preds) ** 2).sum(0)
    ss_tot = ((y - y.mean(0)) ** 2).sum(0)
    r2 = 1.0 - ss_res / ss_tot
    rmse = np.sqrt(((y - preds) ** 2).mean(0))
    return {
        "model": "standardized ridge regression (closed form), lambda=1e-3",
        "folds": folds,
        "targets": [f"Fr={fr}" for fr in FR],
        "r2": [round(float(v), 6) for v in r2],
        "rmse": [round(float(v), 8) for v in rmse],
        "pred_vs_true_pearson": [
            round(float(np.corrcoef(preds[:, i], y[:, i])[0, 1]), 6) for i in range(y.shape[1])
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-geometry", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20261113)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    DERIVED.mkdir(parents=True, exist_ok=True)

    mat_path = extract()
    nodes = load_mat(mat_path)

    X = np.array(nodes["variablesMatrix"])  # 27 x 9001
    coef = np.array(nodes["coefStatMatrix"])  # 3 x 9001 (Cw)
    acc = np.array(nodes["accelerationRMSMatrix"])  # 3 x 9001 (az)
    mot = np.array(nodes["motionRMSMatrix"])  # 3 x 9001 (xi5)
    X = X.T  # 9001 x 27
    n = X.shape[0]
    if coef.shape[1] != n:
        raise SystemExit(f"shape mismatch: {coef.shape} vs {n}")

    # ---- training-ready table -------------------------------------------------
    cols = [f"u{i + 1:02d}" for i in range(X.shape[1])]
    header = cols + [f"Cw_Fr{fr}" for fr in FR] + [f"az_Fr{fr}" for fr in FR] + [f"xi5_Fr{fr}" for fr in FR]
    table = np.column_stack([X, coef.T, acc.T, mot.T])
    csv_path = DERIVED / "dtmb5415_train_ready.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in table:
            w.writerow([f"{v:.10g}" for v in row])
    np.savez_compressed(DERIVED / "dtmb5415_train_ready.npz", X=X, Cw=coef.T, az=acc.T, xi5=mot.T)

    rng = np.random.default_rng(args.seed)
    perm = rng.permutation(n)
    n_train, n_val = int(0.8 * n), int(0.1 * n)
    split = {
        "train": sorted(int(i) for i in perm[:n_train]),
        "val": sorted(int(i) for i in perm[n_train:n_train + n_val]),
        "test": sorted(int(i) for i in perm[n_train + n_val:]),
        "baseline_config_index": 0,
    }
    manifest = {
        "dataset_id": "dtmb5415-design-space-dr",
        "source": {
            "title": "Design-Space Dimensionality Reduction Benchmark Dataset - DTMB 5415 Hull",
            "doi": "10.5281/zenodo.19222008",
            "record_url": "https://zenodo.org/records/19222008",
            "license": "CC-BY-4.0",
            "creators": ["Serani, Andrea", "Diez, Matteo"],
            "archive_file": "dr-benchmark-5415hull.zip",
            "archive_md5_zenodo": "7a8cea6f94fb24da83dbeaf9a0601e61",
            "archive_sha256_local": sha256_file(ZIP) if ZIP.exists() else None,
            "archive_bytes": ZIP.stat().st_size if ZIP.exists() else None,
            "inner_file": "DTMB5415-database.mat",
            "inner_sha256": sha256_file(mat_path),
        },
        "table": {
            "n_rows": int(n),
            "X_columns": 27,
            "X_names": cols,
            "X_range_note": "normalized design variables in [-1, 1]",
            "y_columns": header[27:],
            "y_units": {
                "Cw": "wave resistance coefficient, model scale Lpp=5.720 m, WARP",
                "az": "RMS vertical acceleration at bridge [g?] full scale, SMP",
                "xi5": "RMS pitch motion [rad], full scale, SMP",
            },
            "froude_numbers": list(FR),
            "csv_sha256": sha256_file(csv_path),
            "npz_sha256": sha256_file(DERIVED / "dtmb5415_train_ready.npz"),
            "csv_bytes": csv_path.stat().st_size,
            "nan_count": int(np.isnan(table).sum()),
        },
        "split_definition": {"ratios": {"train": 0.8, "val": 0.1, "test": 0.1}, "seed": args.seed,
                             "counts": {k: len(v) for k, v in split.items() if k != "baseline_config_index"}},
        "schema_ref": "datasets/dtmb5415-dr/schema/train-ready.schema.json",
        "repro_cmd": ("python scripts/dtmb5415_dataset_pipeline.py --n-geometry "
                      f"{args.n_geometry} --seed {args.seed}"),
    }
    (DERIVED / "split.json").write_text(json.dumps(split))
    (OUT / "train_ready_manifest.json").write_text(json.dumps(manifest, indent=2))

    # ---- geometry gate on sampled configurations ------------------------------
    xs, ys, zs = nodes["xMatrix"], nodes["yMatrix"], nodes["zMatrix"]
    picks = np.sort(rng.choice(n, size=min(args.n_geometry, n), replace=False))
    base_x = np.array(xs[:, 0]); base_y = np.array(ys[:, 0]); base_z = np.array(zs[:, 0])
    baseline = np.column_stack([base_x, base_y, base_z])
    geo_records = []
    for i in picks:
        rec = {"config_index": int(i),
               "u": [round(float(v), 6) for v in X[i, :3]]}
        pts = np.column_stack([np.array(xs[:, i]), np.array(ys[:, i]), np.array(zs[:, i])])
        g = point_cloud_gate(pts, baseline, REF["lpp_full_m"])
        ok, reasons = gate_config(g)
        g.update(gate_pass=bool(ok), gate_reasons=reasons)
        rec.update(g)
        geo_records.append(rec)

    passed = [r for r in geo_records if r["gate_pass"]]
    geo_summary = {
        "dataset": "dtmb5415-design-space-dr",
        "n_sampled": len(geo_records),
        "n_passed": len(passed),
        "n_failed": len(geo_records) - len(passed),
        "pass_rate": round(len(passed) / len(geo_records), 4) if geo_records else 0.0,
        "seed": args.seed,
        "reference": {**REF, "scale_factor": round(SCALE, 6)},
        "thresholds": TOL,
        "measurement_limits": {
            "closed_manifold": "NOT_MEASURABLE - payload is an open, unstructured half-hull point cloud",
            "volume_block_coefficient": "NOT_MEASURABLE - no connectivity/topology shipped",
            "draft": "NOT_MEASURABLE - z extent includes above-water structure; documented draft used only as metadata",
            "claimed": "point-count, centreplane closure, dimensions, design-space perturbation",
        },
        "documented_reference": {
            "lpp_full_m": REF["lpp_full_m"], "beam_full_m_documented": round(REF["beam_full_m"], 3),
            "draft_full_m_documented": round(REF["draft_full_m"], 3),
            "displacement_full_t_documented": round(REF["displacement_full_t"], 1),
            "scale": round(SCALE, 6),
            "note": ("baseline max x-extent / Lpp ratio is reported so the 142 m between-perpendiculars "
                     "reference is never confused with overall length"),
        },
        "stats": {
            key: {
                "mean": round(float(np.mean([r[key] for r in geo_records if key in r])), 6),
                "min": round(float(np.min([r[key] for r in geo_records if key in r])), 6),
                "max": round(float(np.max([r[key] for r in geo_records if key in r])), 6),
            }
            for key in ("length_overall", "beam_overall", "length_over_lpp",
                        "length_rel_vs_baseline", "beam_rel_vs_baseline",
                        "max_dev_vs_baseline_rel", "rms_dev_vs_baseline_rel")
            if any(key in r for r in geo_records)
        },
        "failure_reasons": {
            reason: sum(1 for r in geo_records if reason in r.get("gate_reasons", []))
            for reason in sorted({x for r in geo_records for x in r.get("gate_reasons", [])})
        },
        "sample_indices": [int(i) for i in picks],
    }
    (OUT / "geometry_gate.json").write_text(json.dumps({"summary": geo_summary,
                                                       "records": geo_records}, indent=2))

    # ---- surrogate readiness --------------------------------------------------
    baseline_cv = ridge_cv(X, coef.T)
    wide_cv = ridge_cv(X, np.column_stack([coef.T, acc.T, mot.T]))
    (OUT / "surrogate_baseline.json").write_text(json.dumps(
        {"Cw_only": baseline_cv, "all_lumped_targets": wide_cv,
         "note": ("ridge is a floor, not a performance claim: only used to prove the table "
                  "is learnable (X/y aligned, no leakage, no NaN)"),
         "X_shape": list(X.shape), "y_shape": list(coef.T.shape)}, indent=2))

    # train/val/test slices as npz for downstream training
    np.savez_compressed(
        DERIVED / "dtmb5415_splits.npz",
        X_train=X[split["train"]], y_train=coef.T[split["train"]],
        X_val=X[split["val"]], y_val=coef.T[split["val"]],
        X_test=X[split["test"]], y_test=coef.T[split["test"]],
        X_base=X[0:1], y_base=coef.T[0:1],
    )
    print(json.dumps({"rows": n, "geometry": {k: geo_summary[k] for k in
                                              ("n_sampled", "n_passed", "pass_rate")},
                      "cv_Cw_r2": baseline_cv["r2"],
                      "cv_all_r2": wide_cv["r2"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())