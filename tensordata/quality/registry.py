"""Profile registry: named, composable, versioned rule bundles."""

from __future__ import annotations

from .base import Profile

# Externally visible ruleset version stored on every QualityReport.
# Bump only with a deliberate compatibility decision; stage 1 keeps "0.1.0"
# because rule behaviour and finding shapes are unchanged.
RULESET_VERSION = "0.1.0"


class UnknownProfileError(KeyError):
    """Raised when a check requests a profile that was never registered."""


class RuleRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, Profile] = {}

    def register(self, profile: Profile) -> None:
        if profile.name in self._profiles:
            raise ValueError(f"Profile already registered: {profile.name}")
        seen: set[str] = set()
        for rule in profile.rules:
            if rule.rule_id in seen:
                raise ValueError(f"Duplicate rule in profile {profile.name}: {rule.rule_id}")
            seen.add(rule.rule_id)
        self._profiles[profile.name] = profile

    def get(self, name: str) -> Profile:
        try:
            return self._profiles[name]
        except KeyError:
            raise UnknownProfileError(
                f"Unknown quality profile: {name!r}. Registered: {sorted(self._profiles)}"
            ) from None

    def profile_names(self) -> list[str]:
        return sorted(self._profiles)


def build_default_registry() -> RuleRegistry:
    """Wire the built-in 'general', 'tabular' and 'hull-mesh' profiles."""

    from .profiles.general import GENERAL_PROFILE
    from .profiles.hull_mesh import HULL_MESH_PROFILE
    from .profiles.tabular import TABULAR_PROFILE

    registry = RuleRegistry()
    registry.register(GENERAL_PROFILE)
    registry.register(TABULAR_PROFILE)
    registry.register(HULL_MESH_PROFILE)
    return registry
