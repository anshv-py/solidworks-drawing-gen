"""Stable, content-derived identifiers.

IDs depend only on geometry (rounded to ``ROUND_DIGITS`` decimals of a mm), not
on traversal order, so re-analysing the same file yields the same IDs and
downstream references (DrawingPlan, QA) stay valid.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

ROUND_DIGITS = 4


def _fmt(value: object) -> str:
    if isinstance(value, float):
        v = round(value, ROUND_DIGITS)
        return repr(0.0 if v == 0 else v)  # normalise -0.0
    if isinstance(value, (list, tuple)):
        return "(" + ",".join(_fmt(v) for v in value) + ")"
    return str(value)


def signature(*parts: object) -> str:
    return hashlib.sha1("|".join(_fmt(p) for p in parts).encode()).hexdigest()


def make_id(prefix: str, sig: str, length: int = 10) -> str:
    return f"{prefix}-{sig[:length]}"


def feature_id(prefix: str, member_signatures: Iterable[str]) -> str:
    return make_id(prefix, signature(*sorted(member_signatures)), 8)


def dedupe(ids: Sequence[str]) -> list[str]:
    """Disambiguate identical IDs deterministically (suffix by occurrence order)."""
    seen: dict[str, int] = {}
    out = []
    for i in ids:
        n = seen.get(i, 0)
        seen[i] = n + 1
        out.append(i if n == 0 else f"{i}.{n}")
    return out
