"""Generate the evaluation/test CAD models (STEP + STL) deterministically with OCCT.

Every model is built from explicit construction parameters. Those parameters are
written to ``manifest.json`` and are the ground truth the geometry tests compare
against - no expected value is typed by hand anywhere else.

Usage:
    uv run python scripts/generate_fixtures.py [--out examples/models]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Callable

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepFilletAPI import BRepFilletAPI_MakeChamfer, BRepFilletAPI_MakeFillet
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.StlAPI import StlAPI_Writer
from OCP.TopAbs import TopAbs_EDGE
from OCP.OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap
from OCP.TopExp import TopExp
from OCP.TopoDS import TopoDS, TopoDS_Shape

Shape = TopoDS_Shape


# --------------------------------------------------------------------------- primitives


def box(x0: float, y0: float, z0: float, dx: float, dy: float, dz: float) -> Shape:
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), dx, dy, dz).Shape()


def cyl(p: tuple[float, float, float], d: tuple[float, float, float], r: float, h: float) -> Shape:
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*p), gp_Dir(*d)), r, h).Shape()


def cut(a: Shape, *tools: Shape) -> Shape:
    for t in tools:
        a = BRepAlgoAPI_Cut(a, t).Shape()
    return a


def fuse(a: Shape, *tools: Shape) -> Shape:
    for t in tools:
        a = BRepAlgoAPI_Fuse(a, t).Shape()
    return a


def clean(s: Shape) -> Shape:
    """Merge coplanar/co-cylindrical faces left by booleans (as CAD exporters do)."""
    u = ShapeUpgrade_UnifySameDomain(s, True, True, False)
    u.Build()
    return u.Shape()


def unique_edges(shape: Shape):
    m = ShapeMap()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, m)
    return [TopoDS.Edge(m.FindKey(i)) for i in range(1, m.Size() + 1)]


def edges_near(shape: Shape, point: tuple[float, float, float], tol: float = 1e-3):
    """Edges whose mid-point is within tol of point (used to pick edges for blends)."""
    found = []
    for e in unique_edges(shape):
        c = BRepAdaptor_Curve(e)
        m = c.Value(0.5 * (c.FirstParameter() + c.LastParameter()))
        if math.dist((m.X(), m.Y(), m.Z()), point) < tol:
            found.append(e)
    return found


def fillet(shape: Shape, radius: float, mids: list[tuple[float, float, float]]) -> Shape:
    mk = BRepFilletAPI_MakeFillet(shape)
    for m in mids:
        es = edges_near(shape, m)
        if len(es) != 1:
            raise RuntimeError(f"expected one edge at {m}, found {len(es)}")
        mk.Add(radius, es[0])
    mk.Build()
    return mk.Shape()


def chamfer(shape: Shape, dist: float, mids: list[tuple[float, float, float]]) -> Shape:
    mk = BRepFilletAPI_MakeChamfer(shape)
    for m in mids:
        es = edges_near(shape, m)
        if len(es) != 1:
            raise RuntimeError(f"expected one edge at {m}, found {len(es)}")
        mk.Add(dist, es[0])
    mk.Build()
    return mk.Shape()


# --------------------------------------------------------------------------- models
# Each builder returns (shape, expected) where expected holds construction values.


def plate_with_holes():
    L, W, T = 120.0, 80.0, 10.0
    corner = [(15.0, 15.0), (105.0, 15.0), (15.0, 65.0), (105.0, 65.0)]
    s = box(0, 0, 0, L, W, T)
    s = cut(s, *[cyl((x, y, -1), (0, 0, 1), 4.0, T + 2) for x, y in corner])
    s = cut(s, cyl((60, 40, -1), (0, 0, 1), 10.0, T + 2))
    exp = {
        "bbox_size": [L, W, T],
        "volume": L * W * T - 4 * math.pi * 16 * T - math.pi * 100 * T,
        "holes": [{"diameter": 8.0, "through": True, "count": 4}, {"diameter": 20.0, "through": True, "count": 1}],
        "patterns": [{"pattern_type": "RECTANGULAR", "count": 4, "member_diameter": 8.0, "pitches": [50.0, 90.0]}],
    }
    return clean(s), exp


def mounting_plate():
    L, W, T = 150.0, 100.0, 8.0
    s = box(0, 0, 0, L, W, T)
    row = [(35.0, 20.0), (75.0, 20.0), (115.0, 20.0)]
    s = cut(s, *[cyl((x, y, -1), (0, 0, 1), 3.3, T + 2) for x, y in row])
    cb = [(35.0, 75.0), (115.0, 75.0)]
    for x, y in cb:
        s = cut(s, cyl((x, y, -1), (0, 0, 1), 3.3, T + 2), cyl((x, y, T - 4.0), (0, 0, 1), 5.5, 5.0))
    s = clean(s)
    s = fillet(s, 10.0, [(0, 0, T / 2), (L, 0, T / 2), (0, W, T / 2), (L, W, T / 2)])
    exp = {
        "bbox_size": [L, W, T],
        "holes": [
            {"diameter": 6.6, "through": True, "count": 5},
        ],
        "counterbores": [{"diameter": 11.0, "depth": 4.0, "count": 2}],
        "fillets": [{"radius": 10.0, "concave": False, "count": 4}],
        "patterns": [{"pattern_type": "LINEAR", "count": 3, "member_diameter": 6.6, "pitches": [40.0]}],
    }
    return s, exp


def pocketed_block():
    L, W, H = 100.0, 60.0, 30.0
    s = box(0, 0, 0, L, W, H)
    s = cut(s, box(25, 15, H - 10.0, 50.0, 30.0, 11.0))  # pocket 50 x 30 x 10
    s = cut(s, cyl((10.0, 10.0, H - 15.0), (0, 0, 1), 3.0, 16.0))  # blind hole d6 depth 15
    exp = {
        "bbox_size": [L, W, H],
        "volume": L * W * H - 50 * 30 * 10 - math.pi * 9 * 15,
        "pockets": [{"length": 50.0, "width": 30.0, "depth": 10.0, "count": 1}],
        "holes": [{"diameter": 6.0, "through": False, "depth": 15.0, "count": 1}],
    }
    return clean(s), exp


def bracket():
    # L-bracket: base 80 x 50 x 10, upright wall 80 x 10 x 60 along y=0..10
    s = fuse(box(0, 0, 0, 80, 50, 10), box(0, 0, 10, 80, 10, 50))
    s = clean(s)
    s = fillet(s, 5.0, [(40.0, 10.0, 10.0)])  # inside corner fillet (concave)
    s = cut(s, *[cyl((x, 32.5, -1), (0, 0, 1), 4.5, 12) for x in (20.0, 60.0)])
    # through slot in upright: width 10, centre distance 30, centred at x=40, z=40
    slot = fuse(
        box(25.0, -1, 35.0, 30.0, 12, 10.0),
        cyl((25.0, -1, 40.0), (0, 1, 0), 5.0, 12),
        cyl((55.0, -1, 40.0), (0, 1, 0), 5.0, 12),
    )
    s = clean(cut(s, slot))
    exp = {
        "bbox_size": [80.0, 50.0, 60.0],
        "holes": [{"diameter": 9.0, "through": True, "count": 2}],
        "slots": [{"width": 10.0, "length": 40.0, "center_distance": 30.0, "through": True, "count": 1}],
        "fillets": [{"radius": 5.0, "concave": True, "count": 1}],
    }
    return s, exp


def shaft():
    s = fuse(
        cyl((0, 0, 0), (0, 0, 1), 10.0, 40.0),
        cyl((0, 0, 40), (0, 0, 1), 15.0, 60.0),
        cyl((0, 0, 100), (0, 0, 1), 10.0, 40.0),
    )
    s = clean(s)
    # 1 x 45 deg chamfers on both end circles: pick the circular edges by a point on them
    mk = BRepFilletAPI_MakeChamfer(s)
    for e in unique_edges(s):
        c = BRepAdaptor_Curve(e)
        p = c.Value(c.FirstParameter())
        on_end = min(abs(p.Z()), abs(p.Z() - 140.0)) < 1e-6
        if on_end and abs(math.hypot(p.X(), p.Y()) - 10.0) < 1e-6:
            mk.Add(1.0, e)
    mk.Build()
    s = mk.Shape()
    exp = {
        "bbox_size": [30.0, 30.0, 140.0],
        "bosses": [{"diameter": 20.0, "count": 2}, {"diameter": 30.0, "count": 1}],
        "chamfers": [{"distance": 1.0, "count": 2}],
        "holes": [],
    }
    return s, exp


def flange():
    # Simplified from the attached reference drawing's nominal sizes (no thread, no tolerances).
    s = fuse(cyl((0, 0, 0), (0, 0, 1), 50.0, 10.0), cyl((0, 0, 10), (0, 0, 1), 22.5, 30.0))
    s = cut(s, cyl((0, 0, -1), (0, 0, 1), 10.0, 42.0))
    holes = []
    for k in range(8):
        a = math.radians(45.0 * k + 90.0)
        holes.append(cyl((43.0 * math.cos(a), 43.0 * math.sin(a), -1), (0, 0, 1), 4.0, 12.0))
    s = clean(cut(s, *holes))
    exp = {
        "bbox_size": [100.0, 100.0, 40.0],
        "volume": math.pi * (2500 * 10 + 22.5**2 * 30) - math.pi * 100 * 40 - 8 * math.pi * 16 * 10,
        "holes": [{"diameter": 8.0, "through": True, "count": 8}, {"diameter": 20.0, "through": True, "count": 1}],
        "bosses": [{"diameter": 45.0, "count": 1}, {"diameter": 100.0, "count": 1}],
        "patterns": [{"pattern_type": "CIRCULAR", "count": 8, "member_diameter": 8.0, "pitch_circle_diameter": 86.0, "angular_step_deg": 45.0}],
    }
    return s, exp


def cylindrical_part():
    s = cyl((0, 0, 0), (0, 0, 1), 25.0, 80.0)
    s = cut(s, cyl((0, 0, 50.0), (0, 0, 1), 6.0, 31.0))  # blind axial hole d12 depth 30
    s = cut(s, cyl((-30.0, 0, 20.0), (1, 0, 0), 3.0, 60.0))  # cross hole d6 through, below the bore
    s = clean(s)
    exp = {
        "bbox_size": [50.0, 50.0, 80.0],
        "holes": [
            {"diameter": 12.0, "through": False, "depth": 30.0, "count": 1},
            {"diameter": 6.0, "through": True, "count": 1},
        ],
        "bosses": [{"diameter": 50.0, "count": 1}],
    }
    return s, exp


def enclosure():
    L, W, H, t = 100.0, 60.0, 40.0, 2.0
    s = cut(box(0, 0, 0, L, W, H), box(t, t, t, L - 2 * t, W - 2 * t, H))
    s = cut(s, *[cyl((x, -1, 20.0), (0, 1, 0), 2.5, 4.0) for x in (30.0, 70.0)])
    s = clean(s)
    exp = {
        "bbox_size": [L, W, H],
        "volume": L * W * H - (L - 2 * t) * (W - 2 * t) * (H - t) - 2 * math.pi * 6.25 * t,
        "pockets": [{"length": 96.0, "width": 56.0, "depth": 38.0, "count": 1}],
        "holes": [{"diameter": 5.0, "through": True, "count": 2}],
    }
    return s, exp


def chamfered_block():
    s = box(0, 0, 0, 60.0, 40.0, 20.0)
    s = chamfer(s, 3.0, [(30.0, 0.0, 20.0)])  # top front edge, 3 x 3
    s = fillet(s, 4.0, [(30.0, 40.0, 20.0)])  # top back edge, R4 round
    exp = {
        "bbox_size": [60.0, 40.0, 20.0],
        "chamfers": [{"distance": 3.0, "count": 1}],
        "fillets": [{"radius": 4.0, "concave": False, "count": 1}],
        "holes": [],
    }
    return s, exp


MODELS: dict[str, Callable[[], tuple[Shape, dict]]] = {
    "plate_with_holes": plate_with_holes,
    "mounting_plate": mounting_plate,
    "pocketed_block": pocketed_block,
    "bracket": bracket,
    "shaft": shaft,
    "flange": flange,
    "cylindrical_part": cylindrical_part,
    "enclosure": enclosure,
    "chamfered_block": chamfered_block,
}

STL_MODELS = ("plate_with_holes", "flange", "bracket")


# --------------------------------------------------------------------------- writers


def write_step(shape: Shape, path: Path, unit: str = "MM") -> None:
    Interface_Static.SetCVal_s("write.step.unit", unit)
    try:
        w = STEPControl_Writer()
        w.Transfer(shape, STEPControl_AsIs)
        if w.Write(str(path)) != IFSelect_RetDone:
            raise RuntimeError(f"STEP write failed: {path}")
    finally:
        Interface_Static.SetCVal_s("write.step.unit", "MM")


def write_stl(shape: Shape, path: Path, deflection: float = 0.05) -> None:
    BRepMesh_IncrementalMesh(shape, deflection, False, 0.2, True)
    w = StlAPI_Writer()
    w.ASCIIMode = False
    if not w.Write(shape, str(path)):
        raise RuntimeError(f"STL write failed: {path}")


def generate(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"generator": "scripts/generate_fixtures.py", "units": "mm", "models": {}}
    # OCCT prints transfer statistics on stdout; keep them off our stdout.
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        for name, builder in MODELS.items():
            shape, expected = builder()
            write_step(shape, out / f"{name}.step")
            entry = {"step": f"{name}.step", "expected": expected}
            if name in STL_MODELS:
                write_stl(shape, out / f"{name}.stl")
                entry["stl"] = f"{name}.stl"
            manifest["models"][name] = entry
        # unit-conversion fixture: plate written in metres and inches must read back in mm
        shape, expected = plate_with_holes()
        write_step(shape, out / "plate_with_holes_metres.step", unit="M")
        write_step(shape, out / "plate_with_holes_inches.step", unit="INCH")
        manifest["unit_variants"] = {
            "plate_with_holes_metres.step": {"declared_unit": "metre", "expected": expected},
            "plate_with_holes_inches.step": {"declared_unit": "INCH", "expected": expected},
        }
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "examples" / "models")
    args = ap.parse_args()
    m = generate(args.out)
    print(f"wrote {len(m['models'])} models to {args.out}")


if __name__ == "__main__":
    main()
