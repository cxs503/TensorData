"""The 'tabular' profile: general integrity plus CSV structure checks.

Composes the general rules first so finding order matches the legacy inline
implementation (file.* before tabular.*).
"""

from __future__ import annotations

from ..base import Profile
from ..rules import (
    CsvParseableRule,
    CsvSummaryRule,
    DuplicateRowsRule,
    HeaderPresentRule,
    MissingCellsRule,
    NonEmptyRule,
    RowsPresentRule,
    RowWidthRule,
    Sha256MatchesMetadataRule,
    SizeMatchesMetadataRule,
)
from .general import GENERAL_PROFILE

TABULAR_PROFILE = Profile(
    name="tabular",
    version="0.1.0",
    rules=(
        # integrity first (legacy finding order)
        NonEmptyRule(),
        SizeMatchesMetadataRule(),
        Sha256MatchesMetadataRule(),
        # csv structure
        HeaderPresentRule(),
        RowsPresentRule(),
        RowWidthRule(),
        MissingCellsRule(),
        DuplicateRowsRule(),
        CsvParseableRule(),
        CsvSummaryRule(),
    ),
)

TABULAR_RULE_IDS = TABULAR_PROFILE.rule_ids()
GENERAL_RULE_IDS = GENERAL_PROFILE.rule_ids()
