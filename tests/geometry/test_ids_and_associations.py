from geometry_service.analyze import analyze_file
from shared_types import SourceFormat


def test_ids_are_stable_across_runs(models_dir, analyzed):
    first, _ = analyzed["mounting_plate"]
    second, _ = analyze_file(models_dir / "mounting_plate.step", SourceFormat.STEP, with_preview=False)
    assert [f.id for f in first.features] == [f.id for f in second.features]
    assert [f.id for f in first.faces] == [f.id for f in second.faces]
    assert [e.id for e in first.edges] == [e.id for e in second.edges]


def test_ids_are_unique_and_references_resolve(analyzed):
    for name, (ir, _) in analyzed.items():
        face_ids = {f.id for f in ir.faces}
        edge_ids = {e.id for e in ir.edges}
        vertex_ids = {v.id for v in ir.vertices}
        feature_ids = [f.id for f in ir.features]
        assert len(face_ids) == len(ir.faces), name
        assert len(edge_ids) == len(ir.edges), name
        assert len(set(feature_ids)) == len(feature_ids), name
        for f in ir.faces:
            assert set(f.edge_ids) <= edge_ids and set(f.adjacent_face_ids) <= face_ids
        for e in ir.edges:
            assert set(e.face_ids) <= face_ids and set(e.vertex_ids) <= vertex_ids
        for feat in ir.features:
            assert feat.face_ids, (name, feat.id)
            assert set(feat.face_ids) <= face_ids, (name, feat.id)
            assert set(feat.edge_ids) <= edge_ids, (name, feat.id)
            if feat.type == "PATTERN":
                assert set(feat.member_feature_ids) <= set(feature_ids)


def test_adjacency_is_symmetric(analyzed):
    ir, _ = analyzed["bracket"]
    adj = {f.id: set(f.adjacent_face_ids) for f in ir.faces}
    for a, nbs in adj.items():
        for b in nbs:
            assert a in adj[b]


def test_edge_convexity_counts_on_pocketed_block(analyzed):
    ir, _ = analyzed["pocketed_block"]
    counts = {}
    for e in ir.edges:
        counts[e.convexity] = counts.get(e.convexity, 0) + 1
    # 12 box edges + 4 pocket rim + 1 hole rim convex; 4 floor + 4 corner + 1 hole bottom concave
    assert counts["CONVEX"] == 17
    assert counts["CONCAVE"] == 9
