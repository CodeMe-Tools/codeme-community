"""Tests for codeme-verify: Multi-ecosystem discovery, test execution, diagnostics, and repairs."""

import io
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from codeme.verify.cli import main, run_verification, parse_args
from codeme.verify.diagnostics import VerifyDiagnostic, format_diagnostics_json
from codeme.verify.discovery import DiscoveredProject, ProjectDiscovery
from codeme.verify.repair import MechanicalRepair
from codeme.verify.runner import TestRunner


def test_discovery_python_pytest(tmp_path):
    """Discovery identifies Python pytest project by pyproject.toml."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.pytest.ini_options]\naddopts = '-q'\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover()

    assert proj is not None
    assert proj.ecosystem == "python"
    assert proj.framework == "pytest"
    assert "pytest" in proj.command[-1] or "pytest" in proj.command[-2]


def test_discovery_python_unittest(tmp_path):
    """Discovery identifies Python project without pytest configuration as unittest."""
    setup_py = tmp_path / "setup.py"
    setup_py.write_text("from setuptools import setup; setup(name='test')\n", encoding="utf-8")
    test_file = tmp_path / "test_example.py"
    test_file.write_text("import unittest\nclass T(unittest.TestCase): pass\n", encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover()

    assert proj is not None
    assert proj.ecosystem == "python"


def test_discovery_node_vitest_and_jest(tmp_path):
    """Discovery identifies Node.js projects with vitest or jest."""
    pkg_json = tmp_path / "package.json"
    pkg_json.write_text('{"devDependencies": {"vitest": "^1.0.0"}}', encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover()

    assert proj is not None
    assert proj.ecosystem == "node"
    assert proj.framework == "vitest"
    assert "vitest" in proj.command

    # Switch to jest
    pkg_json.write_text('{"devDependencies": {"jest": "^29.0.0"}}', encoding="utf-8")
    proj_jest = discovery.discover()
    assert proj_jest is not None
    assert proj_jest.framework == "jest"
    assert "jest" in proj_jest.command


def test_discovery_swift(tmp_path):
    """Discovery identifies Swift projects by Package.swift."""
    pkg_swift = tmp_path / "Package.swift"
    pkg_swift.write_text('// swift-tools-version:5.5\nimport PackageDescription\n', encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover(test_pattern="MyTest")

    assert proj is not None
    assert proj.ecosystem == "swift"
    assert proj.command == ["swift", "test", "--filter", "MyTest"]


def test_discovery_rust_cargo(tmp_path):
    """Discovery identifies Rust projects via Cargo.toml."""
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text('[package]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_main.rs").write_text("#[test]\nfn test_ok() {}\n", encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover(test_pattern="test_ok")

    assert proj is not None
    assert proj.ecosystem == "rust"
    assert proj.framework == "cargo"
    assert proj.command == ["cargo", "test", "--", "test_ok"]


def test_discovery_go(tmp_path):
    """Discovery identifies Go projects via go.mod."""
    go_mod = tmp_path / "go.mod"
    go_mod.write_text("module example.com/demo\n\ngo 1.21\n", encoding="utf-8")
    (tmp_path / "app_test.go").write_text("package main\nimport \"testing\"\nfunc TestX(t *testing.T){}\n", encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover(test_pattern="TestX")

    assert proj is not None
    assert proj.ecosystem == "go"
    assert proj.framework == "go"
    assert proj.command == ["go", "test", "-v", "./...", "-run", "TestX"]


def test_discovery_cmake_ctest(tmp_path):
    """Discovery identifies C/C++ projects via CMakeLists.txt."""
    cmake = tmp_path / "CMakeLists.txt"
    cmake.write_text("cmake_minimum_required(VERSION 3.20)\nproject(demo)\nenable_testing()\n", encoding="utf-8")
    (tmp_path / "test_runner.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")

    discovery = ProjectDiscovery(tmp_path)
    proj = discovery.discover(test_pattern="unit_tests")

    assert proj is not None
    assert proj.ecosystem == "cpp"
    assert proj.framework == "ctest"
    assert proj.command == ["ctest", "--output-on-failure", "-R", "unit_tests"]


def test_runner_passing_test_suite_silent(tmp_path, capsys):
    """Passing test suite exits 0 with zero bytes on stdout and stderr (ADR-0002)."""
    # Create valid python test project
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='dummy'\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_pass.py").write_text("def test_ok(): assert 1 == 1\n", encoding="utf-8")

    args = parse_args(["run", "--repo", str(tmp_path)])
    exit_code = run_verification(args)

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_runner_failing_test_suite_diagnostics(tmp_path, capsys):
    """Failing test suite exits non-zero with actionable CDM-VRF diagnostics."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='dummy'\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fail.py").write_text("def test_assert(): assert 1 == 2\n", encoding="utf-8")

    args = parse_args(["run", "--repo", str(tmp_path)])
    exit_code = run_verification(args)

    assert exit_code != 0
    captured = capsys.readouterr()
    assert "CDM-VRF-" in captured.err
    assert "Remediation:" in captured.err


