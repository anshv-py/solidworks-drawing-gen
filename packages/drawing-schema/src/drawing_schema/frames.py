"""View frames: which model directions a view looks along and draws right/up.

Pure math shared by the planner (view assignment) and the compiler (projection).
``eye`` points from the part toward the viewer; the view plane's y axis is eye × x.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from drawing_schema import ViewFrame, ViewOrientation

Vec = tuple[float, float, float]

_S3 = 1.0 / math.sqrt(3.0)
_S2 = 1.0 / math.sqrt(2.0)

# Z_UP frame: front viewer at -Y, top viewer at +Z, right viewer at +X.
_Z_UP: dict[ViewOrientation, tuple[Vec, Vec]] = {
    ViewOrientation.FRONT: ((0.0, -1.0, 0.0), (1.0, 0.0, 0.0)),
    ViewOrientation.BACK: ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)),
    ViewOrientation.TOP: ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    ViewOrientation.BOTTOM: ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0)),
    ViewOrientation.RIGHT: ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    ViewOrientation.LEFT: ((-1.0, 0.0, 0.0), (0.0, -1.0, 0.0)),
    ViewOrientation.ISOMETRIC: ((_S3, -_S3, _S3), (_S2, _S2, 0.0)),
    # dimetric / trimetric: standard-ish pictorial directions (not dimensioned)
    ViewOrientation.DIMETRIC: ((0.35, -0.87, 0.35), (0.93, 0.37, 0.0)),
    ViewOrientation.TRIMETRIC: ((0.5, -0.75, 0.43), (0.83, 0.55, 0.0)),
}


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Vec) -> Vec:
    n = math.sqrt(sum(c * c for c in a))
    return (a[0] / n, a[1] / n, a[2] / n)


def _zup_to_yup(v: Vec) -> Vec:
    # Y_UP model coords (x, y, z) correspond to Z_UP coords (x, -z, y); inverse mapping:
    return (v[0], v[2], -v[1])


@dataclass(frozen=True)
class Frame:
    eye: Vec
    x: Vec
    y: Vec

    def project(self, p: Vec) -> tuple[float, float]:
        return (
            p[0] * self.x[0] + p[1] * self.x[1] + p[2] * self.x[2],
            p[0] * self.y[0] + p[1] * self.y[1] + p[2] * self.y[2],
        )

    def depth(self, p: Vec) -> float:
        return p[0] * self.eye[0] + p[1] * self.eye[1] + p[2] * self.eye[2]


def view_frame(orientation: ViewOrientation, frame: ViewFrame = ViewFrame.Z_UP) -> Frame:
    eye, x = _Z_UP[orientation]
    eye, x = _unit(eye), _unit(x)
    if frame == ViewFrame.Y_UP:
        eye, x = _zup_to_yup(eye), _zup_to_yup(x)
    y = _unit(_cross(eye, x))
    return Frame(eye=eye, x=x, y=y)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
