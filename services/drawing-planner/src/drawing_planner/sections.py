"""Section views (RULES 1.3): a full section drawn in place of an orthographic view.

For the features a section trigger fired on (``view_rules.section_triggers``), the cutting plane contains
the feature's axis and is parallel to a selected orthographic view, which is then drawn as SECTION A-A
(ISO 128-44). The cutting plane is indicated in another selected view that sees it edge-on; if none
does, the first such view of the projected-view pool is added. One section per drawing: triggers whose
feature axis lies in that plane are satisfied by it, the others stay reported.
"""

from __future__ import annotations

from drawing_schema import AuxiliaryView, ConventionalBreak, SectionPlane, SectionView, ViewOrientation
from drawing_schema.frames import Frame, auxiliary_frame, dot
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


def hidden_in_section(ir: GeometryIR, section: SectionView, frame: Frame) -> set[str]:
    """Features a full section does not show: those the cutting plane misses. They lie either in the
    removed half or behind the cut face (a section has no hidden lines), so their dimensions belong in
    another view. Edge treatments (fillets, chamfers) show in the section outline and are not listed."""
    point, normal = section_frame(ir, section, frame)

    def side(p) -> float:
        return sum((p[i] - point[i]) * normal[i] for i in range(3))

    out = set()
    for f in ir.features:
        t = f.type.value
        if t in ("HOLE", "BOSS", "GROOVE"):
            r = (f.outer_diameter if t == "GROOVE" else f.diameter) / 2
            a, o = f.axis.direction, f.axis.origin
            ln = f.depth if t in ("HOLE", "GROOVE") else f.height
            ends = [o, tuple(o[i] + a[i] * ln for i in range(3))]
            # the cylinder's extent along the normal: axis ends +/- r * |sin(axis, normal)|
            s = r * max(0.0, 1 - dot(a, normal) ** 2) ** 0.5
            lo, hi = min(side(e) for e in ends) - s, max(side(e) for e in ends) + s
        elif t in ("POCKET", "SLOT"):
            u = f.length_direction
            n = f.floor_normal if t == "POCKET" else tuple(-x for x in f.depth_direction)
            v = (n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0])
            depth = f.depth or 0.0
            corners = [tuple(f.center[i] + su * f.length / 2 * u[i] + sv * f.width / 2 * v[i] + sd * depth * n[i]
                             for i in range(3)) for su in (-1, 1) for sv in (-1, 1) for sd in (0, 1)]
            lo, hi = min(side(c) for c in corners), max(side(c) for c in corners)
        else:
            continue
        if lo > 1e-6 or hi < -1e-6:
            out.add(f.id)
    return out


def plan_auxiliary_views(ir: GeometryIR, views: list[ViewOrientation], frames: dict[ViewOrientation, Frame],
                         triggers: list[ViewTrigger]):
    """-> (auxiliary views, their frames): one per distinct angled direction, looking along it; the
    parent is a selected view that sees the direction true length (where the arrow goes)."""
    features = {f.id: f for f in ir.features}
    out: list[AuxiliaryView] = []
    out_frames: dict[str, Frame] = {}
    dirs: list[tuple[tuple, list[str]]] = []
    for t in triggers:
        for fid in t.feature_ids:
            f = features.get(fid)
            d = f.axis.direction if f is not None and hasattr(f, "axis") else None
            if d is None:
                continue
            for known, members in dirs:
                if abs(dot(known, d) - 1) < 1e-6:
                    members.append(fid)
                    break
            else:
                dirs.append((tuple(d), [fid]))
    for d, members in dirs:
        parent = next((o for o in PREFERENCE if o in views and abs(dot(frames[o].eye, d)) < 1e-6), None)
        if parent is None:
            continue
        k = len(out)
        av = AuxiliaryView(id=f"V-AUX-{k + 1}", label="D", parent_view_id=f"V-{parent.value}",
                           feature_id=members[0], covers=sorted(members))
        out.append(av)
        out_frames[av.id] = auxiliary_frame(d, frames[parent])
    return out, out_frames


def plan_break(ir: GeometryIR, triggers: list[ViewTrigger], sections: list[SectionView]):
    """RULES 1.6 for turned parts: the middle of the longest constant diameter, keeping max(Ø, 15 %) of it at
    each end and clear of every other feature, when the removal shortens the part by at least 20 %.
    -> (breaks, triggers with ``satisfied`` updated)."""
    if not any(t.kind == ViewTriggerKind.BREAK for t in triggers) or sections:
        return [], triggers
    bosses = [f for f in ir.features if f.type.value == "BOSS"]
    if not bosses:
        return [], triggers
    boss = max(bosses, key=lambda b: (b.height, b.diameter, b.id))
    a, o = boss.axis.direction, boss.axis.origin
    margin = max(boss.diameter, 0.15 * boss.height)
    lo, hi = margin, boss.height - margin
    total = max(ir.bounding_box.size)
    if hi - lo < 0.2 * total:
        return [], triggers
    faces = {f.id: f for f in ir.faces}
    edges = {e.id: e for e in ir.edges}

    def along(p) -> float:
        return sum((p[i] - o[i]) * a[i] for i in range(3))

    for f in ir.features:
        if f.id == boss.id or f.type.value == "PATTERN":
            continue
        pts = [p for fid in f.face_ids if fid in faces for eid in faces[fid].edge_ids if eid in edges
               for p in (edges[eid].start, edges[eid].end)]
        if not pts:
            continue
        s0, s1 = min(along(p) for p in pts), max(along(p) for p in pts)
        if s1 > lo + 1e-6 and s0 < hi - 1e-6:
            if f.type.value == "BOSS" and abs(abs(dot(f.axis.direction, a)) - 1) < 1e-6:
                continue  # a coaxial diameter elsewhere on the shaft only touches the break via shared edges
            return [], triggers
    gap = min(0.2 * (hi - lo), 0.6 * boss.diameter)
    brk = ConventionalBreak(feature_id=boss.id, start=tuple(o[i] + a[i] * lo for i in range(3)),
                            end=tuple(o[i] + a[i] * hi for i in range(3)), gap=round(gap, 3))
    return [brk], [t.model_copy(update={"satisfied": True}) if t.kind == ViewTriggerKind.BREAK else t
                   for t in triggers]


def section_frame(ir: GeometryIR, section: SectionView, frame: Frame) -> tuple[tuple, tuple]:
    """(point on the cutting plane, normal toward the removed half = the section view's eye)."""
    feat = next(f for f in ir.features if f.id == section.plane.through_feature_id)
    return tuple(feat.axis.origin), tuple(frame.eye)


__all__ = ["hidden_in_section", "plan_auxiliary_views", "plan_break", "plan_sections", "section_frame"]
