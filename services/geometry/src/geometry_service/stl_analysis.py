"""STL -> GeometryIR (tessellated path: every value is inferred, never exact)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from OCP.RWStl import RWStl

from geometry_schema import (
    AnalysisInfo,
    Body,
    BodyKind,
    BoundingBox,
    GeometryIR,
    MassProperties,
    PrincipalAxis,
    SourceInfo,
    TopologyCounts,
)
from shared_types import Diagnostic, Representation, Severity, SourceFormat
from geometry_service.occt import geom as g
from geometry_service.occt.compat import kernel_version
from geometry_service.errors import CadImportError

Progress = Callable[[str, float], None]


def read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(nodes Nx3 float64, triangles Mx3 int64, 0-based). RWStl merges coincident nodes."""
    tri = RWStl.ReadFile_s(str(path))
    if tri is None or tri.NbTriangles() == 0:
        raise CadImportError("STL_READ_FAILED", "OCCT could not read any triangles from the STL file")
    nodes = np.array([g.pnt(tri.Node(i)) for i in range(1, tri.NbNodes() + 1)], dtype=np.float64)
    tris = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
    return nodes, tris


def _watertight(tris: np.ndarray) -> bool:
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    _, counts = np.unique(e, axis=0, return_counts=True)
    return bool(np.all(counts == 2))


def _mesh_mass(nodes: np.ndarray, tris: np.ndarray):
    """Volume, centroid and inertia tensor (unit density) via signed tetrahedra about the origin."""
    a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
    v = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0
    vol = v.sum()
    centroid = (v[:, None] * (a + b + c) / 4.0).sum(axis=0) / vol
    # second moments of each tetra (0, a, b, c): covariance-based canonical formula
    s = a + b + c
    cov = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            cov[i, j] = (
                v * (a[:, i] * a[:, j] + b[:, i] * b[:, j] + c[:, i] * c[:, j] + s[:, i] * s[:, j])
            ).sum() / 20.0
    cov -= vol * np.outer(centroid, centroid)
    inertia = np.trace(cov) * np.eye(3) - cov
    return float(vol), centroid, inertia


def analyze_stl(
    path: Path, *, filename: str, sha256: str, size_bytes: int, progress: Progress | None = None
) -> GeometryIR:
    report = progress or (lambda msg, pct: None)
    t0 = time.monotonic()
    report("Reading STL", 10)
    nodes, tris = read_stl(path)
    diagnostics = [
        Diagnostic(
            code="STL_UNITS_ASSUMED_MM",
            severity=Severity.WARNING,
            message="STL files carry no units; millimetres are assumed",
        ),
        Diagnostic(
            code="TESSELLATED_GEOMETRY",
            severity=Severity.WARNING,
            message="geometry is a triangle mesh: all measurements are approximations of the design surface",
        ),
        Diagnostic(
            code="STL_FEATURES_NOT_RECOGNIZED",
            severity=Severity.INFO,
            message="feature recognition on meshes is not implemented yet (milestone 1)",
        ),
    ]
    report("Measuring mesh", 50)
    lo, hi = tuple(nodes.min(axis=0)), tuple(nodes.max(axis=0))
    a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
    area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2.0)
    closed = _watertight(tris)
    principal: list[PrincipalAxis] = []
    if closed:
        vol, centroid, inertia = _mesh_mass(nodes, tris)
        if vol < 0:  # inward-facing orientation
            vol, centroid, inertia = -vol, centroid, -inertia
            diagnostics.append(
                Diagnostic(code="STL_INVERTED", severity=Severity.WARNING, message="triangles are oriented inward")
            )
        w, vecs = np.linalg.eigh(inertia)
        principal = sorted(
            (
                PrincipalAxis(direction=g.canonical_direction(tuple(float(x) for x in vecs[:, k])), moment=float(w[k]))
                for k in range(3)
            ),
            key=lambda p: (round(p.moment, 3), p.direction),
        )
        mass = MassProperties(volume=vol, surface_area=area, centroid=tuple(float(x) for x in centroid))
    else:
        diagnostics.append(
            Diagnostic(
                code="STL_NOT_WATERTIGHT",
                severity=Severity.WARNING,
                message="mesh is not watertight; volume and centroid are unavailable",
            )
        )
        mass = MassProperties(volume=None, surface_area=area, centroid=None)
    bbox = BoundingBox(min=lo, max=hi, size=g.sub(hi, lo))
    report("Assembling GeometryIR", 95)
    return GeometryIR(
        source=SourceInfo(
            filename=filename, format=SourceFormat.STL, sha256=sha256, size_bytes=size_bytes,
            kernel_version=kernel_version(),
        ),
        representation=Representation.TESSELLATED,
        bounding_box=bbox,
        mass_properties=mass,
        principal_axes=principal,
        symmetry_candidates=[],
        topology=TopologyCounts(
            solids=0, shells=1, faces=0, edges=0, vertices=int(len(nodes)), triangles=int(len(tris))
        ),
        bodies=[
            Body(
                id="BODY-1", kind=BodyKind.MESH, is_closed=closed, is_valid=None,
                mass_properties=mass, bounding_box=bbox,
            )
        ],
        faces=[],
        edges=[],
        vertices=[],
        features=[],
        diagnostics=diagnostics,
        analysis=AnalysisInfo(
            duration_s=round(time.monotonic() - t0, 3),
            linear_tolerance_mm=0.0,
            angular_tolerance_deg=0.0,
            recognizers=[],
            not_recognized=["ALL (mesh feature recognition planned)"],
        ),
    )
