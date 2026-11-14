"""Small explicit SI unit registry for deterministic physics CSV validation.

This is intentionally not a general-purpose units package. Unknown units remain
inconclusive; no dimensional meaning is guessed from arbitrary strings.
"""
from __future__ import annotations

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
    "s": Unit("time", 1.0),
    "ms": Unit("time", 0.001),
    "min": Unit("time", 60.0),
    "h": Unit("time", 3600.0),
    "kg": Unit("mass", 1.0),
    "g": Unit("mass", 0.001),
    "kg/m3": Unit("density", 1.0),
    "g/cm3": Unit("density", 1000.0),
    "m/s": Unit("velocity", 1.0),
    "km/h": Unit("velocity", 1.0 / 3.6),
    "pa": Unit("pressure", 1.0),
    "kpa": Unit("pressure", 1000.0),
    "mpa": Unit("pressure", 1_000_000.0),
    "n": Unit("force", 1.0),
    "kn": Unit("force", 1000.0),
    "k": Unit("temperature", 1.0),
    "degc": Unit("temperature", 1.0, 273.15),
    "c": Unit("temperature", 1.0, 273.15),
}


def normalize_unit(value: str) -> str:
    return " ".join(str(value).strip().lower().replace("³", "3").split())


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
