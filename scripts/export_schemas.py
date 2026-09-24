"""Export the Pydantic contracts as JSON Schema (source for TypeScript / C# types).

Usage: uv run python scripts/export_schemas.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drawing_schema import DrawingPlan
from geometry_schema import GeometryIR

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    ROOT / "packages/geometry-schema/schema/geometry-ir.schema.json": GeometryIR,
    ROOT / "packages/drawing-schema/schema/drawing-plan.schema.json": DrawingPlan,
}


def _tuples_to_items(node):
    """Rewrite 2020-12 ``prefixItems`` tuples as draft-07 ``items`` arrays (TS/C# generators)."""
    if isinstance(node, dict):
        node = {k: _tuples_to_items(v) for k, v in node.items()}
        if "prefixItems" in node:
            items = node.pop("prefixItems")
            node["items"] = items
            node["additionalItems"] = False
        return node
    if isinstance(node, list):
        return [_tuples_to_items(v) for v in node]
    return node


def render(model) -> str:
    schema = _tuples_to_items(model.model_json_schema(mode="serialization"))
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if committed schemas are stale")
    args = ap.parse_args()
    stale = []
    for path, model in TARGETS.items():
        text = render(model)
        if args.check:
            if not path.exists() or path.read_text() != text:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("stale schemas (run scripts/export_schemas.py):", *stale, sep="\n  ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
