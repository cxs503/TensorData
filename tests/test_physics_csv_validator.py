import json

from tensordata.quality.physics_csv import PhysicsProfileError, validate_physics_csv


def _write_profile(tmp_path, checks=None):
    profile = {
        "profile_id": "ship-flow-test",
        "version": "0.1.0",
        "domain": "ship_flow",
        "variables": [
            {"name": "t", "role": "time", "unit": "s"},
            {"name": "u", "role": "state", "unit": "m/s"},
            {"name": "rho", "role": "state", "unit": "kg/m3", "valid_range": [0.01, 2000.0]},
        ],
        "checks": checks or [
            {"check_id": "finite", "kind": "finite_values", "required": True,
             "applicability": "all state values", "variables": ["u", "rho"]},
            {"check_id": "time", "kind": "monotonic_axis", "required": True,
             "applicability": "transient time axis", "variables": ["t"]},
            {"check_id": "units", "kind": "unit_consistency", "required": True,
             "applicability": "all declared units", "variables": ["u", "rho"]},
            {"check_id": "bounds", "kind": "physical_bounds", "required": True,
             "applicability": "declared admissible range", "variables": ["rho"]},
        ],
        "rights_policy": "require_cleared",
    }
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _write_csv(tmp_path, body):
    path = tmp_path / "fields.csv"
    path.write_text(body, encoding="utf-8")
    return path


def test_physics_csv_validator_passes_declared_deterministic_checks(tmp_path):
    profile = _write_profile(tmp_path)
    dataset = _write_csv(tmp_path, "t,u,rho\n0,1.2,998\n1,1.3,997\n2,1.4,996\n")
    report = validate_physics_csv(dataset, profile, rights_status="cleared")
    assert report["overall_status"] == "passed"
    assert {item["state"] for item in report["checks"]} == {"passed"}
    assert report["input_fingerprints"]["dataset_sha256"]
    assert report["evidence_refs"][0].startswith("file:sha256:")


def test_physics_csv_validator_detects_non_finite_values_and_bounds(tmp_path):
    profile = _write_profile(tmp_path)
    dataset = _write_csv(tmp_path, "t,u,rho\n0,nan,998\n1,1.3,-5\n")
    report = validate_physics_csv(dataset, profile, rights_status="cleared")
    assert report["overall_status"] == "failed"
    failed = {item["check_id"] for item in report["checks"] if item["state"] == "failed"}
    assert {"finite", "bounds"} <= failed


def test_physics_csv_validator_never_passes_unsupported_required_conservation(tmp_path):
    checks = [
        {"check_id": "mass-conservation", "kind": "conservation", "required": True,
         "applicability": "requires a declared control volume and flux formulation"}
    ]
    profile = _write_profile(tmp_path, checks)
    dataset = _write_csv(tmp_path, "t,u,rho\n0,1.2,998\n1,1.3,997\n")
    report = validate_physics_csv(dataset, profile, rights_status="cleared")
    assert report["overall_status"] == "inconclusive"
    assert report["checks"][0]["state"] == "inconclusive"


def test_physics_csv_validator_blocks_uncleared_rights(tmp_path):
    profile = _write_profile(tmp_path)
    dataset = _write_csv(tmp_path, "t,u,rho\n0,1.2,998\n1,1.3,997\n")
    report = validate_physics_csv(dataset, profile, rights_status="unknown")
    assert report["overall_status"] == "failed"
    assert any(item["check_id"] == "dataset.rights_cleared" for item in report["checks"])


def test_physics_csv_validator_rejects_duplicate_profile_variables(tmp_path):
    profile = _write_profile(tmp_path)
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["variables"].append(data["variables"][0])
    profile.write_text(json.dumps(data), encoding="utf-8")
    dataset = _write_csv(tmp_path, "t,u,rho\n0,1.2,998\n")
    try:
        validate_physics_csv(dataset, profile, rights_status="cleared")
    except PhysicsProfileError as exc:
        assert "duplicate variable" in str(exc)
    else:
        raise AssertionError("duplicate variables must be rejected")


def test_physics_csv_validator_does_not_accept_placeholder_unit_labels(tmp_path):
    profile = _write_profile(tmp_path)
    data = json.loads(profile.read_text(encoding="utf-8"))
    data["variables"][1]["unit"] = "REQUIRED: velocity unit"
    profile.write_text(json.dumps(data), encoding="utf-8")
    dataset = _write_csv(tmp_path, "t,u,rho\n0,1.2,998\n1,1.3,997\n")
    report = validate_physics_csv(dataset, profile, rights_status="cleared")
    assert report["overall_status"] == "inconclusive"
    unit_check = next(item for item in report["checks"] if item["check_id"] == "units")
    assert unit_check["state"] == "inconclusive"
