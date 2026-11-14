"""Pure-python STL geometry measurement used by quality rules and pipelines.

The quality engine is a dependency-free library: rules must not require numpy or
trimesh. This module therefore parses both binary and ASCII STL with the
standard library only, and derives the geometric descriptors the hull-mesh
profile checks:

- triangle count, bounding box, surface area, signed volume (divergence form),
- degenerate (zero-area) faces,
- edge-use histogram -> boundary edges (used once) and non-manifold edges (>2),
- Euler characteristic of the face-vertex complex,
- winding defects (same-direction edge reuse) and the flips needed to repair
  them, plus the signed volume evaluated on the repaired shell,
- port/starboard area symmetry error (area is orientation-independent, so this
  stays meaningful on meshes whose faces are not all outward-wound).

Triangle vertices are keyed by their exact float32 bit pattern after rounding to
9 significant decimals; STL writers repeat the exact same float32 values for
shared edges, so exact keys are sufficient and avoid weld tolerance drift.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

_BINARY_HEADER = 80
_BINARY_TRI = 50
_COORD_DECIMALS = 9


@dataclass
class MeshStats:
    fmt: str
    n_triangles: int
    n_unique_vertices: int
    bbox_min: tuple[float, float, float]
    bbox_max: tuple[float, float, float]
    volume: float
    surface_area: float
    n_degenerate: int
    n_boundary_edges: int
    n_nonmanifold_edges: int
    n_inconsistent_edges: int
    n_winding_flips: int
    n_shells: int
    euler_characteristic: int
    symmetry_error: float
    area_mean: float
    notes: list[str] = field(default_factory=list)

    @property
    def length(self) -> float:
        return self.bbox_max[0] - self.bbox_min[0]

    @property
    def beam(self) -> float:
        return self.bbox_max[1] - self.bbox_min[1]

    @property
    def depth(self) -> float:
        return self.bbox_max[2] - self.bbox_min[2]

    @property
    def is_closed(self) -> bool:
        return self.n_boundary_edges == 0 and self.n_nonmanifold_edges == 0

    @property
    def volume_abs(self) -> float:
        return abs(self.volume)

    def to_dict(self) -> dict:
        return {
            "format": self.fmt,
            "n_triangles": self.n_triangles,
            "n_unique_vertices": self.n_unique_vertices,
            "bbox_min": list(self.bbox_min),
            "bbox_max": list(self.bbox_max),
            "length": round(self.length, 6),
            "beam": round(self.beam, 6),
            "depth": round(self.depth, 6),
            "volume": round(self.volume, 6),
            "volume_abs": round(self.volume_abs, 6),
            "surface_area": round(self.surface_area, 6),
            "n_degenerate": self.n_degenerate,
            "n_boundary_edges": self.n_boundary_edges,
            "n_nonmanifold_edges": self.n_nonmanifold_edges,
            "n_inconsistent_edges": self.n_inconsistent_edges,
            "n_winding_flips": self.n_winding_flips,
            "n_shells": self.n_shells,
            "euler_characteristic": self.euler_characteristic,
            "symmetry_error": round(self.symmetry_error, 6),
            "closed": self.is_closed,
        }


def _detect_format(path: Path) -> tuple[str, int]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(5)
    if head.lower() == b"solid":
        # Both ASCII and binary STL may begin with "solid". Prefer binary only
        # when the declared triangle count exactly matches the byte length.
        with path.open("rb") as fh:
            fh.read(_BINARY_HEADER)
            raw = fh.read(4)
        if len(raw) == 4:
            (count,) = struct.unpack("<I", raw)
            if size == _BINARY_HEADER + 4 + _BINARY_TRI * count:
                return "binary", size
        return "ascii", size
    return "binary", size
    if head.lower() == b"solid":
        # ASCII STL also starts with "solid"; decide on the exact binary length.
        with path.open("rb") as fh:
            fh.read(80)
            raw = fh.read(4)
        if len(raw) == 4:
            (count,) = struct.unpack("<I", raw)
            if size == _BINARY_HEADER + 4 + _BINARY_TRI * count:
                return "binary", size
        return "ascii", size
    return "binary", size


def _parse_binary(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    tris = []
    with path.open("rb") as fh:
        fh.read(_BINARY_HEADER)
        raw = fh.read(4)
        if len(raw) != 4:
            raise ValueError("binary STL truncated header")
        (count,) = struct.unpack("<I", raw)
        if path.stat().st_size != _BINARY_HEADER + 4 + _BINARY_TRI * count:
            raise ValueError("binary STL size inconsistent with declared triangle count")
        unpack = struct.Struct("<12fH").unpack
        for _ in range(count):
            rec = fh.read(_BINARY_TRI)
            if len(rec) != _BINARY_TRI:
                raise ValueError("binary STL truncated body")
            vals = unpack(rec)
            tris.append((vals[3:6], vals[6:9], vals[9:12]))
    return tris


def _parse_ascii(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    tris = []
    vertices: list[tuple[float, float, float]] = []
    with path.open("r", encoding="ascii", errors="replace") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
                if len(vertices) == 3:
                    tris.append(tuple(vertices))
                    vertices = []
    return tris


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _key(v):
    return (
        round(v[0], _COORD_DECIMALS),
        round(v[1], _COORD_DECIMALS),
        round(v[2], _COORD_DECIMALS),
    )


def _repair_winding(tris, edge_faces):
    """Propagate a consistent orientation across the face-adjacency graph.

    Returns (flip_flags, n_components, n_unvisited). ``edge_faces`` maps an
    undirected vertex-key edge to [(face_index, direction)] where direction is
    1 when the face traverses the edge from the smaller to the larger key.
    """
    n = len(tris)
    flip = [-1] * n
    components = 0
    for seed in range(n):
        if flip[seed] != -1:
            continue
        components += 1
        flip[seed] = 0
        stack = [seed]
        while stack:
            f = stack.pop()
            a, b, c = tris[f]
            ka, kb, kc = _key(a), _key(b), _key(c)
            for u, v in ((ka, kb), (kb, kc), (kc, ka)):
                k = (u, v) if u <= v else (v, u)
                d = 1 if u <= v else 0
                for g, dg in edge_faces[k]:
                    if g == f:
                        continue
                    # consistent orientation => the shared edge is traversed in
                    # opposite directions by the two faces, so neighbouring faces
                    # inherit the same flip parity only when d != dg.
                    expected = 1 - flip[f] if d == dg else flip[f]
                    if flip[g] == -1:
                        flip[g] = expected
                        stack.append(g)
    unvisited = sum(1 for x in flip if x == -1)
    return flip, components, unvisited


def _components_unvisited(n, flip):
    return sum(1 for x in flip if x == -1)


def measure_triangles(tris, fmt: str) -> MeshStats:
    """Measure a triangle soup (each triangle = 3 xyz tuples)."""
    if not tris:
        raise ValueError("mesh contains no triangles")

    xs = []
    ys = []
    zs = []
    edge_use: dict[tuple, int] = {}
    edge_faces: dict[tuple, list[tuple[int, int]]] = {}
    for idx, (a, b, c) in enumerate(tris):
        xs.extend((a[0], b[0], c[0]))
        ys.extend((a[1], b[1], c[1]))
        zs.extend((a[2], b[2], c[2]))
        ka, kb, kc = _key(a), _key(b), _key(c)
        for u, v in ((ka, kb), (kb, kc), (kc, ka)):
            k = (u, v) if u <= v else (v, u)
            edge_use[k] = edge_use.get(k, 0) + 1
            edge_faces.setdefault(k, []).append((idx, 1 if u <= v else 0))

    boundary = sum(1 for count in edge_use.values() if count == 1)
    nonmanifold = sum(1 for count in edge_use.values() if count > 2)
    # two faces sharing an edge in the same direction => inconsistent winding
    inconsistent = sum(1 for uses in edge_faces.values() if len(uses) == 2 and uses[0][1] == uses[1][1])

    flip, components, unvisited = _repair_winding(tris, edge_faces)
    n_flips = sum(1 for f in flip if f == 1)

    area_sum = 0.0
    vol6 = 0.0
    area_port = 0.0
    area_star = 0.0
    for idx, tri in enumerate(tris):
        a, b, c = tri
        if flip[idx] == 1:
            b, c = c, b
        n = _cross(_sub(b, a), _sub(c, a))
        norm = math.sqrt(_dot(n, n))
        area = 0.5 * norm
        area_sum += area
        vol6 += _dot(a, _cross(b, c))
        cy = (a[1] + b[1] + c[1]) / 3.0
        if cy > 0:
            area_port += area
        elif cy < 0:
            area_star += area

    n_tri = len(tris)
    area_mean = area_sum / n_tri
    eps = max(area_mean * 1e-9, 1e-15)
    degenerate = 0
    for tri in tris:
        a, b, c = tri
        n = _cross(_sub(b, a), _sub(c, a))
        if 0.5 * math.sqrt(_dot(n, n)) <= eps:
            degenerate += 1

    verts = {_key(v) for tri in tris for v in tri}
    euler = len(verts) - len(edge_use) + n_tri
    volume = vol6 / 6.0

    notes = []
    if n_flips:
        notes.append(f"winding repaired on {n_flips} faces")
    if components > 1:
        notes.append(f"{components} disconnected shells")
    if unvisited:
        notes.append(f"{unvisited} faces unreachable during winding repair")
    if degenerate:
        notes.append(f"{degenerate} zero-area triangles")

    return MeshStats(
        fmt=fmt,
        n_triangles=n_tri,
        n_unique_vertices=len(verts),
        bbox_min=(min(xs), min(ys), min(zs)),
        bbox_max=(max(xs), max(ys), max(zs)),
        volume=volume,
        surface_area=area_sum,
        n_degenerate=degenerate,
        n_boundary_edges=boundary,
        n_nonmanifold_edges=nonmanifold,
        n_inconsistent_edges=inconsistent,
        euler_characteristic=euler,
        symmetry_error=(abs(area_port - area_star) / (area_port + area_star)
                        if (area_port + area_star) else float("inf")),
        area_mean=area_mean,
        n_winding_flips=n_flips,
        n_shells=components,
        notes=notes,
    )


def load_triangles(path: Path | str) -> tuple[list, MeshStats]:
    """Parse an STL and return triangles re-oriented into a consistent shell.

    The returned triangles carry a coherent winding, which makes the signed
    volume meaningful even when the payload has local winding flips (a real
    defect in several published hull builders).
    """
    path = Path(path)
    fmt, _ = _detect_format(path)
    tris = _parse_binary(path) if fmt == "binary" else _parse_ascii(path)
    stats = measure_triangles(tris, fmt)
    if stats.n_winding_flips:
        edge_faces: dict[tuple, list[tuple[int, int]]] = {}
        for idx, (a, b, c) in enumerate(tris):
            ka, kb, kc = _key(a), _key(b), _key(c)
            for u, v in ((ka, kb), (kb, kc), (kc, ka)):
                k = (u, v) if u <= v else (v, u)
                edge_faces.setdefault(k, []).append((idx, 1 if u <= v else 0))
        flip, _, _ = _repair_winding(tris, edge_faces)
        tris = [(a, c, b) if flip[i] == 1 else (a, b, c) for i, (a, b, c) in enumerate(tris)]
    return tris, stats


def _clip_below(tri, level):
    """Clip a triangle to the half space z <= level (returns polygon vertices)."""
    out = []
    for i in range(3):
        p = tri[i]
        q = tri[(i + 1) % 3]
        pin = p[2] <= level
        qin = q[2] <= level
        if pin:
            out.append(p)
        if pin != qin:
            t = (level - p[2]) / (q[2] - p[2])
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), level))
    return out


def volume_below(tris, level: float) -> tuple[float, float, float]:
    """Volume below a horizontal plane, plus the submerged x-extent.

    Uses the vertical vector field F = (0, 0, max(z - level, 0)) ... in its
    equivalent form: for the closed shell, ``V(z<level) = oint (z-level) n_z dA``
    with the integrand restricted to the submerged triangles, because
    div(F)=1 below the plane and 0 above. For a triangle ``n_z dA`` is constant
    so each clipped polygon contributes ``mean(z-level) * 0.5 * cross_z``.
    """
    total = 0.0
    xs: list[float] = []
    for tri in tris:
        zs = (tri[0][2], tri[1][2], tri[2][2])
        if min(zs) > level:
            continue
        poly = _clip_below(tri, level) if min(zs) <= level < max(zs) else list(tri)
        if len(poly) < 3:
            continue
        for i in range(1, len(poly) - 1):
            a, b, c = poly[0], poly[i], poly[i + 1]
            cross_z = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            zbar = (a[2] + b[2] + c[2]) / 3.0
            total += (zbar - level) * 0.5 * cross_z
        if max(zs) >= level:
            for p in poly:
                if abs(p[2] - level) < 1e-12:
                    xs.append(p[0])
    length = (max(xs) - min(xs)) if len(xs) >= 2 else 0.0
    return total, length, (min(xs) if xs else 0.0)


def read_stl(path: Path | str) -> MeshStats:
    path = Path(path)
    fmt, _ = _detect_format(path)
    tris = _parse_binary(path) if fmt == "binary" else _parse_ascii(path)
    return measure_triangles(tris, fmt)