"""Comprehensive verification suite for codeme-syntax."""

import io
import sys
from codeme.syntax.cli import main


def run_syntax_cli(args, monkeypatch, capsys):
    """Helper to run the syntax CLI and capture returncode, stdout, and stderr."""
    # We capture sys.stderr directly as the CLI writes to sys.stderr
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestSyntaxVerification:

    def test_valid_python_silent_success(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "valid.py"
        py_file.write_text(
            'def add(a: int, b: int) -> int:\n'
            '    """Returns sum of two numbers."""\n'
            '    return a + b\n\n'
            'class Greeter:\n'
            '    def __init__(self, name: str):\n'
            '        self.name = name\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_valid_js_and_ts_silent_success(self, tmp_path, monkeypatch, capsys):
        js_file = tmp_path / "app.js"
        js_file.write_text(
            '// Valid JavaScript\n'
            'function greet(name) {\n'
            '  const msg = `Hello, ${name}!`;\n'
            '  return [1, 2, 3].map(x => x * 2);\n'
            '}\n'
        )
        ts_file = tmp_path / "service.ts"
        ts_file.write_text(
            'export interface User {\n'
            '  id: string;\n'
            '  email: string;\n'
            '}\n'
            'export const loadUser = (id: string): User => ({\n'
            '  id,\n'
            '  email: `${id}@example.com`\n'
            '});\n'
        )
        code_js, out_js, err_js = run_syntax_cli(["run", "--file", str(js_file)], monkeypatch, capsys)
        assert code_js == 0
        assert out_js == ""
        assert err_js == ""

        code_ts, out_ts, err_ts = run_syntax_cli(["run", "--file", str(ts_file)], monkeypatch, capsys)
        assert code_ts == 0
        assert out_ts == ""
        assert err_ts == ""

    def test_valid_swift_silent_success(self, tmp_path, monkeypatch, capsys):
        swift_file = tmp_path / "User.swift"
        swift_file.write_text(
            '// Valid Swift declaration\n'
            'import Foundation\n\n'
            'struct User {\n'
            '    let id: UUID\n'
            '    let username: String\n'
            '    \n'
            '    func greeting() -> String {\n'
            '        return "Hello, \\(username)"\n'
            '    }\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(swift_file)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_python(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "broken.py"
        py_file.write_text(
            'def calculate(x)\n'
            '    return x * 2\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-" in stderr
        assert "broken.py:1:" in stderr
        assert "Recommendation:" in stderr

    def test_syntax_error_detection_js_unclosed_brace(self, tmp_path, monkeypatch, capsys):
        js_file = tmp_path / "broken.js"
        js_file.write_text(
            'function calc() {\n'
            '  return 42;\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(js_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-004" in stderr
        assert "Unclosed delimiter" in stderr

    def test_syntax_error_detection_swift_unmatched_delimiter(self, tmp_path, monkeypatch, capsys):
        swift_file = tmp_path / "broken.swift"
        swift_file.write_text(
            'func test() {\n'
            '    let arr = [1, 2, 3)\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(swift_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-004" in stderr
        assert "Mismatched delimiter" in stderr

    def test_deterministic_repair_python_missing_colon(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "missing_colon.py"
        py_file.write_text(
            'def compute(total, discount)\n'
            '    if total > 100\n'
            '        return total - discount\n'
            '    return total\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired_content = py_file.read_text()
        assert "def compute(total, discount):" in repaired_content
        assert "if total > 100:" in repaired_content

        # Verify subsequent run passes without needing fix
        code2, _, _ = run_syntax_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code2 == 0

    def test_deterministic_repair_python_unclosed_bracket(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "unclosed_bracket.py"
        py_file.write_text(
            'data = [1, 2, 3\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired = py_file.read_text()
        assert repaired.strip().endswith("]")

    def test_deterministic_repair_python_unclosed_quote(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "unclosed_quote.py"
        py_file.write_text(
            'title = "Codeme Community Core\n'
            'count = 42\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired = py_file.read_text()
        assert 'title = "Codeme Community Core"' in repaired

    def test_deterministic_repair_js_unclosed_delimiter(self, tmp_path, monkeypatch, capsys):
        js_file = tmp_path / "unclosed.js"
        js_file.write_text(
            'function execute() {\n'
            '  console.log("running");\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(js_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired = js_file.read_text()
        assert repaired.strip().endswith("}")

    def test_deterministic_repair_js_unclosed_quote(self, tmp_path, monkeypatch, capsys):
        js_file = tmp_path / "quote.js"
        js_file.write_text(
            'const msg = "Welcome to Codeme;\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(js_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired = js_file.read_text()
        assert 'const msg = "Welcome to Codeme";' in repaired

    def test_deterministic_repair_swift_unclosed_delimiters(self, tmp_path, monkeypatch, capsys):
        swift_file = tmp_path / "unclosed.swift"
        swift_file.write_text(
            'class Item {\n'
            '    var name: String = "Test"\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(swift_file), "--fix"], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired = swift_file.read_text()
        assert repaired.strip().endswith("}")

    def test_unrepairable_syntax_rollback_and_preservation(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "hopeless.py"
        corrupted = 'def 123 +++ return !!!\n'
        py_file.write_text(corrupted)

        code, stdout, stderr = run_syntax_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-" in stderr

        # Verify strict rollback: file content is completely intact and not corrupted
        assert py_file.read_text() == corrupted

    def test_repo_scan_mode(self, tmp_path, monkeypatch, capsys):
        # Create a repo with mixed files
        (tmp_path / "file1.py").write_text("x = 1\n")
        (tmp_path / "file2.js").write_text("const y = 2;\n")
        (tmp_path / "file3.swift").write_text("let z = 3\n")

        code, stdout, stderr = run_syntax_cli(["run", "--repo", str(tmp_path)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""
