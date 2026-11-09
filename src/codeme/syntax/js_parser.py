"""JavaScript and TypeScript lexical structure parsing and deterministic repair."""

from typing import List, Optional, Tuple
from codeme.syntax.diagnostic import SyntaxDiagnostic, build_snippet


class JSParser:
    """Parses and deterministically repairs JavaScript/TypeScript source files."""

    def parse(self, source: str, file_path: str = "<unknown>") -> Optional[SyntaxDiagnostic]:
        """Performs lexical structure verification on JS/TS source.

        Returns None if valid, or a SyntaxDiagnostic if a syntax violation is detected.
        """
        stack: List[Tuple[str, int, int]] = []
        lines = source.splitlines(keepends=True)

        in_string: Optional[str] = None  # "'", '"', or '`'
        template_depth: List[int] = []   # tracks brace depth inside `${...}` in template strings
        in_block_comment = False
        quote_start: Tuple[int, int] = (0, 0)

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            i = 0
            n = len(line)

            while i < n:
                ch = line[i]
                col = i + 1

                # Handling block comment
                if in_block_comment:
                    if line[i:i+2] == "*/":
                        in_block_comment = False
                        i += 2
                        continue
                    i += 1
                    continue

                # Handling string or template literal
                if in_string is not None:
                    if ch == "\\":
                        i += 2
                        continue

                    if in_string == "`":
                        # Check for template expression interpolation `${`
                        if line[i:i+2] == "${":
                            template_depth.append(len(stack))
                            stack.append(("{", line_num, col))
                            in_string = None
                            i += 2
                            continue
                        elif ch == "`":
                            in_string = None
                            i += 1
                            continue
                        else:
                            i += 1
                            continue
                    else:
                        # Regular single or double quote
                        if ch == in_string:
                            in_string = None
                            i += 1
                            continue
                        elif ch in ("\n", "\r"):
                            # Non-multiline string unclosed at EOL
                            return SyntaxDiagnostic(
                                code="CDM-SYN-005",
                                file_path=file_path,
                                line=quote_start[0],
                                col=quote_start[1],
                                message=f"Unterminated string literal ({in_string})",
                                snippet=build_snippet(source, quote_start[0], quote_start[1]),
                                recommendation=f"Close the string literal with matching {in_string} before end of line.",
                            )
                        else:
                            i += 1
                            continue

                # Check for line comment
                if line[i:i+2] == "//":
                    break

                # Check for block comment start
                if line[i:i+2] == "/*":
                    in_block_comment = True
                    i += 2
                    continue

                # Check for string starts
                if ch in ("'", '"', "`"):
                    in_string = ch
                    quote_start = (line_num, col)
                    i += 1
                    continue

                # Check open delimiters
                if ch in ("(", "[", "{"):
                    stack.append((ch, line_num, col))
                    i += 1
                    continue

                # Check closing delimiters
                if ch in (")", "]", "}"):
                    matching = {"(": ")", "[": "]", "{": "}"}
                    if not stack:
                        return SyntaxDiagnostic(
                            code="CDM-SYN-004",
                            file_path=file_path,
                            line=line_num,
                            col=col,
                            message=f"Unmatched closing delimiter '{ch}'",
                            snippet=build_snippet(source, line_num, col),
                            recommendation=f"Remove extraneous '{ch}' or add matching open delimiter.",
                        )

                    top_char, top_line, top_col = stack.pop()
                    if matching.get(top_char) != ch:
                        return SyntaxDiagnostic(
                            code="CDM-SYN-004",
                            file_path=file_path,
                            line=line_num,
                            col=col,
                            message=f"Mismatched delimiter: expected '{matching.get(top_char)}', got '{ch}'",
                            snippet=build_snippet(source, line_num, col),
                            recommendation=f"Replace '{ch}' with '{matching.get(top_char)}' or fix nesting.",
                        )

                    # If we closed a template expression brace
                    if template_depth and len(stack) == template_depth[-1]:
                        template_depth.pop()
                        in_string = "`"

                    i += 1
                    continue

                i += 1

        if in_block_comment:
            return SyntaxDiagnostic(
                code="CDM-SYN-002",
                file_path=file_path,
                line=len(lines),
                col=1,
                message="Unterminated block comment '/*'",
                snippet=build_snippet(source, len(lines), 1),
                recommendation="Close block comment with '*/'.",
            )

        if in_string is not None:
            return SyntaxDiagnostic(
                code="CDM-SYN-005",
                file_path=file_path,
                line=quote_start[0],
                col=quote_start[1],
                message=f"Unterminated string literal ({in_string})",
                snippet=build_snippet(source, quote_start[0], quote_start[1]),
                recommendation=f"Close string literal with matching {in_string}.",
            )

        if stack:
            top_char, top_line, top_col = stack[-1]
            matching = {"(": ")", "[": "]", "{": "}"}
            expected = matching.get(top_char, "")
            return SyntaxDiagnostic(
                code="CDM-SYN-004",
                file_path=file_path,
                line=top_line,
                col=top_col,
                message=f"Unclosed delimiter '{top_char}'",
                snippet=build_snippet(source, top_line, top_col),
                recommendation=f"Add missing closing delimiter '{expected}'.",
            )

        return None

    def repair(self, source: str, file_path: str = "<unknown>", max_passes: int = 5) -> Tuple[bool, str, Optional[SyntaxDiagnostic]]:
        """Attempts deterministic surgical repairs on JS/TS source.

        Returns:
            (repaired, new_source, diagnostic)
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

            fixed = self._attempt_pass(working_source, diag)
            if fixed is not None and fixed != working_source:
                working_source = fixed
            else:
                break

        final_diag = self.parse(working_source, file_path)
        if final_diag is None:
            return True, working_source, None

        # Rollback: cannot deterministically repair
        return False, source, original_diag

    def _attempt_pass(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        # 1. Unclosed string quote repair
        if diag.code == "CDM-SYN-005":
            lines = source.splitlines(keepends=True)
            if 1 <= diag.line <= len(lines):
                line = lines[diag.line - 1]
                nl = "\n" if line.endswith("\n") else ""
                clean = line[:-1] if nl else line

                # Check unclosed quote
                for q in ("'", '"', "`"):
                    if q in diag.message or (clean.count(q) % 2 == 1):
                        # If line ends with semicolon, put quote before semicolon
                        if clean.endswith(";"):
                            new_line = clean[:-1] + q + ";" + nl
                        # Append quote before any // comment
                        elif "//" in clean:
                            parts = clean.split("//", 1)
                            code_part = parts[0].rstrip()
                            if code_part.endswith(";"):
                                new_line = code_part[:-1] + q + "; //" + parts[1] + nl
                            else:
                                new_line = code_part + q + " //" + parts[1] + nl
                        else:
                            new_line = clean + q + nl
                        lines[diag.line - 1] = new_line
                        return "".join(lines)

        # 2. Unclosed delimiters
        if diag.code == "CDM-SYN-004" and "Unclosed delimiter" in diag.message:
            # Determine unclosed delimiters from scanning
            stack, _ = self._collect_unclosed_stack(source)
            if stack:
                matching = {"(": ")", "[": "]", "{": "}"}
                closing = "".join(matching[ch] for ch, _, _ in reversed(stack) if ch in matching)
                if source.endswith("\n"):
                    return source[:-1] + closing + "\n"
                return source + closing

        return None

    def _collect_unclosed_stack(self, source: str) -> Tuple[List[Tuple[str, int, int]], Optional[str]]:
        stack: List[Tuple[str, int, int]] = []
        lines = source.splitlines(keepends=True)
        in_string: Optional[str] = None
        in_block = False

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            i = 0
            n = len(line)
            while i < n:
                ch = line[i]
                if in_block:
                    if line[i:i+2] == "*/":
                        in_block = False
                        i += 2
                        continue
                    i += 1
                    continue
                if in_string is not None:
                    if ch == "\\":
                        i += 2
                        continue
                    if ch == in_string:
                        in_string = None
                        i += 1
                        continue
                    elif in_string != "`" and ch in ("\n", "\r"):
                        in_string = None
                    i += 1
                    continue
                if line[i:i+2] == "//":
                    break
                if line[i:i+2] == "/*":
                    in_block = True
                    i += 2
                    continue
                if ch in ("'", '"', "`"):
                    in_string = ch
                    i += 1
                    continue
                if ch in ("(", "[", "{"):
                    stack.append((ch, line_num, i + 1))
                    i += 1
                    continue
                if ch in (")", "]", "}"):
                    matching = {"(": ")", "[": "]", "{": "}"}
                    if stack and matching.get(stack[-1][0]) == ch:
                        stack.pop()
                    i += 1
                    continue
                i += 1
        return stack, in_string
