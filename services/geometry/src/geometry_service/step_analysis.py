"""STEP -> GeometryIR (exact B-Rep path)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopoDS import TopoDS_Shape

from geometry_schema import (
    AnalysisInfo,
    Axis,
    Body,
    BodyKind,
    BoundingBox,
    ConeSurface,
    Convexity,
    CylinderSurface,
    Edge,
    Face,
    GeometryIR,
    MassProperties,
    OtherSurface,
    PlaneSurface,
    PrincipalAxis,
    SourceInfo,
    SphereSurface,
    SurfaceType,
    SymmetryCandidate,
    TopologyCounts,
    TorusSurface,
    Vertex,
)
from shared_types import Diagnostic, Representation, Severity, SourceFormat
from geometry_service.step_metadata import read_step_metadata
from geometry_service import ids
from geometry_service.errors import CadImportError
from geometry_service.features.blends import recognize_chamfers, recognize_fillets
from geometry_service.features.context import RecognitionContext, Tolerances
from geometry_service.features.cylindrical import group_cylinders, recognize_bosses, recognize_holes
from geometry_service.features.patterns import recognize_hole_patterns
from geometry_service.features.prismatic import recognize_pockets, recognize_slots
from geometry_service.occt import geom as g
from geometry_service.occt.compat import AsciiStringSequence, kernel_version
from geometry_service.occt.convexity import PointClassifier, classify_edge
from geometry_service.occt.faces import describe_edge, describe_face, vertex_point
from geometry_service.occt.topology import TopologyIndex

Progress = Callable[[str, float], None]

RECOGNIZERS = ["HOLE", "BOSS", "SLOT", "POCKET", "FILLET", "CHAMFER", "PATTERN(HOLE)"]
NOT_RECOGNIZED = ["THREAD (not representable in plain B-Rep; needs PMI/user input)", "BOSS (non-cylindrical)"]


def read_step(path: Path) -> tuple[TopoDS_Shape, list[str]]:
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise CadImportError("STEP_READ_FAILED", f"OCCT could not read the STEP file (status {status})")
    reader.SetSystemLengthUnit(1.0)  # results in millimetres
    if reader.TransferRoots() == 0:
        raise CadImportError("STEP_NO_GEOMETRY", "the STEP file contains no transferable geometry")
    shape = reader.OneShape()
    if shape.IsNull():
        raise CadImportError("STEP_NO_GEOMETRY", "the STEP file produced an empty shape")
    lengths, angles, solids = AsciiStringSequence(), AsciiStringSequence(), AsciiStringSequence()
    reader.FileUnits(lengths, angles, solids)
    units = sorted({lengths.Value(i).ToCString() for i in range(1, lengths.Length() + 1)})
    return shape, units


def _bbox(lo: g.Vec, hi: g.Vec) -> BoundingBox:
    return BoundingBox(min=lo, max=hi, size=g.sub(hi, lo))


def _mass(shape: TopoDS_Shape, closed: bool) -> tuple[MassProperties, GProp_GProps | None]:
    area = g.surface_properties(shape).Mass()
    if not closed:
        return MassProperties(volume=None, surface_area=area, centroid=None), None
    vp = g.volume_properties(shape)
    return MassProperties(volume=vp.Mass(), surface_area=area, centroid=g.pnt(vp.CentreOfMass())), vp


def _principal_axes(vp: GProp_GProps | None) -> list[PrincipalAxis]:
    if vp is None:
        return []
    pp = vp.PrincipalProperties()
    moments = pp.Moments()
    axes = [pp.FirstAxisOfInertia(), pp.SecondAxisOfInertia(), pp.ThirdAxisOfInertia()]
    out = [
        PrincipalAxis(direction=g.canonical_direction(g.dvec(a)), moment=m)
        for a, m in zip(axes, moments)
    ]
    return sorted(out, key=lambda a: (round(a.moment, 3), a.direction))


def _symmetry(faces, centre: g.Vec, principal: list[PrincipalAxis], tol: float) -> list[SymmetryCandidate]:
    normals: list[g.Vec] = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
    for pa in principal:
        if not any(g.parallel(pa.direction, n, 0.5) for n in normals):
            normals.append(pa.direction)
    out = []
    for n in normals:
        matched = 0
        for fi in faces:
            d = g.dot(g.sub(fi.centroid, centre), n)
            mirrored = g.sub(fi.centroid, g.scale(n, 2 * d))
            if any(
                o.surface_type == fi.surface_type
                and abs(o.area - fi.area) <= max(tol, 1e-6 * fi.area)
                and g.dist(o.centroid, mirrored) < tol
                for o in faces
            ):
                matched += 1
        score = matched / len(faces) if faces else 0.0
        if score >= 0.5:
            out.append(
                SymmetryCandidate(
                    plane_point=centre, plane_normal=n, score=round(score, 4), method="face_centroid_reflection"
                )
            )
    return sorted(out, key=lambda s: (-s.score, s.plane_normal))


def _surface_model(fi) -> object:
    t = fi.surface_type
    if t == SurfaceType.PLANE:
        return PlaneSurface(origin=fi.origin, normal=fi.normal)
    if t == SurfaceType.CYLINDER:
        return CylinderSurface(
            axis=Axis(origin=fi.origin, direction=fi.axis_dir),
            radius=fi.radius,
            concave=bool(fi.concave),
            angular_extent_deg=fi.angular_extent_deg,
        )
    if t == SurfaceType.CONE:
        return ConeSurface(
            axis=Axis(origin=fi.origin, direction=fi.axis_dir),
            half_angle_deg=fi.half_angle_deg,
            reference_radius=fi.radius,
            apex=fi.apex,
            concave=bool(fi.concave),
        )
    if t == SurfaceType.SPHERE:
        return SphereSurface(center=fi.origin, radius=fi.radius, concave=bool(fi.concave))
    if t == SurfaceType.TORUS:
        return TorusSurface(
            axis=Axis(origin=fi.origin, direction=fi.axis_dir),
            major_radius=fi.radius,
            minor_radius=fi.minor_radius,
        )
    return OtherSurface(surface_type=t)


def _face_signature(fi) -> str:
    params: list[object] = [fi.surface_type.value, fi.area, fi.centroid]
    if fi.radius is not None:
        params.append(fi.radius)
    if fi.normal is not None:
        params.append(fi.normal)
    return ids.signature(*params)


def analyze_step(
    path: Path, *, filename: str, sha256: str, size_bytes: int, progress: Progress | None = None
) -> GeometryIR:
    report = progress or (lambda msg, pct: None)
    t0 = time.monotonic()
    diagnostics: list[Diagnostic] = []

    report("Importing STEP", 5)
    shape, file_units = read_step(path)

    report("Checking geometry", 15)
    valid = BRepCheck_Analyzer(shape).IsValid()
    if not valid:
        diagnostics.append(
            Diagnostic(
                code="INVALID_BREP",
                severity=Severity.WARNING,
                message="BRepCheck reports the shape as invalid; measurements may be unreliable",
            )
        )

    report("Indexing topology", 25)
    topo = TopologyIndex.build(shape)
    if not topo.solids:
        diagnostics.append(
            Diagnostic(
                code="NO_SOLID",
                severity=Severity.WARNING,
                message="no closed solid found; volume, convexity and feature recognition are unavailable",
            )
        )
    if len(topo.solids) > 1:
        diagnostics.append(
            Diagnostic(
                code="MULTIPLE_SOLIDS",
                severity=Severity.INFO,
                message=f"{len(topo.solids)} solids found; properties are reported per body and combined",
            )
        )

    lo, hi = g.bounding_box(shape)
    diag = g.dist(lo, hi)
    tol = Tolerances(linear=max(1e-4, 1e-6 * diag), angular_deg=0.5, probe=min(0.05, max(1e-4, 1e-4 * diag)))

    report("Measuring faces and edges", 35)
    faces = [describe_face(i, f) for i, f in enumerate(topo.faces)]
    for fi in faces:
        fi.signature = _face_signature(fi)
    face_ids = ids.dedupe([ids.make_id("FACE", fi.signature) for fi in faces])
    edges = [describe_edge(i, e) for i, e in enumerate(topo.edges)]
    for ei in edges:
        ei.signature = ids.signature(ei.curve_type.value, ei.length, ei.mid, sorted([ei.start, ei.end]))
    edge_ids = ids.dedupe([ids.make_id("EDGE", ei.signature) for ei in edges])
    vpts = [vertex_point(v) for v in topo.vertices]
    vertex_ids = ids.dedupe([ids.make_id("VTX", ids.signature(p)) for p in vpts])

    report("Classifying edges", 50)
    classifiers = [PointClassifier(s, 1e-7) for s in topo.solids]
    convexity: list[Convexity] = []
    for e, fs in enumerate(topo.edge_faces):
        if topo.is_degenerated(e):
            convexity.append(Convexity.UNKNOWN)
        elif len(fs) == 1:
            convexity.append(Convexity.SEAM if topo.is_seam(e) else Convexity.BOUNDARY)
        elif len(fs) == 2 and topo.face_solid[fs[0]] is not None:
            clf = classifiers[topo.face_solid[fs[0]]]
            convexity.append(
                classify_edge(topo.edges[e], topo.faces[fs[0]], topo.faces[fs[1]], clf, tol.probe)
            )
        else:
            convexity.append(Convexity.UNKNOWN)

    report("Recognizing features", 65)
    ctx = RecognitionContext(
        topo=topo,
        faces=faces,
        edges=edges,
        convexity=convexity,
        face_ids=face_ids,
        edge_ids=edge_ids,
        classifiers=classifiers,
        tol=tol,
    )
    features: list = []
    if topo.solids:
        groups = group_cylinders(ctx)
        holes = recognize_holes(ctx, groups)
        slots = recognize_slots(ctx, groups)
        bosses = recognize_bosses(ctx, groups)
        fillets = recognize_fillets(ctx)
        chamfers = recognize_chamfers(ctx)
        pockets = recognize_pockets(ctx)
        patterns = recognize_hole_patterns(ctx, holes, bosses)
        features = [*holes, *slots, *bosses, *pockets, *fillets, *chamfers, *patterns]
        features.sort(key=lambda f: (f.type.value, f.id))
        unknown = sum(1 for c in convexity if c == Convexity.UNKNOWN)
        if unknown:
            diagnostics.append(
                Diagnostic(
                    code="EDGE_CONVEXITY_UNKNOWN",
                    severity=Severity.INFO,
                    message=f"convexity could not be determined for {unknown} edge(s)",
                    entity_ids=sorted(edge_ids[e] for e, c in enumerate(convexity) if c == Convexity.UNKNOWN)[:50],
                )
            )

    report("Computing properties", 85)
    closed = bool(topo.solids)
    mass, vp = _mass(shape, closed)
    principal = _principal_axes(vp)
    centre = g.scale(g.add(lo, hi), 0.5)
    symmetry = _symmetry(faces, centre, principal, max(1e-3, 1e-5 * diag))

    bodies = []
    for s_i, solid in enumerate(topo.solids):
        slo, shi = g.bounding_box(solid)
        smass, _ = _mass(solid, True)
        bodies.append(
            Body(
                id=f"BODY-{s_i + 1}",
                kind=BodyKind.SOLID,
                is_closed=True,
                is_valid=BRepCheck_Analyzer(solid).IsValid(),
                mass_properties=smass,
                bounding_box=_bbox(slo, shi),
                face_ids=sorted(face_ids[f] for f in range(len(faces)) if topo.face_solid[f] == s_i),
            )
        )
    if not bodies:
        bodies.append(
            Body(
                id="BODY-1",
                kind=BodyKind.SHELL,
                is_closed=False,
                is_valid=valid,
                mass_properties=mass,
                bounding_box=_bbox(lo, hi),
                face_ids=sorted(face_ids),
            )
        )

    face_models = [
        Face(
            id=face_ids[i],
            index=i + 1,
            body_id=f"BODY-{(topo.face_solid[i] or 0) + 1}",
            surface_type=fi.surface_type,
            surface=_surface_model(fi),
            area=fi.area,
            centroid=fi.centroid,
            edge_ids=sorted(edge_ids[e] for e in topo.face_edges[i]),
            adjacent_face_ids=sorted(face_ids[x] for x in topo.adjacent_faces(i)),
        )
        for i, fi in enumerate(faces)
    ]
    edge_models = [
        Edge(
            id=edge_ids[i],
            index=i + 1,
            curve_type=ei.curve_type,
            length=ei.length,
            start=ei.start,
            end=ei.end,
            vertex_ids=sorted(vertex_ids[v] for v in topo.edge_vertices[i]),
            face_ids=sorted(face_ids[f] for f in topo.edge_faces[i]),
            convexity=convexity[i],
            circle_center=ei.circle_center,
            circle_radius=ei.circle_radius,
            circle_axis=ei.circle_axis,
        )
        for i, ei in enumerate(edges)
    ]
    vertex_models = [Vertex(id=vertex_ids[i], index=i + 1, point=p) for i, p in enumerate(vpts)]

    report("Assembling GeometryIR", 95)
    return GeometryIR(
        source=SourceInfo(
            filename=filename,
            format=SourceFormat.STEP,
            sha256=sha256,
            size_bytes=size_bytes,
            file_length_units=file_units,
            kernel_version=kernel_version(),
        ),
        cad_metadata=read_step_metadata(path),
        representation=Representation.EXACT_BREP,
        bounding_box=_bbox(lo, hi),
        mass_properties=mass,
        principal_axes=principal,
        symmetry_candidates=symmetry,
        topology=TopologyCounts(
            solids=len(topo.solids),
            shells=topo.shells_count,
            faces=len(faces),
            edges=len(edges),
            vertices=len(vpts),
        ),
        bodies=bodies,
        faces=sorted(face_models, key=lambda f: f.index),
        edges=sorted(edge_models, key=lambda e: e.index),
        vertices=vertex_models,
        features=features,
        diagnostics=diagnostics,
        analysis=AnalysisInfo(
            duration_s=round(time.monotonic() - t0, 3),
            linear_tolerance_mm=tol.linear,
            angular_tolerance_deg=tol.angular_deg,
            recognizers=RECOGNIZERS,
            not_recognized=NOT_RECOGNIZED,
        ),
    )


def shape_for_preview(path: Path) -> TopoDS_Shape:
    return read_step(path)[0]


__all__ = ["analyze_step", "read_step", "CadImportError", "shape_for_preview"]
