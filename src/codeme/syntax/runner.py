"""Syntax verification runner orchestrating multi-language parsing and repair."""

import os
import sys
from pathlib import Path
from typing import List, Optional

from codeme.syntax.diagnostic import SyntaxDiagnostic
from codeme.syntax.python_parser import PythonParser
from codeme.syntax.js_parser import JSParser
from codeme.syntax.swift_parser import SwiftParser
from codeme.syntax.treesitter_parser import TreeSitterParser

PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
SWIFT_EXTS = {".swift"}
RUST_EXTS = {".rs"}
GO_EXTS = {".go"}
CPP_EXTS = {".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".h"}
JAVA_EXTS = {".java"}
KOTLIN_EXTS = {".kt", ".kts"}
RUBY_EXTS = {".rb"}
TREESITTER_EXTS = RUST_EXTS | GO_EXTS | CPP_EXTS | JAVA_EXTS | KOTLIN_EXTS | RUBY_EXTS

SUPPORTED_EXTS = PYTHON_EXTS | JS_EXTS | SWIFT_EXTS | TREESITTER_EXTS

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".tox", ".idea", ".vscode"
}


class SyntaxRunner:
    """Executes syntax verification and deterministic repair across a repo or file."""

    def __init__(self, fix: bool = False, verbose: bool = False):
        self.fix = fix
        self.verbose = verbose
        self.py_parser = PythonParser()
        self.js_parser = JSParser()
        self.swift_parser = SwiftParser()
        self.ts_parser = TreeSitterParser()

    def discover_files(self, target_path: Path) -> List[Path]:
        """Finds all supported source files, ignoring ignored directories."""
        if target_path.is_file():
            if target_path.suffix.lower() in SUPPORTED_EXTS:
                return [target_path]
            return []

        files: List[Path] = []
        for root, dirs, filenames in os.walk(target_path):
            # Prune excluded directories in-place
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.endswith(".egg-info")]
            for filename in filenames:
                file_path = Path(root) / filename
                if file_path.suffix.lower() in SUPPORTED_EXTS:
                    files.append(file_path)
        return sorted(files)

    def run_file(self, file_path: Path) -> Optional[SyntaxDiagnostic]:
        """Runs syntax check (and repair if configured) on a single file."""
        ext = file_path.suffix.lower()
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            return SyntaxDiagnostic(
                code="CDM-SYN-007",
                file_path=str(file_path),
                line=0,
                col=0,
                message=f"Failed to read file: {e}",
                snippet=None,
                recommendation="Check file read permissions and encoding.",
            )

        str_path = str(file_path)
        if ext in PYTHON_EXTS:
            parser = self.py_parser
            is_ts = False
        elif ext in JS_EXTS:
            parser = self.js_parser
            is_ts = False
        elif ext in SWIFT_EXTS:
            parser = self.swift_parser
            is_ts = False
        elif ext in TREESITTER_EXTS:
            parser = self.ts_parser
            is_ts = True
        else:
            return None

        if self.fix:
            if is_ts:
                repaired, new_source, diag = parser.repair(source, file_path=str_path, ext=ext)
            else:
                repaired, new_source, diag = parser.repair(source, file_path=str_path)
            if repaired:
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(new_source)
                except Exception as e:
                    return SyntaxDiagnostic(
                        code="CDM-SYN-007",
                        file_path=str_path,
                        line=0,
                        col=0,
                        message=f"Failed to write repaired file: {e}",
                        snippet=None,
                        recommendation="Check file write permissions.",
                    )
            return diag
        else:
            if is_ts:
                return parser.parse(source, file_path=str_path, ext=ext)
            else:
                return parser.parse(source, file_path=str_path)

    def run(self, repo_path: Optional[str] = None, file_path: Optional[str] = None) -> int:
        """Executes verification over target path or file.

        Returns 0 on clean pass (universal silent success contract),
        or 1 on syntax violation with diagnostics emitted to stderr.
        """
        targets: List[Path] = []
        if file_path:
            p = Path(file_path).resolve()
            if not p.exists():
                sys.stderr.write(f"[CDM-SYN-007] {file_path}: File not found\n")
                return 1
            targets = [p]
        else:
            base_dir = Path(repo_path).resolve() if repo_path else Path.cwd().resolve()
            if not base_dir.exists():
                sys.stderr.write(f"[CDM-SYN-007] {base_dir}: Directory not found\n")
                return 1
            targets = self.discover_files(base_dir)

        diagnostics: List[SyntaxDiagnostic] = []
        for target in targets:
            diag = self.run_file(target)
            if diag is not None:
                diagnostics.append(diag)

        if not diagnostics:
            # Universal contract: Routine success outputs 0 bytes on stdout/stderr and exits with code 0
            return 0

        # Output diagnostics to stderr
        for diag in diagnostics:
            sys.stderr.write(diag.format() + "\n\n")

        return 1
