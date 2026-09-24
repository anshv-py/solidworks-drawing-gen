"""Deterministic drawing QA + repair actions.

``validate(plan, candidates, geometry, compiled, rendered) -> QaReport``. CRITICAL issues block
export. Repairs are compiler options (``REDUCE_SCALE``, ``INCREASE_TIER_GAP``) applied by the
pipeline for at most ``QA_MAX_RETRIES`` (default 3) extra iterations. Visual (vision-model) QA is
not implemented, and no LLM is used.
"""

from drawing_qa.checks import INCREASE_TIER_GAP, REDUCE_SCALE, Rendered, validate

DEFAULT_MAX_RETRIES = 3
__all__ = ["validate", "Rendered", "REDUCE_SCALE", "INCREASE_TIER_GAP", "DEFAULT_MAX_RETRIES"]
