"""Compliance report: the primary rule set's Universal Mandatory Minimum (EX 1), checked per drawing.

``build_compliance`` works on the plan alone (the pipeline calls it before compiling, to decide the
release stamp) and again with the QA report and the drawing scale (the final report). Hard blockers
(EX 1 gate rule: items 1-8 and 11) stamp the sheet NOT FOR MANUFACTURE and make the explicit release step
refuse; they never block generation or downloads. Warnings (9, 10, 12) are reported.
"""

from __future__ import annotations

import re

from drawing_schema import DrawingPlan, DrawingStandard
from drawing_schema.candidates import DimensionCandidate
from drawing_schema.compliance import ComplianceItem, ComplianceReport, ComplianceStatus as S
from drawing_schema.qa import QaReport
from drawing_schema.roles import FeatureRole, RoleSource, ViewTrigger
from geometry_schema import FeatureType, GeometryIR

# EX 1 item 7: "full thread callout (standard, size, pitch, class)", e.g. M8x1.25-6H
FULL_THREAD = re.compile(r"^\s*M\s*\d+(\.\d+)?\s*[xX×]\s*\d+(\.\d+)?\s*-\s*\d[A-Za-z]{1,2}(\d[A-Za-z]{1,2})?\s*$")
STAMP_DEFAULT = "NOT FOR MANUFACTURE - INCOMPLETE (SEE COMPLIANCE REPORT)"


def _spec(plan: DrawingPlan, name: str) -> tuple[bool, str]:
    f = getattr(plan.engineering_information, name)
    if f.status != "SPECIFIED":
        return False, ""
    origin = {"DEFAULT": " (rule-set default)", "CAD_MODEL": " (from the CAD file)"}.get(
        f.source.value if f.source else "", "")
    return True, f"{f.value}{origin}"


def _item(n: int, requirement: str, blockers: set[int], status: S, details: list[str] | None = None) -> ComplianceItem:
    return ComplianceItem(number=n, requirement=requirement, hard_blocker=n in blockers, status=status,
                          details=details or [])


