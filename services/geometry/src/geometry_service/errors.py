"""Errors shared across the geometry service (no OCCT imports here)."""

from __future__ import annotations


class CadImportError(Exception):
    """The file could not be imported as CAD geometry."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
