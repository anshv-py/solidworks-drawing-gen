"""Drawing compiler: DrawingPlan + dimension candidates + GeometryIR -> CompiledDrawing.

Deterministic sheet layout (projection method, ISO 5455 scale), dimension/leader placement,
center marks and centerlines. Contains no LLM calls and no CAD-kernel calls.
"""

from drawing_compiler.compiler import CompileOptions, LayoutError, compile_drawing, scale_factor

__all__ = ["CompileOptions", "LayoutError", "compile_drawing", "scale_factor"]
