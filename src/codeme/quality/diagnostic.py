"""Quality diagnostics and violation reporting."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class QualityDiagnostic:
    code: str
    file_path: str
    line: int
    col: int
    message: str
    snippet: Optional[str] = None
    recommendation: Optional[str] = None

    def format(self) -> str:
        loc = f"{self.file_path}:{self.line}:{self.col}" if self.line > 0 else self.file_path
        lines = [f"[{self.code}] {loc}: {self.message}"]
        if self.snippet:
            lines.append(self.snippet)
        if self.recommendation:
            lines.append(f"  Recommendation: {self.recommendation}")
        return "\n".join(lines)


def build_snippet(source: str, line: int, col: int) -> str:
    """Builds a formatted snippet with line number and column pointer."""
    if not source:
        return ""
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return ""

    target_line = lines[line - 1]
    line_num_str = f"{line:4d} | "
    indent = " " * len(line_num_str)

    pointer_pos = max(0, col - 1)
    pointer_line = f"{indent}{' ' * pointer_pos}^"

    return f"{line_num_str}{target_line}\n{pointer_line}"
