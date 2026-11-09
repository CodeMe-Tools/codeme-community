"""Python AST parsing and deterministic repair."""

import ast
import re
from typing import List, Optional, Tuple
from codeme.syntax.diagnostic import SyntaxDiagnostic, build_snippet


def scan_python_delimiters(source: str) -> Tuple[List[Tuple[str, int, int]], Optional[Tuple[str, int, int]]]:
    """Scans Python source for unclosed delimiters and unclosed quotes.

    Returns:
        (unclosed_delimiters_stack, unclosed_quote_info)
        where unclosed_delimiters_stack is a list of (char, line, col)
        and unclosed_quote_info is Optional[(quote_str, line, col)]
    """
    stack: List[Tuple[str, int, int]] = []
    lines = source.splitlines(keepends=True)

    in_quote: Optional[str] = None
    quote_start: Tuple[int, int] = (0, 0)

    for line_idx, line in enumerate(lines):
        line_num = line_idx + 1
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            col = i + 1

            if in_quote is not None:
                if in_quote in ('"""', "'''"):
                    if line[i:i+3] == in_quote:
                        in_quote = None
                        i += 3
                        continue
                    elif ch == '\\':
                        i += 2
                        continue
                    else:
                        i += 1
                        continue
                else:
                    if ch == '\\':
                        i += 2
                        continue
                    elif ch == in_quote:
                        in_quote = None
                        i += 1
                        continue
                    elif ch in ('\n', '\r'):
                        # Single-line quote unclosed at EOL
                        return stack, (in_quote, quote_start[0], quote_start[1])
                    else:
                        i += 1
                        continue

            # Not in quote
            if ch == '#':
                # Comment continues to end of line
                break

            # Check triple quotes
            if line[i:i+3] in ('"""', "'''"):
                in_quote = line[i:i+3]
                quote_start = (line_num, col)
                i += 3
                continue

            # Check single quotes
            if ch in ('"', "'"):
                in_quote = ch
                quote_start = (line_num, col)
                i += 1
                continue

            # Check open delimiters
            if ch in ('(', '[', '{'):
                stack.append((ch, line_num, col))
                i += 1
                continue

            # Check closing delimiters
            if ch in (')', ']', '}'):
                matching = {'(': ')', '[': ']', '{': '}'}
                if stack:
                    top_char, _, _ = stack[-1]
                    if matching.get(top_char) == ch:
                        stack.pop()
                    else:
                        # Mismatched delimiter
                        pass
                i += 1
                continue

            i += 1

    if in_quote is not None:
        return stack, (in_quote, quote_start[0], quote_start[1])

    return stack, None


