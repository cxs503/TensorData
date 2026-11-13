"""Model weight-file inventory: discovery, git status, registry reconciliation."""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.model_asset_inventory import build_inventory, to_markdown
from tensordata.modelreg import ModelRegistry
from tests.test_modelreg import make_model, register


def test_inventory_finds_loose_and_registered_weights(tmp_path):
    repo = tmp_path / "somerepo"
    (repo / "weights").mkdir(parents=True)
    loose = repo / "weights" / "surrogate.pt"
    loose.write_bytes(b"\x00\x01fake-torch-payload")
    (repo / "notes.txt").write_text("not a weight file")

    fixture = make_model(tmp_path, seed=41)
    registry_root = tmp_path / "registry"
    registry = ModelRegistry(registry_root)
    register(registry, fixture)

    inventory = build_inventory(scan_roots=[repo], registry_roots=[registry_root])
    summary = inventory["summary"]
    assert summary["n_loose_files"] == 1
    assert summary["n_weight_files"] == 1
    assert summary["n_torch_pt"] == 1
    entry = inventory["entries"][0]
    assert entry["path"].endswith("surrogate.pt")
    assert entry["provenance_status"] == "unregistered"
    assert entry["tracked"] is None  # not inside a git repository
    assert entry["registered_as"] == []

    markdown = to_markdown(inventory)
    assert "surrogate.pt" in markdown
    assert "**unregistered**" in markdown


def test_inventory_links_a_file_to_its_model_identity(tmp_path):
    """A weight file that is byte-identical to a registered artifact must be linked."""
    fixture = make_model(tmp_path, seed=42)
    registry_root = tmp_path / "registry"
    register(ModelRegistry(registry_root), fixture)

    copy_dir = tmp_path / "elsewhere"
    copy_dir.mkdir()
    copy = copy_dir / "copy_of_weights.npz"
    copy.write_bytes(fixture["weights"].read_bytes())

    inventory = build_inventory(scan_roots=[copy_dir], registry_roots=[registry_root])
    loose = [e for e in inventory["entries"] if e.get("location") == "loose_file"]
    assert len(loose) == 1
    assert loose[0]["provenance_status"] == "registered"
    assert loose[0]["registered_as"][0]["model_id"] == "synthetic-affine"


def test_inventory_classifies_registry_payloads_separately(tmp_path):
    fixture = make_model(tmp_path, seed=43)
    registry_root = tmp_path / "registry"
    register(ModelRegistry(registry_root), fixture)
    inventory = build_inventory(scan_roots=[registry_root], registry_roots=[registry_root])
    payloads = [e for e in inventory["entries"]
                if e.get("location") == "registry_payload"]
    assert payloads, inventory["summary"]
    assert all(e["provenance_status"] == "registered" for e in payloads)
    assert inventory["summary"]["n_loose_files"] == 0


def test_inventory_ignores_non_weight_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "model.json").write_text("{}")
    (repo / "data.csv").write_text("a,b\n1,2\n")
    inventory = build_inventory(scan_roots=[repo], registry_roots=[tmp_path / "empty"])
    assert inventory["summary"]["n_weight_files"] == 0


def test_inventory_cli_writes_json(tmp_path):
    import json
    import subprocess

    repo = Path(__file__).resolve().parents[1]
    out = tmp_path / "inv.json"
    result = subprocess.run([sys.executable, "scripts/model_asset_inventory.py",
                             "--scan", str(tmp_path), "--registry", str(tmp_path / "reg"),
                             "--out", str(out), "--markdown", str(tmp_path / "inv.md")],
                            cwd=repo, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    body = json.loads(out.read_text())
    assert body["schema"] == "model-asset-inventory/1.0"
    assert (tmp_path / "inv.md").read_text().startswith("- weight files found")