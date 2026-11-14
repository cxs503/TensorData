"""Model asset registry: schema, immutable versions, hash/fingerprint binding, CLI."""

from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tensordata.modelreg import (
    ModelRegistry,
    RegistryError,
    fingerprint_arrays,
    load_model,
    sha256_file,
    validate_manifest,
)
from tensordata.modelreg import schema as mschema

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# synthetic fixtures
# --------------------------------------------------------------------------- #
def make_table(seed: int, n: int = 60, n_in: int = 4, n_out: int = 3):
    rng = np.random.default_rng(seed)
    X = (rng.random((n, n_in)) * 2 - 1).astype(np.float32)
    W = rng.normal(size=(n_out, n_in))
    b = rng.normal(size=n_out)
    y = (X @ W.T + b).astype(np.float32)
    idx = rng.permutation(n)
    split = {
        "idx_train": np.sort(idx[: int(0.7 * n)]).astype(np.int64),
        "idx_val": np.sort(idx[int(0.7 * n): int(0.85 * n)]).astype(np.int64),
        "idx_test": np.sort(idx[int(0.85 * n):]).astype(np.int64),
    }
    return {"X": X, "y": y, **split}, np.asarray(W), np.asarray(b), X


def make_model(tmp_path: Path, seed: int = 7, version: str = "0.1.0") -> dict:
    work = tmp_path / f"src-{seed}"
    work.mkdir(parents=True, exist_ok=True)
    arrays, W, b, X = make_table(seed)
    np.savez(work / "training_table.npz", **arrays)
    np.savez(work / "weights.npz", W=W.astype(np.float64), b=b.astype(np.float64))
    extra = {"seed": seed, "n_rows": int(X.shape[0])}
    fp = fingerprint_arrays(arrays, extra)
    eval_card = {
        "protocol": "synthetic held-out rows",
        "metrics": {"out_0": {"r2": 1.0}},
    }
    (work / "eval_card.json").write_text(json.dumps(eval_card))
    manifest = {
        "schema_version": mschema.SCHEMA_VERSION,
        "model_id": "synthetic-affine",
        "version": version,
        "display_name": "synthetic affine test model",
        "task": {
            "task_type": "regression",
            "objective": "identity-ish affine map for registry tests",
            "domain_tags": ["synthetic"],
            "targets": [{"name": f"out_{i}", "unit": "-"} for i in range(3)],
        },
        "io_contract": {
            "inputs": [{"name": "x", "media_type": "application/json", "shape": ["n", 4],
                        "dtype": "float64", "columns": ["a", "b", "c", "d"]}],
            "outputs": [{"name": "y", "media_type": "application/json", "shape": ["n", 3],
                         "dtype": "float64"}],
            "batch_axis": 0,
            "preprocessing": {"input_center": None, "input_scale": None,
                              "output_center": None, "output_scale": None},
            "loader": {"kind": "numpy-affine"},
        },
        "artifacts": [
            {"role": "weights", "path": "weights/weights.npz", "sha256": "0" * 64, "bytes": 0,
             "format": "npz-affine", "framework": "numpy"},
            {"role": "eval_card", "path": "eval_card.json", "sha256": "0" * 64, "bytes": 0,
             "format": "eval-card/1.0", "framework": "python"},
            {"role": "training_table", "path": "training_table.npz", "sha256": "0" * 64,
             "bytes": 0, "format": "npz-array-digest-v1", "framework": "numpy"},
        ],
        "training_data": {
            "datasets": [{"dataset_ref": "synthetic-table", "dataset_version": f"seed-{seed}",
                          "fingerprint": fp["fingerprint"]}],
            "fingerprint": fp["fingerprint"],
            "fingerprint_recipe": {
                "kind": "array-digest-v1",
                "table_path": "training_table.npz",
                "arrays": {"X": "X", "y": "y", "idx_train": "idx_train",
                           "idx_val": "idx_val", "idx_test": "idx_test"},
                "array_digests": fp["arrays"],
                "extra": extra,
            },
            "split": {"scheme": "holdout", "seed": seed, "n_train": len(arrays["idx_train"]),
                      "n_val": len(arrays["idx_val"]), "n_test": len(arrays["idx_test"])},
        },
        "training_config": {"algorithm": "closed-form affine"},
        "evaluation": {"protocol": "synthetic held-out rows", "status": "evaluated",
                       "metrics": {"out_0": {"r2": 1.0}}},
        "applicability_domain": {
            "description": "unit box of the synthetic design space",
            "bounds": {"x": [-1.0, 1.0]},
            "out_of_domain_policy": "flag",
            "caveats": ["synthetic only"],
        },
        "provenance": {"created_by": "tests", "repro_cmd": "pytest tests/test_modelreg.py"},
        "rights": {"license": "Apache-2.0", "data_license": "synthetic"},
    }
    return {"manifest": manifest, "work": work, "weights": work / "weights.npz",
            "table": work / "training_table.npz", "W": W, "b": b, "X": X}


