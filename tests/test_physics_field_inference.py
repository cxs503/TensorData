"""Tests for column field/unit inference (PV stage-3 gap-filler).

Fixtures are real-shaped ship-resistance tables written inline: the point of the
tests is the *inference rule*, not a mock of the validator.
"""
import json

import pytest

from tensordata.quality.fields import (
    UNKNOWN_RATE_LIMIT,
    build_profile,
    infer_column,
    monotonic_axis_within_groups,
    profile_columns,
    profile_columns_from_file,
)
from tensordata.quality.physics_csv import validate_physics_csv
from tensordata.quality.units import convert_value, get_unit, si_scale

ENVELOPE = (
    "variant,group,Fn,V_kn,Re,CF,Ct,Rt_kN,Pe_kW,iE_deg,S\n"
    "NOM,nominal,0.1,9.231794944425568,927898027.75,0.0015449245,0.0020755935,"
    "226.1101004668271,1073.8514768644047,13.904320695720699,9424.0\n"
    "NOM,nominal,0.12,11.078153933310682,1113477633.30,0.0015104000,0.0020410446,"
    "320.1788573143817,1824.7280669617812,13.904320695720699,9424.0\n"
)


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------ unit registry
def test_knot_and_kilonewton_stay_distinct():
    # ``kn`` keeps its historical kilonewton meaning; knots are ``knot``/``kt``.
    assert get_unit("kn").dimension == "force"
    assert si_scale("kn", "N") == 1000.0
    assert get_unit("knot").dimension == "velocity"
    assert convert_value(1.0, "knot", "m/s") == pytest.approx(1852.0 / 3600.0)


def test_new_dimensions_used_by_the_ship_export():
    assert si_scale("kw", "W") == pytest.approx(1000.0)
    assert si_scale("deg", "rad") == pytest.approx(0.017453292519943295)
    assert si_scale("m2", "m2") == 1.0
    with pytest.raises(ValueError):
        si_scale("kn", "m/s")  # force vs velocity must not silently convert


# --------------------------------------------------------------- name resolution
@pytest.mark.parametrize(
    ("column", "field", "unit"),
    [
        ("Rt_kN", "Rt", "kn"),
        ("V_kn", "V", "knot"),
        ("V_ms", "V", "m/s"),
        ("Pe_kW", "Pe", "kw"),
        ("iE_deg", "iE", "deg"),
        ("one_plus_k", "one_plus_k", None),
    ],
)
def test_case_sensitive_suffix_resolution(column, field, unit):
    spec, source_unit, basis = infer_column(column)
    assert spec is not None and spec.symbol == field
    assert source_unit == unit
    assert basis


def test_unknown_column_is_reported_unknown_not_guessed():
    report = profile_columns(["Fn", "mystery"], [{"Fn": "0.1", "mystery": "3.0"}])
    assert report["unknown_columns"] == ["mystery"]
    assert report["unknown_rate"] == pytest.approx(0.5)
    assert not report["meets_unknown_limit"]


def test_categorical_columns_are_not_counted_as_numeric():
    headers, rows = ENVELOPE.splitlines()[0].split(","), [
        dict(zip(ENVELOPE.splitlines()[0].split(","), line.split(",")))
        for line in ENVELOPE.splitlines()[1:]
    ]
    report = profile_columns(headers, rows)
    assert report["numeric_columns"] == 9
    assert {entry["column"] for entry in report["columns"] if entry["kind"] == "categorical"} == {
        "variant", "group"
    }


# ----------------------------------------------------------------- identification
def test_identification_gives_si_factor_and_redundancy_agreement(tmp_path):
    text = ENVELOPE + (
        "NOM,nominal,0.14,12.924512922195799,1299057238.85,0.0014821048,0.0020252952,"
        "432.4362221758879,2875.2416845788703,13.904320695720699,9424.0\n"
    )
    path = _write(tmp_path, "envelope.csv", text)
    report = profile_columns_from_file(path)
    assert report["unknown_rate"] == 0.0
    factors = {entry["column"]: entry["si_scale"] for entry in report["columns"]
               if entry["kind"] == "numeric"}
    assert factors["Rt_kN"] == pytest.approx(1000.0)
    assert factors["V_kn"] == pytest.approx(1852.0 / 3600.0)
    assert factors["iE_deg"] == pytest.approx(0.017453292519943295)
    assert all(entry["confidence"] in {"high", "medium"} for entry in report["columns"]
               if entry["status"] == "identified")