def test_mechanical_repair_missing_import(tmp_path, capsys):
    """Mechanical repair detects missing import, injects it, and verifies test pass."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='dummy'\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    
    # Missing 'pytest' or 'os' import causing NameError
    test_code = (
        "def test_needs_os():\n"
        "    assert os.path.exists('.')\n"
    )
    (tests_dir / "test_repair.py").write_text(test_code, encoding="utf-8")

    # Run with --fix
    args = parse_args(["run", "--repo", str(tmp_path), "--fix"])
    exit_code = run_verification(args)

    assert exit_code == 0
    # Verified: import os was inserted and test passed!
    content = (tests_dir / "test_repair.py").read_text(encoding="utf-8")
    assert "import os" in content

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_mechanical_repair_missing_fixture(tmp_path):
    """Mechanical repair creates stub for missing pytest fixture and verifies pass."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='dummy'\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    test_code = (
        "def test_with_custom_fixture(mock_db):\n"
        "    assert mock_db is None\n"
    )
    (tests_dir / "test_fixture.py").write_text(test_code, encoding="utf-8")

    args = parse_args(["run", "--repo", str(tmp_path), "--fix"])
    exit_code = run_verification(args)

    assert exit_code == 0
    conftest = tests_dir / "conftest.py"
    assert conftest.exists()
    assert "def mock_db()" in conftest.read_text(encoding="utf-8")


def test_parse_rust_output(tmp_path):
    """TestRunner parses rustc compile errors and cargo test panics into structured diagnostics."""
    runner = TestRunner(tmp_path)

    # 1. Compiler error
    rust_err = (
        "error[E0425]: cannot find value `foo` in this scope\n"
        "  --> tests/test_main.rs:12:5\n"
        "   |\n"
        "12 |     foo();\n"
        "   |     ^^^ not found in this scope\n"
    )
    diags = runner._parse_rust_output(rust_err)
    assert len(diags) == 1
    assert diags[0].code == "E0425"
    assert diags[0].file == "tests/test_main.rs"
    assert diags[0].line == 12
    assert diags[0].column == 5
    assert "cannot find value `foo`" in diags[0].message

    # 2. Panic failure
    panic_err = "failures:\n---- test_add stdout ----\nthread 'test_add' panicked at tests/test_main.rs:8:5: assertion `left == right` failed"
    diags2 = runner._parse_rust_output(panic_err)
    assert len(diags2) == 1
    assert diags2[0].code == "CDM-VRF-001"
    assert diags2[0].file == "tests/test_main.rs"
    assert diags2[0].line == 8
    assert "test_add" in diags2[0].message


def test_parse_go_output(tmp_path):
    """TestRunner parses Go compiler/vet and test failures into structured diagnostics."""
    runner = TestRunner(tmp_path)

    go_err = (
        "app_test.go:10:5: undefined: fmt.Println\n"
        "--- FAIL: TestCalc (0.01s)\n"
        "    app_test.go:18: expected 5, got 10\n"
    )
    diags = runner._parse_go_output(go_err)
    assert len(diags) == 2
    assert diags[0].code == "CDM-VRF-002"
    assert diags[0].file == "app_test.go"
    assert diags[0].line == 10
    assert diags[1].code == "CDM-VRF-001"
    assert diags[1].line == 18
    assert "TestCalc" in diags[1].message


def test_parse_cpp_output(tmp_path):
    """TestRunner parses C/C++ compiler and CTest failures."""
    runner = TestRunner(tmp_path)

    cpp_err = (
        "/src/main.cpp:25:5: error: 'vector' was not declared in this scope\n"
        "The following tests FAILED:\n"
        "  1 - MathTests (Failed)\n"
    )
    diags = runner._parse_cpp_output(cpp_err)
    assert len(diags) == 2
    assert diags[0].code == "CDM-VRF-002"
    assert diags[0].line == 25
    assert diags[1].code == "CDM-VRF-001"
    assert diags[1].file == "CMakeLists.txt"
    assert "MathTests" in diags[1].message


def test_mechanical_repair_polyglot(tmp_path):
    """Mechanical repair fixes missing imports for Rust, Go, and C++ files."""
    repairer = MechanicalRepair(tmp_path)

    # 1. Rust repair
    rs_file = tmp_path / "lib.rs"
    rs_file.write_text("fn test() { let m = HashMap::new(); }\n", encoding="utf-8")
    rs_diag = VerifyDiagnostic(
        code="E0425",
        file="lib.rs",
        line=1,
        column=1,
        message="cannot find type `HashMap` in this scope",
        remediation="import HashMap",
    )

    # 2. Go repair
    go_file = tmp_path / "main.go"
    go_file.write_text("package main\n\nfunc Run() { fmt.Println(1) }\n", encoding="utf-8")
    go_diag = VerifyDiagnostic(
        code="CDM-VRF-002",
        file="main.go",
        line=3,
        column=1,
        message="undefined: fmt.Println",
        remediation="import fmt",
    )

    # 3. C++ repair
    cpp_file = tmp_path / "app.cpp"
    cpp_file.write_text("int main() { std::vector<int> v; return 0; }\n", encoding="utf-8")
    cpp_diag = VerifyDiagnostic(
        code="CDM-VRF-002",
        file="app.cpp",
        line=1,
        column=1,
        message="'vector' was not declared in this scope",
        remediation="include <vector>",
    )

    applied, snapshots = repairer.plan_and_apply([rs_diag, go_diag, cpp_diag])
    assert applied is True
    assert len(snapshots) == 3

    assert "use std::collections::HashMap;\n" in rs_file.read_text(encoding="utf-8")
    assert 'import "fmt"\n' in go_file.read_text(encoding="utf-8")
    assert "#include <vector>\n" in cpp_file.read_text(encoding="utf-8")

    # Test rollback guarantee
    repairer.rollback(snapshots)
    assert "HashMap;\n" not in rs_file.read_text(encoding="utf-8")
    assert 'import "fmt"' not in go_file.read_text(encoding="utf-8")
    assert "#include <vector>" not in cpp_file.read_text(encoding="utf-8")