def register(registry: ModelRegistry, fixture: dict) -> dict:
    return registry.register(fixture["manifest"], {
        "weights/weights.npz": fixture["weights"],
        "eval_card.json": fixture["work"] / "eval_card.json",
        "training_table.npz": fixture["table"],
    })


# --------------------------------------------------------------------------- #
# schema
# --------------------------------------------------------------------------- #
def test_schema_accepts_complete_manifest(tmp_path):
    fixture = make_model(tmp_path)
    assert validate_manifest(fixture["manifest"]) == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda m: m.pop("training_data"), "training_data"),
    (lambda m: m.update(model_id="Synthetic Affine"), "model_id"),
    (lambda m: m.update(version="v1"), "version"),
    (lambda m: m["artifacts"].pop(0), "role 'weights'"),
    (lambda m: m["artifacts"][0].update(sha256="not-a-hash"), "sha256"),
    (lambda m: m["io_contract"]["loader"].update(kind="magic"), "loader"),
    (lambda m: m["training_data"]["datasets"][0].update(fingerprint="deadbeef"), "fingerprint"),
    (lambda m: m["applicability_domain"]["bounds"].update(x=[1, -1]), "bounds.x"),
    (lambda m: m["applicability_domain"].update(out_of_domain_policy="ignore"),
     "out_of_domain_policy"),
    (lambda m: m["evaluation"].update(status="evaluated") or
     [a.update(role="other") for a in m["artifacts"] if a["role"] == "eval_card"], "eval_card"),
])
def test_schema_rejects_broken_manifests(tmp_path, mutate, needle):
    fixture = make_model(tmp_path)
    mutate(fixture["manifest"])
    errors = validate_manifest(fixture["manifest"])
    assert errors, "expected validation errors"
    assert any(needle in e for e in errors), errors


def test_manifest_checksum_detects_edits(tmp_path):
    fixture = make_model(tmp_path)
    body = mschema.finalize(fixture["manifest"])
    assert validate_manifest(body) == []
    body["task"]["objective"] = "silently changed"
    assert "[manifest_sha256]" not in " ".join(validate_manifest(body))
    assert any("manifest_sha256" in e for e in validate_manifest(body))


