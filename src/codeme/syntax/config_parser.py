"""Deterministic syntax parser and repair for structured config (JSON, TOML) and Shell scripts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Optional, Tuple

from codeme.syntax.diagnostic import SyntaxDiagnostic, build_snippet


class ConfigAndShellParser:
    """Validates JSON, TOML, and Shell scripts with zero external dependencies."""

    JSON_EXTS = {".json"}
    TOML_EXTS = {".toml"}
    SHELL_EXTS = {".sh", ".bash", ".zsh"}

    def parse(self, source: str, file_path: str = "<unknown>", ext: Optional[str] = None) -> Optional[SyntaxDiagnostic]:
        """Validate JSON, TOML, or Shell syntax. Returns None on valid syntax."""
        resolved_ext = (ext or Path(file_path).suffix).lower()

        if resolved_ext in self.JSON_EXTS:
            return self._parse_json(source, file_path)
        if resolved_ext in self.TOML_EXTS:
            return self._parse_toml(source, file_path)
        if resolved_ext in self.SHELL_EXTS:
            return self._parse_shell(source, file_path, resolved_ext)
        return None

    def repair(
        self,
        source: str,
        file_path: str = "<unknown>",
        ext: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[SyntaxDiagnostic]]:
        """Attempt deterministic repair (e.g. trailing commas in JSON) and re-verify."""
        resolved_ext = (ext or Path(file_path).suffix).lower()
        diag = self.parse(source, file_path=file_path, ext=resolved_ext)
        if diag is None:
            return False, source, None

        if resolved_ext in self.JSON_EXTS:
            # Strip trailing commas before '}' or ']'
            candidate = re.sub(r",(\s*[}\]])", r"\1", source)
            if candidate != source and self._parse_json(candidate, file_path) is None:
                return True, candidate, None

        return False, source, diag

    def _parse_json(self, source: str, file_path: str) -> Optional[SyntaxDiagnostic]:
        try:
            json.loads(source)
            return None
        except json.JSONDecodeError as e:
            return SyntaxDiagnostic(
                code="CDM-SYN-016",
                file_path=file_path,
                line=e.lineno,
                col=e.colno,
                message=f"JSON syntax error: {e.msg}",
                snippet=build_snippet(source, e.lineno, e.colno),
                recommendation="Fix malformed JSON syntax (check quotes, commas, and braces).",
            )

    def _parse_toml(self, source: str, file_path: str) -> Optional[SyntaxDiagnostic]:
        try:
            tomllib.loads(source)
            return None
        except tomllib.TOMLDecodeError as e:
            msg = str(e)
            line, col = 1, 1
            m = re.search(r"at line (\d+), column (\d+)", msg)
            if m:
                line = int(m.group(1))
                col = int(m.group(2))
            return SyntaxDiagnostic(
                code="CDM-SYN-017",
                file_path=file_path,
                line=line,
                col=col,
                message=f"TOML syntax error: {msg}",
                snippet=build_snippet(source, line, col),
                recommendation="Fix malformed TOML key/value, table header, or string quoting.",
            )

    def _parse_shell(self, source: str, file_path: str, ext: str) -> Optional[SyntaxDiagnostic]:
        shell_bin = "bash" if ext == ".bash" else ("zsh" if ext == ".zsh" else "sh")
        resolved = shutil.which(shell_bin) or shutil.which("sh")
        if not resolved:
            return None

        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=ext, delete=False, encoding="utf-8") as tmp:
                tmp.write(source)
                tmp_path = tmp.name

            proc = subprocess.run([resolved, "-n", tmp_path], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                return None

            err_text = (proc.stderr or proc.stdout).strip()
            line = 1
            m = re.search(r"line (\d+):", err_text)
            if m:
                line = int(m.group(1))
            return SyntaxDiagnostic(
                code="CDM-SYN-018",
                file_path=file_path,
                line=line,
                col=1,
                message=f"Shell syntax error: {err_text.splitlines()[-1] if err_text else 'invalid syntax'}",
                snippet=build_snippet(source, line, 1),
                recommendation="Fix unbalanced quotes, control structures (if/fi, do/done), or invalid shell syntax.",
            )
        except Exception:
            return None
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
