"""Feature recognition vs. construction parameters (scripts/generate_fixtures.py manifest)."""

from collections import Counter

import pytest

from geometry_schema import FeatureType

ALL = ["plate_with_holes", "mounting_plate", "pocketed_block", "bracket", "shaft", "flange",
       "cylindrical_part", "enclosure", "chamfered_block"]
ABS = 1e-6


def feats(ir, t):
    return [f for f in ir.features if f.type == t]


@pytest.mark.parametrize("name", ALL)
def test_holes(analyzed, manifest, name):
    ir, _ = analyzed[name]
    exp = manifest["models"][name]["expected"].get("holes", [])
    holes = feats(ir, FeatureType.HOLE)
    assert len(holes) == sum(e["count"] for e in exp)
    for e in exp:
        match = [h for h in holes if abs(h.diameter - e["diameter"]) < ABS and h.through == e["through"]]
        assert len(match) == e["count"], (name, e)
        if "depth" in e:
            assert all(h.depth == pytest.approx(e["depth"], abs=ABS) for h in match)
    for h in holes:
        assert h.confidence >= 0.95
        assert h.provenance.exact


def test_counterbores(analyzed, manifest):
    ir, _ = analyzed["mounting_plate"]
    [exp] = manifest["models"]["mounting_plate"]["expected"]["counterbores"]
    cbs = [h for h in feats(ir, FeatureType.HOLE) if h.counterbore is not None]
    assert len(cbs) == exp["count"]
    for h in cbs:
        assert h.kind == "COUNTERBORE"
        assert h.counterbore.diameter == pytest.approx(exp["diameter"], abs=ABS)
        assert h.counterbore.depth == pytest.approx(exp["depth"], abs=ABS)
        assert h.axis.direction == pytest.approx((0, 0, -1), abs=ABS)  # entry from the counterbore side (top)
        assert h.axis.origin[2] == pytest.approx(8.0, abs=ABS)


def test_blind_hole_axis_points_into_material(analyzed):
    ir, _ = analyzed["pocketed_block"]
    [h] = feats(ir, FeatureType.HOLE)
    assert not h.through
    assert h.axis.origin == pytest.approx((10.0, 10.0, 30.0), abs=ABS)
    assert h.axis.direction == pytest.approx((0.0, 0.0, -1.0), abs=ABS)
    assert len(h.face_ids) == 2  # wall + floor


@pytest.mark.parametrize("name", ["plate_with_holes", "mounting_plate", "flange"])
def test_patterns(analyzed, manifest, name):
    ir, _ = analyzed[name]
    [exp] = manifest["models"][name]["expected"]["patterns"]
    [p] = feats(ir, FeatureType.PATTERN)
    assert p.pattern_type == exp["pattern_type"]
    assert p.count == exp["count"] == len(p.member_feature_ids)
    by_id = {f.id: f for f in ir.features}
    assert all(by_id[m].diameter == pytest.approx(exp["member_diameter"], abs=ABS) for m in p.member_feature_ids)
    if "pitches" in exp:
        assert p.pitches == pytest.approx(exp["pitches"], abs=ABS)
    if "pitch_circle_diameter" in exp:
        assert p.pitch_circle_diameter == pytest.approx(exp["pitch_circle_diameter"], abs=ABS)
        assert p.angular_step_deg == pytest.approx(exp["angular_step_deg"], abs=1e-6)
        assert p.center == pytest.approx((0.0, 0.0, p.center[2]), abs=ABS)


def test_no_pattern_for_mixed_or_small_groups(analyzed):
    for name in ["pocketed_block", "bracket", "enclosure", "cylindrical_part"]:
        assert not feats(analyzed[name][0], FeatureType.PATTERN), name


@pytest.mark.parametrize("name", ["pocketed_block", "enclosure"])
def test_pockets(analyzed, manifest, name):
    ir, _ = analyzed[name]
    [exp] = manifest["models"][name]["expected"]["pockets"]
    [p] = feats(ir, FeatureType.POCKET)
    assert (p.length, p.width, p.depth) == pytest.approx((exp["length"], exp["width"], exp["depth"]), abs=ABS)
    assert p.floor_normal == pytest.approx((0, 0, 1), abs=ABS)


def test_no_false_pockets(analyzed):
    for name in ["plate_with_holes", "mounting_plate", "bracket", "shaft", "flange", "cylindrical_part", "chamfered_block"]:
        assert not feats(analyzed[name][0], FeatureType.POCKET), name


def test_slot(analyzed, manifest):
    ir, _ = analyzed["bracket"]
    [exp] = manifest["models"]["bracket"]["expected"]["slots"]
    [s] = feats(ir, FeatureType.SLOT)
    assert s.width == pytest.approx(exp["width"], abs=ABS)
    assert s.length == pytest.approx(exp["length"], abs=ABS)
    assert s.center_distance == pytest.approx(exp["center_distance"], abs=ABS)
    assert s.through is exp["through"]
    assert s.center == pytest.approx((40.0, 5.0, 40.0), abs=ABS)
    assert s.length_direction == pytest.approx((1, 0, 0), abs=ABS)


@pytest.mark.parametrize("name", ["mounting_plate", "bracket", "chamfered_block"])
def test_fillets(analyzed, manifest, name):
    ir, _ = analyzed[name]
    exp = manifest["models"][name]["expected"]["fillets"]
    fl = feats(ir, FeatureType.FILLET)
    assert len(fl) == sum(e["count"] for e in exp)
    for e in exp:
        assert sum(1 for f in fl if abs(f.radius - e["radius"]) < ABS and f.concave == e["concave"]) == e["count"]


@pytest.mark.parametrize("name", ["shaft", "chamfered_block"])
def test_chamfers(analyzed, manifest, name):
    ir, _ = analyzed[name]
    [exp] = manifest["models"][name]["expected"]["chamfers"]
    ch = feats(ir, FeatureType.CHAMFER)
    assert len(ch) == exp["count"]
    for c in ch:
        assert (c.distance_1, c.distance_2) == pytest.approx((exp["distance"], exp["distance"]), abs=ABS)
        assert c.angle_deg == pytest.approx(45.0, abs=1e-6)


@pytest.mark.parametrize("name", ["shaft", "flange", "cylindrical_part"])
def test_bosses(analyzed, manifest, name):
    ir, _ = analyzed[name]
    exp = manifest["models"][name]["expected"]["bosses"]
    got = Counter(round(b.diameter, 6) for b in feats(ir, FeatureType.BOSS))
    assert got == Counter({e["diameter"]: e["count"] for e in exp})


def test_threads_are_never_invented(analyzed):
    for ir, _ in analyzed.values():
        assert all(f.type != "THREAD" for f in ir.features)
        assert any("THREAD" in s for s in ir.analysis.not_recognized)
