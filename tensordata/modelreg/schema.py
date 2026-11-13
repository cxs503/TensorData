"""Model-asset manifest schema (``model-manifest/1.0``) and canonical checksums.

A model asset is not "a weights file".  It is a contract: an identifier, the task
it solves, the exact input/output convention a caller must honour, the weights
payload, the *fingerprint of the data it was trained on*, the evaluation evidence,
and the domain where the numbers may be trusted.  This module defines that
contract and the digests that bind its parts together.

Design rules
------------
* No domain semantics live here.  Target names, units and applicability bounds
  are caller-supplied data; this module only checks structure.
* Every digest is canonical (sorted keys, no whitespace) and reproducible from
  the files themselves, so a manifest cannot silently claim someone else's
  weights or someone else's training table.
* Validation never mutates the caller's manifest; :func:`finalize` returns a new
  dict with ``manifest_sha256`` filled in.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "model-manifest/1.0"
SEMVER_SCHEMA = "https://semver.org/spec/v2.0.0.html"

TASK_TYPES = frozenset({"regression", "classification", "generation", "closure", "policy", "other"})
ARTIFACT_ROLES = frozenset({"weights", "tokenizer", "config", "eval_card", "training_table", "other"})
LOADER_KINDS = frozenset({"torch-mlp", "numpy-affine"})
OUT_OF_DOMAIN_POLICIES = frozenset({"flag", "reject"})

MODEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9]*([._-][a-z0-9]+)*$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.\-]+)?$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT_PREFIX = "sha256:"


class ManifestError(ValueError):
    """Raised when a manifest is structurally invalid or fails its checks."""


# --------------------------------------------------------------------------- #
# digests
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> str:
    """Stable JSON encoding used for every checksum in the registry."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def array_digest(array: Any) -> str:
    """Digest of a numeric array's dtype, shape and raw C-order bytes.

    ``numpy`` is imported lazily: the registry stays usable (validation,
    inventory, hash checks) on installations without numpy.
    """
    import numpy as np

    arr = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(f"{arr.dtype.str}|{arr.shape}|".encode())
    digest.update(arr.tobytes(order="C"))
    return digest.hexdigest()


def compose_fingerprint(entries: Mapping[str, str]) -> str:
    """Composite fingerprint over named digests (sorted, canonical)."""
    return FINGERPRINT_PREFIX + sha256_bytes(canonical_json(dict(sorted(entries.items()))).encode())


