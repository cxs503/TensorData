"""Core types for the TensorData quality engine.

The engine is a pure library: it operates on filesystem paths and plain data,
with no FastAPI, SQLAlchemy or settings imports. The API layer resolves an
artifact to a path, calls the engine, and persists the returned result.

Versioning contract:
- ``RULESET_VERSION`` is the externally visible, test-pinned ruleset string
  stored on every ``QualityReport``.
- Each rule additionally carries its own ``version`` so reports can name the
  exact rule implementations that executed (``summary_json["executed_rules"]``).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class FileScan:
    """Measured properties of the payload bytes, taken in one streaming pass."""

    size_bytes: int
    sha256: str

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0


@dataclass
class CsvScan:
    """One streaming pass over a CSV payload.

    ``parse_error`` mirrors the legacy inline behaviour: a decode/parse failure
    during header reading discards the header finding too, while a failure
    during row iteration keeps findings emitted before the loop (the header
    check) and drops the row statistics.
    """

    headers: list[str] = field(default_factory=list)
    row_count: int = 0
    column_count: int = 0
    missing_cells: int = 0
    duplicate_rows: int = 0
    malformed_rows: int = 0
    parse_error: str | None = None
    parse_error_phase: str | None = None  # "header" | "rows"


@dataclass
class RuleContext:
    """Immutable inputs plus lazily computed, memoized format scans.

    Rules never touch the database or the request layer; they see a path, the
    recorded metadata they must verify against, and shared scans.
    """

    path: Path
    expected_sha256: str
    expected_size_bytes: int
    scan: FileScan
    _scans: dict[str, Any] = field(default_factory=dict, repr=False)

    def csv_scan(self) -> CsvScan:
        """Stream-parse the payload as UTF-8 CSV once; reuse across rules.

        Duplicate detection digests each normalized row (JSON encoding, then
        SHA-256) so memory stays bounded per row instead of holding the full
        text of every distinct row.
        """

        if "csv" not in self._scans:
            self._scans["csv"] = _parse_csv(self.path)
        return self._scans["csv"]


def _parse_csv(path: Path) -> CsvScan:
    import csv

    result = CsvScan()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source)
            try:
                result.headers = next(reader, [])
            except (UnicodeDecodeError, csv.Error) as exc:
                result.parse_error = str(exc)
                result.parse_error_phase = "header"
                return result
            seen_row_digests: set[str] = set()
            for row in reader:
                result.row_count += 1
                if len(row) != len(result.headers):
                    result.malformed_rows += 1
                normalized = tuple(value.strip() for value in row)
                result.missing_cells += sum(1 for value in normalized if not value)
                digest = sha256(
                    json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                if digest in seen_row_digests:
                    result.duplicate_rows += 1
                else:
                    seen_row_digests.add(digest)
            result.column_count = len(result.headers)
    except (UnicodeDecodeError, csv.Error) as exc:
        result.parse_error = str(exc)
        result.parse_error_phase = "rows"
        return result
    return result


@dataclass
class Finding:
    """One structured check result. Shape is the legacy findings_json entry."""

    rule_id: str
    severity: str
    message: str
    count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        finding: dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
        }
        if self.count is not None:
            finding["count"] = self.count
        return finding


@dataclass
class RuleOutcome:
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class Rule(ABC):
    """A single, independently versioned quality check."""

    rule_id: ClassVar[str]
    version: ClassVar[str]

    @abstractmethod
    def run(self, ctx: RuleContext) -> RuleOutcome: ...


@dataclass(frozen=True)
class Profile:
    """An ordered composition of rules under a stable name and version."""

    name: str
    version: str
    rules: tuple[Rule, ...]

    def rule_ids(self) -> list[str]:
        return [rule.rule_id for rule in self.rules]


@dataclass
class EngineResult:
    status: str  # "passed" | "failed"
    ruleset_version: str
    profile: str
    findings: list[Finding]
    summary: dict[str, Any]

    def finding_dicts(self) -> list[dict[str, Any]]:
        return [finding.to_dict() for finding in self.findings]
