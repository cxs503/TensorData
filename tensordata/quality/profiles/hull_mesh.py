"""The 'hull-mesh' profile: integrity plus triangular surface-geometry checks.

Intended for container hull / appendage surface meshes (binary or ASCII STL)
before they enter CFD, potential-flow or structural pipelines. It answers the
question ``is this geometry usable?`` rather than ``are these bytes the bytes we
recorded?``: the companion integrity rules are composed first so a consumed
payload still fails on a checksum mismatch.

Deliberately domain-agnostic in implementation (any closed triangle surface),
while the thresholds are tuned for ship hulls: a hull below ~1k triangles has no
usable waterline/bulb detail, and hull meshes are mirror-symmetric about y=0.
"""

from __future__ import annotations

from ..base import Profile
from ..rules import (
    NonEmptyRule,
    Sha256MatchesMetadataRule,
    SizeMatchesMetadataRule,
)
from ..rules.mesh_geometry import (
    ClosedManifoldRule,
    DegenerateFaceRule,
    ExtentSanityRule,
    MeshNoteRule,
    PortStarboardSymmetryRule,
    StlParsesRule,
    TriangleCountFloorRule,
    VolumeFiniteRule,
    WindingConsistencyRule,
)
HULL_MESH_PROFILE = Profile(
    name="hull-mesh",
    version="0.1.0",
    rules=(
        # integrity first, mirroring the general/tabular composition order
        NonEmptyRule(),
        SizeMatchesMetadataRule(),
        Sha256MatchesMetadataRule(),
        # geometry
        StlParsesRule(),
        TriangleCountFloorRule(),
        DegenerateFaceRule(),
        ClosedManifoldRule(),
        VolumeFiniteRule(),
        WindingConsistencyRule(),
        ExtentSanityRule(),
        PortStarboardSymmetryRule(),
        MeshNoteRule(),
    ),
)
