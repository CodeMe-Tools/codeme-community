"""Clean code analysis: unused import detection and trailing whitespace checks."""

import ast
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from codeme.quality.diagnostic import QualityDiagnostic, build_snippet


@dataclass
class ImportItem:
    bound_name: str
    original_name: str
    node: ast.AST
    alias: ast.alias
    is_from_import: bool
    module: Optional[str] = None


class UsedNamesVisitor(ast.NodeVisitor):
    """Gathers all identifier names referenced in code outside import statements."""

    def __init__(self) -> None:
        self.used_names: Set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:
        # Do not collect names defined in import
        return

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Do not collect names defined in import
        return

    def visit_Name(self, node: ast.Name) -> None:
        self.used_names.add(node.id)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # String annotations or __all__ elements
        if isinstance(node.value, str):
            # Check if this could be an identifier
            val = node.value.strip()
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", val):
                self.used_names.add(val)
        self.generic_visit(node)


def find_unused_imports(source: str, file_path: str = "<unknown>") -> List[Tuple[ImportItem, QualityDiagnostic]]:
    """Analyzes Python source to locate unused imports."""
    results: List[Tuple[ImportItem, QualityDiagnostic]] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return results

    # 1. Gather all imported items
    imports: List[ImportItem] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                imports.append(ImportItem(
                    bound_name=bound,
                    original_name=alias.name,
                    node=node,
                    alias=alias,
                    is_from_import=False,
                    module=None,
                ))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                # Compiler directives like `from __future__ import annotations` are never referenced as runtime names
                continue
            if node.names and node.names[0].name == "*":
                # Wildcard import cannot be reliably tracked
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                imports.append(ImportItem(
                    bound_name=bound,
                    original_name=alias.name,
                    node=node,
                    alias=alias,
                    is_from_import=True,
                    module=node.module,
                ))

    # 2. Gather used names across the AST
    visitor = UsedNamesVisitor()
    visitor.visit(tree)
    used_names = visitor.used_names

    # Check for dunder all or other special usage
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                used_names.add(elt.value)

    # 3. Filter unused
    for item in imports:
        # Ignore special cases like __init__.py re-exports or __all__
        if item.bound_name not in used_names:
            line = item.node.lineno
            col = item.node.col_offset + 1
            snippet = build_snippet(source, line, col)
            diag = QualityDiagnostic(
                code="CDM-QLT-006",
                file_path=file_path,
                line=line,
                col=col,
                message=f"Unused import '{item.bound_name}'",
                snippet=snippet,
                recommendation=f"Remove unused import '{item.bound_name}' or reference it in the module.",
            )
            results.append((item, diag))

    return results


def remove_unused_imports(source: str, unused_items: List[ImportItem], file_path: str = "<unknown>") -> str:
    """Deterministically removes unused imports from source code.

    Validates with ast.parse to ensure safety; rolls back if syntax breaks.
    """
    if not unused_items:
        return source

    lines = source.splitlines(keepends=True)
    unused_bound_names = {item.bound_name for item in unused_items}

    # Group unused items by their AST statement node
    nodes_to_remove: Set[ast.AST] = set()
    node_to_unused: dict = {}
    for item in unused_items:
        node_to_unused.setdefault(item.node, []).append(item)

    new_lines = list(lines)

    for node, items in node_to_unused.items():
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)

        if isinstance(node, ast.Import):
            remaining_names = [a for a in node.names if (a.asname or a.name.split(".")[0]) not in unused_bound_names]
            if not remaining_names:
                # Remove entire statement lines
                for l in range(start_line - 1, end_line):
                    new_lines[l] = ""
            else:
                # Rewrite import line
                names_str = ", ".join(f"{a.name} as {a.asname}" if a.asname else a.name for a in remaining_names)
                indent = " " * node.col_offset
                new_lines[start_line - 1] = f"{indent}import {names_str}\n"
                for l in range(start_line, end_line):
                    new_lines[l] = ""

        elif isinstance(node, ast.ImportFrom):
            remaining_names = [a for a in node.names if (a.asname or a.name) not in unused_bound_names]
            if not remaining_names:
                # Remove entire statement lines
                for l in range(start_line - 1, end_line):
                    new_lines[l] = ""
            else:
                # Reconstruct clean import
                mod = ("." * getattr(node, "level", 0)) + (node.module or "")
                names_str = ", ".join(f"{a.name} as {a.asname}" if a.asname else a.name for a in remaining_names)
                indent = " " * node.col_offset
                new_lines[start_line - 1] = f"{indent}from {mod} import {names_str}\n"
                for l in range(start_line, end_line):
                    new_lines[l] = ""

    candidate = "".join(new_lines)
    # Validate result with AST
    try:
        ast.parse(candidate, filename=file_path)
        return candidate
    except Exception:
        # Rollback on any issue
        return source


def check_trailing_whitespace(source: str, file_path: str) -> List[QualityDiagnostic]:
    """Detects trailing whitespace on source lines."""
    diagnostics: List[QualityDiagnostic] = []
    lines = source.splitlines()

    for idx, line in enumerate(lines):
        line_num = idx + 1
        if line.endswith(" ") or line.endswith("\t"):
            # Find column where trailing whitespace starts
            stripped = line.rstrip(" \t")
            col = len(stripped) + 1
            snippet = build_snippet(source, line_num, col)
            diagnostics.append(QualityDiagnostic(
                code="CDM-QLT-007",
                file_path=file_path,
                line=line_num,
                col=col,
                message=f"Trailing whitespace on line {line_num}",
                snippet=snippet,
                recommendation=f"Strip trailing whitespace from line {line_num}.",
            ))

    return diagnostics


def fix_trailing_whitespace(source: str) -> str:
    """Removes trailing whitespace from each line preserving line endings."""
    lines = source.splitlines(keepends=True)
    fixed_lines = []
    for line in lines:
        if line.endswith("\r\n"):
            fixed_lines.append(line[:-2].rstrip(" \t") + "\r\n")
        elif line.endswith("\n"):
            fixed_lines.append(line[:-1].rstrip(" \t") + "\n")
        else:
            fixed_lines.append(line.rstrip(" \t"))
    return "".join(fixed_lines)