def build_compliance(plan: DrawingPlan, ir: GeometryIR, candidates: list[DimensionCandidate], *,
                     hard_blockers: list[int], stamp_text: str = STAMP_DEFAULT, qa: QaReport | None = None,
                     extra_triggers: list[ViewTrigger] | None = None) -> ComplianceReport:
    blockers = set(hard_blockers)
    m = plan.manufacturing
    tb = plan.title_block
    placed = {s.candidate_id for s in plan.dimension_selections}
    cands = {c.id: c for c in candidates}
    items: list[ComplianceItem] = []

    # 1 title block
    missing = []
    if not (tb.part_number or tb.drawing_number):
        missing.append("part / drawing number")
    if not (tb.revision or m.revisions):
        missing.append("revision")
    ok, _ = _spec(plan, "material")
    if not ok:
        missing.append("material")
    from_cad = [f"from CAD: {a}" for a in plan.cad_metadata_applied]
    items.append(_item(1, "Title block complete (part number, revision, material, scale, sheet, projection, units)",
                       blockers, S.FAIL if missing else S.PASS,
                       ([f"missing: {', '.join(missing)}"] if missing else
                        ["scale, sheet size, projection symbol and units are always printed"]) + from_cad))

    # 2 general tolerance, 3 default finish
    ok, v = _spec(plan, "general_tolerance")
    if not ok:
        ok, v = _spec(plan, "linear_tolerance")
    items.append(_item(2, "General tolerance note present", blockers, S.PASS if ok else S.FAIL,
                       [v] if ok else ["no general tolerance declared (turn on the rule-set defaults or enter one)"]))
    ok, v = _spec(plan, "surface_finish")
    items.append(_item(3, "Default surface finish note present", blockers, S.PASS if ok else S.FAIL,
                       [v] if ok else ["no default surface finish declared"]))

    # 4 datum reference frame
    letters = {d.letter for d in m.datums}
    if not m.frames:
        items.append(_item(4, "Datum reference frame declared for GD&T", blockers, S.NOT_APPLICABLE,
                           ["no GD&T on the drawing"]))
    else:
        problems = []
        if "A" not in letters and any(f.datums for f in m.frames):
            problems.append("GD&T references datums but datum A is not declared")
        for i, f in enumerate(m.frames, 1):
            undefined = [r.letter for r in f.datums if r.letter not in letters]
            if undefined:
                problems.append(f"frame {i} ({f.characteristic.value}) references undeclared datum(s) "
                                + ", ".join(undefined))
        items.append(_item(4, "Datum reference frame declared for GD&T", blockers, S.FAIL if problems else S.PASS,
                           problems or [f"datums {', '.join(sorted(letters))}"]))

    # 5 every feature dimensioned
    covered: set[str] = set()
    for cid in placed:
        c = cands.get(cid)
        if c is not None:
            covered |= set(c.feature_ids)
    note_features = {fid for t in plan.view_triggers if t.kind.value == "THICKNESS_NOTE" for fid in t.feature_ids}
    covered |= note_features
    for f in ir.features:
        if f.type == FeatureType.PATTERN and (f.id in covered or covered & set(f.member_feature_ids)):
            covered |= {f.id, *f.member_feature_ids}
    undimensioned = [f"{f.type.value.lower()} {f.id}" for f in ir.features if f.id not in covered]
    items.append(_item(5, "Every feature dimensioned or covered by the general tolerance", blockers,
                       S.FAIL if undimensioned else S.PASS,
                       [f"no dimension: {', '.join(undimensioned[:12])}"] if undimensioned else []))

    # 6 no duplicate dimensions
    dup_issues = [i.message for i in (qa.issues if qa else []) if i.check_id in ("QA-DIM-003", "QA-DIM-004")]
    # the same candidate placed twice (a measurement shown in two views); chains / repeated intervals are
    # removed by the planner and re-checked by QA (QA-DIM-003 / QA-DIM-004)
    seen: dict[str, int] = {}
    for s in plan.dimension_selections:
        seen[s.candidate_id] = seen.get(s.candidate_id, 0) + 1
    dups = [f"{cid} placed {n} times" for cid, n in seen.items() if n > 1]
    items.append(_item(6, "No duplicate dimensions", blockers, S.FAIL if (dup_issues or dups) else S.PASS,
                       dup_issues + dups))

    # 7 threads
    roles = plan.feature_roles
    tapped = [a for a in roles if a.role == FeatureRole.TAPPED_HOLE]
    threads = {t.feature_id: t for t in m.threads}
    if not tapped and not threads:
        items.append(_item(7, "Every thread fully designated (standard, size, pitch, class, depth)", blockers,
                           S.NOT_APPLICABLE, ["no tapped holes known - automatic thread recognition arrives in "
                                              "phase 4; until then a thread is known once its callout is entered"]))
    else:
        problems = []
        feats = {f.id: f for f in ir.features}
        for a in tapped:
            if a.target.ref not in threads:
                problems.append(f"{a.description}: tapped hole without a thread callout")
        for fid, t in threads.items():
            if not FULL_THREAD.match(t.designation):
                problems.append(f"{t.designation}: not a full designation (e.g. M8x1.25-6H)")
            h = feats.get(fid)
            if h is not None and getattr(h, "through", True) is False and t.depth is None:
                problems.append(f"{t.designation}: blind thread without a depth")
        items.append(_item(7, "Every thread fully designated (standard, size, pitch, class, depth)", blockers,
                           S.FAIL if problems else S.PASS, problems))

    # 8 functional features explicitly toleranced
    tol_cands = {t.candidate_id for t in m.tolerances}
    frame_refs = {f.target.ref for f in m.frames} | {d.target.ref for d in m.datums}
    lacking = []
    feats = {f.id: f for f in ir.features}
    for a in roles:
        if a.role == FeatureRole.NONE:
            continue
        ref = a.target.ref
        ids = {ref, *getattr(feats.get(ref), "member_feature_ids", [])}
        for p in ir.features:
            if p.type == FeatureType.PATTERN and ref in p.member_feature_ids:
                ids.add(p.id)
        has_tol = any(set(cands[c].feature_ids) & ids for c in tol_cands if c in cands)
        if not (ids & frame_refs or has_tol):
            lacking.append(f"{a.description} ({a.role.value})")
    items.append(_item(8, "Every functional / mating feature has an explicit tolerance or GD&T", blockers,
                       S.FAIL if lacking else S.PASS,
                       [f"only the general tolerance: {', '.join(lacking)}"] if lacking else []))

    # 9 view triggers
    triggers = list(plan.view_triggers) + list(extra_triggers or [])
    open_triggers = [t for t in triggers if not t.satisfied]
    items.append(_item(9, "Section / detail / auxiliary / break views wherever their triggers fire", blockers,
                       S.WARN if open_triggers else S.PASS,
                       [f"{t.kind.value}: {t.message} ({t.rule}) - not drawn yet" for t in open_triggers]))

    # 10 units / standard consistency
    general = plan.engineering_information.general_tolerance.value or ""
    mixed = plan.drawing_standard == DrawingStandard.ASME and general.upper().startswith("ISO")
    items.append(_item(10, "One unit system and one tolerancing standard sheet-wide", blockers,
                       S.WARN if mixed else S.PASS,
                       [f"ASME Y14.5 drawing with an {general} general tolerance - mixed standards"] if mixed
                       else [f"mm; {plan.drawing_standard.value}"]))

    # 11 revision
    items.append(_item(11, "Revision block updated", blockers, S.PASS if (tb.revision or m.revisions) else S.FAIL,
                       [] if (tb.revision or m.revisions) else
                       ["no revision - automatic revision logging on CAD change arrives in phase 7"]))

    # 12 weight / material
    items.append(_item(12, "Weight / material block populated", blockers, S.PASS if tb.weight else S.WARN,
                       [tb.weight] if tb.weight else
                       ["weight not given: the CAD file states no mass and the material is unknown or not in the "
                        "density table (enter the material or the weight)"]))

    releasable = not any(i.hard_blocker and i.status == S.FAIL for i in items)
    return ComplianceReport(
        rule_set=plan.rule_set or "manual",
        items=items,
        assumed_roles=[a for a in roles if a.source == RoleSource.INFERRED],
        view_triggers=triggers,
        releasable=releasable,
        stamp=None if releasable else stamp_text,
    )


__all__ = ["build_compliance", "FULL_THREAD"]
