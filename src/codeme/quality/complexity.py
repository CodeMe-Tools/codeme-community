"""Cyclomatic complexity and nesting depth analysis."""

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from codeme.quality.diagnostic import QualityDiagnostic, build_snippet
from codeme.syntax.treesitter_parser import TreeSitterParser, EXT_TO_LANG

TS_BRANCH_NODES = {
    "if_expression", "if_statement", "while_expression", "while_statement",
    "for_expression", "for_statement", "for_range_loop", "loop_expression",
    "do_statement", "enhanced_for_statement", "match_arm", "case_statement",
    "expression_case_clause", "type_case_clause", "communication_case_clause",
    "when_entry", "catch_clause", "catch_block", "rescue", "unless", "until"
}

TS_COMPOUND_NODES = {
    "if_expression", "if_statement", "while_expression", "while_statement",
    "for_expression", "for_statement", "for_range_loop", "loop_expression",
    "do_statement", "match_expression", "switch_statement", "when_expression",
    "try_statement", "catch_clause", "catch_block", "rescue", "unless", "until"
}

TS_BOOL_OPS = {b"&&", b"||", b"and", b"or"}

TS_FUNCTION_TYPES = {
    "function_item", "function_declaration", "method_declaration",
    "function_definition", "method", "singleton_method", "constructor_declaration"
}


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


def _extract_ts_ident(node) -> Optional[str]:
    """Recursively search for identifier name in declarator node."""
    if node is None:
        return None
    if node.type in ("identifier", "name", "field_identifier"):
        return node.text.decode("utf-8")
    for child in node.children:
        found = _extract_ts_ident(child)
        if found:
            return found
    return None


def analyze_treesitter_functions(
    source: str,
    file_path: str = "<unknown>",
    ext: Optional[str] = None
) -> List[FunctionMetrics]:
    """Analyzes polyglot functions (Rust, Go, C++, Java, Kotlin, Ruby) via Tree-sitter CST."""
    metrics: List[FunctionMetrics] = []
    if ext is None:
        ext = Path(file_path).suffix.lower()

    lang_key = EXT_TO_LANG.get(ext.lower())
    if not lang_key:
        return metrics

    try:
        ts_parser = TreeSitterParser()
        parser, _ = ts_parser._get_parser_and_config(lang_key)
        tree = parser.parse(source.encode("utf-8"))
    except Exception:
        return metrics

    def walk_tree(node):
        if node.type in TS_FUNCTION_TYPES:
            # Extract function name
            name = None
            name_node = node.child_by_field_name("name") or node.child_by_field_name("declarator")
            if name_node:
                name = _extract_ts_ident(name_node)
            if not name:
                name = f"func_line_{node.start_point.row + 1}"

            # Calculate cyclomatic complexity inside function
            complexity = 1
            def walk_comp(child):
                nonlocal complexity
                if child.type in TS_BRANCH_NODES:
                    complexity += 1
                elif child.type == "binary_expression":
                    for op_child in child.children:
                        if op_child.text in TS_BOOL_OPS:
                            complexity += 1
                # Do not recurse into nested function definitions
                for c in child.children:
                    if c.type not in TS_FUNCTION_TYPES:
                        walk_comp(c)

            body_node = node.child_by_field_name("body")
            if body_node:
                for c in body_node.children:
                    walk_comp(c)

            # Calculate nesting depth
            max_depth = 1
            def walk_nest(child, depth):
                nonlocal max_depth
                max_depth = max(max_depth, depth)
                for c in child.children:
                    if c.type not in TS_FUNCTION_TYPES:
                        new_depth = depth + 1 if c.type in TS_COMPOUND_NODES else depth
                        walk_nest(c, new_depth)

            if body_node:
                walk_nest(body_node, 1)

            metrics.append(FunctionMetrics(
                name=name,
                line=node.start_point.row + 1,
                col=node.start_point.column + 1,
                complexity=complexity,
                nesting_depth=max_depth,
            ))

        for child in node.children:
            walk_tree(child)

    walk_tree(tree.root_node)
    return metrics


def analyze_functions(
    source: str,
    file_path: str = "<unknown>",
    ext: Optional[str] = None
) -> List[FunctionMetrics]:
    """Analyzes all functions and methods for complexity and nesting."""
    if ext is None:
        ext = Path(file_path).suffix.lower()

    if ext == ".py":
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
    elif ext in EXT_TO_LANG:
        return analyze_treesitter_functions(source, file_path=file_path, ext=ext)

    return []


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
