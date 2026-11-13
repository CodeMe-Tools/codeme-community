"""Syntax verification runner orchestrating multi-language parsing and repair."""

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from codeme.syntax.diagnostic import SyntaxDiagnostic
from codeme.syntax.python_parser import PythonParser
from codeme.syntax.js_parser import JSParser
from codeme.syntax.swift_parser import SwiftParser
from codeme.syntax.treesitter_parser import TreeSitterParser
from codeme.syntax.config_parser import ConfigAndShellParser
from codeme.syntax.grammar_installer import GrammarManager

PYTHON_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
SWIFT_EXTS = {".swift"}
RUST_EXTS = {".rs"}
GO_EXTS = {".go"}
CPP_EXTS = {".c", ".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".h"}
JAVA_EXTS = {".java"}
KOTLIN_EXTS = {".kt", ".kts"}
RUBY_EXTS = {".rb"}
TREESITTER_EXTS = RUST_EXTS | GO_EXTS | CPP_EXTS | JAVA_EXTS | KOTLIN_EXTS | RUBY_EXTS
CONFIG_SHELL_EXTS = (
    ConfigAndShellParser.JSON_EXTS
    | ConfigAndShellParser.TOML_EXTS
    | ConfigAndShellParser.SHELL_EXTS
)

SUPPORTED_EXTS = PYTHON_EXTS | JS_EXTS | SWIFT_EXTS | TREESITTER_EXTS | CONFIG_SHELL_EXTS

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".tox", ".idea", ".vscode"
}


class SyntaxRunner:
    """Executes syntax verification and deterministic repair across a repo or file."""

    def __init__(
        self,
        fix: bool = False,
        verbose: bool = False,
        auto_install: bool = False,
        no_install: bool = False,
    ):
        self.fix = fix
        self.verbose = verbose
        self.py_parser = PythonParser()
        self.js_parser = JSParser()
        self.swift_parser = SwiftParser()
        self.grammar_manager = GrammarManager(auto_install=auto_install, no_install=no_install)
        self.ts_parser = TreeSitterParser(grammar_manager=self.grammar_manager)
        self.config_parser = ConfigAndShellParser()

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
        elif ext in CONFIG_SHELL_EXTS:
            parser = self.config_parser
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

    def _record_audit(self, base_dir: Path, exit_code: int, duration_ms: float, raw_bytes: int, returned_bytes: int, diag_count: int) -> None:
        try:
            from codeme.core.audit import AuditLog, AuditLogger, TokenMetrics, generate_run_id
            logger = AuditLogger(log_dir=base_dir / ".codeme" / "logs")
            metrics = TokenMetrics.calculate(raw_output_bytes=raw_bytes, returned_bytes=returned_bytes)
            logger.record_run(AuditLog(
                run_id=generate_run_id(),
                tool_or_command="codeme-syntax",
                exit_code=exit_code,
                duration_ms=duration_ms,
                metrics=metrics,
                diagnostics_count=diag_count,
            ))
        except Exception:
            pass

    def run(self, repo_path: Optional[str] = None, file_path: Optional[str] = None) -> int:
        """Executes verification over target path or file.

        Returns 0 on clean pass (universal silent success contract),
        or 1 on syntax violation with diagnostics emitted to stderr.
        """
        start_time = time.perf_counter()
        targets: List[Path] = []
        if file_path:
            p = Path(file_path).resolve()
            if not p.exists():
                sys.stderr.write(f"[CDM-SYN-007] {file_path}: File not found\n")
                return 1
            targets = [p]
            base_dir = p.parent
        else:
            base_dir = Path(repo_path).resolve() if repo_path else Path.cwd().resolve()
            if not base_dir.exists():
                sys.stderr.write(f"[CDM-SYN-007] {base_dir}: Directory not found\n")
                return 1
            targets = self.discover_files(base_dir)

        diagnostics: List[SyntaxDiagnostic] = []
        raw_bytes = 0
        for target in targets:
            try:
                raw_bytes += target.stat().st_size
            except OSError:
                pass
            diag = self.run_file(target)
            if diag is not None:
                diagnostics.append(diag)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        if not diagnostics:
            self._record_audit(base_dir, 0, duration_ms, raw_bytes, 0, 0)
            # Universal contract: Routine success outputs 0 bytes on stdout/stderr and exits with code 0
            return 0

        # Output diagnostics to stderr
        out_text = "".join(diag.format() + "\n\n" for diag in diagnostics)
        sys.stderr.write(out_text)
        self._record_audit(base_dir, 1, duration_ms, raw_bytes, len(out_text.encode("utf-8")), len(diagnostics))

        return 1
