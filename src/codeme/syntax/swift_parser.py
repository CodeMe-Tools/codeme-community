"""Swift syntax, delimiter balance, and declaration parsing with deterministic repair."""

from typing import List, Optional, Tuple
from codeme.syntax.diagnostic import SyntaxDiagnostic, build_snippet


class SwiftParser:
    """Parses and deterministically repairs Swift source files."""

    DECLARATION_KEYWORDS = {
        "func", "class", "struct", "enum", "protocol", "actor",
        "extension", "if", "guard", "for", "while", "switch"
    }

    def parse(self, source: str, file_path: str = "<unknown>") -> Optional[SyntaxDiagnostic]:
        """Checks Swift source for balanced delimiters, strings, and declaration blocks."""
        stack: List[Tuple[str, int, int]] = []
        lines = source.splitlines(keepends=True)

        in_multiline_string = False
        in_singleline_string = False
        string_start: Tuple[int, int] = (0, 0)
        block_comment_depth = 0
        interpolation_depth: List[int] = []

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            i = 0
            n = len(line)

            while i < n:
                ch = line[i]
                col = i + 1

                # Handling nested block comments
                if block_comment_depth > 0:
                    if line[i:i+2] == "/*":
                        block_comment_depth += 1
                        i += 2
                        continue
                    elif line[i:i+2] == "*/":
                        block_comment_depth -= 1
                        i += 2
                        continue
                    i += 1
                    continue

                # Handling multiline string
                if in_multiline_string:
                    if line[i:i+3] == '"""':
                        in_multiline_string = False
                        i += 3
                        continue
                    elif ch == "\\":
                        i += 2
                        continue
                    i += 1
                    continue

                # Handling singleline string
                if in_singleline_string:
                    if ch == "\\":
                        if line[i:i+2] == "\\(":
                            # String interpolation: pushes '(' to stack and suspends string mode
                            interpolation_depth.append(len(stack))
                            stack.append(("(", line_num, col))
                            in_singleline_string = False
                            i += 2
                            continue
                        i += 2
                        continue
                    elif ch == '"':
                        in_singleline_string = False
                        i += 1
                        continue
                    elif ch in ("\n", "\r"):
                        return SyntaxDiagnostic(
                            code="CDM-SYN-005",
                            file_path=file_path,
                            line=string_start[0],
                            col=string_start[1],
                            message='Unterminated string literal (")',
                            snippet=build_snippet(source, string_start[0], string_start[1]),
                            recommendation='Close the string literal with matching quotation mark (") before newline.',
                        )
                    i += 1
                    continue

                # Check for line comment
                if line[i:i+2] == "//":
                    break

                # Check for block comment
                if line[i:i+2] == "/*":
                    block_comment_depth += 1
                    i += 2
                    continue

                # Check for multiline string start
                if line[i:i+3] == '"""':
                    in_multiline_string = True
                    string_start = (line_num, col)
                    i += 3
                    continue

                # Check for singleline string start
                if ch == '"':
                    in_singleline_string = True
                    string_start = (line_num, col)
                    i += 1
                    continue

                # Delimiters
                if ch in ("(", "[", "{"):
                    stack.append((ch, line_num, col))
                    i += 1
                    continue

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

                    # If this closing parenthesis ends a string interpolation \(...)
                    if interpolation_depth and len(stack) == interpolation_depth[-1]:
                        interpolation_depth.pop()
                        in_singleline_string = True

                    i += 1
                    continue

                i += 1

        if block_comment_depth > 0:
            return SyntaxDiagnostic(
                code="CDM-SYN-003",
                file_path=file_path,
                line=len(lines),
                col=1,
                message="Unterminated block comment '/*'",
                snippet=build_snippet(source, len(lines), 1),
                recommendation="Close block comment with '*/'.",
            )

        if in_multiline_string:
            return SyntaxDiagnostic(
                code="CDM-SYN-005",
                file_path=file_path,
                line=string_start[0],
                col=string_start[1],
                message='Unterminated multiline string literal (""")',
                snippet=build_snippet(source, string_start[0], string_start[1]),
                recommendation='Close multiline string with matching """.',
            )

        if in_singleline_string:
            return SyntaxDiagnostic(
                code="CDM-SYN-005",
                file_path=file_path,
                line=string_start[0],
                col=string_start[1],
                message='Unterminated string literal (")',
                snippet=build_snippet(source, string_start[0], string_start[1]),
                recommendation='Close string literal with matching ".',
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
        """Attempts deterministic surgical repairs on Swift source."""
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

        # Rollback
        return False, source, original_diag

    def _attempt_pass(self, source: str, diag: SyntaxDiagnostic) -> Optional[str]:
        # 1. Unclosed string quote
        if diag.code == "CDM-SYN-005":
            lines = source.splitlines(keepends=True)
            if 1 <= diag.line <= len(lines):
                line = lines[diag.line - 1]
                nl = "\n" if line.endswith("\n") else ""
                clean = line[:-1] if nl else line
                if clean.endswith(";"):
                    clean = clean[:-1] + '";'
                elif "//" in clean:
                    parts = clean.split("//", 1)
                    clean = parts[0].rstrip() + '" //' + parts[1]
                else:
                    clean = clean + '"'
                lines[diag.line - 1] = clean + nl
                return "".join(lines)

        # 2. Unclosed delimiters
        if diag.code == "CDM-SYN-004" and "Unclosed delimiter" in diag.message:
            # Reconstruct stack
            stack: List[str] = []
            lines = source.splitlines(keepends=True)
            for line in lines:
                clean = line.split("//")[0]
                for ch in clean:
                    if ch in ("(", "[", "{"):
                        stack.append(ch)
                    elif ch in (")", "]", "}"):
                        matching = {"(": ")", "[": "]", "{": "}"}
                        if stack and matching.get(stack[-1]) == ch:
                            stack.pop()
            if stack:
                matching = {"(": ")", "[": "]", "{": "}"}
                closing = "".join(matching[ch] for ch in reversed(stack) if ch in matching)
                if source.endswith("\n"):
                    return source[:-1] + closing + "\n"
                return source + closing

        return None
