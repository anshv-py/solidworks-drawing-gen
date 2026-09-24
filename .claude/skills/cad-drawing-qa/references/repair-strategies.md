# Repair strategies (issue → DrawingPlanPatch)

| Issue | Patch |
|---|---|
| View outside sheet / excessive overlap | reduce scale to next ISO 5455 step; or change sheet size (only if user allowed AUTO sheet) |
| View-view overlap | re-run layout with larger gaps; move projected view along its alignment axis only |
| Excessive whitespace | increase scale one ISO step |
| Missing dimension | add candidate id to plan (deterministic, from policy) |
| Duplicate dimension | remove all but the placement in the preferred view |
| Redundant chain | drop the lowest-priority link |
| Dimension overlap | re-run annotation layout for that view with stagger |
| Missing center mark / callout | add annotation op for the feature |
| Wrong orientation | recompute orientation transform; regenerate views |
| Engineering info without source | clear the field to UNSPECIFIED |

Patches are validated against the DrawingPlan schema before compilation. The
LLM may *propose* patches; the patch must pass the same deterministic
validation as a fresh plan.