# --------------------------------------------------------------------------- #
# registry lifecycle
# --------------------------------------------------------------------------- #
def test_register_list_load_and_verify(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    body = register(registry, fixture)

    assert body["manifest_sha256"] == mschema.canonical_checksum(body)
    weights = next(a for a in body["artifacts"] if a["role"] == "weights")
    assert weights["sha256"] == sha256_file(fixture["weights"])

    rows = registry.list_models()
    assert [r["model_id"] for r in rows] == ["synthetic-affine"]
    assert rows[0]["version"] == "0.1.0"
    assert rows[0]["eval_status"] == "evaluated"

    loaded = registry.load_manifest("synthetic-affine")
    assert loaded["manifest_sha256"] == body["manifest_sha256"]

    report = registry.verify("synthetic-affine")
    assert report["ok"], report
    assert {c["name"] for c in report["checks"]} >= {
        "manifest_structural", "artifact:weights", "training_data_fingerprint"}


def test_versions_are_immutable_and_resolve_to_latest(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    register(registry, fixture)
    with pytest.raises(RegistryError):
        register(registry, fixture)

    second = make_model(tmp_path, seed=8, version="0.2.0")
    register(registry, second)
    assert registry.versions("synthetic-affine") == ["0.1.0", "0.2.0"]
    assert registry.load_manifest("synthetic-affine")["version"] == "0.2.0"
    assert registry.load_manifest("synthetic-affine", "0.1.0")["version"] == "0.1.0"
    with pytest.raises(RegistryError):
        registry.load_manifest("synthetic-affine", "9.9.9")


def test_registration_requires_payloads(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    with pytest.raises(RegistryError):
        registry.register(fixture["manifest"], {})


def test_verify_detects_swapped_weights(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    register(registry, fixture)

    other = make_model(tmp_path, seed=11)
    model_dir = registry.model_dir("synthetic-affine", "0.1.0")
    (model_dir / "weights/weights.npz").write_bytes(other["weights"].read_bytes())

    report = registry.verify("synthetic-affine")
    assert not report["ok"]
    failed = {c["name"] for c in report["checks"] if not c.get("ok", True)}
    assert "artifact:weights" in failed


def test_verify_detects_training_data_mismatch(tmp_path):
    """Weights + manifest self-consistent, but the table is not the declared one."""
    fixture = make_model(tmp_path, seed=7)
    registry = ModelRegistry(tmp_path / "registry")
    body = register(registry, fixture)

    other = make_model(tmp_path, seed=12)
    model_dir = registry.model_dir("synthetic-affine", "0.1.0")
    replaced = model_dir / "training_table.npz"
    replaced.write_bytes(other["table"].read_bytes())

    # re-sign the manifest so the artifact digest is "correct" but the data
    # fingerprint still describes the original table: exactly the 张冠李戴 case
    body["artifacts"] = [
        {**a, "sha256": sha256_file(model_dir / a["path"]),
         "bytes": (model_dir / a["path"]).stat().st_size} for a in body["artifacts"]
    ]
    body = mschema.finalize(body)
    (model_dir / "model.json").write_text(mschema.canonical_json(body) + "\n")

    report = registry.verify("synthetic-affine")
    assert not report["ok"]
    binding = next(c for c in report["checks"] if c["name"] == "training_data_fingerprint")
    assert binding["status"] == "mismatch"
    artifacts = [c for c in report["checks"] if c["name"].startswith("artifact:")]
    assert all(c["ok"] for c in artifacts), "artifact digests were re-signed on purpose"


# --------------------------------------------------------------------------- #
# load-and-use
# --------------------------------------------------------------------------- #
def test_predictor_matches_affine_reference(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    register(registry, fixture)
    predictor = load_model(registry, "synthetic-affine")

    rows = fixture["X"][:5].astype(float).tolist()
    out = np.asarray(predictor.predict(rows))
    assert out.shape == (5, 3)
    assert np.allclose(out, np.asarray(rows) @ fixture["W"].T + fixture["b"], atol=1e-9)
    assert predictor.output_names == ["out_0", "out_1", "out_2"]


def test_predictor_flags_out_of_domain_rows(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    register(registry, fixture)
    predictor = load_model(registry, "synthetic-affine")

    inside = fixture["X"][0].astype(float).tolist()
    outside = [2.5, 0.0, 0.0, 0.0]
    report = predictor.predict_report([inside, outside])
    assert report["out_of_domain"]["n_out_of_domain"] == 1
    assert report["out_of_domain"]["rows"] == [1]

    predictor.manifest["applicability_domain"]["out_of_domain_policy"] = "reject"
    from tensordata.modelreg import LoaderError

    with pytest.raises(LoaderError):
        predictor.predict_report([outside])


def test_predictor_rejects_wrong_input_width(tmp_path):
    fixture = make_model(tmp_path)
    registry = ModelRegistry(tmp_path / "registry")
    register(registry, fixture)
    predictor = load_model(registry, "synthetic-affine")
    from tensordata.modelreg import LoaderError

    with pytest.raises(LoaderError):
        predictor.predict([[0.0, 0.0]])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli(*args, cwd=REPO):
    return subprocess.run([sys.executable, "-m", "tensordata.modelreg.cli", *args],
                          capture_output=True, text=True, cwd=cwd, timeout=180)


def test_cli_register_list_verify_predict(tmp_path):
    fixture = make_model(tmp_path, seed=21)
    registry_root = tmp_path / "cli-registry"
    work = fixture["work"]

    result = _cli("--root", str(registry_root), "register",
                  "--manifest", str(work / "manifest.json"))
    # no manifest file yet -> explicit failure, not a crash traceback
    assert result.returncode != 0

    (work / "manifest.json").write_text(json.dumps(fixture["manifest"]))
    result = _cli("--root", str(registry_root), "register",
                  "--manifest", str(work / "manifest.json"),
                  "--artifact", "weights/weights.npz", str(fixture["weights"]),
                  "--artifact", "eval_card.json", str(work / "eval_card.json"),
                  "--artifact", "training_table.npz", str(fixture["table"]))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["registered"] == "synthetic-affine@0.1.0"

    listed = _cli("--root", str(registry_root), "list", "--json")
    assert json.loads(listed.stdout)[0]["model_id"] == "synthetic-affine"

    verified = _cli("--root", str(registry_root), "verify", "synthetic-affine")
    assert verified.returncode == 0, verified.stdout
    assert json.loads(verified.stdout)["ok"] is True

    (work / "rows.json").write_text(json.dumps(fixture["X"][:3].tolist()))
    (work / "out.json").write_text("")
    predicted = _cli("--root", str(registry_root), "predict", "synthetic-affine",
                     "--input", str(work / "rows.json"), "--out", str(work / "out.json"))
    assert predicted.returncode == 0, predicted.stderr
    body = json.loads((work / "out.json").read_text())
    assert len(body["outputs"]) == 3
    assert body["columns"] == ["out_0", "out_1", "out_2"]

    tampered = registry_root / "synthetic-affine/0.1.0/weights/weights.npz"
    tampered.write_bytes(b"tampered")
    assert _cli("--root", str(registry_root), "verify", "synthetic-affine").returncode == 1


# --------------------------------------------------------------------------- #
# the registered DTMB 5415 surrogate, when present
# --------------------------------------------------------------------------- #
REGISTRY = REPO / "models"
D5415 = REGISTRY / "dtmb5415-lumped-surrogate"


@pytest.mark.skipif(\n    not D5415.is_dir() or importlib.util.find_spec("torch") is None,\n    reason="DTMB 5415 surrogate or optional torch runtime is unavailable",\n)
def test_registered_5415_surrogate_verifies_and_predicts():
    registry = ModelRegistry(REGISTRY)
    report = registry.verify("dtmb5415-lumped-surrogate")
    assert report["ok"], report

    manifest = registry.load_manifest("dtmb5415-lumped-surrogate")
    assert manifest["training_data"]["fingerprint"].startswith("sha256:")
    assert manifest["evaluation"]["status"] == "evaluated"

    predictor = load_model(registry, "dtmb5415-lumped-surrogate")
    rng = np.random.default_rng(0)
    X = rng.uniform(-1, 1, size=(4, 27))
    out = np.asarray(predictor.predict(X))
    assert out.shape == (4, 9)
    assert np.isfinite(out).all()
    # monotone envelope: predictions must stay inside the plausible range of the
    # training targets, i.e. the surrogate is not returning garbage
    metrics = manifest["evaluation"]["metrics"]
    for j, name in enumerate(predictor.output_names):
        lo, hi = metrics[name]["y_true_range"]
        span = hi - lo
        assert lo - 0.5 * span <= out[:, j].min() and out[:, j].max() <= hi + 0.5 * span

    flagged = predictor.predict_report([[5.0] * 27])
    assert flagged["out_of_domain"]["n_out_of_domain"] == 1


@pytest.mark.skipif(not D5415.is_dir(), reason="DTMB 5415 surrogate not registered in this checkout")
def test_5415_manifest_matches_eval_card():
    model_dir = D5415 / "1.0.0"
    manifest = json.loads((model_dir / "model.json").read_text())
    card = json.loads((model_dir / "eval_card.json").read_text())
    assert manifest["evaluation"]["metrics"] == card["targets"]
    assert set(manifest["evaluation"]["metrics"]) == {
        t["name"] for t in manifest["task"]["targets"]}
    assert card["split"]["n_test"] == manifest["training_data"]["split"]["n_test"]
    assert sha256_file(model_dir / "eval_card.json") == next(
        a["sha256"] for a in manifest["artifacts"] if a["role"] == "eval_card")