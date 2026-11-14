"""TensorData quality engine.

Pure-library quality checks: profiles compose versioned rules, the engine
streams the payload once, isolates rule crashes as error findings, and returns
a report value the API layer persists. See docs/quality/engine.md.
"""

from .base import (
    CsvScan,
    EngineResult,
    FileScan,
    Finding,
    Profile,
    Rule,
    RuleContext,
    RuleOutcome,
)
from .engine import QualityEngine, measure_file
from .registry import RULESET_VERSION, RuleRegistry, UnknownProfileError, build_default_registry
from .physics_csv import PhysicsProfileError, validate_physics_csv

__all__ = [
    "QUALITY_RULESET_VERSION",
    "RULESET_VERSION",
    "CsvScan",
    "EngineResult",
    "FileScan",
    "Finding",
    "Profile",
    "PhysicsProfileError",
    "QualityEngine",
    "Rule",
    "RuleContext",
    "RuleOutcome",
    "RuleRegistry",
    "UnknownProfileError",
    "build_default_registry",
    "measure_file",
    "validate_physics_csv",
]

QUALITY_RULESET_VERSION = RULESET_VERSION
