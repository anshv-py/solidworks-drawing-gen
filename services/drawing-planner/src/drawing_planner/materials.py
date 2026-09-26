"""Nominal densities (g/cm³) of common engineering materials, for the title block weight (EX 1 item 12:
"populated from CAD mass properties"): weight = exact B-Rep volume × nominal density of the *stated*
material. A material that matches no entry gives no weight - nothing is guessed. Values are the usual
handbook nominal densities; the printed weight is marked (CALC.).
"""

from __future__ import annotations

import re

# (pattern on the upper-cased material designation, density g/cm³, what it matched) - specific first
_TABLE: list[tuple[str, float, str]] = [
    (r"\b(316L?|1\.4401|1\.4404|X2CRNIMO17)", 7.98, "stainless steel 316"),
    (r"\b(304L?|1\.4301|1\.4307|X5CRNI18)", 7.93, "stainless steel 304"),
    (r"STAINLESS|INOX|\b1\.4\d{3}\b", 7.9, "stainless steel"),
    (r"TI-?6AL-?4V|\bGRADE\s*5\b|3\.7165", 4.43, "titanium Ti-6Al-4V"),
    (r"TITAN", 4.51, "titanium"),
    (r"\b7075\b|ALZN5,5MGCU", 2.81, "aluminium 7075"),
    (r"\b2024\b|ALCU4MG1", 2.78, "aluminium 2024"),
    (r"\b5083\b|ALMG4,5MN", 2.66, "aluminium 5083"),
    (r"\b(6061|6082|6060|6063)\b|ALMGSI|ALSI1MGMN", 2.70, "aluminium 6xxx"),
    (r"ALUMIN|\bEN AW\b|\bAL\b", 2.70, "aluminium"),
    (r"\bGJS\b|EN-GJS|DUCTILE|\bGGG", 7.1, "ductile cast iron"),
    (r"\bGJL\b|EN-GJL|CAST IRON|\bGG\s?\d", 7.2, "grey cast iron"),
    (r"BRASS|MESSING|CUZN", 8.5, "brass"),
    (r"BRONZE|CUSN", 8.8, "bronze"),
    (r"COPPER|\bCU-?ETP\b|KUPFER", 8.94, "copper"),
    (r"\bPOM\b|ACETAL|DELRIN", 1.41, "POM"),
    (r"\bPEEK\b", 1.30, "PEEK"),
    (r"\bPA ?66?\b|NYLON|POLYAMID", 1.14, "polyamide"),
    (r"\bPTFE\b|TEFLON", 2.15, "PTFE"),
    (r"\bABS\b", 1.05, "ABS"),
    (r"\bPC\b|POLYCARBONAT", 1.20, "polycarbonate"),
    (r"\bPE-?HD\b|\bHDPE\b", 0.95, "HDPE"),
    # structural grades carry suffixes (S355JR, 42CrMo4+QT): match the grade as a prefix
    (r"\b(S235|S275|S355|S460|42CRMO4|34CRNIMO6|16MNCR5)|\b(C45|C35|4140|4340|1018|1045|A36)\b|\bSTEEL|\bSTAHL"
     r"|\bST\s?37|\bST\s?52",
     7.85, "steel"),
]


def density(material: str) -> tuple[float, str] | None:
    """(g/cm³, matched material family) for a material designation, or None."""
    m = material.upper()
    for pattern, rho, what in _TABLE:
        if re.search(pattern, m):
            return rho, what
    return None


def format_mass(grams: float) -> str:
    return f"{grams:.0f} g" if grams < 1000 else f"{grams / 1000:.3g} kg"


__all__ = ["density", "format_mass"]
