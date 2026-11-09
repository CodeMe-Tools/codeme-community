"""Cyclomatic complexity and nesting depth analysis."""

import ast
from dataclasses import dataclass
from typing import List
from codeme.quality.diagnostic import QualityDiagnostic, build_snippet


@dataclass
class FunctionMetrics:
    name: str
    line: int
    col: int
    complexity: int
    nesting_depth: int


class ComplexityVisitor(ast.NodeVisitor):
    """Computes McCabe cyclomatic complexity of an AST subtree."""

    def __init__(self) -> None:
        self.complexity = 1  # Base complexity

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each 'and' or 'or' adds decision points: len(values) - 1
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        # Each case in match statement represents a branch
        if hasattr(node, "cases"):
            self.complexity += max(0, len(node.cases) - 1)
        self.generic_visit(node)


def compute_nesting_depth(node: ast.AST) -> int:
    """Computes the maximum nesting depth of compound statements within a node."""
    max_depth = 0

    def walk_block(statements: List[ast.stmt], current_depth: int) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, current_depth)

        for stmt in statements:
            if isinstance(stmt, ast.If):
                # An If block increments nesting depth
                walk_block(stmt.body, current_depth + 1)

                # Check orelse: if orelse has a single ast.If, it's an 'elif' (same depth)
                if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
                    walk_block(stmt.orelse, current_depth)  # 'elif' keeps current_depth
                elif stmt.orelse:
                    walk_block(stmt.orelse, current_depth + 1)

            elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)):
                walk_block(stmt.body, current_depth + 1)
                if hasattr(stmt, "orelse") and stmt.orelse:
                    walk_block(stmt.orelse, current_depth + 1)
                if hasattr(stmt, "handlers"):
                    for handler in stmt.handlers:
                        walk_block(handler.body, current_depth + 1)
                if hasattr(stmt, "finalbody") and stmt.finalbody:
                    walk_block(stmt.finalbody, current_depth + 1)

            elif hasattr(stmt, "body") and isinstance(stmt.body, list):
                walk_block(stmt.body, current_depth + 1)

    if hasattr(node, "body") and isinstance(node.body, list):
        walk_block(node.body, 1)

    return max_depth


def analyze_functions(source: str, file_path: str = "<unknown>") -> List[FunctionMetrics]:
    """Analyzes all functions and methods in Python source for complexity and nesting."""
    metrics: List[FunctionMetrics] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return metrics

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visitor = ComplexityVisitor()
            # Visit body of the function (ignoring nested functions when computing this function's direct complexity)
            for child in node.body:
                visitor.visit(child)

            nesting = compute_nesting_depth(node)
            metrics.append(FunctionMetrics(
                name=node.name,
                line=node.lineno,
                col=node.col_offset + 1,
                complexity=visitor.complexity,
                nesting_depth=nesting,
            ))

    return metrics


def check_complexity(
    source: str,
    file_path: str,
    max_complexity: int = 10,
    max_nesting_depth: int = 4
) -> List[QualityDiagnostic]:
    """Checks cyclomatic complexity and nesting depth thresholds."""
    diagnostics: List[QualityDiagnostic] = []
    func_metrics = analyze_functions(source, file_path)

    for m in func_metrics:
        if m.complexity > max_complexity:
            snippet = build_snippet(source, m.line, m.col)
            diagnostics.append(QualityDiagnostic(
                code="CDM-QLT-001",
                file_path=file_path,
                line=m.line,
                col=m.col,
                message=f"Cyclomatic complexity of function '{m.name}' is {m.complexity} (max allowed {max_complexity})",
                snippet=snippet,
                recommendation=f"Refactor function '{m.name}' into smaller, focused helper functions.",
            ))

        if m.nesting_depth > max_nesting_depth:
            snippet = build_snippet(source, m.line, m.col)
            diagnostics.append(QualityDiagnostic(
                code="CDM-QLT-002",
                file_path=file_path,
                line=m.line,
                col=m.col,
                message=f"Nesting depth of function '{m.name}' is {m.nesting_depth} (max allowed {max_nesting_depth})",
                snippet=snippet,
                recommendation=f"Flatten nested blocks in '{m.name}' using guard clauses, early returns, or helper functions.",
            ))

    return diagnostics
