"""Section views (RULES 1.3): a full section drawn in place of an orthographic view.

For the features a section trigger fired on (``view_rules.section_triggers``), the cutting plane contains
the feature's axis and is parallel to a selected orthographic view, which is then drawn as SECTION A-A
(ISO 128-44). The cutting plane is indicated in another selected view that sees it edge-on; if none
does, the first such view of the projected-view pool is added. One section per drawing: triggers whose
feature axis lies in that plane are satisfied by it, the others stay reported.
"""

from __future__ import annotations

from drawing_schema import SectionPlane, SectionView, ViewOrientation
from drawing_schema.frames import Frame, dot
from drawing_schema.roles import ViewTrigger, ViewTriggerKind
from geometry_schema import GeometryIR

_EPS = 1e-6
PREFERENCE = [ViewOrientation.FRONT, ViewOrientation.RIGHT, ViewOrientation.TOP, ViewOrientation.LEFT,
              ViewOrientation.BOTTOM, ViewOrientation.BACK]


def _in_plane(feature, point, normal) -> bool:
    axis = feature.axis
    return (abs(dot(axis.direction, normal)) < 1e-6
            and abs(dot([axis.origin[i] - point[i] for i in range(3)], normal)) < 1e-4)


def plan_sections(ir: GeometryIR, views: list[ViewOrientation], pool: list[ViewOrientation],
                  frames: dict[ViewOrientation, Frame], triggers: list[ViewTrigger]):
    """-> (sections, views to add, triggers with ``satisfied`` updated)."""
    features = {f.id: f for f in ir.features}
    wanted = [t for t in triggers if t.kind == ViewTriggerKind.SECTION]
    for t in wanted:
        feat = next((features[f] for f in t.feature_ids if f in features and hasattr(features[f], "axis")), None)
        if feat is None:
            continue
        a = feat.axis.direction
        cut = next((o for o in PREFERENCE if o in views and abs(dot(a, frames[o].eye)) < _EPS), None)
        if cut is None:
            continue
        normal = frames[cut].eye
        edge_on = [o for o in PREFERENCE if o != cut and o in frames and abs(dot(frames[o].eye, normal)) < _EPS]
        parent = next((o for o in edge_on if o in views), None)
        extra = []
        if parent is None:
            parent = next((o for o in edge_on if o in pool), None)
            if parent is None:
                continue
            extra = [parent]
        section = SectionView(id=f"V-{cut.value}", label="A", parent_view_id=f"V-{parent.value}",
                              plane=SectionPlane(through_feature_id=feat.id), replaces=cut)
        point = feat.axis.origin
        out = []
        for tr in triggers:
            ok = tr.kind == ViewTriggerKind.SECTION and all(
                f in features and hasattr(features[f], "axis") and _in_plane(features[f], point, normal)
                for f in tr.feature_ids)
            out.append(tr.model_copy(update={"satisfied": True}) if ok else tr)
        return [section], extra, out
    return [], [], triggers


def section_frame(ir: GeometryIR, section: SectionView, frame: Frame) -> tuple[tuple, tuple]:
    """(point on the cutting plane, normal toward the removed half = the section view's eye)."""
    feat = next(f for f in ir.features if f.id == section.plane.through_feature_id)
    return tuple(feat.axis.origin), tuple(frame.eye)


__all__ = ["plan_sections", "section_frame"]
