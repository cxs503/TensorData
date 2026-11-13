#!/usr/bin/env python3
"""Inventory model-weight files on disk and reconcile them with the registry.

Background: the 2026-11-13 asset-form survey found that *model assets* are the
one form that exists only as loose files — trained weights without a declared
task, IO contract, training-data fingerprint or evaluation card.  Before
registering anything you need to know what is out there, and whether a file is
committed (an asset) or a local experiment (evidence only).

What it does
------------
* walks the scan roots for known weight-file extensions,
* records sha256/size/mtime, owning git repo and whether the file is tracked,
* reconciles the sha256 against every registered model artifact, so a weight
  file can be linked to a model identity instead of a path,
* emits a JSON report plus a compact markdown table.

Nothing here interprets the weights: the inventory is a *catalogue of unknowns*,
which is exactly what a registry is for.

Usage::

    python scripts/model_asset_inventory.py --scan /root/tensor-ecosystem . \
        --out artifacts/GAP-ASSET-MODEL-REGISTRY/inventory.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tensordata.modelreg import ModelRegistry, sha256_file  # noqa: E402

# ``.npz``/``.pkl``/``.bin`` are ambiguous by name (tables, caches); they are
# included because numpy/state-dict weights are common, and the sha256
# reconciliation — not the filename — decides whether a file *is* a model asset.
WEIGHT_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".pkl", ".joblib", ".safetensors",
                   ".npz", ".h5", ".hdf5", ".bin", ".params", ".msgpack"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
             ".ruff_cache", "site-packages", "dist", "build", ".mypy_cache"}


# Filename triage only: the suffix says nothing about whether a file is a model
# asset, so each candidate gets a *hint* that a human (or the registry) must
# confirm.  `weights`-looking files inside a `models/` directory are the real
# candidates; `.pt` dumps under `cache/` or `artifacts/` are tensors, not models.
def path_hint(path: Path) -> str:
    parts = [p.lower() for p in path.parts]
    name = path.name.lower()
    if "cache" in parts or "_cache" in parts:
        return "benchmark_cache"
    if "models" in parts or "model" in parts[:-1]:
        return "model_dir"
    if any(tag in name for tag in ("weights", "state_dict", "checkpoint", "ckpt")):
        return "experiment_bundle"
    if any("bundle" in p or p.endswith(".ngo") for p in parts):
        return "experiment_bundle"
    if "artifacts" in parts:
        return "artifact_dump"
    return "unknown"


CANDIDATE_HINTS = {"model_dir", "experiment_bundle"}


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def git_context(path: Path) -> dict:
    top = _git(["rev-parse", "--show-toplevel"], path.parent)
    if not top:
        return {"repo": None, "tracked": None, "commit": None}
    repo = Path(top)
    rel = path.relative_to(repo).as_posix()
    tracked = _git(["ls-files", "--error-unmatch", rel], repo)
    commit = _git(["rev-parse", "HEAD"], repo)
    status = _git(["status", "--porcelain", "--", rel], repo)
    return {
        "repo": repo.name,
        "repo_path": str(repo),
        "tracked": tracked is not None,
        "commit": commit,
        "worktree_state": "clean" if status == "" else ("untracked" if status else "modified"),
    }


def iter_weight_files(roots: list[Path], registry_roots: list[Path]):
    registry_payloads: set[Path] = set()
    for root in registry_roots:
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in WEIGHT_SUFFIXES:
                    registry_payloads.add(p.resolve())
    for root in roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in WEIGHT_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            yield p, p.resolve() in registry_payloads


def load_registered_index(registry_roots: list[Path]) -> dict[str, list[dict]]:
    """sha256 -> [{model_id, version, role}] for every registered artifact."""
    index: dict[str, list[dict]] = {}
    for root in registry_roots:
        registry = ModelRegistry(root)
        for row in registry.list_models():
            if row.get("status") == "invalid":
                continue
            manifest = registry.load_manifest(row["model_id"], row["version"])
            for art in manifest.get("artifacts", []):
                index.setdefault(art["sha256"], []).append({
                    "model_id": row["model_id"], "version": row["version"],
                    "role": art.get("role"), "path": art.get("path"),
                })
    return index


def build_inventory(scan_roots=None, registry_roots=None, max_bytes: int | None = None) -> dict:
    roots = [Path(r).resolve() for r in (scan_roots or [REPO, Path("/root/tensor-ecosystem")])]
    reg_roots = [Path(r).resolve() for r in (registry_roots or [REPO / "models"])]
    registered = load_registered_index(reg_roots)

    entries = []
    for path, in_registry in iter_weight_files(roots, reg_roots):
        try:
            size = path.stat().st_size
            digest = sha256_file(path)
        except OSError as exc:  # unreadable file is information too
            entries.append({"path": str(path), "error": str(exc)})
            continue
        matches = registered.get(digest, [])
        ctx = {"repo": None, "tracked": None, "commit": None} if in_registry else git_context(path)
        entries.append({
            "path": str(path),
            "bytes": size,
            "sha256": digest,
            "suffix": path.suffix.lower(),
            "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                                  .isoformat(timespec="seconds"),
            "location": "registry_payload" if in_registry else "loose_file",
            "path_hint": "registry_payload" if in_registry else path_hint(path),
            "registered_as": matches,
            "provenance_status": "registered" if matches else "unregistered",
            **ctx,
        })

    loose = [e for e in entries if e.get("location") == "loose_file"]
    tracked = [e for e in loose if e.get("tracked")]
    summary = {
        "scan_roots": [str(r) for r in roots],
        "registry_roots": [str(r) for r in reg_roots],
        "n_weight_files": len(entries),
        "n_registry_payloads": sum(1 for e in entries if e.get("location") == "registry_payload"),
        "n_loose_files": len(loose),
        "n_loose_tracked_in_git": len(tracked),
        "n_unregistered": sum(1 for e in loose if e.get("provenance_status") == "unregistered"),
        "by_suffix": {},
        "by_repo": {},
        "n_torch_pt": sum(1 for e in entries if e.get("suffix") == ".pt"),
        "n_torch_pt_tracked": sum(1 for e in entries if e.get("suffix") == ".pt"
                                  and e.get("tracked")),
        "by_path_hint": {},
        "n_candidate_model_assets": 0,
        "n_tensor_dumps": 0,
    }
    for e in entries:
        hint = e.get("path_hint") or "unknown"
        summary["by_path_hint"][hint] = summary["by_path_hint"].get(hint, 0) + 1
        if hint in CANDIDATE_HINTS:
            summary["n_candidate_model_assets"] += 1
        if hint in {"benchmark_cache", "artifact_dump"}:
            summary["n_tensor_dumps"] += 1
        suffix = e.get("suffix") or "?"
        summary["by_suffix"][suffix] = summary["by_suffix"].get(suffix, 0) + 1
        repo = e.get("repo") or "(no git repo)"
        summary["by_repo"][repo] = summary["by_repo"].get(repo, 0) + 1
    return {
        "schema": "model-asset-inventory/1.0",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "weight_suffixes": sorted(WEIGHT_SUFFIXES),
        "summary": summary,
        "entries": sorted(entries, key=lambda e: (e.get("location") or "", e.get("path") or "")),
    }


def to_markdown(inventory: dict) -> str:
    s = inventory["summary"]
    lines = [
        "| model file | bytes | hint | git | sha256 (12) | registry |",
        "|---|---|---|---|---|---|",
    ]
    for e in inventory["entries"]:
        if not e.get("path"):
            continue
        git = ("tracked" if e.get("tracked") else
               ("untracked" if e.get("tracked") is False else ("registry" if e.get("location")
                                                                == "registry_payload" else "no-git")))
        reg = ", ".join(f"{m['model_id']}@{m['version']}/{m['role']}"
                        for m in e.get("registered_as", [])) or "**unregistered**"
        lines.append(f"| `{e['path']}` | {e.get('bytes')} | {e.get('path_hint')} | {git} | "
                     f"`{(e.get('sha256') or '')[:12]}` | {reg} |")
    head = (f"- weight files found: **{s['n_weight_files']}** "
            f"({s['n_loose_files']} loose, {s['n_registry_payloads']} registry payloads)\n"
            f"- loose files tracked in git: **{s['n_loose_tracked_in_git']}**; "
            f"unregistered: **{s['n_unregistered']}**\n"
            f"- `.pt` files: {s['n_torch_pt']} ({s['n_torch_pt_tracked']} tracked); "
            f"model-asset candidates: **{s['n_candidate_model_assets']}**, "
            f"tensor dumps/caches: {s['n_tensor_dumps']}\n")
    return head + "\n" + "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scan", nargs="*", default=None, help="roots to walk for weight files")
    parser.add_argument("--registry", nargs="*", default=None, help="registry roots to reconcile")
    parser.add_argument("--out", default=None, help="write JSON here")
    parser.add_argument("--markdown", default=None, help="write a markdown table here")
    args = parser.parse_args(argv)

    inventory = build_inventory(args.scan, args.registry)
    out = Path(args.out) if args.out else (
        REPO / "artifacts" / "GAP-ASSET-MODEL-REGISTRY" / "inventory.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2))
    if args.markdown:
        Path(args.markdown).write_text(to_markdown(inventory))
    print(json.dumps(inventory["summary"], indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())