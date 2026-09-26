"""Product data of a STEP file (ISO 10303-21): part number, name, revision, material, mass.

Read directly from the exchange file's DATA section (no geometry kernel involved):

- ``PRODUCT(id, name, description, ...)``               - identifier / name of the part
- ``PRODUCT_DEFINITION_FORMATION[_WITH_SPECIFIED_SOURCE](id, ...)`` - the version (revision) id
- ``MATERIAL_DESIGNATION(name, (definitions))``         - AP214 / AP242 material
- user-defined attributes (AP214 convention used by CAD systems to export custom properties):
  ``PROPERTY_DEFINITION`` -> ``PROPERTY_DEFINITION_REPRESENTATION`` -> ``REPRESENTATION`` whose items are
  ``DESCRIPTIVE_REPRESENTATION_ITEM(name, value)`` or ``MEASURE_REPRESENTATION_ITEM(name, value, unit)``

Nothing is guessed: translator placeholders ("Open CASCADE STEP translator ..."), empty ids and
unevaluated CAD property links (e.g. ``"SW-Material@Part1.SLDPRT"``) are ignored. Every value keeps
the STEP entity it came from. Which custom properties a given CAD system exports is UNVERIFIED for
real SolidWorks / CATIA / NX files (tested on synthetic files following the AP214 convention).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from geometry_schema import CadMetadata

MAX_BYTES = 200 * 1024 * 1024
_PLACEHOLDER = re.compile(r"^(open cascade step translator.*|none|any|n/?a|unknown|default|part\d*|)$", re.IGNORECASE)
_LINK = re.compile(r'^\s*"?sw-[^@]*@|^\s*\$prp', re.IGNORECASE)  # SolidWorks link text (never evaluated)
_KEYS = {
    "material": ("material", "materialname", "materialdesignation", "werkstoff"),
    "part_number": ("partnumber", "partno", "partnum", "number", "articlenumber", "itemnumber"),
    "revision": ("revision", "rev", "revisionlevel", "version"),
    "description": ("description", "title", "designation", "benennung"),
    "mass": ("mass", "weight", "masse", "gewicht"),
}


class _Parser:
    """Minimal Part 21 argument parser: strings, #refs, numbers, enums, $, *, lists, typed values."""

    def __init__(self, text: str) -> None:
        self.t, self.i = text, 0

    def ws(self) -> None:
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n":
            self.i += 1

    def value(self):
        self.ws()
        c = self.t[self.i]
        if c == "'":
            j, out = self.i + 1, []
            while True:
                k = self.t.index("'", j)
                out.append(self.t[j:k])
                if k + 1 < len(self.t) and self.t[k + 1] == "'":
                    out.append("'")
                    j = k + 2
                    continue
                self.i = k + 1
                return _decode("".join(out))
        if c == "(":
            self.i += 1
            items = []
            self.ws()
            if self.t[self.i] == ")":
                self.i += 1
                return items
            while True:
                items.append(self.value())
                self.ws()
                if self.t[self.i] == ",":
                    self.i += 1
                    continue
                self.i += 1  # ')'
                return items
        m = re.compile(r"#\d+|\.[A-Z_0-9]+\.|[-+]?\d[\d.]*(?:E[-+]?\d+)?|\$|\*|[A-Z_][A-Z_0-9]*").match(self.t, self.i)
        if not m:
            raise ValueError(f"unexpected {self.t[self.i:self.i + 20]!r}")
        tok = m.group(0)
        self.i = m.end()
        if tok[0] == "#":
            return ("REF", int(tok[1:]))
        if tok[0].isalpha() or tok[0] == "_":  # typed value, e.g. MASS_MEASURE(1.5)
            self.ws()
            if self.i < len(self.t) and self.t[self.i] == "(":
                return (tok, self.value())
            return tok
        if tok in ("$", "*") or tok.startswith("."):
            return None if tok == "$" else tok
        return float(tok)


def _decode(s: str) -> str:
    """ISO 10303-21 string escapes: \\X2\\hhhh...\\X0\\ (UCS-2), \\X\\hh (ISO 8859-1), \\\\."""
    s = re.sub(r"\\X2\\((?:[0-9A-F]{4})+)\\X0\\",
               lambda m: "".join(chr(int(m.group(1)[k:k + 4], 16)) for k in range(0, len(m.group(1)), 4)), s)
    s = re.sub(r"\\X\\([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), s)
    return s.replace("\\\\", "\\")


def _entities(text: str) -> dict[int, tuple[str, list]]:
    """Simple instances of the interesting types only (complex instances are skipped)."""
    wanted = ("PRODUCT", "PRODUCT_DEFINITION_FORMATION", "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE",
              "PRODUCT_DEFINITION", "PRODUCT_DEFINITION_SHAPE", "MATERIAL_DESIGNATION", "PROPERTY_DEFINITION",
              "PROPERTY_DEFINITION_REPRESENTATION", "REPRESENTATION", "DESCRIPTIVE_REPRESENTATION_ITEM",
              "MEASURE_REPRESENTATION_ITEM", "NEXT_ASSEMBLY_USAGE_OCCURRENCE")
    start = text.find("DATA;")
    out: dict[int, tuple[str, list]] = {}
    for m in re.finditer(r"#(\d+)\s*=\s*([A-Z_][A-Z_0-9]*)\s*\(", text[start:] if start >= 0 else text):
        name = m.group(2)
        if name not in wanted:
            continue
        p = _Parser(text[start:] if start >= 0 else text)
        p.i = m.end() - 1
        try:
            out[int(m.group(1))] = (name, p.value())
        except (ValueError, IndexError):
            continue
    return out


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _clean(v) -> str | None:
    if not isinstance(v, str):
        return None
    v = " ".join(v.split())
    if _PLACEHOLDER.match(v) or _LINK.match(v):
        return None
    return v[:80]


def _mass_grams(value: str | float, unit_hint: str = "") -> float | None:
    if isinstance(value, float):
        num, unit = value, unit_hint
    else:
        m = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?)\s*([a-zA-Z]*)\s*$", value)
        if not m:
            return None
        num, unit = float(m.group(1).replace(",", ".")), m.group(2) or unit_hint
    factor = {"g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0, "kilogram": 1000.0, "lb": 453.59237,
              "lbs": 453.59237}.get(unit.lower())
    return None if factor is None or num <= 0 else num * factor


