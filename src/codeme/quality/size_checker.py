"""File size and function size limits checking."""

import ast
from typing import List
from codeme.quality.diagnostic import QualityDiagnostic, build_snippet


def check_size_limits(
    source: str,
    file_path: str,
    max_file_lines: int = 500,
    max_function_lines: int = 50
) -> List[QualityDiagnostic]:
    """Validates file length and function lengths against configured limits."""
    diagnostics: List[QualityDiagnostic] = []
    lines = source.splitlines()
    total_lines = len(lines)

    # 1. File size check
    if total_lines > max_file_lines:
        snippet = build_snippet(source, 1, 1)
        diagnostics.append(QualityDiagnostic(
            code="CDM-QLT-003",
            file_path=file_path,
            line=1,
            col=1,
            message=f"File length is {total_lines} lines (max allowed {max_file_lines})",
            snippet=snippet,
            recommendation=f"Decompose {file_path} into cohesive smaller modules.",
        ))

    # 2. Function size check (for Python files)
    if file_path.endswith(".py"):
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return diagnostics

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end_lineno = getattr(node, "end_lineno", node.lineno)
                func_length = end_lineno - node.lineno + 1
                if func_length > max_function_lines:
                    col = node.col_offset + 1
                    snippet = build_snippet(source, node.lineno, col)
                    diagnostics.append(QualityDiagnostic(
                        code="CDM-QLT-004",
                        file_path=file_path,
                        line=node.lineno,
                        col=col,
                        message=f"Function '{node.name}' length is {func_length} lines (max allowed {max_function_lines})",
                        snippet=snippet,
                        recommendation=f"Refactor '{node.name}' into smaller single-responsibility functions.",
                    ))

    return diagnostics
