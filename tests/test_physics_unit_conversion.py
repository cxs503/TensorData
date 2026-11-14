import json

from tensordata.quality.physics_csv import validate_physics_csv


def _profile(path, *, source_unit, target_unit="kg/m3", valid_range=(990, 1000)):
    profile = {
        "profile_id": "unit-conversion",
        "version": "0.1.0",
        "domain": "ship_flow",
        "variables": [{
            "name": "rho", "role": "state", "unit": target_unit,
            "source_unit": source_unit, "valid_range": list(valid_range),
        }],
        "checks": [
            {"check_id": "units", "kind": "unit_consistency", "required": True,
             "applicability": "dimensional compatibility", "variables": ["rho"]},
            {"check_id": "bounds", "kind": "physical_bounds", "required": True,
             "applicability": "range in declared target unit", "variables": ["rho"]},
        ],
        "rights_policy": "metadata_only",
    }
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_density_values_are_converted_before_physical_range_check(tmp_path):
    profile = _profile(tmp_path / "profile.json", source_unit="g/cm3")
    dataset = tmp_path / "data.csv"
    dataset.write_text("rho\n0.998\n0.997\n", encoding="utf-8")
    report = validate_physics_csv(dataset, profile)
    assert report["overall_status"] == "passed"
    assert report["summary"]["unit_conversions"]["rho"] == {
        "source_unit": "g/cm3", "target_unit": "kg/m3"
    }
    bounds = next(check for check in report["checks"] if check["check_id"] == "bounds")
    assert bounds["state"] == "passed"


def test_incompatible_dimensions_fail_unit_check(tmp_path):
    profile = _profile(tmp_path / "profile.json", source_unit="s")
    dataset = tmp_path / "data.csv"
    dataset.write_text("rho\n998\n997\n", encoding="utf-8")
    report = validate_physics_csv(dataset, profile)
    units = next(check for check in report["checks"] if check["check_id"] == "units")
    assert units["state"] == "failed"
    assert "Incompatible physical dimensions" in units["details"]
    assert report["overall_status"] == "failed"


def test_unknown_units_are_inconclusive_not_silently_accepted(tmp_path):
    profile = _profile(tmp_path / "profile.json", source_unit="furlong/s")
    dataset = tmp_path / "data.csv"
    dataset.write_text("rho\n998\n997\n", encoding="utf-8")
    report = validate_physics_csv(dataset, profile)
    units = next(check for check in report["checks"] if check["check_id"] == "units")
    assert units["state"] == "inconclusive"
    assert report["overall_status"] == "inconclusive"


def test_temperature_offset_conversion_is_supported():
    from tensordata.quality.units import convert_value
    assert convert_value(0.0, "degC", "K") == 273.15
    assert convert_value(273.15, "K", "degC") == 0.0
