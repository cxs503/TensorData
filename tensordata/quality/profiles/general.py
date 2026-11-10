"""The 'general' profile: integrity checks only (legacy behaviour)."""

from __future__ import annotations

from ..base import Profile
from ..rules import NonEmptyRule, Sha256MatchesMetadataRule, SizeMatchesMetadataRule

GENERAL_PROFILE = Profile(
    name="general",
    version="0.1.0",
    rules=(
        NonEmptyRule(),
        SizeMatchesMetadataRule(),
        Sha256MatchesMetadataRule(),
    ),
)
