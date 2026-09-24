"""Version-specific OCP binding details (cadquery-ocp 8.x / OCCT 8).

OCCT 8 bindings expose NCollection instantiations under ``OCP.OCP.collections``;
the OCCT 7.x ``TopTools_IndexedMapOfShape`` names are not available.
"""

from __future__ import annotations

from importlib import metadata

from OCP.OCP.collections import (  # noqa: F401 - re-exported
    IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeListMap,
    IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap,
    Sequence_TCollection_AsciiString as AsciiStringSequence,
)


def kernel_version() -> str:
    """Version of the OCP bindings (tracks the OCCT version, e.g. 8.0.1)."""
    for dist in ("cadquery-ocp", "cadquery-ocp-novtk"):
        try:
            return f"OCP {metadata.version(dist)}"
        except metadata.PackageNotFoundError:
            continue
    return "OCP unknown"
