"""hull-mesh profile: accepts a real closed shell, rejects placeholder geometry."""

from pathlib import Path

import pytest

from tensordata.geometry import load_triangles, measure_triangles, volume_below
from tensordata.quality import QualityEngine, build_default_registry, measure_file


def _cube():
    v = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5),
         (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)]
    f = [(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [(v[a], v[b], v[c]) for a, b, c in f]


def _write_ascii(path: Path, tris) -> Path:
    lines = ["solid t"]
    for tri in tris:
        lines.append("facet normal 0 0 0")
        lines.append("outer loop")
        for p in tri:
            lines.append(f"vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
        lines.append("endloop")
        lines.append("endfacet")
    lines.append("endsolid t")
    path.write_text("\n".join(lines))
    return path


def _prism_tris(n_sides: int = 300):
    """Closed polygonal prism: n_sides side quads + two fans, watertight by construction."""
    import math

    ring = [(math.cos(2 * math.pi * i / n_sides), math.sin(2 * math.pi * i / n_sides))
            for i in range(n_sides)]
    bot = [(x, y, 0.0) for x, y in ring]
    top = [(x, y, 1.0) for x, y in ring]
    cb = (0.0, 0.0, 0.0)
    ct = (0.0, 0.0, 1.0)
    tris = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        tris.append((bot[i], bot[j], top[j]))
        tris.append((bot[i], top[j], top[i]))
        tris.append((cb, bot[j], bot[i]))          # bottom cap, faces -z
        tris.append((ct, top[i], top[j]))          # top cap, faces +z
    return tris


def test_cube_volume_and_plane_integral_are_analytic():
    stats = measure_triangles(_cube(), "ascii")
    assert stats.n_triangles == 12
    assert stats.is_closed
    assert stats.volume == pytest.approx(1.0, rel=1e-12)
    assert volume_below(_cube(), 0.0)[0] == pytest.approx(0.5, rel=1e-12)
    assert volume_below(_cube(), 0.25)[0] == pytest.approx(0.75, rel=1e-12)
    assert volume_below(_cube(), 0.25)[1] == pytest.approx(1.0)


def test_placeholder_mesh_is_rejected(tmp_path):
    """A 304-triangle open placeholder (the observed ship-platform failure mode) must fail."""
    tris = _prism_tris(76)[:303]  # omit one face so the surface is genuinely open
    path = _write_ascii(tmp_path / "placeholder.stl", tris)
    engine = QualityEngine(build_default_registry())
    scan = measure_file(path)
    result = engine.run("hull-mesh", path, expected_sha256=scan.sha256,
                        expected_size_bytes=scan.size_bytes)
    assert result.status == "failed"
    ids = {f.rule_id for f in result.findings if f.severity == "error"}
    assert "mesh.triangle_count_floor" in ids
    assert "mesh.closed_manifold" in ids


def test_closed_high_resolution_mesh_passes(tmp_path):
    tris = _prism_tris(300)  # 1200 triangles, closed manifold by construction
    assert measure_triangles(tris, "ascii").is_closed
    path = _write_ascii(tmp_path / "hull.stl", tris)
    engine = QualityEngine(build_default_registry())
    scan = measure_file(path)
    result = engine.run("hull-mesh", path, expected_sha256=scan.sha256,
                        expected_size_bytes=scan.size_bytes)
    assert result.status == "passed", result.finding_dicts()
    assert result.summary["mesh_closed"] is True
    assert result.summary["mesh_triangle_count"] == len(tris)


def test_checksum_mismatch_fails(tmp_path):
    path = _write_ascii(tmp_path / "hull.stl", _prism_tris(300))
    engine = QualityEngine(build_default_registry())
    scan = measure_file(path)
    result = engine.run("hull-mesh", path, expected_sha256="0" * 64,
                        expected_size_bytes=scan.size_bytes)
    assert result.status == "failed"
    assert "file.sha256_matches_metadata" in {f.rule_id for f in result.findings}


def test_unparsable_payload_reports_parse_error(tmp_path):
    path = tmp_path / "garbage.stl"
    path.write_bytes(b"not an stl at all" * 10)
    engine = QualityEngine(build_default_registry())
    scan = measure_file(path)
    result = engine.run("hull-mesh", path, expected_sha256=scan.sha256,
                        expected_size_bytes=scan.size_bytes)
    assert result.status == "failed"
    assert any(f.rule_id.startswith("mesh.") for f in result.findings)
