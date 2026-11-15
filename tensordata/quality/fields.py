"""Deterministic column field/unit inference for physics CSV tables.

The physics CSV adapter (``tensordata.quality.physics_csv``) validates a table
against a *hand-declared* profile. It cannot answer the question a reviewer of a
real export asks first: "for every numeric column, what physical field is this
and in which unit?" This module answers that question from evidence only:

1. an explicit symbol table (``Fn``, ``Rt``, ``Pe`` ...) for the domain,
2. a **case-sensitive** unit-suffix table (``_kN`` kilonewton vs ``_kn`` knot),
3. dimensional agreement between the suffix unit and the symbol's dimension,
4. magnitude plausibility inside a declared physical range,
5. cross-column redundancy (same field exported twice in two units).

Nothing is guessed from free text. A column that no rule recognises is reported
as ``unknown`` with ``source_unit = None``; the caller decides whether the
unknown rate is acceptable. Inferred units are returned with the exact SI
conversion factor (``si_scale``) so a reviewer can recompute every number by
hand, and the report is directly convertible into a physics validation profile
(``build_profile``) so the existing PV chain can then re-check the same table.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .units import get_unit, si_scale

UNKNOWN_RATE_LIMIT = 0.10


@dataclass(frozen=True)
class FieldSpec:
    symbol: str
    quantity: str
    dimension: str
    canonical_unit: str
    role: str
    valid_range: tuple[float, float] | None = None
    ambiguous_symbol: bool = False


#: Half-open physical ranges in the canonical SI unit. They are sanity gates for
#: a ship-scale resistance/power export, not type approval limits.
_FIELD_LIST: tuple[FieldSpec, ...] = (
    FieldSpec("Fn", "Froude number", "dimensionless", "1", "independent", (0.0, 1.5)),
    FieldSpec("Re", "Reynolds number", "dimensionless", "1", "derived", (0.0, 1e13)),
    FieldSpec("CF", "friction resistance coefficient", "dimensionless", "1", "derived", (0.0, 0.02)),
    FieldSpec("CR", "residuary resistance coefficient", "dimensionless", "1", "derived", (0.0, 0.02)),
    FieldSpec("CA", "correlation allowance coefficient", "dimensionless", "1", "derived", (0.0, 0.005)),
    FieldSpec("CAA", "air resistance coefficient", "dimensionless", "1", "derived", (0.0, 0.005)),
    FieldSpec("Ct", "total resistance coefficient", "dimensionless", "1", "derived", (0.0, 0.05)),
    FieldSpec("Cw", "wave resistance coefficient", "dimensionless", "1", "derived", (0.0, 0.05)),
    FieldSpec("one_plus_k", "form factor (1+k)", "dimensionless", "1", "constant", (1.0, 3.0)),
    FieldSpec("Rt", "total resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("Rf", "friction resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("Rw", "wave resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("RB", "bulbous-bow resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("Rtr", "transom resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("RA", "air resistance", "force", "N", "output", (0.0, 5e7)),
    FieldSpec("Pe", "effective power", "power", "W", "output", (0.0, 5e8)),
    FieldSpec("Ps", "shaft power", "power", "W", "output", (0.0, 5e8)),
    FieldSpec("Pd", "delivered power", "power", "W", "output", (0.0, 5e8)),
    FieldSpec("V", "ship speed", "velocity", "m/s", "independent", (0.0, 40.0)),
    FieldSpec("Vs", "service speed", "velocity", "m/s", "constant", (0.0, 40.0)),
    FieldSpec("S", "wetted surface area", "area", "m2", "constant", (1.0, 1e6), True),
    FieldSpec("iE", "waterline entrance half-angle", "angle", "rad", "constant", (0.0, math.pi / 2)),
    FieldSpec("Lpp", "length between perpendiculars", "length", "m", "constant", (1.0, 600.0)),
    FieldSpec("Lwl", "waterline length", "length", "m", "constant", (1.0, 600.0)),
    FieldSpec("B", "breadth", "length", "m", "constant", (0.5, 100.0), True),
    FieldSpec("T", "draft", "length", "m", "constant", (0.05, 40.0), True),
    FieldSpec("rho", "water density", "density", "kg/m3", "constant", (900.0, 1100.0)),
    FieldSpec("nu", "kinematic viscosity", "kinematic_viscosity", "m2/s", "constant", (1e-8, 1e-4)),
    FieldSpec("g", "gravitational acceleration", "acceleration", "m/s2", "constant", (9.0, 10.0)),
)

FIELDS: dict[str, FieldSpec] = {spec.symbol: spec for spec in _FIELD_LIST}

#: Case-insensitive fallback, only where the lower-cased symbol is unique in the
#: table and at least two characters long (``S`` must not alias ``s`` seconds).
_LOWER_ALIAS: dict[str, FieldSpec] = {}
for _spec in _FIELD_LIST:
    _key = _spec.symbol.lower()
    if len(_key) >= 2 and _key not in _LOWER_ALIAS:
        _LOWER_ALIAS[_key] = _spec
    elif len(_key) >= 2:
        _LOWER_ALIAS.pop(_key, None)  # ambiguous lower-cased symbol: drop alias

#: Column-name unit suffixes, **case sensitive**. ``kN`` is a force (kilonewton)
#: while ``kn`` is a speed (knot) — the collision that makes a case-insensitive
#: parser unsafe on real ship-resistance exports. ``ms`` is read as m/s (speed),
#: the convention used by the platform's own exports, not as milliseconds.
_UNIT_SUFFIXES: dict[str, str] = {
    "kN": "kn",
    "N": "n",
    "kn": "knot",
    "knot": "knot",
    "kt": "kt",
    "kW": "kw",
    "MW": "mw",
    "W": "w",
    "ms": "m/s",
    "m/s": "m/s",
    "m2": "m2",
    "m^2": "m2",
    "m3": "m3",
    "kg/m3": "kg/m3",
    "deg": "deg",
    "rad": "rad",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "s": "s",
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _read_table(csv_path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def infer_column(name: str) -> tuple[FieldSpec | None, str | None, list[str]]:
    """Resolve a column name to ``(field, source_unit, basis)``.

    ``source_unit`` is ``None`` when the name carries no unit suffix; the caller
    then falls back to the field's canonical unit and says so in the basis.
    """
    if name in FIELDS:
        return FIELDS[name], None, ["symbol_table"]
    parts = name.split("_")
    for cut in range(len(parts) - 1, 0, -1):
        head, tail = "_".join(parts[:cut]), "_".join(parts[cut:])
        spec = FIELDS.get(head) or _LOWER_ALIAS.get(head.lower())
        if spec is None:
            continue
        if tail in _UNIT_SUFFIXES:
            return spec, _UNIT_SUFFIXES[tail], ["symbol_table", f"unit_suffix:{tail}"]
        # underscore name such as one_plus_k whose tail is not a unit
        continue
    if name in _LOWER_ALIAS:
        return _LOWER_ALIAS[name], None, ["symbol_table_lowercase"]
    return None, None, []


def profile_columns(
    headers: Sequence[str],
    rows: Sequence[dict[str, str]],
) -> dict[str, Any]:
    """Per-column field/unit report for one CSV table."""
    columns: list[dict[str, Any]] = []
    numeric_names: list[str] = []
    for name in headers:
        values = [row.get(name, "") for row in rows]
        numbers = [_number(value) for value in values]
        numeric = bool(numbers) and all(value is not None for value in numbers)
        if not numeric:
            columns.append({
                "column": name,
                "kind": "categorical",
                "status": "not_numeric",
                "field": None,
                "source_unit": None,
                "canonical_unit": None,
                "si_scale": None,
            })
            continue
        numeric_names.append(name)
        spec, suffix_unit, basis = infer_column(name)
        entry: dict[str, Any] = {
            "column": name,
            "kind": "numeric",
            "row_count": len(numbers),
            "field": spec.symbol if spec else None,
            "quantity": spec.quantity if spec else None,
            "dimension": spec.dimension if spec else None,
            "role": spec.role if spec else None,
        }
        if spec is None:
            entry.update({
                "status": "unknown",
                "source_unit": None,
                "canonical_unit": None,
                "si_scale": None,
                "si_offset": None,
                "confidence": "unknown",
                "basis": [],
            })
            columns.append(entry)
            continue

        source_unit = suffix_unit or spec.canonical_unit
        basis = list(basis) + ([] if suffix_unit else ["canonical_unit_assumed"])
        source = get_unit(source_unit)
        if source is None:
            entry.update({
                "status": "unknown_unit",
                "source_unit": source_unit,
                "canonical_unit": spec.canonical_unit,
                "si_scale": None,
                "si_offset": None,
                "confidence": "low",
                "basis": basis + ["unit_not_in_registry"],
            })
            columns.append(entry)
            continue
        if source.dimension != spec.dimension:
            entry.update({
                "status": "unit_conflict",
                "source_unit": source_unit,
                "canonical_unit": spec.canonical_unit,
                "si_scale": None,
                "si_offset": None,
                "confidence": "low",
                "basis": basis + [
                    f"dimension_conflict: symbol dimension {spec.dimension} "
                    f"vs suffix unit dimension {source.dimension}"
                ],
            })
            columns.append(entry)
            continue

        factor = si_scale(source_unit, spec.canonical_unit)
        canonical = [number * factor for number in numbers]
        observed = {"min": min(canonical), "max": max(canonical), "unit": spec.canonical_unit}
        magnitude_ok = True
        if spec.valid_range:
            low, high = spec.valid_range
            magnitude_ok = all(low <= value <= high for value in canonical)
            basis.append("magnitude_within_declared_range" if magnitude_ok
                         else "magnitude_outside_declared_range")
        confidence = "high"
        if not suffix_unit or spec.ambiguous_symbol:
            confidence = "medium"
        if not magnitude_ok:
            confidence = "low"
        entry.update({
            "status": "identified",
            "source_unit": source_unit,
            "canonical_unit": spec.canonical_unit,
            "si_scale": factor,
            "si_offset": source.offset,
            "declared_range": list(spec.valid_range) if spec.valid_range else None,
            "observed_canonical_range": observed,
            "magnitude_within_range": magnitude_ok,
            "confidence": confidence,
            "basis": basis,
        })
        columns.append(entry)

    numeric_entries = [entry for entry in columns if entry["kind"] == "numeric"]
    identified = [e for e in numeric_entries if e["status"] == "identified"]
    unknown = [e["column"] for e in numeric_entries if e["status"] == "unknown"]
    broken_units = [e["column"] for e in numeric_entries
                    if e["status"] in {"unit_conflict", "unknown_unit"}]

    # Cross-column redundancy: the same field exported in two units must agree
    # after conversion; disagreement means one unit label is wrong.
    by_field: dict[str, list[dict[str, Any]]] = {}
    for entry in identified:
        by_field.setdefault(entry["column"].split("_")[0], []).append(entry)
    redundant: list[dict[str, Any]] = []
    for head, entries in by_field.items():
        if head not in FIELDS:
            continue
        spec = FIELDS[head]
        for index, left in enumerate(entries):
            for right in entries[index + 1:]:
                if left["source_unit"] == right["source_unit"]:
                    continue
                values_left = [_number(row.get(left["column"], "")) for row in rows]
                values_right = [_number(row.get(right["column"], "")) for row in rows]
                deviations = [
                    abs(a * left["si_scale"] - b * right["si_scale"])
                    / max(abs(a * left["si_scale"]), abs(b * right["si_scale"]), 1e-30)
                    for a, b in zip(values_left, values_right)
                    if a is not None and b is not None
                ]
                worst = max(deviations) if deviations else None
                redundant.append({
                    "field": spec.symbol,
                    "columns": [left["column"], right["column"]],
                    "worst_relative_deviation": worst,
                    "agrees": worst is not None and worst <= 1e-6,
                })
                for entry in (left, right):
                    if worst is not None and worst <= 1e-6:
                        entry["basis"].append(f"cross_column_agreement:{right['column']}"
                                              if entry is left else
                                              f"cross_column_agreement:{left['column']}")
                        entry["confidence"] = "high"

    rate = (len(unknown) / len(numeric_entries)) if numeric_entries else 0.0
    return {
        "columns": columns,
        "numeric_columns": len(numeric_entries),
        "identified_columns": len(identified),
        "unknown_columns": unknown,
        "broken_unit_columns": broken_units,
        "unknown_rate": rate,
        "unknown_rate_limit": UNKNOWN_RATE_LIMIT,
        "meets_unknown_limit": rate <= UNKNOWN_RATE_LIMIT,
        "redundancy_checks": redundant,
        "all_units_resolved": not broken_units and not unknown,
    }


def profile_columns_from_file(csv_path: str | Path) -> dict[str, Any]:
    headers, rows = _read_table(csv_path)
    report = profile_columns(headers, rows)
    report["source"] = str(Path(csv_path).resolve())
    return report


def build_profile(
    column_report: dict[str, Any],
    *,
    profile_id: str,
    version: str = "0.1.0",
    domain: str = "ship_resistance",
    rights_policy: str = "allow_internal_restricted",
    axis_columns: Sequence[str] = (),
) -> dict[str, Any]:
    """Turn an inference report into a physics CSV validation profile.

    Only ``identified`` numeric columns become variables; unknown columns are
    listed in ``notes.unknown_columns`` so the omission is visible rather than
    silently dropping a column from the gate.
    """
    variables: list[dict[str, Any]] = []
    for entry in column_report["columns"]:
        if entry.get("status") != "identified":
            continue
        variable: dict[str, Any] = {
            "name": entry["column"],
            "role": entry["role"],
            "unit": entry["canonical_unit"],
            "source_unit": entry["source_unit"],
        }
        if entry.get("declared_range"):
            variable["valid_range"] = list(entry["declared_range"])
        variables.append(variable)
    names = [variable["name"] for variable in variables]
    checks: list[dict[str, Any]] = [
        {
            "check_id": "dataset.finite_values",
            "kind": "finite_values",
            "required": True,
            "applicability": "all recognised columns present and finite",
            "variables": names,
        },
        {
            "check_id": "dataset.units_resolvable",
            "kind": "unit_consistency",
            "required": True,
            "applicability": "declared source unit convertible to canonical SI unit",
            "variables": names,
        },
        {
            "check_id": "dataset.physical_bounds",
            "kind": "physical_bounds",
            "required": True,
            "applicability": "canonical SI values inside declared sanity range",
            "variables": names,
        },
    ]
    for axis in axis_columns:
        if axis in names:
            checks.append({
                "check_id": f"dataset.axis_monotonic.{axis}",
                "kind": "monotonic_axis",
                "required": True,
                "applicability": "rows ordered by the independent variable",
                "variables": [axis],
            })
    return {
        "profile_id": profile_id,
        "version": version,
        "domain": domain,
        "variables": variables,
        "checks": checks,
        "rights_policy": rights_policy,
        "notes": {
            "generated_by": "tensordata.quality.fields.build_profile",
            "unknown_columns": list(column_report["unknown_columns"]),
            "unit_conflict_columns": list(column_report["broken_unit_columns"]),
        },
    }

def monotonic_axis_within_groups(
    rows: Sequence[dict[str, str]],
    axis: str,
    group: str,
) -> dict[str, Any]:
    """Axis monotonicity per group for grouped exports (variant-major tables).

    The physics adapter's ``monotonic_axis`` check assumes the whole file is
    ordered by one axis. A variant envelope (13 variants x Fn grid) restarts the
    axis for each variant, so the file-level check fails spuriously. This helper
    checks the same property inside each group, which is the property the export
    actually promises.
    """
    groups: dict[str, list[float]] = {}
    offenders: list[str] = []
    for row_number, row in enumerate(rows, start=2):
        value = _number(row.get(axis, ""))
        if value is None:
            offenders.append(f"{axis}@row{row_number} is not finite numeric")
            continue
        groups.setdefault(row.get(group, ""), []).append(value)
    decreasing: list[str] = []
    for name, values in groups.items():
        collapsed = [value for index, value in enumerate(values)
                     if index == 0 or value != values[index - 1]]
        if not all(later > earlier for earlier, later in zip(collapsed, collapsed[1:])):
            decreasing.append(name)
    return {
        "axis": axis,
        "group_column": group,
        "groups": len(groups),
        "monotonic_within_groups": not decreasing and not offenders,
        "non_monotonic_groups": decreasing,
        "non_numeric": offenders,
        "rows_per_group": {name: len(values) for name, values in groups.items()},
    }
