"""CAD change handling (EX 2): feature diff between two versions of a part, and the drawing settings
carried from the previous version's drawing to the new one.

Feature ids are content hashes, so an unchanged feature keeps its id. Changed features are paired as
*resized* (same type, same place, other size) or *moved* (same type and size, other place); the rest
are added / removed. Planar faces are matched by orientation and plane position. Everything the user
entered that points at a matched feature / face is re-pointed; what points at a removed one is dropped
and reported - never silently kept. A revision entry (next letter, change summary, date) is appended.
The regenerated drawing is complete and deterministic from the carried settings: there are no manual
edits on the sheet to preserve.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date

from drawing_schema.settings import DrawingSettings
from geometry_schema import FeatureType, GeometryIR, SurfaceType

from drawing_planner.candidates import generate_candidates

_POS_TOL = 1e-3
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # ISO: no I, O, Q


@dataclass
class FeatureDiff:
    unchanged: list[str] = field(default_factory=list)
    resized: list[tuple[str, str]] = field(default_factory=list)  # (old id, new id)
    moved: list[tuple[str, str]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    face_map: dict[str, str] = field(default_factory=dict)  # old planar face id -> new
    describe: dict[str, str] = field(default_factory=dict)  # feature id -> words

    @property
    def changed(self) -> bool:
        return bool(self.resized or self.moved or self.added or self.removed)

    def id_map(self) -> dict[str, str]:
        out = {i: i for i in self.unchanged}
        out.update(dict(self.resized))
        out.update(dict(self.moved))
        out.update(self.face_map)
        return out

    def summary(self) -> str:
        parts = []
        for label, items in (("ADDED", self.added), ("REMOVED", self.removed)):
            if items:
                parts.append(f"{label} " + ", ".join(self.describe.get(i, i) for i in items))
        for label, pairs in (("RESIZED", self.resized), ("MOVED", self.moved)):
            if pairs:
                parts.append(f"{label} " + ", ".join(self.describe.get(n, n) for _, n in pairs))
        return "; ".join(parts) or "NO FEATURE CHANGES"

    def as_dict(self) -> dict:
        return {"unchanged": self.unchanged, "resized": self.resized, "moved": self.moved, "added": self.added,
                "removed": self.removed, "summary": self.summary()}


def _anchor(f):
    if hasattr(f, "axis"):
        return tuple(f.axis.origin)
    if hasattr(f, "center") and f.center is not None:
        return tuple(f.center)
    return None


def _size(f) -> tuple:
    keys = ("diameter", "depth", "height", "width", "length", "radius", "distance_1", "distance_2",
            "inner_diameter", "outer_diameter", "inner_radius", "angle_deg", "count", "through")
    return tuple(round(float(getattr(f, k)), 4) for k in keys if getattr(f, k, None) is not None)


def _words(f) -> str:
    t = f.type.value
    if t == "HOLE":
        return f"HOLE Ø{f.diameter:g}"
    if t == "BOSS":
        return f"Ø{f.diameter:g} DIAMETER"
    if t == "PATTERN":
        return f"{f.count}X {f.member_type.value} PATTERN"
    return t


def diff_features(old: GeometryIR, new: GeometryIR) -> FeatureDiff:
    d = FeatureDiff()
    of = {f.id: f for f in old.features if f.type != FeatureType.PATTERN}
    nf = {f.id: f for f in new.features if f.type != FeatureType.PATTERN}
    d.describe = {f.id: _words(f) for f in (*old.features, *new.features)}
    d.unchanged = sorted(set(of) & set(nf))
    gone = sorted(set(of) - set(nf))
    fresh = sorted(set(nf) - set(of))
    for rule, out in ((lambda a, b: _anchor(a) is not None and _anchor(b) is not None
                       and math.dist(_anchor(a), _anchor(b)) < _POS_TOL, d.resized),
                      (lambda a, b: _size(a) == _size(b), d.moved)):
        for o in list(gone):
            match = next((n for n in fresh if nf[n].type == of[o].type and rule(of[o], nf[n])), None)
            if match is not None:
                out.append((o, match))
                gone.remove(o)
                fresh.remove(match)
    d.added, d.removed = fresh, gone
    # patterns follow their members: kept if all members map, else added / removed
    for p in (x for x in old.features if x.type == FeatureType.PATTERN):
        if p.id in {x.id for x in new.features}:
            d.unchanged.append(p.id)
    # planar faces: same outward normal and plane offset
    def key(face):
        n = face.surface.normal
        return tuple(round(c, 6) for c in n) + (round(sum(n[i] * face.centroid[i] for i in range(3)), 4),)

    new_planes: dict[tuple, list] = {}
    for f in new.faces:
        if f.surface_type == SurfaceType.PLANE:
            new_planes.setdefault(key(f), []).append(f)
    for f in old.faces:
        if f.surface_type != SurfaceType.PLANE:
            continue
        same = new_planes.get(key(f), [])
        if len(same) == 1:
            d.face_map[f.id] = same[0].id
        elif same:
            d.face_map[f.id] = min(same, key=lambda g: (math.dist(g.centroid, f.centroid), g.id)).id
    return d


def next_revision(settings: DrawingSettings) -> str:
    revs = [r.revision for r in settings.manufacturing.revisions] + (
        [settings.title_block.revision] if settings.title_block.revision else [])
    last = revs[-1] if revs else None
    if last is None or last in ("-", "0"):
        return "A"
    if last.isdigit():
        return str(int(last) + 1)
    up = last.upper()
    if len(up) == 1 and up in LETTERS and up != LETTERS[-1]:
        return LETTERS[LETTERS.index(up) + 1]
    return up + "A" if len(up) < 4 else up


@dataclass
class CarriedSettings:
    settings: DrawingSettings
    carried: list[str]
    dropped: list[str]
    revision: str


def carry_settings(previous: DrawingSettings, old_ir: GeometryIR, new_ir: GeometryIR, diff: FeatureDiff,
                   today: date | None = None) -> CarriedSettings:
    """The previous drawing's settings for the new version: ids re-pointed, orphans dropped, a revision
    entry appended."""
    mapping = diff.id_map()
    raw = previous.model_dump_json()
    # candidate ids embed feature ids (DIM-CALLOUT-HOLE-1a2b...): re-point every known id in place
    for old_id, new_id in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        if old_id != new_id:
            raw = raw.replace(old_id, new_id)
    data = json.loads(raw)
    feats = {f.id for f in new_ir.features}
    faces = {f.id for f in new_ir.faces}
    cands = {c.id for c in generate_candidates(new_ir, previous.dimensions.decimal_places,
                                               previous.dimensions.trailing_zeros, [])}
    carried, dropped = [], []

    def target_ok(t: dict) -> bool:
        return (t.get("feature_id") in feats) if t.get("feature_id") else (t.get("face_id") in faces)

    def keep(items: list, ok, what) -> list:
        out = []
        for it in items:
            (out.append(it), carried.append(what(it))) if ok(it) else dropped.append(what(it))
        return out

    data["feature_roles"] = keep(data.get("feature_roles", []), lambda r: target_ok(r["target"]),
                                 lambda r: f"role {r['role']} on {r['target'].get('feature_id') or r['target'].get('face_id')}")
    m = data["manufacturing"]
    m["datums"] = keep(m["datums"], lambda x: target_ok(x["target"]), lambda x: f"datum {x['letter']}")
    letters = {x["letter"] for x in m["datums"]}
    m["frames"] = keep(m["frames"], lambda x: target_ok(x["target"]) and all(r["letter"] in letters for r in x["datums"]),
                       lambda x: f"{x['characteristic']} frame")
    m["surface_finish_marks"] = keep(m["surface_finish_marks"], lambda x: target_ok(x["target"]),
                                     lambda x: f"Ra {x['ra_um']}")
    m["feature_notes"] = keep(m["feature_notes"], lambda x: target_ok(x["target"]), lambda x: f"note '{x['text']}'")
    m["threads"] = keep(m["threads"], lambda x: x["feature_id"] in feats, lambda x: f"thread {x['designation']}")
    m["tolerances"] = keep(m["tolerances"], lambda x: x["candidate_id"] in cands, lambda x: f"tolerance on {x['candidate_id']}")
    m["inspection_dimensions"] = keep(m["inspection_dimensions"], lambda x: x in cands, lambda x: f"inspection {x}")
    m["basic_dimensions"] = keep(m["basic_dimensions"], lambda x: x in cands, lambda x: f"TED {x}")
    rev = next_revision(previous)
    stamp = (today or date.today()).isoformat()
    history = list(m.get("revisions") or [])
    if not history and previous.title_block.revision:  # the issue being revised, so the table shows it too
        history = [{"revision": previous.title_block.revision, "description": "AS PREVIOUSLY ISSUED", "date": "",
                    "approved_by": ""}]
    m["revisions"] = history[-11:] + [{"revision": rev, "description": diff.summary()[:80], "date": stamp,
                                       "approved_by": ""}]
    data["title_block"]["revision"] = rev
    return CarriedSettings(settings=DrawingSettings.model_validate(data), carried=carried, dropped=dropped,
                           revision=rev)


__all__ = ["CarriedSettings", "FeatureDiff", "carry_settings", "diff_features", "next_revision"]
