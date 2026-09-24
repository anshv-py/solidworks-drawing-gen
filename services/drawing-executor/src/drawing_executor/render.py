"""DXF -> PDF / SVG / PNG at true sheet size (ezdxf drawing add-on + matplotlib)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import ezdxf  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import (  # noqa: E402
    BackgroundPolicy,
    ColorPolicy,
    Configuration,
    LineweightPolicy,
)
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402

MM_PER_INCH = 25.4


def render(dxf_path, sheet_w: float, sheet_h: float, outputs: dict[str, str], png_dpi: int = 150) -> None:
    """outputs: {"pdf": path, "svg": path, "png": path} (any subset)."""
    doc = ezdxf.readfile(str(dxf_path))
    fig = plt.figure(figsize=(sheet_w / MM_PER_INCH, sheet_h / MM_PER_INCH))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_axis_off()
    pt_per_mm = 72.0 / MM_PER_INCH  # the matplotlib backend draws DXF lineweights (mm) as points
    cfg = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.BLACK,
        lineweight_policy=LineweightPolicy.ABSOLUTE,
        lineweight_scaling=pt_per_mm,
        min_lineweight=0.13 * pt_per_mm,
    )
    # adjust_figure=False: keep the true sheet size (the backend would otherwise refit the figure)
    Frontend(RenderContext(doc), MatplotlibBackend(ax, adjust_figure=False), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    ax.set_xlim(0, sheet_w)
    ax.set_ylim(0, sheet_h)
    ax.set_aspect("equal")
    fig.set_size_inches(sheet_w / MM_PER_INCH, sheet_h / MM_PER_INCH)
    for fmt, path in outputs.items():
        fig.savefig(str(path), format=fmt, dpi=png_dpi if fmt == "png" else 300, facecolor="white")
    plt.close(fig)
