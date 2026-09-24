"""Content-based CAD file type detection. The extension alone is never trusted."""

from __future__ import annotations

import re
import struct
from pathlib import Path

from shared_types import SourceFormat

ALLOWED_EXTENSIONS: dict[str, SourceFormat] = {
    ".step": SourceFormat.STEP,
    ".stp": SourceFormat.STEP,
    ".stl": SourceFormat.STL,
}

_STEP_MAGIC = b"ISO-10303-21;"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_filename(name: str | None) -> str:
    """Display-only filename: basename, restricted charset, bounded length."""
    base = (name or "model").replace("\\", "/").split("/")[-1]
    base = _SAFE_NAME.sub("_", base).strip(" .") or "model"
    return base[:200]


def format_from_extension(name: str) -> SourceFormat | None:
    return ALLOWED_EXTENSIONS.get(Path(name).suffix.lower())


def sniff(path: Path) -> SourceFormat | None:
    """Identify STEP (ISO 10303-21 header) or STL (binary size formula / ASCII grammar)."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(4096)
    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(_STEP_MAGIC):
        return SourceFormat.STEP
    if size >= 84:
        (count,) = struct.unpack_from("<I", head, 80) if len(head) >= 84 else (None,)
        if count is not None and count > 0 and size == 84 + 50 * count:
            return SourceFormat.STL
    if stripped[:5].lower() == b"solid" and b"facet" in head and b"vertex" in head:
        return SourceFormat.STL
    return None
