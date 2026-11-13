"""Quality gate runner coordinating complexity, size, architecture, and clean code gates."""

import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from codeme.quality.config import QualityConfig
from codeme.quality.diagnostic import QualityDiagnostic
from codeme.quality.complexity import check_complexity
from codeme.quality.size_checker import check_size_limits
from codeme.quality.architecture import check_architecture_rules
from codeme.quality.clean_code import (
    find_unused_imports,
    remove_unused_imports,
    check_trailing_whitespace,
    fix_trailing_whitespace,
)
from codeme.syntax.treesitter_parser import EXT_TO_LANG

PYTHON_EXTS = {".py"}
TREESITTER_EXTS = set(EXT_TO_LANG.keys())
SUPPORTED_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".swift", ".json", ".md"} | TREESITTER_EXTS

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".tox", ".idea", ".vscode",
    "tests", "__tests__", ".next", ".astro"
}


class QualityRunner:
    """Executes quality checks and clean-code fixes across a repo or file."""

    def __init__(self, config: Optional[QualityConfig] = None, fix: bool = False, verbose: bool = False):
        self.config = config or QualityConfig()
        self.fix = fix
        self.verbose = verbose

    def discover_files(self, target_path: Path) -> List[Path]:
        """Finds all verifiable source files."""
        if target_path.is_file():
            return [target_path]

        files: List[Path] = []
        for root, dirs, filenames in os.walk(target_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.endswith(".egg-info")]
            for filename in filenames:
                file_path = Path(root) / filename
                if file_path.suffix.lower() in SUPPORTED_EXTS:
                    files.append(file_path)
        return sorted(files)

    def run_file(self, file_path: Path) -> List[QualityDiagnostic]:
        """Runs quality gates on a single file, applying fixes if configured."""
        diagnostics: List[QualityDiagnostic] = []
        str_path = str(file_path)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            diagnostics.append(QualityDiagnostic(
                code="CDM-QLT-999",
                file_path=str_path,
                line=0,
                col=0,
                message=f"Failed to read file: {e}",
                snippet=None,
                recommendation="Verify file permissions and UTF-8 encoding.",
            ))
            return diagnostics

        modified = False

        # Apply fixes if requested
        if self.fix:
            # 1. Fix trailing whitespace
            if self.config.check_trailing_whitespace:
                fixed_source = fix_trailing_whitespace(source)
                if fixed_source != source:
                    source = fixed_source
                    modified = True

            # 2. Fix unused imports in Python files
            if self.config.check_unused_imports and file_path.suffix == ".py":
                unused_items = find_unused_imports(source, file_path=str_path)
                if unused_items:
                    items = [item for item, _ in unused_items]
                    fixed_source = remove_unused_imports(source, items, file_path=str_path)
                    if fixed_source != source:
                        source = fixed_source
                        modified = True

            if modified:
                try:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(source)
                except Exception as e:
                    diagnostics.append(QualityDiagnostic(
                        code="CDM-QLT-999",
                        file_path=str_path,
                        line=0,
                        col=0,
                        message=f"Failed to write fixed file: {e}",
                        snippet=None,
                        recommendation="Check file write permissions.",
                    ))
                    return diagnostics

        # Run verification checks
        # 1. Trailing whitespace check
        if self.config.check_trailing_whitespace:
            diagnostics.extend(check_trailing_whitespace(source, str_path))

        # 2. Size limits check (file and function)
        diagnostics.extend(check_size_limits(
            source,
            str_path,
            max_file_lines=self.config.max_file_lines,
            max_function_lines=self.config.max_function_lines,
        ))

        # 3. Complexity & nesting (Python + Polyglot Tree-sitter)
        if file_path.suffix == ".py" or file_path.suffix in TREESITTER_EXTS:
            diagnostics.extend(check_complexity(
                source,
                str_path,
                max_complexity=self.config.max_cyclomatic_complexity,
                max_nesting_depth=self.config.max_nesting_depth,
            ))

        # Python-specific checks
        if file_path.suffix == ".py":
            # 4. Architecture / DDD boundary rules
            diagnostics.extend(check_architecture_rules(
                source,
                str_path,
                rules=self.config.architecture_rules,
            ))

            # 5. Unused imports check
            if self.config.check_unused_imports:
                unused_results = find_unused_imports(source, str_path)
                for _, diag in unused_results:
                    diagnostics.append(diag)

        return diagnostics

    def _record_audit(self, base_dir: Path, exit_code: int, duration_ms: float, raw_bytes: int, returned_bytes: int, diag_count: int) -> None:
        try:
            from codeme.core.audit import AuditLog, AuditLogger, TokenMetrics, generate_run_id
            logger = AuditLogger(log_dir=base_dir / ".codeme" / "logs")
            metrics = TokenMetrics.calculate(raw_output_bytes=raw_bytes, returned_bytes=returned_bytes)
            logger.record_run(AuditLog(
                run_id=generate_run_id(),
                tool_or_command="codeme-quality",
                exit_code=exit_code,
                duration_ms=duration_ms,
                metrics=metrics,
                diagnostics_count=diag_count,
            ))
        except Exception:
            pass

    def run(self, repo_path: Optional[str] = None, file_path: Optional[str] = None) -> int:
        """Executes verification across repository or target file.

        Returns 0 on clean pass (universal silent success contract),
        or 1 on quality violation with diagnostics emitted to stderr.
        """
        start_time = time.perf_counter()
        targets: List[Path] = []
        if file_path:
            p = Path(file_path).resolve()
            if not p.exists():
                sys.stderr.write(f"[CDM-QLT-999] {file_path}: File not found\n")
                return 1
            targets = [p]
            base_dir = p.parent
        else:
            base_dir = Path(repo_path).resolve() if repo_path else Path.cwd().resolve()
            if not base_dir.exists():
                sys.stderr.write(f"[CDM-QLT-999] {base_dir}: Directory not found\n")
                return 1
            targets = self.discover_files(base_dir)

        all_diagnostics: List[QualityDiagnostic] = []
        raw_bytes = 0
        for target in targets:
            try:
                raw_bytes += target.stat().st_size
            except OSError:
                pass
            diags = self.run_file(target)
            all_diagnostics.extend(diags)

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        if not all_diagnostics:
            self._record_audit(base_dir, 0, duration_ms, raw_bytes, 0, 0)
            # Universal contract: Routine success outputs 0 bytes on stdout/stderr and exits with code 0
            return 0

        out_text = "".join(diag.format() + "\n\n" for diag in all_diagnostics)
        sys.stderr.write(out_text)
        self._record_audit(base_dir, 1, duration_ms, raw_bytes, len(out_text.encode("utf-8")), len(all_diagnostics))

        return 1
