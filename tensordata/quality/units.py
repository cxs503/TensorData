"""Small explicit SI unit registry for deterministic physics CSV validation.

This is intentionally not a general-purpose units package. Unknown units remain
inconclusive; no dimensional meaning is guessed from arbitrary strings.

Case is significant before normalisation for one real ambiguity found in ship
resistance exports (PV-EX1 pilot): ``_kN`` is a force suffix (kilonewton) while
``_kn`` is a speed suffix (knot). Both would normalise to ``kn``. The registry
therefore keeps ``kn`` as kilonewton (existing behaviour, unchanged) and exposes
knots only under the unambiguous keys ``knot``/``kt``; callers that parse a
raw column suffix must resolve the case *before* calling here — see
``tensordata.quality.fields``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Unit:
    dimension: str
    scale: float
    offset: float = 0.0


_UNITS = {
    "1": Unit("dimensionless", 1.0),
    "dimensionless": Unit("dimensionless", 1.0),
    "m": Unit("length", 1.0),
    "cm": Unit("length", 0.01),
    "mm": Unit("length", 0.001),
    "km": Unit("length", 1000.0),
    "m2": Unit("area", 1.0),
    "cm2": Unit("area", 1e-4),
    "m3": Unit("volume", 1.0),
    "s": Unit("time", 1.0),
    "ms": Unit("time", 0.001),
    "min": Unit("time", 60.0),
    "h": Unit("time", 3600.0),
    "kg": Unit("mass", 1.0),
    "g": Unit("mass", 0.001),
    "kg/m3": Unit("density", 1.0),
    "g/cm3": Unit("density", 1000.0),
    "m/s": Unit("velocity", 1.0),
    "m/s2": Unit("acceleration", 1.0),
    "km/h": Unit("velocity", 1.0 / 3.6),
    # knots: 1852 m per 3600 s. Deliberately *not* spelled "kn" (kilonewton).
    "knot": Unit("velocity", 1852.0 / 3600.0),
    "kt": Unit("velocity", 1852.0 / 3600.0),
    "m2/s": Unit("kinematic_viscosity", 1.0),
    "pa": Unit("pressure", 1.0),
    "kpa": Unit("pressure", 1000.0),
    "mpa": Unit("pressure", 1_000_000.0),
    "n": Unit("force", 1.0),
    "kn": Unit("force", 1000.0),
    "w": Unit("power", 1.0),
    "kw": Unit("power", 1000.0),
    "mw": Unit("power", 1_000_000.0),
    "rad": Unit("angle", 1.0),
    "deg": Unit("angle", math.pi / 180.0),
    "degree": Unit("angle", math.pi / 180.0),
    "k": Unit("temperature", 1.0),
    "degc": Unit("temperature", 1.0, 273.15),
    "c": Unit("temperature", 1.0, 273.15),
}


def normalize_unit(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("³", "3").replace("²", "2").split())


def get_unit(value: str) -> Unit | None:
    return _UNITS.get(normalize_unit(value))


def compatible(source: str, target: str) -> bool:
    left, right = get_unit(source), get_unit(target)
    return left is not None and right is not None and left.dimension == right.dimension


def convert_value(value: float, source: str, target: str) -> float:
    left, right = get_unit(source), get_unit(target)
    if left is None or right is None:
        raise ValueError(f"unsupported unit conversion: {source!r} -> {target!r}")
    if left.dimension != right.dimension:
        raise ValueError(f"incompatible units: {source!r} -> {target!r}")
    return (value * left.scale + left.offset - right.offset) / right.scale


def si_scale(source: str, target: str) -> float:
    """Multiplicative factor such that ``value_source * factor == value_target``."""
    left, right = get_unit(source), get_unit(target)
    if left is None or right is None:
        raise ValueError(f"unsupported unit conversion: {source!r} -> {target!r}")
    if left.dimension != right.dimension:
        raise ValueError(f"incompatible units: {source!r} -> {target!r}")
    if left.offset or right.offset:
        raise ValueError("si_scale is undefined for offset units (temperature)")
    return left.scale / right.scale