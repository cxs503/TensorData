"""Quality engine: runs a profile against a payload and returns a report value.

Reliability rules baked in (stage 1, audit D1/D2/D3):
- the payload is measured once, streaming (1 MiB chunks);
- every report records ``measured_sha256`` / ``measured_size_bytes`` next to
  the recorded metadata it verified against (D1);
- a rule that raises is converted into an ``rule.execution_failed`` *error*
  finding — a crashing rule can never yield a passing report (D2);
- the executed rule list with per-rule versions lands in
  ``summary_json["executed_rules"]`` (D3).

The summary base keys (``size_bytes`` = measured size, ``sha256_verified``)
and the tabular keys match the legacy inline implementation exactly; all new
keys are additive.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .base import (
    SEVERITY_ERROR,
    EngineResult,
    FileScan,
    Finding,
    Profile,
    RuleContext,
    RuleOutcome,
)
from .registry import RULESET_VERSION, RuleRegistry

_CHUNK = 1024 * 1024


def measure_file(path: Path) -> FileScan:
    digest = sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(_CHUNK):
            size += len(chunk)
            digest.update(chunk)
    return FileScan(size_bytes=size, sha256=digest.hexdigest())


class QualityEngine:
    def __init__(self, registry: RuleRegistry):
        self._registry = registry

    @property
    def registry(self) -> RuleRegistry:
        return self._registry

    def run(
        self,
        profile_name: str,
        path: Path,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> EngineResult:
        profile: Profile = self._registry.get(profile_name)
        scan = measure_file(path)
        ctx = RuleContext(
            path=path,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            scan=scan,
        )

        findings: list[Finding] = []
        rule_summaries: list[dict[str, Any]] = []
        executed_rules: list[dict[str, str]] = []
        for rule in profile.rules:
            executed_rules.append({"rule_id": rule.rule_id, "version": rule.version})
            try:
                outcome: RuleOutcome = rule.run(ctx)
            except Exception as exc:  # noqa: BLE001 - rule isolation is the contract
                findings.append(
                    Finding(
                        rule_id="rule.execution_failed",
                        severity=SEVERITY_ERROR,
                        message=f"Rule {rule.rule_id} raised {type(exc).__name__} and did not complete",
                    )
                )
                continue
            findings.extend(outcome.findings)
            rule_summaries.append(outcome.summary)

        summary: dict[str, Any] = {
            "size_bytes": scan.size_bytes,
            "sha256_verified": scan.sha256 == expected_sha256,
        }
        for rule_summary in rule_summaries:
            summary.update(rule_summary)
        summary["measured_sha256"] = scan.sha256
        summary["measured_size_bytes"] = scan.size_bytes
        summary["profile_version"] = profile.version
        summary["executed_rules"] = executed_rules

        status = "failed" if any(f.severity == SEVERITY_ERROR for f in findings) else "passed"
        return EngineResult(
            status=status,
            ruleset_version=RULESET_VERSION,
            profile=profile_name,
            findings=findings,
            summary=summary,
        )