class PythonParser:
    """Parses and deterministically repairs Python source files."""

    COLON_KEYWORDS = (
        "def", "class", "if", "elif", "else", "for", "while",
        "try", "except", "finally", "with", "match", "case"
    )

    def parse(self, source: str, file_path: str = "<unknown>") -> Optional[SyntaxDiagnostic]:
        """Parses Python source using AST.

        Returns None if valid, or a SyntaxDiagnostic if parsing fails.
        """
        try:
            ast.parse(source, filename=file_path)
            return None
        except SyntaxError as e:
            line = e.lineno or 1
            col = e.offset or 1
            msg = e.msg or "invalid syntax"
            snippet = build_snippet(source, line, col)

            code = "CDM-SYN-001"
            rec = "Review and fix Python syntax error."

            if "expected ':'" in msg.lower() or "colon" in msg.lower():
                code = "CDM-SYN-006"
                rec = "Add missing ':' at the end of the statement header."
            elif "was never closed" in msg.lower() or "unclosed" in msg.lower():
                code = "CDM-SYN-004"
                rec = "Add missing closing bracket/parenthesis/delimiter."
            elif "unterminated string literal" in msg.lower() or "string literal" in msg.lower():
                code = "CDM-SYN-005"
                rec = "Close the unterminated string literal with matching quotation mark."

            return SyntaxDiagnostic(
                code=code,
                file_path=file_path,
                line=line,
                col=col,
                message=f"SyntaxError: {msg}",
                snippet=snippet,
                recommendation=rec,
            )

    def repair(self, source: str, file_path: str = "<unknown>", max_passes: int = 5) -> Tuple[bool, str, Optional[SyntaxDiagnostic]]:
        """Attempts deterministic surgical repairs on Python source.

        Returns:
            (repaired, new_source, diagnostic)
            If repairs succeed and reparse is valid: (True, repaired_source, None)
            If already valid: (False, source, None)
            If cannot repair: (False, source, original_diagnostic)
        """
        current_diag = self.parse(source, file_path)
        if current_diag is None:
            return False, source, None

        original_diag = current_diag
        working_source = source

        for _ in range(max_passes):
            diag = self.parse(working_source, file_path)
            if diag is None:
                return True, working_source, None

            fixed_candidate = self._attempt_pass(working_source, diag)
            if fixed_candidate is not None and fixed_candidate != working_source:
                working_source = fixed_candidate
            else:
                break

        # Check final parse
        final_diag = self.parse(working_source, file_path)
        if final_diag is None:
            return True, working_source, None

        # Rollback: cannot deterministically repair, preserve original source intact
        return False, source, original_diag

    def _attempt_pass(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        """Tries candidate repair strategies for the current diagnostic."""
        # 1. Missing colon repair
        fixed = self._repair_missing_colon(source, diag)
        if fixed:
            return fixed

        # 2. Unterminated string quote repair
        fixed = self._repair_unclosed_quote(source, diag)
        if fixed:
            return fixed

        # 3. Unclosed brackets / delimiters repair
        fixed = self._repair_unclosed_delimiters(source, diag)
        if fixed:
            return fixed

        return None

    def _repair_missing_colon(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        """Inspects error line and preceding non-blank line for missing colon."""
        lines = source.splitlines(keepends=True)
        target_lines = [diag.line]
        if diag.line > 1:
            target_lines.append(diag.line - 1)

        for ln in target_lines:
            if ln < 1 or ln > len(lines):
                continue
            line_content = lines[ln - 1]
            stripped = line_content.strip()

            # Check comment
            code_part = line_content
            comment_part = ""
            if "#" in line_content:
                parts = line_content.split("#", 1)
                code_part = parts[0]
                comment_part = "#" + parts[1]

            code_stripped = code_part.rstrip()
            if not code_stripped:
                continue

            # Check if line begins with a compound keyword
            first_word = code_stripped.lstrip().split()[0] if code_stripped.lstrip() else ""
            # Handle async def / async for / async with
            if first_word == "async":
                words = code_stripped.lstrip().split()
                if len(words) > 1 and words[1] in ("def", "for", "with"):
                    first_word = f"async {words[1]}"

            is_header = any(
                code_stripped.lstrip().startswith(kw + " ") or code_stripped.lstrip() == kw
                for kw in self.COLON_KEYWORDS
            ) or code_stripped.lstrip().startswith("async def ") or code_stripped.lstrip().startswith("async for ") or code_stripped.lstrip().startswith("async with ")

            if is_header and not code_stripped.endswith(":"):
                # Append ':' before comment or newline
                if comment_part:
                    new_line = code_stripped + ": " + comment_part
                else:
                    new_line = code_stripped + ":\n" if line_content.endswith("\n") else code_stripped + ":"

                new_lines = list(lines)
                new_lines[ln - 1] = new_line
                candidate = "".join(new_lines)
                return candidate

        return None

    def _repair_unclosed_quote(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        """Detects unclosed string literals on line and closes them."""
        stack, unclosed_quote = scan_python_delimiters(source)
        if unclosed_quote:
            quote_char, q_line, q_col = unclosed_quote
            lines = source.splitlines(keepends=True)
            if 1 <= q_line <= len(lines):
                target = lines[q_line - 1]
                # Strip trailing newline
                nl = "\n" if target.endswith("\n") else ""
                clean_target = target[:-1] if nl else target

                # If there's a comment, put quote before comment
                if "#" in clean_target:
                    parts = clean_target.split("#", 1)
                    new_line = parts[0].rstrip() + quote_char + " #" + parts[1] + nl
                else:
                    new_line = clean_target + quote_char + nl

                lines[q_line - 1] = new_line
                return "".join(lines)

        # Fallback heuristic based on diag.line
        lines = source.splitlines(keepends=True)
        if 1 <= diag.line <= len(lines):
            line = lines[diag.line - 1]
            nl = "\n" if line.endswith("\n") else ""
            clean_line = line[:-1] if nl else line

            # Count quotes
            dq_count = len(re.findall(r'(?<!\\)"', clean_line))
            sq_count = len(re.findall(r"(?<!\\)'", clean_line))

            quote_to_add = None
            if dq_count % 2 == 1:
                quote_to_add = '"'
            elif sq_count % 2 == 1:
                quote_to_add = "'"

            if quote_to_add:
                new_line = clean_line + quote_to_add + nl
                lines[diag.line - 1] = new_line
                return "".join(lines)

        return None

    def _repair_unclosed_delimiters(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        """Closes unclosed brackets (), [], {}."""
        stack, _ = scan_python_delimiters(source)
        if not stack:
            return None

        matching = {'(': ')', '[': ']', '{': '}'}
        closing_chars = [matching[ch] for ch, _, _ in reversed(stack) if ch in matching]
        if not closing_chars:
            return None

        # Check if closing before a colon on a statement line
        lines = source.splitlines(keepends=True)
        if 1 <= diag.line <= len(lines):
            line = lines[diag.line - 1]
            # e.g. def foo(a, b: -> insert ')' before ':'
            if ":" in line:
                idx = line.rfind(":")
                candidate_line = line[:idx] + "".join(closing_chars) + line[idx:]
                new_lines = list(lines)
                new_lines[diag.line - 1] = candidate_line
                candidate_source = "".join(new_lines)
                if self.parse(candidate_source) is None:
                    return candidate_source

        # Otherwise, append unclosed delimiters at end of source / line
        # If last line has an unclosed delimiter:
        last_ch, last_line, last_col = stack[-1]
        if 1 <= last_line <= len(lines):
            target = lines[last_line - 1]
            nl = "\n" if target.endswith("\n") else ""
            clean = target[:-1] if nl else target
            new_lines = list(lines)
            new_lines[last_line - 1] = clean + "".join(closing_chars) + nl
            candidate_source = "".join(new_lines)
            if self.parse(candidate_source) is None:
                return candidate_source

        # Try appending to the end of the file
        if source.endswith("\n"):
            candidate = source[:-1] + "".join(closing_chars) + "\n"
        else:
            candidate = source + "".join(closing_chars)

        return candidate
