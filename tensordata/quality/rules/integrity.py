"""Integrity rules: payload measured against recorded artifact metadata.

Behavior and rule ids are identical to the legacy inline implementation
(``file.non_empty``, ``file.size_matches_metadata``,
``file.sha256_matches_metadata``).
"""

from __future__ import annotations

from ..base import SEVERITY_ERROR, Finding, Rule, RuleContext, RuleOutcome


class NonEmptyRule(Rule):
    rule_id = "file.non_empty"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        if ctx.scan.is_empty:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message="Artifact is empty",
                    )
                ]
            )
        return RuleOutcome()


class SizeMatchesMetadataRule(Rule):
    rule_id = "file.size_matches_metadata"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        if ctx.scan.size_bytes != ctx.expected_size_bytes:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message="Stored size differs from metadata",
                    )
                ]
            )
        return RuleOutcome()


class Sha256MatchesMetadataRule(Rule):
    rule_id = "file.sha256_matches_metadata"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        if ctx.scan.sha256 != ctx.expected_sha256:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message="Stored checksum differs from metadata",
                    )
                ]
            )
        return RuleOutcome()
