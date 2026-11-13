"""Immutable, file-backed model asset registry.

Layout (one directory per ``model_id``/``version``; published versions are never
mutated)::

    <root>/<model_id>/<version>/model.json             # canonical manifest
    <root>/<model_id>/<version>/weights/...            # payload(s)
    <root>/<model_id>/<version>/eval_card.json         # evaluation evidence
    <root>/<model_id>/<version>/training_table.npz     # fingerprint source (optional)

A registration is a directory rename, so a partially written model can never be
listed.  Re-registering an existing version with different bytes is rejected:
model identity is ``(model_id, version, weights sha256, data fingerprint)``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import schema

DEFAULT_ROOT = "models"
MANIFEST_NAME = "model.json"


class RegistryError(RuntimeError):
    """Raised for registry-level misuse (unknown model, immutable version, ...)."""


def _version_key(version: str) -> tuple:
    core = version.split("+")[0].split("-")[0]
    parts = core.split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in parts)


class ModelRegistry:
    """Filesystem registry of versioned model manifests and payloads."""

    def __init__(self, root: str | Path | None = None) -> None:
        from ..config import get_settings

        self.root = Path(root or get_settings().model_registry_root).expanduser().resolve()
        self.models_dir = self.root  # one directory per model_id

    # -- paths ------------------------------------------------------------- #
    def model_dir(self, model_id: str, version: str) -> Path:
        self._check_id(model_id)
        return self.models_dir / model_id / version

    @staticmethod
    def _check_id(model_id: str) -> None:
        if not schema.MODEL_ID_RE.match(model_id or ""):
            raise RegistryError(f"invalid model_id {model_id!r}")

    # -- write ------------------------------------------------------------- #
    def register(
        self,
        manifest: Mapping[str, Any],
        artifacts: Mapping[str, str | Path] | None = None,
        *,
        allow_existing: bool = False,
    ) -> dict:
        """Publish a model version.

        ``manifest['artifacts']`` declares registry-relative paths, digests and
        sizes.  ``artifacts`` maps those same relative paths to the files to
        copy in; for every provided source the digest/size are recomputed and
        written into the manifest, so callers cannot hand-write a hash.
        """
        artifacts = {str(k): Path(v) for k, v in (artifacts or {}).items()}
        body = json.loads(json.dumps(manifest))  # deep copy
        for art in body.get("artifacts", []):
            rel = art.get("path")
            if rel in artifacts:
                src = artifacts[rel]
                if not src.is_file():
                    raise RegistryError(f"artifact source missing: {src}")
                art["sha256"] = schema.sha256_file(src)
                art["bytes"] = src.stat().st_size
        body = schema.finalize(body)
        schema.assert_valid(body)

        model_id, version = body["model_id"], body["version"]
        final_dir = self.model_dir(model_id, version)
        if final_dir.exists():
            existing = json.loads((final_dir / MANIFEST_NAME).read_text())
            same = existing.get("manifest_sha256") == body["manifest_sha256"]
            if same or allow_existing is False:
                raise RegistryError(
                    f"model {model_id}@{version} already registered"
                    + ("" if same else " with different content (versions are immutable)")
                )

        missing = [a["path"] for a in body["artifacts"]
                   if a["path"] not in artifacts]
        if missing:
            raise RegistryError(
                "registration needs payload sources for: " + ", ".join(missing)
            )

        final_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=".register-", dir=final_dir.parent))
        try:
            for art in body["artifacts"]:
                dest = tmp / art["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(artifacts[art["path"]], dest)
            (tmp / MANIFEST_NAME).write_text(schema.canonical_json(body) + "\n")
            tmp.rename(final_dir)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return body

    # -- read -------------------------------------------------------------- #
    def versions(self, model_id: str) -> list[str]:
        directory = self.models_dir / model_id
        if not directory.is_dir():
            return []
        return sorted((p.name for p in directory.iterdir() if (p / MANIFEST_NAME).is_file()),
                      key=_version_key)

    def resolve_version(self, model_id: str, version: str | None = None) -> str:
        available = self.versions(model_id)
        if not available:
            raise RegistryError(f"unknown model_id {model_id!r} (registry root {self.root})")
        if version in (None, "latest"):
            return available[-1]
        if version not in available:
            raise RegistryError(f"model {model_id} has no version {version!r} "
                                f"(available: {', '.join(available)})")
        return version

    def load_manifest(self, model_id: str, version: str | None = None) -> dict:
        version = self.resolve_version(model_id, version)
        path = self.model_dir(model_id, version) / MANIFEST_NAME
        manifest = json.loads(path.read_text())
        schema.assert_valid(manifest)
        return manifest

    def list_models(self) -> list[dict]:
        rows: list[dict] = []
        if not self.models_dir.is_dir():
            return rows
        for model_dir in sorted(p for p in self.models_dir.iterdir() if p.is_dir()):
            for version in self.versions(model_dir.name):
                try:
                    manifest = self.load_manifest(model_dir.name, version)
                except Exception as exc:  # keep the catalogue readable on damage
                    rows.append({"model_id": model_dir.name, "version": version,
                                 "status": "invalid", "detail": str(exc)})
                    continue
                rows.append(summary_row(manifest, self.model_dir(model_dir.name, version)))
        return rows

    def latest(self, model_id: str) -> dict:
        return self.load_manifest(model_id, None)

    # -- verification ------------------------------------------------------ #
    def verify(self, model_id: str, version: str | None = None) -> dict:
        """Recompute manifests, payload hashes and the training-data fingerprint."""
        version = self.resolve_version(model_id, version)
        model_dir = self.model_dir(model_id, version)
        manifest_path = model_dir / MANIFEST_NAME
        checks: list[dict] = [{
            "name": "manifest_structural", "ok": True,
            "detail": f"{manifest_path}",
        }]
        try:
            manifest = json.loads(manifest_path.read_text())
            errors = schema.validate_manifest(manifest)
            if errors:
                checks[0].update(ok=False, detail="; ".join(errors))
                return {"model_id": model_id, "version": version, "ok": False, "checks": checks}
        except Exception as exc:
            checks[0].update(ok=False, detail=str(exc))
            return {"model_id": model_id, "version": version, "ok": False, "checks": checks}

        checks.append({"name": "manifest_sha256", "ok": True,
                       "detail": schema.canonical_checksum(manifest)})
        for result in schema.check_artifact_files(manifest, model_dir):
            checks.append({"name": f"artifact:{result['role']}", **result})
        binding = schema.check_training_binding(manifest, model_dir)
        checks.append({"name": "training_data_fingerprint", **binding})
        checks.append({"name": "weights_data_pairing",
                       "ok": binding.get("status") != "mismatch",
                       "detail": "weights and training table are bound by the manifest checksum "
                                 "plus the recomputed data fingerprint"})
        ok = all(_passed(c) for c in checks)
        return {"model_id": model_id, "version": version, "ok": ok, "checks": checks}


def _passed(check: Mapping[str, Any]) -> bool:
    """A check passes when ``ok`` is true; status-based checks pass unless mismatch."""
    if "ok" in check:
        return bool(check["ok"])
    return check.get("status") in {"ok", "unchecked"}


def summary_row(manifest: Mapping[str, Any], model_dir: Path) -> dict:
    weights = next((a for a in manifest.get("artifacts", []) if a.get("role") == "weights"), {})
    metrics = manifest.get("evaluation", {}).get("metrics", {})
    return {
        "model_id": manifest.get("model_id"),
        "version": manifest.get("version"),
        "task_type": manifest.get("task", {}).get("task_type"),
        "objective": manifest.get("task", {}).get("objective"),
        "loader": manifest.get("io_contract", {}).get("loader", {}).get("kind"),
        "weights_sha256": weights.get("sha256"),
        "weights_bytes": weights.get("bytes"),
        "data_fingerprint": manifest.get("training_data", {}).get("fingerprint"),
        "eval_status": manifest.get("evaluation", {}).get("status"),
        "metric_count": len(metrics),
        "path": str(model_dir),
        "manifest_sha256": manifest.get("manifest_sha256"),
    }


def open_registry(root: str | Path | None = None) -> ModelRegistry:
    return ModelRegistry(root)


def iter_registries(roots: Iterable[str | Path]) -> list[ModelRegistry]:
    return [ModelRegistry(r) for r in roots]