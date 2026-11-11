"""Comprehensive verification suite for codeme-quality."""

import io
import json
import sys
from codeme.quality.cli import main


def run_quality_cli(args, monkeypatch, capsys):
    """Helper to run the quality CLI and capture returncode, stdout, and stderr."""
    out = io.StringIO()
    err = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    code = main(args)
    return code, out.getvalue(), err.getvalue()


class TestQualityVerification:

    def test_clean_python_file_silent_success(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "clean.py"
        py_file.write_text(
            '"""Clean Python module."""\n\n'
            'def add(a: int, b: int) -> int:\n'
            '    return a + b\n'
        )
        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_cyclomatic_complexity_threshold_violation(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "complex_function.py"
        # Function with complexity > 10 (11 branches)
        branches = "\n".join([f"    if x == {i}:\n        return {i}" for i in range(12)])
        py_file.write_text(f"def evaluate(x: int) -> int:\n{branches}\n    return -1\n")

        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-001" in stderr
        assert "evaluate" in stderr
        assert "max allowed 10" in stderr

    def test_nesting_depth_threshold_violation(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "deep_nesting.py"
        # Function with nesting depth > 4
        py_file.write_text(
            'def deeply_nested(a, b, c, d, e):\n'
            '    if a:\n'
            '        if b:\n'
            '            if c:\n'
            '                if d:\n'
            '                    if e:\n'
            '                        return True\n'
            '    return False\n'
        )
        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-002" in stderr
        assert "Nesting depth" in stderr

    def test_file_size_limit_violation(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "huge_file.py"
        # 505 lines
        lines = ["# line\n" for _ in range(505)]
        py_file.write_text("".join(lines))

        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-003" in stderr
        assert "505 lines" in stderr

    def test_function_size_limit_violation(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "long_function.py"
        # 55 lines in function
        body = "\n".join(["    x += 1" for _ in range(55)])
        py_file.write_text(f"def huge_routine():\n    x = 0\n{body}\n    return x\n")

        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-004" in stderr
        assert "huge_routine" in stderr

    def test_ddd_architecture_layer_boundary_violation(self, tmp_path, monkeypatch, capsys):
        domain_dir = tmp_path / "domain"
        domain_dir.mkdir(parents=True)
        user_entity = domain_dir / "user.py"

        # Domain importing infrastructure component
        user_entity.write_text(
            'from infrastructure.db import DatabaseSession\n\n'
            'class UserEntity:\n'
            '    def __init__(self, id: str):\n'
            '        self.id = id\n'
        )

        code, stdout, stderr = run_quality_cli(["run", "--file", str(user_entity)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-005" in stderr
        assert "Architecture boundary violation" in stderr
        assert "infrastructure.db" in stderr

    def test_ddd_pure_domain_passes(self, tmp_path, monkeypatch, capsys):
        domain_dir = tmp_path / "domain"
        domain_dir.mkdir(parents=True)
        order_entity = domain_dir / "order.py"

        # Pure domain using standard library and dataclasses
        order_entity.write_text(
            'from dataclasses import dataclass\n'
            'from typing import Optional\n\n'
            '@dataclass\n'
            'class Order:\n'
            '    id: str\n'
            '    total: float\n'
            '    customer_id: Optional[str] = None\n'
        )

        code, stdout, stderr = run_quality_cli(["run", "--file", str(order_entity)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

    def test_unused_import_detection_and_fix(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "unused.py"
        py_file.write_text(
            'import os\n'
            'import sys\n'
            'from typing import List, Dict\n\n'
            'def get_version() -> str:\n'
            '    items: List[str] = []\n'
            '    return sys.version\n'
        )
        # 'os' and 'Dict' are unused.
        # Run check without --fix
        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-006" in stderr
        assert "Unused import 'os'" in stderr
        assert "Unused import 'Dict'" in stderr

        # Run with --fix
        code_fix, out_fix, err_fix = run_quality_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code_fix == 0
        assert out_fix == ""
        assert err_fix == ""

        # Verify fixed file content
        fixed_content = py_file.read_text()
        assert "import os" not in fixed_content
        assert "Dict" not in fixed_content
        assert "import sys" in fixed_content
        assert "from typing import List" in fixed_content

        # Subsequent check without fix is completely clean
        code_verify, _, _ = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code_verify == 0

    def test_trailing_whitespace_detection_and_fix(self, tmp_path, monkeypatch, capsys):
        py_file = tmp_path / "whitespace.py"
        py_file.write_text("x = 10    \ny = 20\t\n")

        # Check without fix
        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-007" in stderr

        # Fix
        code_fix, out_fix, err_fix = run_quality_cli(["run", "--file", str(py_file), "--fix"], monkeypatch, capsys)
        assert code_fix == 0
        assert out_fix == ""
        assert err_fix == ""

        assert py_file.read_text() == "x = 10\ny = 20\n"

    def test_custom_config_json(self, tmp_path, monkeypatch, capsys):
        config_file = tmp_path / ".codeme-quality.json"
        config_file.write_text(json.dumps({
            "max_cyclomatic_complexity": 3,
            "max_nesting_depth": 2,
            "max_file_lines": 50,
            "max_function_lines": 10
        }))

        py_file = tmp_path / "mod.py"
        py_file.write_text(
            'def f(x):\n'
            '    if x > 1:\n'
            '        if x > 2:\n'
            '            if x > 3:\n'
            '                return 4\n'
            '    return 0\n'
        )

        # Uses custom config
        code, stdout, stderr = run_quality_cli(["run", "--file", str(py_file), "--config", str(config_file)], monkeypatch, capsys)
        assert code == 1
        assert "CDM-QLT-002" in stderr
        assert "max allowed 2" in stderr

    def test_polyglot_rust_complexity_and_nesting(self, tmp_path, monkeypatch, capsys):
        """Polyglot Tree-sitter quality check analyzes Rust functions for complexity and nesting."""
        rs_file = tmp_path / "handler.rs"
        # Deeply nested and branching Rust function
        code_rs = (
            "fn handle_requests(x: i32, y: i32) -> i32 {\n"
            "    if x > 0 {\n"
            "        if y > 0 {\n"
            "            for i in 0..10 {\n"
            "                if i % 2 == 0 {\n"
            "                    while x < 100 {\n"
            "                        return x + 1;\n"
            "                    }\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "    0\n"
            "}\n"
        )
        rs_file.write_text(code_rs, encoding="utf-8")

        code, stdout, stderr = run_quality_cli(["run", "--file", str(rs_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-002" in stderr
        assert "handle_requests" in stderr
        assert "Nesting depth" in stderr

    def test_polyglot_go_clean_and_complex(self, tmp_path, monkeypatch, capsys):
        """Polyglot Tree-sitter quality check verifies clean Go code and flags complex Go functions."""
        # 1. Clean Go file
        clean_go = tmp_path / "clean.go"
        clean_go.write_text("package main\n\nfunc Add(a, b int) int {\n    return a + b\n}\n", encoding="utf-8")
        code, stdout, stderr = run_quality_cli(["run", "--file", str(clean_go)], monkeypatch, capsys)
        assert code == 0
        assert stdout == ""
        assert stderr == ""

        # 2. Complex Go function with > 10 decision points
        complex_go = tmp_path / "complex.go"
        branches = "\n".join([f"    if x == {i} {{\n        return {i}\n    }}" for i in range(12)])
        complex_go.write_text(f"package main\n\nfunc Route(x int) int {{\n{branches}\n    return -1\n}}\n", encoding="utf-8")
        code2, stdout2, stderr2 = run_quality_cli(["run", "--file", str(complex_go)], monkeypatch, capsys)
        assert code2 == 1
        assert stdout2 == ""
        assert "CDM-QLT-001" in stderr2
        assert "Route" in stderr2

    def test_polyglot_cpp_nesting_violation(self, tmp_path, monkeypatch, capsys):
        """Polyglot Tree-sitter quality check detects excessive nesting depth in C++ functions."""
        cpp_file = tmp_path / "algorithm.cpp"
        code_cpp = (
            "int evaluate(int a, int b, int c, int d, int e) {\n"
            "    if (a) {\n"
            "        if (b) {\n"
            "            while (c) {\n"
            "                for (int i = 0; i < d; ++i) {\n"
            "                    if (e) {\n"
            "                        return 1;\n"
            "                    }\n"
            "                }\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        cpp_file.write_text(code_cpp, encoding="utf-8")

        code, stdout, stderr = run_quality_cli(["run", "--file", str(cpp_file)], monkeypatch, capsys)
        assert code == 1
        assert stdout == ""
        assert "CDM-QLT-002" in stderr
        assert "evaluate" in stderr
