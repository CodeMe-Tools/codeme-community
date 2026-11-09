"""Domain-Driven Design (DDD) and architectural boundary enforcement."""

import ast
from typing import List
from codeme.quality.config import ArchitectureRule
from codeme.quality.diagnostic import QualityDiagnostic, build_snippet


def is_submodule_of(imported_mod: str, forbidden_name: str) -> bool:
    """Checks if imported_mod matches or is a submodule of forbidden_name."""
    if not imported_mod:
        return False
    parts = imported_mod.split(".")
    # If forbidden_name is directly one of the segments or the full module starts with it
    if forbidden_name in parts:
        return True
    if imported_mod == forbidden_name or imported_mod.startswith(forbidden_name + "."):
        return True
    return False


def check_architecture_rules(
    source: str,
    file_path: str,
    rules: List[ArchitectureRule]
) -> List[QualityDiagnostic]:
    """Validates architectural layering rules such as DDD domain purity."""
    diagnostics: List[QualityDiagnostic] = []

    # Normalize path with forward slashes
    norm_path = file_path.replace("\\", "/")

    for rule in rules:
        # Check if file belongs to this layer
        matches_layer = any(pattern in norm_path for pattern in rule.path_patterns)
        if not matches_layer:
            continue

        # File is in protected layer, inspect imports
        if file_path.endswith(".py"):
            try:
                tree = ast.parse(source, filename=file_path)
            except SyntaxError:
                return diagnostics

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in rule.forbidden_imports:
                            if is_submodule_of(alias.name, forbidden):
                                col = node.col_offset + 1
                                snippet = build_snippet(source, node.lineno, col)
                                diagnostics.append(QualityDiagnostic(
                                    code="CDM-QLT-005",
                                    file_path=file_path,
                                    line=node.lineno,
                                    col=col,
                                    message=f"Architecture boundary violation: {rule.layer_name} cannot import infrastructure component '{alias.name}'",
                                    snippet=snippet,
                                    recommendation=(
                                        f"Invert the dependency. Define an interface/port in {rule.layer_name} "
                                        f"and implement it in the infrastructure layer."
                                    ),
                                ))
                elif isinstance(node, ast.ImportFrom):
                    mod_name = node.module or ""
                    for forbidden in rule.forbidden_imports:
                        if is_submodule_of(mod_name, forbidden):
                            col = node.col_offset + 1
                            snippet = build_snippet(source, node.lineno, col)
                            diagnostics.append(QualityDiagnostic(
                                code="CDM-QLT-005",
                                file_path=file_path,
                                line=node.lineno,
                                col=col,
                                message=f"Architecture boundary violation: {rule.layer_name} cannot import infrastructure component '{mod_name}'",
                                snippet=snippet,
                                recommendation=(
                                    f"Invert the dependency. Define an interface/port in {rule.layer_name} "
                                    f"and implement it in the infrastructure layer."
                                ),
                            ))

    return diagnostics
