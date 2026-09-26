"""ISO 286-1/-2 limits of size for the tolerance classes the rule set uses (nominal sizes up to 500 mm).

Deviations are computed from the standard tolerance grades (IT) and the fundamental deviations of
ISO 286-1 tables 1 and 2/3. Only the classes listed below are supported; anything else raises
``UnsupportedFit`` rather than guessing.
"""

from __future__ import annotations

import re

# upper limits of the nominal size ranges (a size equal to a limit belongs to that range: "over a up to b")
_RANGES = (3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500)
# standard tolerance grades, µm
_IT = {
    5: (4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27),
    6: (6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40),
    7: (10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63),
    8: (14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97),
    9: (25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155),
    10: (40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250),
    11: (60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400),
}
# shaft fundamental deviations, µm: upper deviation es (a-h) or lower deviation ei (k-zc)
_ES = {
    "f": (-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68),
    "g": (-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20),
    "h": (0,) * 13,
}
_EI = {
    "k": (0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5),  # grades 4-7; 0 for grades <= 3 and >= 8
    "p": (6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68),
}
_CLASS = re.compile(r"^(?P<letter>[A-Za-z]{1,2})(?P<grade>\d{1,2})$")


class UnsupportedFit(ValueError):
    pass


def _range_index(size: float) -> int:
    if size <= 0 or size > _RANGES[-1]:
        raise UnsupportedFit(f"nominal size {size:g} mm is outside 0-{_RANGES[-1]} mm")
    return next(i for i, upper in enumerate(_RANGES) if size <= upper + 1e-9)


def deviations(size: float, tolerance_class: str) -> tuple[float, float]:
    """(upper, lower) deviation in mm of e.g. ``H7`` (hole) or ``h6`` (shaft) at nominal ``size``."""
    m = _CLASS.match(tolerance_class)
    if not m:
        raise UnsupportedFit(f"not an ISO 286 tolerance class: {tolerance_class!r}")
    letter, grade = m["letter"], int(m["grade"])
    if grade not in _IT:
        raise UnsupportedFit(f"tolerance grade IT{grade} is not tabulated here")
    i = _range_index(size)
    it = _IT[grade][i]
    if letter in ("JS", "js"):
        return it / 2000, -it / 2000
    if letter == "H":
        return it / 1000, 0.0
    hole = letter.isupper()
    shaft = letter.lower()
    if hole:
        raise UnsupportedFit(f"hole class {tolerance_class} is not tabulated here (only H and JS)")
    if shaft in _ES:
        es = _ES[shaft][i]
        return es / 1000, (es - it) / 1000
    if shaft in _EI:
        ei = _EI[shaft][i] if (shaft != "k" or 4 <= grade <= 7) else 0
        return (ei + it) / 1000, ei / 1000
    raise UnsupportedFit(f"shaft class {tolerance_class} is not tabulated here")


__all__ = ["UnsupportedFit", "deviations"]
