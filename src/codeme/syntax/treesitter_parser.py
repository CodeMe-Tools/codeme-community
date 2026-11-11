"""Unified Tree-sitter parser producing concrete syntax trees with robust error recovery."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from codeme.syntax.diagnostic import SyntaxDiagnostic, build_snippet


@dataclass(frozen=True)
class LanguageConfig:
    name: str
    grammar_module: str
    extensions: Tuple[str, ...]
    error_code: str


LANGUAGE_CONFIGS: Dict[str, LanguageConfig] = {
    "rust": LanguageConfig(
        name="Rust",
        grammar_module="tree_sitter_rust",
        extensions=(".rs",),
        error_code="CDM-SYN-010",
    ),
    "go": LanguageConfig(
        name="Go",
        grammar_module="tree_sitter_go",
        extensions=(".go",),
        error_code="CDM-SYN-011",
    ),
    "cpp": LanguageConfig(
        name="C++",
        grammar_module="tree_sitter_cpp",
        extensions=(".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".h"),
        error_code="CDM-SYN-012",
    ),
    "java": LanguageConfig(
        name="Java",
        grammar_module="tree_sitter_java",
        extensions=(".java",),
        error_code="CDM-SYN-013",
    ),
    "kotlin": LanguageConfig(
        name="Kotlin",
        grammar_module="tree_sitter_kotlin",
        extensions=(".kt", ".kts"),
        error_code="CDM-SYN-014",
    ),
    "ruby": LanguageConfig(
        name="Ruby",
        grammar_module="tree_sitter_ruby",
        extensions=(".rb",),
        error_code="CDM-SYN-015",
    ),
}

EXT_TO_LANG: Dict[str, str] = {}
for lang_id, config in LANGUAGE_CONFIGS.items():
    for ext in config.extensions:
        EXT_TO_LANG[ext.lower()] = lang_id


class TreeSitterParser:
    """Parses source code into concrete syntax trees using Tree-sitter grammars.

    Leverages GLR error-recovery nodes (ERROR and MISSING) to pinpoint syntax violations
    without requiring any native host compiler toolchains installed.
    """

    def __init__(self) -> None:
        self._languages: Dict[str, Any] = {}
        self._parsers: Dict[str, Any] = {}

    def get_supported_extensions(self) -> Set[str]:
        """Returns all file extensions supported by the Tree-sitter parser."""
        return set(EXT_TO_LANG.keys())

    def get_language_for_extension(self, ext: str) -> Optional[str]:
        """Maps a file extension to its corresponding Tree-sitter language key."""
        return EXT_TO_LANG.get(ext.lower())

    def _get_parser_and_config(self, lang_key: str) -> Tuple[Any, LanguageConfig]:
        """Lazily imports and instantiates a Tree-sitter parser for the language."""
        if lang_key not in LANGUAGE_CONFIGS:
            raise ValueError(f"Unsupported Tree-sitter language: '{lang_key}'")

        config = LANGUAGE_CONFIGS[lang_key]

        if lang_key not in self._parsers:
            from tree_sitter import Language, Parser

            mod = importlib.import_module(config.grammar_module)
            lang_capsule = mod.language()
            ts_lang = Language(lang_capsule)
            parser = Parser(ts_lang)
            self._languages[lang_key] = ts_lang
            self._parsers[lang_key] = parser

        return self._parsers[lang_key], config

    def parse(
        self,
        source: str,
        file_path: str = "<unknown>",
        ext: Optional[str] = None,
    ) -> Optional[SyntaxDiagnostic]:
        """Parses source code using Tree-sitter.

        Returns None if the file parses cleanly without error nodes (silent success),
        or a structured SyntaxDiagnostic pinpointing the error location.
        """
        if ext is None:
            ext = Path(file_path).suffix.lower()

        lang_key = self.get_language_for_extension(ext)
        if not lang_key:
            return None

        try:
            parser, config = self._get_parser_and_config(lang_key)
        except Exception as e:
            return SyntaxDiagnostic(
                code="CDM-SYN-007",
                file_path=file_path,
                line=0,
                col=0,
                message=f"Tree-sitter parser initialization failed for {lang_key}: {e}",
                snippet=None,
                recommendation=f"Ensure {config.grammar_module} is installed in Python environment.",
            )

        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)

        if not tree.root_node.has_error:
            # Universal silent success contract: 0 errors
            return None

        # Collect error recovery nodes
        error_nodes = self._collect_error_nodes(tree.root_node)
        if not error_nodes:
            # Fallback if has_error is True but no specific node flagged
            return SyntaxDiagnostic(
                code=config.error_code,
                file_path=file_path,
                line=1,
                col=1,
                message=f"SyntaxError: Invalid {config.name} syntax",
                snippet=build_snippet(source, 1, 1),
                recommendation=f"Review and correct {config.name} syntax.",
            )

        # Select primary error node: prefer explicit missing tokens, or earliest error
        missing_nodes = [n for n in error_nodes if n.is_missing]
        target_node = missing_nodes[0] if missing_nodes else error_nodes[0]

        row = target_node.start_point.row
        column = target_node.start_point.column
        line = row + 1
        col = column + 1

        if target_node.is_missing:
            token = target_node.type
            if token in (")", "}", "]", ">"):
                code = "CDM-SYN-004"
                msg = f"SyntaxError: Missing closing delimiter '{token}'"
                rec = f"Insert matching closing delimiter '{token}'."
            else:
                code = config.error_code
                msg = f"SyntaxError: Missing token '{token}'"
                rec = f"Insert missing '{token}' token at line {line}, column {col}."
        else:
            code = config.error_code
            msg = f"SyntaxError: Unexpected token or invalid {config.name} syntax"
            rec = f"Review and correct {config.name} syntax near line {line}, column {col}."

        snippet = build_snippet(source, line, col)
        return SyntaxDiagnostic(
            code=code,
            file_path=file_path,
            line=line,
            col=col,
            message=msg,
            snippet=snippet,
            recommendation=rec,
        )

    def _collect_error_nodes(self, node: Any) -> List[Any]:
        """Recursively traverses the syntax tree to collect all error recovery nodes."""
        errors: List[Any] = []
        if node.is_error or node.is_missing:
            errors.append(node)
            # If it's an explicit missing node, we don't need its non-existent children
            if node.is_missing:
                return errors

        for child in node.children:
            if child.has_error:
                errors.extend(self._collect_error_nodes(child))

        return errors

    def repair(
        self,
        source: str,
        file_path: str = "<unknown>",
        ext: Optional[str] = None,
        max_passes: int = 3,
    ) -> Tuple[bool, str, Optional[SyntaxDiagnostic]]:
        """Attempts deterministic surgical repairs using Tree-sitter error recovery.

        Returns:
            (repaired, repaired_source, None) if successful,
            (False, source, None) if already valid,
            (False, source, original_diagnostic) if unrepairable (guaranteeing safe rollback).
        """
        initial_diag = self.parse(source, file_path=file_path, ext=ext)
        if initial_diag is None:
            return False, source, None

        if ext is None:
            ext = Path(file_path).suffix.lower()

        lang_key = self.get_language_for_extension(ext)
        if not lang_key:
            return False, source, initial_diag

        try:
            parser, _ = self._get_parser_and_config(lang_key)
        except Exception:
            return False, source, initial_diag

        working_source = source
        for _ in range(max_passes):
            tree = parser.parse(working_source.encode("utf-8"))
            if not tree.root_node.has_error:
                return True, working_source, None

            error_nodes = self._collect_error_nodes(tree.root_node)
            if not error_nodes:
                break

            fixed = self._attempt_repair_pass(working_source, error_nodes, lang_key)
            if fixed is not None and fixed != working_source:
                working_source = fixed
            else:
                break

        # Final re-parse verification
        final_tree = parser.parse(working_source.encode("utf-8"))
        if not final_tree.root_node.has_error:
            return True, working_source, None

        # Rollback invariant: discard invalid mutations, keep original file unmodified
        return False, source, initial_diag

    def _attempt_repair_pass(
        self,
        source: str,
        error_nodes: List[Any],
        lang_key: str,
    ) -> Optional[str]:
        """Applies a single surgical repair candidate based on error recovery node info."""
        lines = source.splitlines(keepends=True)

        # 1. Check for missing token/delimiter
        missing_nodes = [n for n in error_nodes if n.is_missing]
        if missing_nodes:
            target = missing_nodes[0]
            token = target.type
            row = target.start_point.row
            col = target.start_point.column

            if 0 <= row < len(lines):
                line_content = lines[row]
                # Insert token at indicated column
                if col <= len(line_content):
                    new_line = line_content[:col] + token + line_content[col:]
                else:
                    nl = "\n" if line_content.endswith("\n") else ""
                    clean = line_content[:-1] if nl else line_content
                    new_line = clean + token + nl

                new_lines = list(lines)
                new_lines[row] = new_line
                return "".join(new_lines)
            elif row >= len(lines):
                # Missing at EOF (e.g. missing closing delimiter or semicolon)
                nl = "\n" if source.endswith("\n") else ""
                clean = source[:-1] if nl else source
                return clean + token + ("\n" if nl else "")

        # 2. Check for common unclosed block patterns (e.g. Ruby missing 'end' or unclosed '}')
        if lang_key == "ruby":
            # Test appending 'end'
            candidate = source.rstrip() + "\nend\n"
            return candidate

        # 3. Test appending missing closing brace '}' at end of file if error is at end
        if source.strip() and not source.rstrip().endswith("}"):
            candidate = source.rstrip() + "\n}\n"
            return candidate

        return None
