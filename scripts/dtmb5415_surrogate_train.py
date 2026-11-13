#!/usr/bin/env python3
"""Train + register the DTMB 5415 lumped-response surrogate (Zenodo 19222008).

Targets (9 columns): Cw (wave resistance coefficient, WARP, model scale), az
(RMS vertical acceleration at bridge, SMP, full scale), xi5 (RMS pitch, SMP),
each at Fr = 0.25 / 0.33 / 0.41.  Inputs: 27 dimensionless design variables of
the DTMB 5415 design space (already normalised to [-1, 1] by the benchmark).

What this produces (all under ``artifacts/GAP-ASSET-MODEL-REGISTRY/``)
  1. ``derived/dtmb5415_train_ready.npz``  X (9001, 27), y (9001, 9), split indices
  2. ``dtmb5415-surrogate/eval_card.json``  per-target held-out error table + ridge baseline
  3. ``dtmb5415-surrogate/metrics.json``, ``loss_history.json``, figures
  4. a registered model asset (weights + eval card + training table) in the
     model registry, bound by weights sha256 and training-table fingerprint

Usage::

    python scripts/dtmb5415_surrogate_train.py \
        --mat /root/ship-data-official/dtmb5415/DTMB5415-database.mat \
        --registry-root models --seed 20261113 --epochs 900
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tensordata.modelreg import ModelRegistry, fingerprint_arrays, sha256_file  # noqa: E402
from tensordata.modelreg import schema as mschema  # noqa: E402

MODEL_ID = "dtmb5415-lumped-surrogate"
VERSION = "1.0.0"
FR = (0.25, 0.33, 0.41)
TARGET_COLUMNS = (
    [f"Cw_Fr{fr:.2f}" for fr in FR]
    + [f"az_Fr{fr:.2f}" for fr in FR]
    + [f"xi5_Fr{fr:.2f}" for fr in FR]
)
DATASET_JSON = REPO / "datasets" / "dtmb5415-dr" / "dataset.json"
DEFAULT_MAT_CANDIDATES = (
    REPO / "data" / "raw" / "dtmb5415" / "DTMB5415-database.mat",
    Path("/root/ship-data-official/dtmb5415/DTMB5415-database.mat"),
)
OUT_ROOT = REPO / "artifacts" / "GAP-ASSET-MODEL-REGISTRY"


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def resolve_mat(path: str | None) -> Path:
    if path:
        candidate = Path(path)
        if not candidate.is_file():
            raise SystemExit(f"--mat not found: {candidate}")
        return candidate
    for candidate in DEFAULT_MAT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise SystemExit("DTMB5415-database.mat not found; pass --mat (see docs/datasets/dtmb5415.md)")


def build_table(mat_path: Path) -> tuple[np.ndarray, np.ndarray, dict]:
    import scipy.io

    wanted = ("variablesMatrix", "coefStatMatrix", "accelerationRMSMatrix", "motionRMSMatrix")
    raw = scipy.io.loadmat(str(mat_path), variable_names=wanted)
    X = np.asarray(raw["variablesMatrix"], dtype=np.float64).T          # (9001, 27)
    y = np.concatenate([
        np.asarray(raw["coefStatMatrix"], dtype=np.float64).T,          # Cw
        np.asarray(raw["accelerationRMSMatrix"], dtype=np.float64).T,   # az
        np.asarray(raw["motionRMSMatrix"], dtype=np.float64).T,         # xi5
    ], axis=1)                                                          # (9001, 9)
    if X.shape != (9001, 27) or y.shape != (9001, 9):
        raise SystemExit(f"unexpected payload shapes X={X.shape} y={y.shape}")
    if not (np.isfinite(X).all() and np.isfinite(y).all()):
        raise SystemExit("payload contains non-finite values")
    info = {
        "mat_path": str(mat_path),
        "mat_sha256": sha256_file(mat_path),
        "n_configurations": int(X.shape[0]),
        "n_design_variables": int(X.shape[1]),
        "n_targets": int(y.shape[1]),
        "input_min": float(X.min()),
        "input_max": float(X.max()),
        "rows_with_all_zero_design": int((np.abs(X).sum(axis=1) == 0).sum()),
    }
    return X, y, info


def split_indices(n: int, seed: int, fractions=(0.8, 0.1, 0.1)) -> dict:
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    n_train = int(round(fractions[0] * n))
    n_val = int(round(fractions[1] * n))
    return {
        "idx_train": np.sort(order[:n_train]).astype(np.int64),
        "idx_val": np.sort(order[n_train:n_train + n_val]).astype(np.int64),
        "idx_test": np.sort(order[n_train + n_val:]).astype(np.int64),
    }


# --------------------------------------------------------------------------- #
# baselines + metrics
# --------------------------------------------------------------------------- #
def ridge_baseline(Xtr, Ytr, Xte, Yte) -> dict:
    """Closed-form ridge (standardised features, intercept) on the same split."""
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    Ztr = (Xtr - mu) / sd
    Zte = (Xte - mu) / sd
    ymu = Ytr.mean(0)
    A = np.hstack([Ztr, np.ones((Ztr.shape[0], 1))])
    lam = 1e-2 * np.eye(A.shape[1])
    lam[-1, -1] = 0.0
    coef = np.linalg.solve(A.T @ A + lam, A.T @ (Ytr - ymu))
    pred = np.hstack([Zte, np.ones((Zte.shape[0], 1))]) @ coef + ymu
    return {name: r2(Yte[:, j], pred[:, j]) for j, name in enumerate(TARGET_COLUMNS)}


def r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    ss_res = float(((y_true - y_pred) ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


def target_metrics(y_true: np.ndarray, y_pred: np.ndarray, *, mape_rel_floor: float = 1e-3) -> dict:
    """Physical-unit metrics; relative errors are filtered away from y ~ 0.

    ``mape_rel_floor`` drops rows whose |y_true| < floor * max|y_true| — for Cw
    that is the wave-cancellation region where a relative error is meaningless
    (the filter is reported, not hidden).
    """
    err = y_pred - y_true
    abs_true = np.abs(y_true)
    keep = abs_true >= mape_rel_floor * max(abs_true.max(), 1e-30)
    rel_pct = np.abs(err[keep] / y_true[keep]) * 100.0 if keep.any() else np.array([np.nan])
    return {
        "r2": r2(y_true, y_pred),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "mae": float(np.abs(err).mean()),
        "mape_pct": float(np.mean(rel_pct)),
        "median_abs_rel_err_pct": float(np.median(rel_pct)),
        "p95_abs_rel_err_pct": float(np.percentile(rel_pct, 95)),
        "max_abs_rel_err_pct": float(np.max(rel_pct)),
        "rel_err_rows": int(keep.sum()),
        "rel_err_rows_dropped": int((~keep).sum()),
        "mape_rel_floor": mape_rel_floor,
        "n_rows": int(y_true.size),
        "y_true_range": [float(y_true.min()), float(y_true.max())],
    }


# --------------------------------------------------------------------------- #
# training
# --------------------------------------------------------------------------- #
def train_mlp(Xtr, Ytr, Xval, Yval, args):
    import torch

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.use_deterministic_algorithms(False)

    x_mu, x_sd = Xtr.mean(0), Xtr.std(0)
    x_sd[x_sd == 0] = 1.0
    y_mu, y_sd = Ytr.mean(0), Ytr.std(0)
    y_sd[y_sd == 0] = 1.0
    Ztr = torch.as_tensor((Xtr - x_mu) / x_sd, dtype=torch.float32)
    Ttr = torch.as_tensor((Ytr - y_mu) / y_sd, dtype=torch.float32)
    Zval = torch.as_tensor((Xval - x_mu) / x_sd, dtype=torch.float32)
    Tval = torch.as_tensor((Yval - y_mu) / y_sd, dtype=torch.float32)

    layers = [Xtr.shape[1], args.hidden, args.hidden, Ytr.shape[1]]
    modules: list = []
    for i, (fan_in, fan_out) in enumerate(zip(layers[:-1], layers[1:])):
        modules.append(torch.nn.Linear(fan_in, fan_out))
        if i < len(layers) - 2:
            modules.append(torch.nn.GELU())
    net = torch.nn.Sequential(*modules)
    optim = torch.optim.Adam(net.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    loss_fn = torch.nn.MSELoss()

    history, best = [], {"val": float("inf"), "epoch": -1, "state": None}
    n = Ztr.shape[0]
    g = torch.Generator().manual_seed(args.seed)
    for epoch in range(1, args.epochs + 1):
        net.train()
        perm = torch.randperm(n, generator=g)
        total = 0.0
        for start in range(0, n, args.batch_size):
            batch = perm[start:start + args.batch_size]
            optim.zero_grad()
            loss = loss_fn(net(Ztr[batch]), Ttr[batch])
            loss.backward()
            optim.step()
            total += float(loss) * batch.numel()
        net.eval()
        with torch.no_grad():
            val = float(loss_fn(net(Zval), Tval))
        train_loss = total / n
        history.append({"epoch": epoch, "train_mse_std": train_loss, "val_mse_std": val})
        if val < best["val"] - 1e-9:
            best = {"val": val, "epoch": epoch,
                    "state": {k: v.detach().clone() for k, v in net.state_dict().items()}}
        if epoch % max(args.epochs // 10, 1) == 0:
            print(f"  epoch {epoch:4d} train {train_loss:.5f} val {val:.5f} best {best['val']:.5f}")
    net.load_state_dict(best["state"])
    net.eval()
    return net, {
        "x_mu": x_mu, "x_sd": x_sd, "y_mu": y_mu, "y_sd": y_sd, "layers": layers,
        "best_epoch": best["epoch"], "best_val_mse_std": best["val"],
    }, history


def predict_mlp(net, scaling, X) -> np.ndarray:
    import torch

    Z = (X - scaling["x_mu"]) / scaling["x_sd"]
    with torch.no_grad():
        out = net(torch.as_tensor(Z, dtype=torch.float32)).numpy().astype(float)
    return out * scaling["y_sd"] + scaling["y_mu"]


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #
def make_figures(Yte, Ypred, baseline_pred_ok: bool, history, outdir: Path) -> list[dict]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    outdir.mkdir(parents=True, exist_ok=True)
    figs = []
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, (j, name) in zip(axes, [(0, "Cw (Fr=0.25)"), (3, "az (Fr=0.25)"), (6, "xi5 (Fr=0.25)")]):
        ax.scatter(Yte[:, j], Ypred[:, j], s=6, alpha=0.35, edgecolors="none")
        lo = min(Yte[:, j].min(), Ypred[:, j].min())
        hi = max(Yte[:, j].max(), Ypred[:, j].max())
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        ax.set_xlabel(f"held-out truth {name}")
        ax.set_ylabel("surrogate prediction")
        ax.set_title(f"{name}  R²={r2(Yte[:, j], Ypred[:, j]):.3f}", fontsize=10)
    fig.suptitle("DTMB 5415 surrogate: 901 held-out configurations (never trained on)", fontsize=11)
    fig.tight_layout()
    f1 = outdir / "fig1_parity_holdout.png"
    fig.savefig(f1, dpi=140)
    plt.close(fig)
    figs.append({"path": str(f1.relative_to(REPO)),
                 "caption": "Parity of surrogate predictions vs held-out solver values for one "
                            "column of each target family (Fr=0.25). Dashed line = 1:1."})

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    groups = [("Cw", slice(0, 3)), ("az", slice(3, 6)), ("xi5", slice(6, 9))]
    for ax, (label, sl) in zip(axes, groups):
        rel = np.abs((Ypred[:, sl] - Yte[:, sl]) / np.where(np.abs(Yte[:, sl]) > 1e-12,
                                                           Yte[:, sl], np.nan)) * 100.0
        rel = np.clip(rel[np.isfinite(rel)], 0, 200)
        ax.hist(rel, bins=60, color="steelblue")
        ax.set_xlabel(f"|relative error| [%] for {label} (clipped at 200)")
        ax.set_ylabel("count")
        ax.set_title(f"{label}: median {np.median(rel):.2f}%, p95 {np.percentile(rel, 95):.1f}%",
                     fontsize=9)
    fig.suptitle("Held-out relative error distributions (relative errors near y=0 are not meaningful)",
                 fontsize=10)
    fig.tight_layout()
    f2 = outdir / "fig2_rel_error_hist.png"
    fig.savefig(f2, dpi=140)
    plt.close(fig)
    figs.append({"path": str(f2.relative_to(REPO)),
                 "caption": "Held-out absolute relative error histograms per target family."})

    fig, ax = plt.subplots(figsize=(6, 3.4))
    ax.plot(history[:, 0], history[:, 1], label="train MSE (standardised)")
    ax.plot(history[:, 0], history[:, 2], label="validation MSE (standardised)")
    ax.set_yscale("log")
    ax.set_xlabel("epoch")
    ax.set_ylabel("MSE")
    ax.legend(fontsize=8)
    ax.set_title("Training curve")
    fig.tight_layout()
    f3 = outdir / "fig3_training_curve.png"
    fig.savefig(f3, dpi=140)
    plt.close(fig)
    figs.append({"path": str(f3.relative_to(REPO)), "caption": "Train/validation loss vs epoch."})
    return figs


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mat", default=None)
    parser.add_argument("--registry-root", default=str(REPO / "models"))
    parser.add_argument("--epochs", type=int, default=400)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20261113)
    parser.add_argument("--skip-register", action="store_true")
    args = parser.parse_args(argv)

    import torch

    run_dir = OUT_ROOT / "dtmb5415-surrogate"
    derived = OUT_ROOT / "derived"
    run_dir.mkdir(parents=True, exist_ok=True)
    derived.mkdir(parents=True, exist_ok=True)

    mat = resolve_mat(args.mat)
    print(f"[1/6] loading payload {mat}")
    X, y, data_info = build_table(mat)
    split = split_indices(X.shape[0], args.seed)
    np.savez_compressed(derived / "dtmb5415_train_ready.npz", X=X, y=y, **split)

    Xtr, Ytr = X[split["idx_train"]], y[split["idx_train"]]
    Xval, Yval = X[split["idx_val"]], y[split["idx_val"]]
    Xte, Yte = X[split["idx_test"]], y[split["idx_test"]]
    print(f"[2/6] split train/val/test = {len(Xtr)}/{len(Xval)}/{len(Xte)}  (seed {args.seed})")

    print(f"[3/6] training MLP {args.hidden}-{args.hidden} for {args.epochs} epochs")
    net, scaling, history = train_mlp(Xtr, Ytr, Xval, Yval, args)

    Ypred = predict_mlp(net, scaling, Xte)
    ridge_r2 = ridge_baseline(Xtr, Ytr, Xte, Yte)
    metrics = {name: target_metrics(Yte[:, j], Ypred[:, j]) for j, name in enumerate(TARGET_COLUMNS)}
    for name, m in metrics.items():
        print(f"   {name:12s} R²={m['r2']:.4f}  p95|rel|={m['p95_abs_rel_err_pct']:6.2f}%  "
              f"median={m['median_abs_rel_err_pct']:6.2f}%  ridge R²={ridge_r2[name]:.4f}")

    print("[4/6] writing weights, training table, eval card")
    weights_path = run_dir / "weights" / "model.pt"
    weights_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": net.state_dict(),
                "format": "torch-state-dict",
                "layers": scaling["layers"]}, weights_path)

    # The delivered table is stored as float32 (the network consumes float32);
    # the fingerprint is computed over *exactly the stored arrays*, so verify()
    # recomputes the same digest from the registry copy.
    table_arrays = {
        "X": X.astype(np.float32),
        "y": y.astype(np.float32),
        "idx_train": split["idx_train"].astype(np.int64),
        "idx_val": split["idx_val"].astype(np.int64),
        "idx_test": split["idx_test"].astype(np.int64),
    }
    table_path = run_dir / "training_table.npz"
    np.savez_compressed(table_path, **table_arrays)

    table_extra = {
        "source_mat_sha256": data_info["mat_sha256"],
        "n_configurations": X.shape[0],
        "target_columns": TARGET_COLUMNS,
        "seed": args.seed,
        "dtypes": {k: str(v.dtype) for k, v in table_arrays.items()},
    }
    fp = fingerprint_arrays(table_arrays, table_extra)

    dataset_meta = json.loads(DATASET_JSON.read_text())
    eval_card = {
        "schema": "eval-card/1.0",
        "model_id": MODEL_ID,
        "version": VERSION,
        "protocol": ("held-out split: 901 configurations never seen during fitting or early "
                     "stopping; metrics in physical units against solver outputs"),
        "split": {"scheme": "holdout-80/10/10 seeded permutation", "seed": args.seed,
                  "n_train": int(len(Xtr)), "n_val": int(len(Xval)), "n_test": int(len(Xte))},
        "targets": metrics,
        "baseline": {
            "kind": "ridge regression (standardised inputs, intercept, lambda=1e-2)",
            "protocol": "same train/test split, per-target R²",
            "r2": ridge_r2,
            "delta_r2_mlp_minus_ridge": {k: metrics[k]["r2"] - ridge_r2[k] for k in metrics},
        },
        "summary": {
            "min_target_r2": min(m["r2"] for m in metrics.values()),
            "median_target_r2": float(np.median([m["r2"] for m in metrics.values()])),
            "median_p95_abs_rel_err_pct": float(np.median(
                [m["p95_abs_rel_err_pct"] for m in metrics.values()])),
            "n_targets": len(metrics),
            "all_targets_beat_ridge": all(metrics[k]["r2"] > ridge_r2[k] for k in metrics),
        },
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "numpy": np.__version__},
        "provenance": {"script": "scripts/dtmb5415_surrogate_train.py",
                       "source_mat_sha256": data_info["mat_sha256"],
                       "dataset_archive_sha256": dataset_meta["provenance"]["archive"]["sha256"]},
    }
    (run_dir / "eval_card.json").write_text(json.dumps(eval_card, indent=2))
    (run_dir / "metrics.json").write_text(json.dumps(
        {"metrics": metrics, "ridge_r2": ridge_r2, "scaling": {
            k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in scaling.items()},
         "data_info": data_info}, indent=2))
    (run_dir / "loss_history.json").write_text(json.dumps(
        {"history": history, "best_epoch": scaling["best_epoch"]}, indent=2))
    np.savez_compressed(derived / "dtmb5415_test_predictions.npz", Yte=Yte, Ypred=Ypred,
                        idx_test=split["idx_test"])
    history_arr = np.array([[h["epoch"], h["train_mse_std"], h["val_mse_std"]] for h in history])
    figs = make_figures(Yte, Ypred, True, history_arr, run_dir / "figs")

    manifest = {
        "schema_version": mschema.SCHEMA_VERSION,
        "model_id": MODEL_ID,
        "version": VERSION,
        "display_name": "DTMB 5415 lumped-response surrogate (Cw/az/xi5, 3 Froude numbers)",
        "created_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "task": {
            "task_type": "regression",
            "domain_tags": ["hydrodynamics", "resistance", "seakeeping", "hull-form-design"],
            "objective": ("map 27 dimensionless DTMB 5415 design variables to 9 lumped "
                          "hydrodynamic responses (Cw, az, xi5 at Fr=0.25/0.33/0.41)"),
            "targets": [
                {"name": name,
                 "unit": {"Cw": "-", "az": "g (RMS, full scale)", "xi5": "rad (RMS, full scale)"}[
                     name.split("_")[0]],
                 "condition": {"froude": float(name.split("Fr")[1])},
                 "description": {"Cw": "wave resistance coefficient (WARP, model scale)",
                                 "az": "RMS vertical acceleration at bridge (SMP, full scale)",
                                 "xi5": "RMS pitch motion (SMP, full scale)"}[name.split("_")[0]]}
                for name in TARGET_COLUMNS
            ],
        },
        "io_contract": {
            "inputs": [{
                "name": "design_variables",
                "media_type": "application/json",
                "shape": ["n", 27],
                "dtype": "float64",
                "units": "normalised design space (dimensionless, benchmark scaling)",
                "columns": [f"dv{i + 1}" for i in range(27)],
                "description": "row-per-configuration design vector, benchmark variables [-1, 1]",
            }],
            "outputs": [{
                "name": "responses",
                "media_type": "application/json",
                "shape": ["n", 9],
                "dtype": "float64",
                "units": "per-target units, see task.targets",
                "columns": list(TARGET_COLUMNS),
            }],
            "batch_axis": 0,
            "preprocessing": {
                "input_center": scaling["x_mu"].tolist(),
                "input_scale": scaling["x_sd"].tolist(),
                "output_center": scaling["y_mu"].tolist(),
                "output_scale": scaling["y_sd"].tolist(),
            },
            "loader": {"kind": "torch-mlp", "layers": [int(v) for v in scaling["layers"]],
                       "activation": "gelu"},
        },
        "artifacts": [
            {"role": "weights", "path": "weights/model.pt", "sha256": "0" * 64, "bytes": 0,
             "format": "torch-state-dict", "framework": f"torch {torch.__version__}",
             "media_type": "application/octet-stream",
             "note": f"MLP {scaling['layers']} GELU, best epoch {scaling['best_epoch']}"},
            {"role": "eval_card", "path": "eval_card.json", "sha256": "0" * 64, "bytes": 0,
             "format": "eval-card/1.0", "framework": "python", "media_type": "application/json"},
            {"role": "training_table", "path": "training_table.npz", "sha256": "0" * 64,
             "bytes": 0, "format": "npz-array-digest-v1", "framework": "numpy",
             "media_type": "application/octet-stream"},
        ],
        "training_data": {
            "datasets": [{
                "dataset_ref": dataset_meta["dataset_id"],
                "dataset_version": dataset_meta["version"],
                "source_uri": "doi:" + dataset_meta["provenance"]["doi"],
                "artifact_sha256": dataset_meta["provenance"]["archive"]["sha256"],
                "fingerprint": fp["fingerprint"],
                "license": dataset_meta["license"],
            }],
            "fingerprint": fp["fingerprint"],
            "fingerprint_recipe": {
                "kind": "array-digest-v1",
                "table_path": "training_table.npz",
                "arrays": {"X": "X", "y": "y", "idx_train": "idx_train",
                           "idx_val": "idx_val", "idx_test": "idx_test"},
                "array_digests": fp["arrays"],
                "extra": table_extra,
            },
            "split": {"scheme": "holdout-80/10/10 seeded permutation", "seed": args.seed,
                      "n_train": int(len(Xtr)), "n_val": int(len(Xval)), "n_test": int(len(Xte))},
        },
        "training_config": {
            "algorithm": "MLP (GELU) trained with Adam on standardised inputs/targets",
            "layers": [int(v) for v in scaling["layers"]],
            "optimizer": "Adam", "lr": args.lr, "weight_decay": args.weight_decay,
            "batch_size": args.batch_size, "epochs": args.epochs,
            "early_stopping": "best validation MSE (standardised targets)",
            "loss": "MSE on standardised targets", "seed": args.seed,
            "environment": eval_card["environment"],
            "training_table": "artifacts/GAP-ASSET-MODEL-REGISTRY/derived/dtmb5415_train_ready.npz",
        },
        "evaluation": {
            "protocol": eval_card["protocol"],
            "split": "holdout 80/10/10, seed " + str(args.seed),
            "status": "evaluated",
            "metrics": metrics,
            "baseline": eval_card["baseline"],
            "caveats": [
                "targets are solver outputs (WARP resistance, SMP seakeeping), not EFD; "
                "surrogate error is bounded by the benchmark's own numerical uncertainty, "
                "which this dataset does not quantify",
                "Cw spans three orders of magnitude and crosses zero near wave cancellation; "
                "relative errors there are excluded by mape_rel_floor and R² is the primary metric",
            ],
        },
        "applicability_domain": {
            "description": ("DTMB 5415 design space of the Zenodo 19222008 benchmark: 27 design "
                            "variables spanning hull-form perturbations around the DTMB 5415 "
                            "baseline, evaluated at Fr = 0.25/0.33/0.41"),
            "bounds": {"design_variables": [math.floor(data_info["input_min"] * 100) / 100,
                                            math.ceil(data_info["input_max"] * 100) / 100]},
            "out_of_domain_policy": "flag",
            "caveats": [
                "no extrapolation beyond the sampled design-space box; predictions there are "
                "flagged, not rejected",
                "valid only for the DTMB 5415 hull family at the three trained Froude numbers",
                "trained on solver data, so systematic solver bias is inherited",
            ],
        },
        "provenance": {
            "created_by": "TensorData agent (mission 17460, agent/m17460)",
            "repro_cmd": (f"python scripts/dtmb5415_surrogate_train.py --mat {mat} "
                          f"--registry-root {args.registry_root} --epochs {args.epochs} "
                          f"--batch-size {args.batch_size} --lr {args.lr:g} "
                          f"--weight-decay {args.weight_decay:g} --hidden {args.hidden} "
                          f"--seed {args.seed}"),
            "code": {"script": "scripts/dtmb5415_surrogate_train.py",
                     "manifest_schema": "schemas/model-manifest.schema.json"},
            "inputs": [{"uri": "doi:" + dataset_meta["provenance"]["doi"],
                        "sha256": dataset_meta["provenance"]["archive"]["sha256"]},
                       {"uri": data_info["mat_path"], "sha256": data_info["mat_sha256"]}],
            "notes": "weights, eval card and training table are copied into the registry by "
                     "ModelRegistry.register, which recomputes every digest",
        },
        "rights": {
            "license": "Apache-2.0",
            "data_license": dataset_meta["license"],
            "redistribution": "weights derived from CC-BY-4.0 data; attribution required",
            "intended_uses": ["surrogate-assisted hull-form design", "benchmark baseline",
                              "unverified design-space screening (not class/regulatory use)"],
        },
    }

    (run_dir / "model_manifest.json").write_text(json.dumps(manifest, indent=2))
    if args.skip_register:
        print("[5/6] skipped registration (--skip-register)")
        return 0

    print(f"[5/6] registering {MODEL_ID}@{VERSION} in {args.registry_root}")
    reg = ModelRegistry(args.registry_root)
    body = reg.register(manifest, {a["path"]: run_dir / a["path"] for a in manifest["artifacts"]})
    report = reg.verify(MODEL_ID, VERSION)
    (run_dir / "verify_report.json").write_text(json.dumps(report, indent=2))
    print(f"[6/6] registered sha256={body['manifest_sha256'][:16]}… verify ok={report['ok']}")
    print(f"      data fingerprint {body['training_data']['fingerprint']}")
    print(f"      figures: {[f['path'] for f in figs]}")
    if not report["ok"]:
        raise SystemExit("verification failed after registration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())