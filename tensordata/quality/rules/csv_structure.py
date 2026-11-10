"""CSV structure rules for the tabular profile.

One shared streaming pass (``RuleContext.csv_scan``) feeds seven rules whose
finding ids, severities and messages mirror the legacy inline implementation
exactly. When the payload is not parseable as UTF-8 CSV, the statistics rules
stay silent and only ``tabular.csv_parseable`` fires — matching the legacy
try/except behaviour, including the edge where a bad header still reports
``tabular.header_present`` when parsing fails later during row iteration.
``CsvSummaryRule`` never fires a finding; it contributes the tabular summary
block the legacy code attached after a successful parse.
"""

from __future__ import annotations

from ..base import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    CsvScan,
    Finding,
    Rule,
    RuleContext,
    RuleOutcome,
)


def _header_check_applies(scan: CsvScan) -> bool:
    # A parse failure while reading the header suppressed the header finding
    # in the legacy implementation; a failure during rows did not.
    return scan.parse_error is None or scan.parse_error_phase == "rows"


def _finding(rule_id: str, severity: str, message: str, count: int | None = None) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, message=message, count=count)


class HeaderPresentRule(Rule):
    rule_id = "tabular.header_present"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        applies = _header_check_applies(scan)
        if applies and (not scan.headers or any(not header.strip() for header in scan.headers)):
            return RuleOutcome(
                findings=[
                    _finding(self.rule_id, SEVERITY_ERROR, "CSV must have non-empty column headers")
                ]
            )
        return RuleOutcome()


class RowsPresentRule(Rule):
    rule_id = "tabular.rows_present"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is None and scan.row_count == 0:
            return RuleOutcome(
                findings=[_finding(self.rule_id, SEVERITY_ERROR, "CSV contains no data rows")]
            )
        return RuleOutcome()


class RowWidthRule(Rule):
    rule_id = "tabular.row_width"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is None and scan.malformed_rows:
            return RuleOutcome(
                findings=[
                    _finding(
                        self.rule_id,
                        SEVERITY_ERROR,
                        "Rows do not match the header column count",
                        count=scan.malformed_rows,
                    )
                ]
            )
        return RuleOutcome()


class MissingCellsRule(Rule):
    rule_id = "tabular.missing_cells"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is None and scan.missing_cells:
            return RuleOutcome(
                findings=[
                    _finding(
                        self.rule_id,
                        SEVERITY_WARNING,
                        "Missing or blank cells detected",
                        count=scan.missing_cells,
                    )
                ]
            )
        return RuleOutcome()


class DuplicateRowsRule(Rule):
    rule_id = "tabular.duplicate_rows"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is None and scan.duplicate_rows:
            return RuleOutcome(
                findings=[
                    _finding(
                        self.rule_id,
                        SEVERITY_WARNING,
                        "Duplicate rows detected",
                        count=scan.duplicate_rows,
                    )
                ]
            )
        return RuleOutcome()


class CsvParseableRule(Rule):
    rule_id = "tabular.csv_parseable"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is not None:
            return RuleOutcome(
                findings=[
                    _finding(
                        self.rule_id,
                        SEVERITY_ERROR,
                        f"CSV parsing failed: {scan.parse_error}",
                    )
                ]
            )
        return RuleOutcome()


class CsvSummaryRule(Rule):
    """Contributes the legacy tabular summary block; never fires findings."""

    rule_id = "tabular.csv_summary"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        scan = ctx.csv_scan()
        if scan.parse_error is not None:
            return RuleOutcome()
        return RuleOutcome(
            summary={
                "row_count": scan.row_count,
                "column_count": len(scan.headers),
                "columns": scan.headers,
                "missing_cells": scan.missing_cells,
                "duplicate_rows": scan.duplicate_rows,
                "malformed_rows": scan.malformed_rows,
            }
        )
