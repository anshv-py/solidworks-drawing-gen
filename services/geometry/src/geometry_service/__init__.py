"""OCCT geometry pipeline: STEP/STL -> GeometryIR.

Importing this package does not import OCCT; use ``geometry_service.analyze``.
The CLI (``python -m geometry_service``) is the process boundary used by the API.
"""

from __future__ import annotations

__all__ = ["analyze_file"]


def analyze_file(*args, **kwargs):  # pragma: no cover - thin lazy re-export
    from geometry_service.analyze import analyze_file as _impl

    return _impl(*args, **kwargs)
