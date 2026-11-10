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

__all__ = [
    "QUALITY_RULESET_VERSION",
    "RULESET_VERSION",
    "CsvScan",
    "EngineResult",
    "FileScan",
    "Finding",
    "Profile",
    "QualityEngine",
    "Rule",
    "RuleContext",
    "RuleOutcome",
    "RuleRegistry",
    "UnknownProfileError",
    "build_default_registry",
    "measure_file",
]

QUALITY_RULESET_VERSION = RULESET_VERSION