@dataclass
class _Meta:
    name: str | None = None
    part_number: str | None = None
    description: str | None = None
    revision: str | None = None
    material: str | None = None
    mass_g: float | None = None
    assembly: bool = False
    attributes: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)


def read_step_metadata(path: Path) -> CadMetadata:
    raw = path.read_bytes()[:MAX_BYTES]
    text = raw.decode("latin-1")
    ents = _entities(text)
    meta = _Meta()
    products = [(i, a) for i, (n, a) in ents.items() if n == "PRODUCT"]
    # an assembly has several products (NEXT_ASSEMBLY_USAGE_OCCURRENCE): identification is ambiguous
    assembly = any(n == "NEXT_ASSEMBLY_USAGE_OCCURRENCE" for n, _ in ents.values()) or len(products) > 1
    meta.assembly = assembly
    if len(products) == 1:
        pid, args = products[0]
        ident, name = _clean(args[0]), _clean(args[1])
        if name:
            meta.name, meta.sources["name"] = name, f"STEP PRODUCT #{pid} name"
        if ident and ident != name:  # an id equal to the name is the file name, not a part number
            meta.part_number, meta.sources["part_number"] = ident, f"STEP PRODUCT #{pid} id"
        desc = _clean(args[2]) if len(args) > 2 else None
        if desc:
            meta.description, meta.sources["description"] = desc, f"STEP PRODUCT #{pid} description"
        for i, (n, a) in sorted(ents.items()):
            if n.startswith("PRODUCT_DEFINITION_FORMATION") and a and len(a) > 2 and a[2] == ("REF", pid):
                rev = _clean(a[0])
                if rev:
                    meta.revision, meta.sources["revision"] = rev, f"STEP {n} #{i} id"
                break

    materials = sorted({_clean(a[0]) for n, a in ents.values() if n == "MATERIAL_DESIGNATION" and a} - {None})
    if len(materials) == 1:
        meta.material = materials[0]
        meta.sources["material"] = "STEP MATERIAL_DESIGNATION"

    # user-defined attributes
    attrs: dict[str, str] = {}
    for i, (n, a) in ents.items():
        if n != "PROPERTY_DEFINITION_REPRESENTATION" or len(a) < 2:
            continue
        rep = ents.get(a[1][1]) if isinstance(a[1], tuple) and a[1][0] == "REF" else None
        if rep is None or rep[0] != "REPRESENTATION" or len(rep[1]) < 2:
            continue
        for ref in rep[1][1] or []:
            item = ents.get(ref[1]) if isinstance(ref, tuple) and ref[0] == "REF" else None
            if item is None or not item[1]:
                continue
            key = item[1][0] if isinstance(item[1][0], str) and item[1][0] else rep[1][0]
            if item[0] == "DESCRIPTIVE_REPRESENTATION_ITEM" and len(item[1]) > 1 and isinstance(item[1][1], str):
                attrs[str(key)] = item[1][1]
            elif item[0] == "MEASURE_REPRESENTATION_ITEM" and len(item[1]) > 1:
                v = item[1][1]
                num = v[1][0] if isinstance(v, tuple) and v[1] else v
                if isinstance(num, float):
                    attrs[str(key)] = f"{num:g}"
    meta.attributes = {k[:40]: " ".join(str(v).split())[:80] for k, v in sorted(attrs.items())}
    by_norm = {_norm(k): (k, v) for k, v in meta.attributes.items()}
    for fld, keys in _KEYS.items():
        hit = next((by_norm[k] for k in keys if k in by_norm), None)
        if hit is None:
            continue
        key, value = hit
        if fld == "mass":
            g = _mass_grams(value) if not _LINK.match(value) else None
            if g is not None and meta.mass_g is None:
                meta.mass_g, meta.sources["mass"] = round(g, 3), f"STEP user-defined attribute '{key}'"
            continue
        v = _clean(value)
        if v and (fld != "description" or meta.description is None):
            # an explicit custom property wins over PRODUCT.id / the formation id / MATERIAL_DESIGNATION
            setattr(meta, fld, v)
            meta.sources[fld] = f"STEP user-defined attribute '{key}'"
    if meta.revision and len(meta.revision) > 4:
        meta.sources.pop("revision", None)
        meta.revision = None  # the title block holds up to 4 characters; a longer "version" is not a revision letter
    return CadMetadata(**asdict(meta))


__all__ = ["read_step_metadata"]
