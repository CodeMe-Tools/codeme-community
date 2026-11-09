"""Quality gate configuration models and loader."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ArchitectureRule:
    layer_name: str
    path_patterns: List[str]
    forbidden_imports: List[str]


@dataclass
class QualityConfig:
    max_cyclomatic_complexity: int = 10
    max_nesting_depth: int = 4
    max_file_lines: int = 500
    max_function_lines: int = 50
    architecture_rules: List[ArchitectureRule] = field(default_factory=lambda: [
        ArchitectureRule(
            layer_name="Domain Layer",
            path_patterns=["domain/", "models/", "src/domain/", "src/models/"],
            forbidden_imports=["infrastructure", "db", "http", "api"]
        )
    ])
    check_unused_imports: bool = True
    check_trailing_whitespace: bool = True

    @classmethod
    def load(cls, config_path: Optional[Path] = None, base_dir: Optional[Path] = None) -> "QualityConfig":
        """Loads configuration from specified path, or searches .codeme-quality.json in base_dir."""
        search_paths: List[Path] = []
        if config_path:
            search_paths.append(config_path)
        else:
            root = base_dir or Path.cwd()
            search_paths.append(root / ".codeme-quality.json")
            search_paths.append(root / "codeme-quality.json")

        for p in search_paths:
            if p.is_file():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return cls.from_dict(data)
                except Exception:
                    pass

        return cls()

    @classmethod
    def from_dict(cls, data: dict) -> "QualityConfig":
        arch_rules = []
        raw_arch = data.get("architecture", {}).get("rules", [])
        if raw_arch:
            for r in raw_arch:
                arch_rules.append(ArchitectureRule(
                    layer_name=r.get("layer_name", r.get("layer", "Unnamed Layer")),
                    path_patterns=r.get("path_patterns", []),
                    forbidden_imports=r.get("forbidden_imports", []),
                ))
        else:
            arch_rules = [
                ArchitectureRule(
                    layer_name="Domain Layer",
                    path_patterns=["domain/", "models/", "src/domain/", "src/models/"],
                    forbidden_imports=["infrastructure", "db", "http", "api"]
                )
            ]

        clean_code = data.get("clean_code", {})
        return cls(
            max_cyclomatic_complexity=data.get("max_cyclomatic_complexity", 10),
            max_nesting_depth=data.get("max_nesting_depth", 4),
            max_file_lines=data.get("max_file_lines", 500),
            max_function_lines=data.get("max_function_lines", 50),
            architecture_rules=arch_rules,
            check_unused_imports=clean_code.get("unused_imports", data.get("check_unused_imports", True)),
            check_trailing_whitespace=clean_code.get("trailing_whitespace", data.get("check_trailing_whitespace", True)),
        )
