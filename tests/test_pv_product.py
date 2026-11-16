"""Product-surface tests for the Physics Dataset Validator (PROD-PV 1.0.0)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tensordata.quality import IDENTITY, PRODUCT_ID, PRODUCT_VERSION, validate_physics_csv
from tensordata.quality.fields import profile_columns_from_file

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO = REPO_ROOT / "scripts" / "pv_demo.py"
FIXTURE_DIR = REPO_ROOT / "examples" / "pv-demo"


def run_demo(out_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DEMO), "--out-dir", str(out_dir), "--quiet", *extra],
        capture_output=True, text=True, timeout=300, check=False,
    )


def test_product_version_is_single_source(tmp_path: Path) -> None:
    report = validate_physics_csv(
        FIXTURE_DIR / "demo-resistance.csv",
        _fixture_profile(tmp_path),
    )
    assert report["product_id"] == PRODUCT_ID == "physics-dataset-validator"
    assert report["product_version"] == PRODUCT_VERSION == IDENTITY.product_version


def test_changelog_documents_the_shipped_version() -> None:
    changelog = (REPO_ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{PRODUCT_VERSION}]" in changelog, "CHANGELOG has no entry for the shipped version"
    for name in ("python3 scripts/pv_demo.py",
                 "docs/validators/PHYSICS_VALIDATOR_QUICKSTART.md"):
        assert name in changelog, f"CHANGELOG does not reference the shipped artifact {name}"


def test_demo_passes_fixture_and_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for target in (first, second):
        proc = run_demo(target, "--repeat", "2")
        assert proc.returncode == 0, proc.stderr[-2000:]
        evidence = json.loads((target / "evidence.json").read_text(encoding="utf-8"))
        dataset = evidence["datasets"][0]
        assert dataset["verdict"] == "passed"
        assert dataset["identified_columns"] == dataset["numeric_columns"] == 8
        assert dataset["unknown_columns"] == []
        # the kN / kn case trap must be resolved by the product and broken by the baseline
        assert dataset["baseline"]["mismatch_count"] == 1
        assert dataset["baseline"]["mismatched_columns"][0]["column"] == "V_kn"
        assert dataset["baseline"]["verdict"] == "failed"
        assert dataset["closures"]["implied_density_kg_m3"]["inside_window"] is True
    assert (json.loads((first / "evidence.json").read_text())["result_digest"]
            == json.loads((second / "evidence.json").read_text())["result_digest"])


def test_demo_injection_sensitivity_is_measured_not_claimed(tmp_path: Path) -> None:
    assert run_demo(tmp_path / "run", "--repeat", "1").returncode == 0
    evidence = json.loads((tmp_path / "run" / "evidence.json").read_text(encoding="utf-8"))
    cases = {case["case"]: case for case in evidence["injections"]}
    assert cases["out_of_range_value"]["detected"] is True
    assert cases["unit_mislabel_in_profile"]["detected"] is True
    assert cases["non_finite_cell"]["detected"] is True
    assert cases["unknown_column_gate"]["detected"] is True
    # documented limitation: a 10x scale error stays inside the declared range window
    assert cases["moderate_scale_error"]["detected"] is False
    assert cases["moderate_scale_error"]["closure_detected"] is True


def test_unknown_rate_gate_is_a_ratio_not_a_column_rule(tmp_path: Path) -> None:
    """One unknown column in a 10-column table sits exactly on the 10% gate (documented)."""
    known = ["Fn", "Re", "CF", "CR", "CA", "Ct", "one_plus_k", "S", "V_kn"]
    header = ",".join(known + ["XX_mystery"])
    rows = [header]
    for index in range(3):
        rows.append(",".join(str(index + 1) for _ in range(len(known) + 1)))
    csv_path = tmp_path / "wide.csv"
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    report = profile_columns_from_file(csv_path)
    assert report["unknown_rate"] == pytest.approx(0.1)
    assert report["meets_unknown_limit"] is True, "the gate is a ratio, not a per-column rule"
    assert report["unknown_columns"] == ["XX_mystery"]


def _fixture_profile(tmp_path: Path) -> Path:
    from tensordata.quality.fields import build_profile

    report = profile_columns_from_file(FIXTURE_DIR / "demo-resistance.csv")
    profile = build_profile(report, profile_id="test-fixture", axis_columns=["Fn"])
    path = tmp_path / "fixture.profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path
