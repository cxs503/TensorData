"""Geometry descriptors for container payloads (STL meshes today)."""

from .stl import (
    MeshStats,
    load_triangles,
    measure_triangles,
    read_stl,
    volume_below,
)

__all__ = ["MeshStats", "load_triangles", "measure_triangles", "read_stl", "volume_below"]
