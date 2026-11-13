"""Geometric quality rules for triangular surface meshes (STL payloads).

Rules operate on the payload path only and stay dependency-free (see
``tensordata.geometry.stl``). They exist because container geometry is the
upstream input of every CFD / potential-flow / structural pipeline: a mesh can
pass checksum integrity and still be an unusable placeholder, an open surface,
or a self-inconsistent volume.

Rule ids are stable and versioned individually; the report pins them through
``summary_json["executed_rules"]``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ...geometry.stl import MeshStats, read_stl
from ..base import SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING, Finding, Rule, RuleContext, RuleOutcome


@lru_cache(maxsize=64)
def _cached(path: str, size: int, mtime_ns: int) -> MeshStats:
    return read_stl(path)


def _mesh(ctx: RuleContext) -> MeshStats:
    stat = ctx.path.stat()
    return _cached(str(ctx.path), stat.st_size, stat.st_mtime_ns)


class StlParsesRule(Rule):
    """The payload must be a readable binary or ASCII STL with triangles."""

    rule_id = "mesh.stl_parses"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception as exc:  # noqa: BLE001 - any parse failure is the finding
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message=f"Payload is not a readable STL: {type(exc).__name__}: {exc}",
                    )
                ]
            )
        return RuleOutcome(
            summary={
                "mesh_format": m.fmt,
                "mesh_triangle_count": m.n_triangles,
                "mesh_unique_vertices": m.n_unique_vertices,
            }
        )


class TriangleCountFloorRule(Rule):
    """Reject meshes too coarse to represent a surface (placeholder guard).

    A hull expressed with a few hundred triangles has no usable curvature,
    waterline or bulb detail; downstream solvers silently produce garbage.
    """

    rule_id = "mesh.triangle_count_floor"
    version = "0.1.0"
    min_triangles = 1000

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:  # parse failure is reported by mesh.stl_parses
            return RuleOutcome()
        if m.n_triangles < self.min_triangles:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message=(
                            f"Mesh has {m.n_triangles} triangles, below the "
                            f"{self.min_triangles}-triangle floor (placeholder geometry)"
                        ),
                        count=m.n_triangles,
                    )
                ],
                summary={"mesh_triangle_floor": self.min_triangles},
            )
        return RuleOutcome(summary={"mesh_triangle_floor": self.min_triangles})


class DegenerateFaceRule(Rule):
    """Zero-area faces break normals, quadrature and volume evaluation."""

    rule_id = "mesh.degenerate_faces"
    version = "0.1.0"
    max_ratio = 1e-6

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        ratio = m.n_degenerate / m.n_triangles if m.n_triangles else 1.0
        summary = {"mesh_degenerate_faces": m.n_degenerate, "mesh_area_mean": round(m.area_mean, 9)}
        if ratio > self.max_ratio:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message=(
                            f"{m.n_degenerate} of {m.n_triangles} triangles are degenerate "
                            f"({ratio:.2e} > {self.max_ratio:.0e} allowed)"
                        ),
                        count=m.n_degenerate,
                    )
                ],
                summary=summary,
            )
        return RuleOutcome(summary=summary)


class ClosedManifoldRule(Rule):
    """A watertight, edge-manifold surface is required for volume & CFD walls."""

    rule_id = "mesh.closed_manifold"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        findings: list[Finding] = []
        if m.n_boundary_edges:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=SEVERITY_ERROR,
                    message=f"{m.n_boundary_edges} boundary (once-used) edges: surface is open",
                    count=m.n_boundary_edges,
                )
            )
        if m.n_nonmanifold_edges:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=SEVERITY_ERROR,
                    message=f"{m.n_nonmanifold_edges} edges shared by more than two faces",
                    count=m.n_nonmanifold_edges,
                )
            )
        summary = {
            "mesh_boundary_edges": m.n_boundary_edges,
            "mesh_nonmanifold_edges": m.n_nonmanifold_edges,
            "mesh_euler_characteristic": m.euler_characteristic,
            "mesh_closed": m.is_closed,
        }
        return RuleOutcome(findings=findings, summary=summary)


class VolumeFiniteRule(Rule):
    """Enclosed volume must be finite and non-zero.

    The magnitude is checked, not the sign: several published hull builders emit
    consistently inside-out windings, which is repairable, while a zero volume
    means the surface does not enclose anything at all.
    """

    rule_id = "mesh.volume_finite"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        summary = {
            "mesh_volume_signed": round(m.volume, 6),
            "mesh_volume_abs": round(m.volume_abs, 6),
            "mesh_surface_area": round(m.surface_area, 6),
        }
        if not (m.volume_abs > 0.0) or m.volume_abs != m.volume_abs:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message=f"Enclosed volume is zero or not finite: {m.volume!r}",
                    )
                ],
                summary=summary,
            )
        return RuleOutcome(summary=summary)


class WindingConsistencyRule(Rule):
    """Outward orientation is required by CFD wall/force integration.

    Reported as a warning: an inside-out but otherwise closed surface is
    repairable (re-orient the shell) rather than unusable.
    """

    rule_id = "mesh.winding_consistency"
    version = "0.1.0"
    max_inconsistent_ratio = 1e-2

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        ratio = m.n_inconsistent_edges / m.n_triangles if m.n_triangles else 1.0
        summary = {
            "mesh_inconsistent_edges": m.n_inconsistent_edges,
            "mesh_inside_out": bool(m.volume < 0.0),
        }
        findings: list[Finding] = []
        if m.volume < 0.0:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=SEVERITY_WARNING,
                    message="Faces are wound inward (signed volume < 0); re-orient before use",
                )
            )
        if ratio > self.max_inconsistent_ratio:
            findings.append(
                Finding(
                    rule_id=self.rule_id,
                    severity=SEVERITY_WARNING,
                    message=(
                        f"{m.n_inconsistent_edges} edges are traversed in the same direction by "
                        f"their two faces ({ratio:.2e} of triangles); local winding flips present"
                    ),
                    count=m.n_inconsistent_edges,
                )
            )
        return RuleOutcome(findings=findings, summary=summary)


class ExtentSanityRule(Rule):
    """Length/beam/depth extents must be finite and non-degenerate."""

    rule_id = "mesh.extent_sanity"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        extents = {"length": m.length, "beam": m.beam, "depth": m.depth}
        bad = {k: v for k, v in extents.items() if not (v > 0.0) or v != v}
        summary = {"mesh_extents": {k: round(v, 6) for k, v in extents.items()}}
        if bad:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_ERROR,
                        message=f"Degenerate mesh extent(s): {bad}",
                    )
                ],
                summary=summary,
            )
        return RuleOutcome(summary=summary)


class PortStarboardSymmetryRule(Rule):
    """Hull meshes are symmetric about y=0; asymmetry signals a broken builder.

    Measured on wetted/outer surface area per side, which is independent of face
    winding, so an inside-out shell does not masquerade as asymmetry.
    """

    rule_id = "mesh.port_starboard_symmetry"
    version = "0.1.0"
    max_error = 1e-3

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        summary = {"mesh_symmetry_error": round(m.symmetry_error, 9)}
        if m.symmetry_error > self.max_error:
            return RuleOutcome(
                findings=[
                    Finding(
                        rule_id=self.rule_id,
                        severity=SEVERITY_WARNING,
                        message=(
                            f"Port/starboard area mismatch {m.symmetry_error:.3e} exceeds "
                            f"{self.max_error:.0e}; verify the hull is intended to be asymmetric"
                        ),
                    )
                ],
                summary=summary,
            )
        return RuleOutcome(summary=summary)


class MeshNoteRule(Rule):
    """Surface formatting notes (triangle count, format) for the report body."""

    rule_id = "mesh.summary_note"
    version = "0.1.0"

    def run(self, ctx: RuleContext) -> RuleOutcome:
        try:
            m = _mesh(ctx)
        except Exception:
            return RuleOutcome()
        return RuleOutcome(
            findings=[
                Finding(
                    rule_id=self.rule_id,
                    severity=SEVERITY_INFO,
                    message=(
                        f"{m.fmt} STL: {m.n_triangles} triangles, {m.n_unique_vertices} vertices, "
                        f"volume={m.volume:.4f}, closed={m.is_closed}"
                    ),
                )
            ]
        )