def test_speed_columns_in_two_units_are_cross_checked(tmp_path):
    text = (
        "Fn,V_kn,V_ms\n"
        "0.1,9.231794944425568,4.749241518390067\n"
        "0.2,18.463589888851136,9.498483036780135\n"
    )
    path = _write(tmp_path, "speeds.csv", text)
    report = profile_columns_from_file(path)
    assert report["redundancy_checks"], "expected a V redundancy check"
    check = report["redundancy_checks"][0]
    assert set(check["columns"]) == {"V_kn", "V_ms"}
    assert check["agrees"] is True
    assert check["worst_relative_deviation"] < 1e-6


def test_column_name_suffix_contradicting_dimension_is_a_conflict(tmp_path):
    path = _write(tmp_path, "bad.csv", "Fn,Rt_kn\n0.1,226.11\n")
    report = profile_columns_from_file(path)
    assert report["broken_unit_columns"] == ["Rt_kn"]
    conflict = next(entry for entry in report["columns"] if entry["column"] == "Rt_kn")
    assert conflict["status"] == "unit_conflict"
    assert any("dimension_conflict" in item for item in conflict["basis"])


# ------------------------------------------------------------- grouped axis check
def test_axis_monotonicity_is_checked_per_group():
    rows = [{"variant": "NOM", "Fn": "0.1"}, {"variant": "NOM", "Fn": "0.2"},
            {"variant": "A", "Fn": "0.1"}, {"variant": "A", "Fn": "0.2"}]
    result = monotonic_axis_within_groups(rows, "Fn", "variant")
    assert result["monotonic_within_groups"] is True
    assert result["groups"] == 2

    broken = rows + [{"variant": "A", "Fn": "0.15"}]
    assert monotonic_axis_within_groups(broken, "Fn", "variant")["monotonic_within_groups"] is False


# ------------------------------------------------------- round trip through the chain
def test_inferred_profile_replays_through_the_physics_validator(tmp_path):
    path = _write(tmp_path, "envelope.csv", ENVELOPE)
    report = profile_columns_from_file(path)
    profile = build_profile(report, profile_id="round-trip", axis_columns=[])
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile), encoding="utf-8")

    validated = validate_physics_csv(path, profile_path, rights_status="cleared")
    assert validated["overall_status"] == "passed"
    assert validated["summary"]["unit_conversions"]["Rt_kN"] == {
        "source_unit": "kn", "target_unit": "N"
    }
    assert validated["summary"]["unit_conversions"]["iE_deg"] == {
        "source_unit": "deg", "target_unit": "rad"
    }

    # out-of-range value must fail the range check
    corrupted = _write(tmp_path, "corrupt.csv", ENVELOPE.replace("226.1101004668271",
                                                                "-226.1101004668271"))
    bad = validate_physics_csv(corrupted, profile_path, rights_status="cleared")
    assert bad["overall_status"] == "failed"
    bounds = next(check for check in bad["checks"]
                  if check["check_id"] == "dataset.physical_bounds")
    assert bounds["state"] == "failed"

    # a mislabeled unit must fail the unit check and never upgrade to passed
    mislabeled = json.loads(json.dumps(profile))
    for variable in mislabeled["variables"]:
        if variable["name"] == "Rt_kN":
            variable["source_unit"] = "knot"
    mislabeled_path = tmp_path / "profile.mislabeled.json"
    mislabeled_path.write_text(json.dumps(mislabeled), encoding="utf-8")
    bad_units = validate_physics_csv(path, mislabeled_path, rights_status="cleared")
    assert bad_units["overall_status"] == "failed"
    units = next(check for check in bad_units["checks"]
                 if check["check_id"] == "dataset.units_resolvable")
    assert units["state"] == "failed"


def test_unknown_rate_limit_is_ten_percent():
    assert UNKNOWN_RATE_LIMIT == pytest.approx(0.10)