def fingerprint_arrays(arrays: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> dict:
    """Fingerprint a training table: per-array digests plus a composite digest.

    ``extra`` carries non-array binding material (split definition, row counts,
    dataset identity) so that two tables with identical numbers but different
    train/test membership cannot collide.
    """
    digests = {name: array_digest(arr) for name, arr in sorted(arrays.items())}
    return {
        "kind": "array-digest-v1",
        "arrays": digests,
        "extra": dict(sorted((extra or {}).items())),
        "fingerprint": compose_fingerprint({**digests, **{f"extra.{k}": canonical_json(v)
                                                          for k, v in (extra or {}).items()}}),
    }


def canonical_checksum(manifest: Mapping[str, Any]) -> str:
    """Checksum of the manifest with its own ``manifest_sha256`` removed."""
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    return sha256_bytes(canonical_json(body).encode())


def finalize(manifest: Mapping[str, Any]) -> dict:
    """Return a copy of ``manifest`` with a valid ``manifest_sha256``."""
    result = json.loads(json.dumps(manifest))  # deep copy, JSON-normalised
    result["manifest_sha256"] = canonical_checksum(result)
    return result


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def _require(cond: bool, errors: list[str], message: str) -> None:
    if not cond:
        errors.append(message)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_sha(value: Any, where: str, errors: list[str]) -> None:
    _require(isinstance(value, str) and bool(SHA256_RE.match(value)),
             errors, f"{where}: expected 64-char lowercase hex sha256, got {value!r}")


def _check_fingerprint(value: Any, where: str, errors: list[str]) -> None:
    _require(
        isinstance(value, str) and value.startswith(FINGERPRINT_PREFIX)
        and bool(SHA256_RE.match(value[len(FINGERPRINT_PREFIX):])),
        errors,
        f"{where}: expected 'sha256:<hex>' fingerprint, got {value!r}",
    )


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Structural validation.  Returns a list of human-readable errors."""
    errors: list[str] = []
    if not isinstance(manifest, Mapping):
        return ["manifest: expected a JSON object"]

    _require(manifest.get("schema_version") == SCHEMA_VERSION, errors,
             f"schema_version: expected {SCHEMA_VERSION!r}, got {manifest.get('schema_version')!r}")
    model_id = manifest.get("model_id")
    _require(isinstance(model_id, str) and bool(MODEL_ID_RE.match(model_id or "")), errors,
             f"model_id: expected lowercase slug, got {model_id!r}")
    version = manifest.get("version")
    _require(isinstance(version, str) and bool(VERSION_RE.match(version or "")), errors,
             f"version: expected semver, got {version!r}")

    # --- task ------------------------------------------------------------- #
    task = manifest.get("task")
    if not isinstance(task, Mapping):
        errors.append("task: expected object")
    else:
        _require(task.get("task_type") in TASK_TYPES, errors,
                 f"task.task_type: expected one of {sorted(TASK_TYPES)}, got {task.get('task_type')!r}")
        _require(isinstance(task.get("objective"), str) and bool(task.get("objective")), errors,
                 "task.objective: expected non-empty string")
        targets = task.get("targets")
        _require(isinstance(targets, list) and len(targets) > 0, errors,
                 "task.targets: expected non-empty list")
        if isinstance(targets, list):
            names = []
            for i, target in enumerate(targets):
                if not isinstance(target, Mapping) or not isinstance(target.get("name"), str):
                    errors.append(f"task.targets[{i}]: expected object with string 'name'")
                    continue
                names.append(target["name"])
                if "unit" in target:
                    _require(isinstance(target["unit"], str), errors,
                             f"task.targets[{i}].unit: expected string")
            _require(len(names) == len(set(names)), errors, "task.targets: duplicate target names")

    # --- io contract ------------------------------------------------------ #
    contract = manifest.get("io_contract")
    if not isinstance(contract, Mapping):
        errors.append("io_contract: expected object")
    else:
        for side in ("inputs", "outputs"):
            specs = contract.get(side)
            _require(isinstance(specs, list) and len(specs) > 0, errors,
                     f"io_contract.{side}: expected non-empty list")
            if not isinstance(specs, list):
                continue
            for i, spec in enumerate(specs):
                if not isinstance(spec, Mapping):
                    errors.append(f"io_contract.{side}[{i}]: expected object")
                    continue
                _require(isinstance(spec.get("name"), str) and bool(spec.get("name")), errors,
                         f"io_contract.{side}[{i}].name: expected non-empty string")
                _require(isinstance(spec.get("media_type"), str) and "/" in str(spec.get("media_type")),
                         errors, f"io_contract.{side}[{i}].media_type: expected e.g. application/json")
                shape = spec.get("shape")
                _require(isinstance(shape, list) and len(shape) > 0, errors,
                         f"io_contract.{side}[{i}].shape: expected non-empty list")
                _require(isinstance(spec.get("dtype"), str) and bool(spec.get("dtype")), errors,
                         f"io_contract.{side}[{i}].dtype: expected string")
        _require(isinstance(contract.get("batch_axis"), int), errors,
                 "io_contract.batch_axis: expected integer")
        loader = contract.get("loader")
        _require(isinstance(loader, Mapping), errors,
                 "io_contract.loader: expected object (kind + parameters)")
        if isinstance(loader, Mapping):
            _require(loader.get("kind") in LOADER_KINDS, errors,
                     f"io_contract.loader.kind: expected one of {sorted(LOADER_KINDS)}, "
                     f"got {loader.get('kind')!r}")

    # --- weights / artifacts --------------------------------------------- #
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append("artifacts: expected non-empty list")
        artifacts = []
    roles: list[str] = []
    for i, art in enumerate(artifacts):
        if not isinstance(art, Mapping):
            errors.append(f"artifacts[{i}]: expected object")
            continue
        role = art.get("role")
        roles.append(role)
        _require(role in ARTIFACT_ROLES, errors,
                 f"artifacts[{i}].role: expected one of {sorted(ARTIFACT_ROLES)}, got {role!r}")
        path = art.get("path")
        _require(isinstance(path, str) and bool(path) and not str(path).startswith("/")
                 and ".." not in Path(str(path)).parts,
                 errors, f"artifacts[{i}].path: expected registry-relative POSIX path")
        _check_sha(art.get("sha256"), f"artifacts[{i}].sha256", errors)
        _require(isinstance(art.get("bytes"), int) and art.get("bytes", -1) >= 0, errors,
                 f"artifacts[{i}].bytes: expected non-negative int")
        if role == "weights":
            _require(isinstance(art.get("format"), str) and bool(art.get("format")), errors,
                     f"artifacts[{i}].format: weights need a declared format")
            _require(isinstance(art.get("framework"), str) and bool(art.get("framework")), errors,
                     f"artifacts[{i}].framework: weights need a declared framework")
    _require("weights" in roles, errors, "artifacts: at least one artifact must have role 'weights'")
    _require(len(roles) == len(set(roles)), errors, "artifacts: duplicate roles")

    # --- training data binding ------------------------------------------- #
    training = manifest.get("training_data")
    if not isinstance(training, Mapping):
        errors.append("training_data: expected object")
    else:
        datasets = training.get("datasets")
        _require(isinstance(datasets, list) and len(datasets) > 0, errors,
                 "training_data.datasets: expected non-empty list")
        for i, ds in enumerate(datasets if isinstance(datasets, list) else []):
            if not isinstance(ds, Mapping):
                errors.append(f"training_data.datasets[{i}]: expected object")
                continue
            _require(isinstance(ds.get("dataset_ref"), str) and bool(ds.get("dataset_ref")), errors,
                     f"training_data.datasets[{i}].dataset_ref: expected non-empty string")
            _require(isinstance(ds.get("dataset_version"), str), errors,
                     f"training_data.datasets[{i}].dataset_version: expected string")
            _check_fingerprint(ds.get("fingerprint"), f"training_data.datasets[{i}].fingerprint", errors)
            if "artifact_sha256" in ds:
                _check_sha(ds.get("artifact_sha256"), f"training_data.datasets[{i}].artifact_sha256",
                           errors)
        _check_fingerprint(training.get("fingerprint"), "training_data.fingerprint", errors)
        split = training.get("split")
        _require(isinstance(split, Mapping), errors, "training_data.split: expected object")
        if isinstance(split, Mapping):
            for key in ("scheme", "seed", "n_train", "n_test"):
                _require(key in split, errors, f"training_data.split.{key}: required")

    # --- evaluation ------------------------------------------------------- #
    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, Mapping):
        errors.append("evaluation: expected object")
    else:
        _require(isinstance(evaluation.get("protocol"), str) and bool(evaluation.get("protocol")),
                 errors, "evaluation.protocol: expected non-empty string (what was held out)")
        _require(isinstance(evaluation.get("metrics"), Mapping) and bool(evaluation.get("metrics")),
                 errors, "evaluation.metrics: expected per-target metric mapping")
        _require(evaluation.get("status") in {"evaluated", "not_evaluated"},
                 errors, "evaluation.status: expected 'evaluated' or 'not_evaluated'")
        if evaluation.get("status") == "evaluated":
            _require("eval_card" in roles, errors,
                     "evaluation.status='evaluated' requires an 'eval_card' artifact")

    # --- applicability domain -------------------------------------------- #
    domain = manifest.get("applicability_domain")
    if not isinstance(domain, Mapping):
        errors.append("applicability_domain: expected object")
    else:
        _require(isinstance(domain.get("description"), str) and bool(domain.get("description")),
                 errors, "applicability_domain.description: expected non-empty string")
        _require(isinstance(domain.get("bounds"), Mapping), errors,
                 "applicability_domain.bounds: expected object of named numeric ranges")
        if isinstance(domain.get("bounds"), Mapping):
            for name, rng in domain["bounds"].items():
                ok = (isinstance(rng, list) and len(rng) == 2 and all(_is_number(v) for v in rng)
                      and rng[0] <= rng[1])
                _require(ok, errors,
                         f"applicability_domain.bounds.{name}: expected [low, high] with low<=high")
        _require(domain.get("out_of_domain_policy") in OUT_OF_DOMAIN_POLICIES, errors,
                 "applicability_domain.out_of_domain_policy: expected 'flag' or 'reject'")
        _require(isinstance(domain.get("caveats"), list), errors,
                 "applicability_domain.caveats: expected list of strings")

    # --- provenance / rights --------------------------------------------- #
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance: expected object")
    else:
        _require(isinstance(provenance.get("created_by"), str) and bool(provenance.get("created_by")),
                 errors, "provenance.created_by: expected non-empty string")
        _require(isinstance(provenance.get("repro_cmd"), str) and bool(provenance.get("repro_cmd")),
                 errors, "provenance.repro_cmd: expected the one-line reproduction command")
    rights = manifest.get("rights")
    _require(isinstance(rights, Mapping) and isinstance(rights.get("license", None), str)
             and bool(rights.get("license")), errors,
             "rights.license: expected non-empty SPDX/license expression")
    if isinstance(rights, Mapping):
        _require(isinstance(rights.get("data_license"), str), errors,
                 "rights.data_license: expected string")

    # --- self checksum ---------------------------------------------------- #
    if "manifest_sha256" in manifest:
        _check_sha(manifest["manifest_sha256"], "manifest_sha256", errors)
        if not errors:
            _require(manifest["manifest_sha256"] == canonical_checksum(manifest), errors,
                     "manifest_sha256: does not match canonical checksum of the manifest body")
    return errors


def assert_valid(manifest: Mapping[str, Any]) -> None:
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestError("invalid model manifest:\n  - " + "\n  - ".join(errors))


def check_artifact_files(manifest: Mapping[str, Any], model_dir: str | Path) -> list[dict]:
    """Recompute every declared artifact digest from the files on disk."""
    model_dir = Path(model_dir)
    results = []
    for art in manifest.get("artifacts", []):
        path = model_dir / art["path"]
        if not path.is_file():
            results.append({"role": art.get("role"), "path": art.get("path"), "ok": False,
                            "detail": "missing file"})
            continue
        actual_sha = sha256_file(path)
        actual_bytes = path.stat().st_size
        ok = actual_sha == art.get("sha256") and actual_bytes == art.get("bytes")
        results.append({
            "role": art.get("role"), "path": art.get("path"), "ok": ok,
            "expected_sha256": art.get("sha256"), "actual_sha256": actual_sha,
            "expected_bytes": art.get("bytes"), "actual_bytes": actual_bytes,
            "detail": "" if ok else "sha256/bytes mismatch (weights or artifact swapped)",
        })
    return results


def check_training_binding(manifest: Mapping[str, Any], model_dir: str | Path) -> dict:
    """Recompute the training-table fingerprint declared in the manifest.

    Returns ``{"status": "ok"|"mismatch"|"unchecked", ...}``.  ``unchecked`` is
    used when the uploaded table cannot be located (it is large and may be
    delivered separately); the artifact digests still bind the manifest.
    """
    training = manifest.get("training_data") or {}
    recipe = training.get("fingerprint_recipe")
    if not isinstance(recipe, Mapping):
        return {"status": "unchecked", "ok": True,
                "detail": "no fingerprint_recipe declared (array digests only)"}
    rel = recipe.get("table_path")
    path = Path(model_dir) / str(rel)
    if not rel or not path.is_file():
        return {"status": "unchecked", "ok": True,
                "detail": f"training table not present in registry ({rel})"}
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - environment dependent
        return {"status": "unchecked", "ok": True, "detail": "numpy unavailable"}

    if path.suffix == ".npz":
        with np.load(path) as data:
            arrays = {name: data[name] for name in recipe.get("arrays", {})}
    else:
        return {"status": "unchecked", "ok": True,
                "detail": f"unsupported table format {path.suffix}"}

    recomputed = fingerprint_arrays(arrays, recipe.get("extra"))
    declared = training.get("fingerprint")
    ok = recomputed["fingerprint"] == declared
    array_ok = all(recomputed["arrays"].get(k) == v
                   for k, v in (recipe.get("array_digests") or recomputed["arrays"]).items())
    return {
        "status": "ok" if (ok and array_ok) else "mismatch",
        "ok": bool(ok and array_ok),
        "declared": declared,
        "recomputed": recomputed["fingerprint"],
        "arrays": recomputed["arrays"],
        "table_path": str(rel),
        "detail": "" if (ok and array_ok) else "training-table fingerprint mismatch: "
                                               "manifest does not belong to this training data",
    }


def summarize_targets(manifest: Mapping[str, Any]) -> list[str]:
    return [t.get("name") for t in manifest.get("task", {}).get("targets", []) if isinstance(t, Mapping)]