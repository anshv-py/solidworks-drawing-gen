"""EX 2: feature diff between CAD versions and the settings carried to the regenerated drawing."""

import pytest

from drawing_planner.revisions import carry_settings, diff_features, next_revision
from drawing_schema.settings import DrawingSettings


def test_diff_pairs_resized_and_added_features(analyzed):
    old, new = analyzed["plate_with_holes"][0], analyzed["plate_with_holes_rev_b"][0]
    d = diff_features(old, new)
    assert len(d.unchanged) == 5 and d.removed == [] and len(d.added) == 1 and len(d.resized) == 1
    assert d.summary() == "ADDED HOLE Ø5; RESIZED HOLE Ø22"
    assert len(d.face_map) == sum(f.surface_type.value == "PLANE" for f in old.faces)
    assert not diff_features(old, old).changed


def test_annotations_follow_changed_features_and_orphans_are_dropped(analyzed):
    old, new = analyzed["plate_with_holes"][0], analyzed["plate_with_holes_rev_b"][0]
    d = diff_features(old, new)
    bore_old, bore_new = d.resized[0]
    face = next(f for f in old.faces if f.surface_type.value == "PLANE")
    s = DrawingSettings.model_validate({
        "title_block": {"revision": "C"},
        "feature_roles": [{"target": {"feature_id": bore_old}, "role": "BEARING_BORE"},
                          {"target": {"feature_id": "HOLE-deleted00"}, "role": "DOWEL_HOLE"}],
        "manufacturing": {"datums": [{"letter": "A", "target": {"face_id": face.id}}],
                          "tolerances": [{"candidate_id": f"DIM-CALLOUT-{bore_old}", "kind": "SYMMETRIC", "upper": 0.05}]}})
    c = carry_settings(s, old, new, d)
    assert [r.target.feature_id for r in c.settings.feature_roles] == [bore_new]
    assert any("HOLE-deleted00" in x for x in c.dropped)
    assert c.settings.manufacturing.datums[0].target.face_id == d.face_map[face.id]
    assert c.settings.manufacturing.tolerances[0].candidate_id == f"DIM-CALLOUT-{bore_new}"
    assert [r.revision for r in c.settings.manufacturing.revisions] == ["C", "D"] and c.revision == "D"
    assert c.settings.title_block.revision == "D"


def test_a_datum_whose_feature_is_gone_is_dropped_with_its_frames(analyzed):
    old, new = analyzed["plate_with_holes"][0], analyzed["plate_with_holes_rev_b"][0]
    d = diff_features(old, new)
    s = DrawingSettings.model_validate({"manufacturing": {
        "datums": [{"letter": "A", "target": {"face_id": "FACE-gone000000"}}],
        "frames": [{"characteristic": "FLATNESS", "tolerance": 0.05, "target": {"face_id": "FACE-gone000000"}}]}})
    c = carry_settings(s, old, new, d)
    # nothing user-entered is left -> the planner re-runs the default datum selection (RULES 4.1)
    assert c.settings.manufacturing.datums == [] and c.settings.manufacturing.frames == []
    assert {"datum A", "FLATNESS frame"} <= set(c.dropped)


@pytest.mark.parametrize("given,expected", [(None, "A"), ("A", "B"), ("H", "J"), ("N", "P"), ("P", "R"), ("7", "8")])
def test_revision_letters_skip_i_o_q(given, expected):
    s = DrawingSettings.model_validate({"title_block": {"revision": given}} if given else {})
    assert next_revision(s) == expected
