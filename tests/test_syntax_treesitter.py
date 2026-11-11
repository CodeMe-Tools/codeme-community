"""Comprehensive verification suite for Tree-sitter multi-language syntax checking."""

import io
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

from codeme.syntax.cli import main
from codeme.syntax.treesitter_parser import TreeSitterParser


def run_syntax_cli(args, monkeypatch):
    """Helper to run the syntax CLI and capture returncode, stdout, and stderr."""
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestTreeSitterSyntaxVerification:

    # 1. Rust
    def test_valid_rust_silent_success(self, tmp_path, monkeypatch):
        rs_file = tmp_path / "main.rs"
        rs_file.write_text(
            'fn main() {\n'
            '    let message = "Hello from Rust!";\n'
            '    println!("{}", message);\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rs_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_rust(self, tmp_path, monkeypatch):
        rs_file = tmp_path / "broken.rs"
        rs_file.write_text(
            'fn main() {\n'
            '    let x: i32 = 10\n'
            '    println!("{}", x);\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rs_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-010" in stderr or "CDM-SYN-004" in stderr
        assert "broken.rs:2:" in stderr or "broken.rs" in stderr
        assert "Recommendation:" in stderr

    # 2. Go
    def test_valid_go_silent_success(self, tmp_path, monkeypatch):
        go_file = tmp_path / "service.go"
        go_file.write_text(
            'package main\n\n'
            'import "fmt"\n\n'
            'func main() {\n'
            '    fmt.Println("Hello from Go!")\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(go_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_go(self, tmp_path, monkeypatch):
        go_file = tmp_path / "broken.go"
        go_file.write_text(
            'package main\n\n'
            'func main() {\n'
            '    println("Unclosed Go block"\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(go_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-011" in stderr or "CDM-SYN-004" in stderr
        assert "broken.go" in stderr

    # 3. C++
    def test_valid_cpp_silent_success(self, tmp_path, monkeypatch):
        cpp_file = tmp_path / "engine.cpp"
        cpp_file.write_text(
            '#include <iostream>\n\n'
            'int main() {\n'
            '    std::cout << "Hello from C++" << std::endl;\n'
            '    return 0;\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(cpp_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_cpp(self, tmp_path, monkeypatch):
        cpp_file = tmp_path / "broken.cpp"
        cpp_file.write_text(
            '#include <iostream>\n\n'
            'int main() {\n'
            '    std::cout << "Missing semicolon" << std::endl\n'
            '    return 0;\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(cpp_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-012" in stderr or "CDM-SYN-004" in stderr
        assert "broken.cpp:4:" in stderr or "broken.cpp" in stderr

    # 4. Java
    def test_valid_java_silent_success(self, tmp_path, monkeypatch):
        java_file = tmp_path / "Application.java"
        java_file.write_text(
            'public class Application {\n'
            '    public static void main(String[] args) {\n'
            '        System.out.println("Hello from Java!");\n'
            '    }\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(java_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_java(self, tmp_path, monkeypatch):
        java_file = tmp_path / "Broken.java"
        java_file.write_text(
            'public class Broken {\n'
            '    public static void main(String[] args) {\n'
            '        System.out.println("Missing semicolon")\n'
            '    }\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(java_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-013" in stderr or "CDM-SYN-004" in stderr
        assert "Broken.java" in stderr

    # 5. Kotlin
    def test_valid_kotlin_silent_success(self, tmp_path, monkeypatch):
        kt_file = tmp_path / "Handler.kt"
        kt_file.write_text(
            'fun main() {\n'
            '    val greeting: String = "Hello from Kotlin!"\n'
            '    println(greeting)\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(kt_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_kotlin(self, tmp_path, monkeypatch):
        kt_file = tmp_path / "broken.kt"
        kt_file.write_text(
            'fun main() {\n'
            '    val greeting = "Unclosed delimiter"\n'
            '    println(greeting\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(kt_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-014" in stderr or "CDM-SYN-004" in stderr
        assert "broken.kt" in stderr

    # 6. Ruby
    def test_valid_ruby_silent_success(self, tmp_path, monkeypatch):
        rb_file = tmp_path / "script.rb"
        rb_file.write_text(
            'def greet(name)\n'
            '  "Hello, #{name}!"\n'
            'end\n\n'
            'puts greet("Ruby")\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rb_file)], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_syntax_error_detection_ruby(self, tmp_path, monkeypatch):
        rb_file = tmp_path / "broken.rb"
        rb_file.write_text(
            'def greet(name)\n'
            '  puts "Unclosed method"\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rb_file)], monkeypatch)
        assert code == 1
        assert stdout == ""
        assert "CDM-SYN-015" in stderr or "CDM-SYN-004" in stderr
        assert "broken.rb" in stderr

    # 7. Deterministic Repair (--fix)
    def test_deterministic_repair_missing_delimiter_cpp(self, tmp_path, monkeypatch):
        cpp_file = tmp_path / "repairable.cpp"
        cpp_file.write_text(
            'int main() {\n'
            '    int answer = 42\n'
            '    return 0;\n'
            '}\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(cpp_file), "--fix"], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        # Verify semicolon was cleanly inserted
        repaired_content = cpp_file.read_text(encoding="utf-8")
        assert "42;" in repaired_content

    def test_deterministic_repair_ruby_missing_end(self, tmp_path, monkeypatch):
        rb_file = tmp_path / "repairable.rb"
        rb_file.write_text(
            'def compute(x)\n'
            '  x * 10\n'
        )
        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rb_file), "--fix"], monkeypatch)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        repaired_content = rb_file.read_text(encoding="utf-8")
        assert "end" in repaired_content

    # 8. Safe Rollback Invariant on Unrepairable Code
    def test_unrepairable_code_rolls_back_safely(self, tmp_path, monkeypatch):
        rs_file = tmp_path / "fatal.rs"
        original_code = 'fn !!! fatal random tokens @#$%^& 123'
        rs_file.write_text(original_code)

        code, stdout, stderr = run_syntax_cli(["run", "--file", str(rs_file), "--fix"], monkeypatch)
        assert code == 1
        assert "CDM-SYN-" in stderr

        # Content must remain identical (zero byte corruption / no half-fixes committed)
        assert rs_file.read_text(encoding="utf-8") == original_code

    # 9. No Host Compiler Invocation
    def test_no_host_compiler_invoked(self, tmp_path, monkeypatch):
        """Verifies that syntax verification does not spawn host compiler subprocesses."""
        rs_file = tmp_path / "pure.rs"
        rs_file.write_text('fn main() { println!("Pure Tree-sitter"); }\n')

        with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
            code, stdout, stderr = run_syntax_cli(["run", "--file", str(rs_file)], monkeypatch)
            assert code == 0
            assert mock_popen.call_count == 0
            assert mock_run.call_count == 0
