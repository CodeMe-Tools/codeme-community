"""Test execution and regression detection engine."""

from pathlib import Path
import re
import subprocess
from typing import List, Optional, Tuple

from codeme.verify.diagnostics import VerifyDiagnostic
from codeme.verify.discovery import DiscoveredProject, ProjectDiscovery


class TestRunner:
    """Executes multi-ecosystem test suites and detects regressions."""

    __test__ = False
    __test__ = False

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir.resolve()

    def get_incremental_targets(self) -> List[str]:
        """Find test files corresponding to modified files via Git."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode != 0:
                return []

            changed_files = []
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    changed_files.append(parts[-1])

            # Filter or map to test files
            targets = []
            for f in changed_files:
                p = Path(f)
                if "test" in p.name.lower():
                    targets.append(str(p))
                else:
                    # Look for test_{stem}.py or {stem}.test.ts
                    candidate_py = self.repo_dir / "tests" / f"test_{p.stem}.py"
                    if candidate_py.exists():
                        targets.append(str(candidate_py.relative_to(self.repo_dir)))
            return targets
        except Exception:
            return []

    def run(
        self,
        project: Optional[DiscoveredProject] = None,
        test_pattern: Optional[str] = None,
        incremental: bool = False,
        timeout: int = 120,
    ) -> Tuple[bool, List[VerifyDiagnostic], str, str]:
        """Runs the test suite.

        Returns:
            Tuple of (success, diagnostics, stdout, stderr)
        """
        if project is None:
            discovery = ProjectDiscovery(self.repo_dir)
            project = discovery.discover(test_pattern=test_pattern)

        if project is None:
            diag = VerifyDiagnostic(
                code="CDM-VRF-005",
                file=".",
                line=0,
                column=0,
                message="No supported test framework or configuration found.",
                remediation="Ensure project contains pyproject.toml, pytest, package.json, or Package.swift.",
            )
            return False, [diag], "", "No test framework found."

        cmd = list(project.command)

        if incremental:
            targets = self.get_incremental_targets()
            if targets:
                cmd.extend(targets)

        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            diag = VerifyDiagnostic(
                code="CDM-VRF-004",
                file=".",
                line=0,
                column=0,
                message=f"Test run timed out after {timeout} seconds.",
                remediation="Check for infinite loops or increase the timeout setting.",
            )
            return False, [diag], "", f"Timed out after {timeout}s"
        except Exception as e:
            diag = VerifyDiagnostic(
                code="CDM-VRF-004",
                file=".",
                line=0,
                column=0,
                message=f"Failed to execute test harness: {str(e)}",
                remediation="Verify test harness installation and execution environment.",
            )
            return False, [diag], "", str(e)

        if returncode == 0:
            return True, [], stdout, stderr

        # Parse failures into actionable diagnostics
        diagnostics = self._parse_output(project, stdout, stderr)
        if not diagnostics:
            # Fallback diagnostic if no specific pattern matched
            combined = (stderr + "\n" + stdout).strip()
            first_line = combined.splitlines()[0] if combined else "Test harness exited with non-zero status"
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=".",
                    line=0,
                    column=0,
                    message=first_line[:200],
                    remediation="Review test output and address failing assertions.",
                )
            )

        return False, diagnostics, stdout, stderr

    def _parse_output(
        self, project: DiscoveredProject, stdout: str, stderr: str
    ) -> List[VerifyDiagnostic]:
        combined = stdout + "\n" + stderr
        diagnostics: List[VerifyDiagnostic] = []

        if project.ecosystem == "python":
            diagnostics.extend(self._parse_python_output(combined))
        elif project.ecosystem == "node":
            diagnostics.extend(self._parse_node_output(combined))
        elif project.ecosystem == "swift":
            diagnostics.extend(self._parse_swift_output(combined))
        elif project.ecosystem == "rust":
            diagnostics.extend(self._parse_rust_output(combined))
        elif project.ecosystem == "go":
            diagnostics.extend(self._parse_go_output(combined))
        elif project.ecosystem == "cpp":
            diagnostics.extend(self._parse_cpp_output(combined))

        return diagnostics

    def _parse_python_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # 1. Missing module / import error: ModuleNotFoundError / NameError
        missing_module = re.search(r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]", output)
        if missing_module:
            mod_name = missing_module.group(1)
            # Find file location if possible
            file_match = re.search(r'File "([^"]+)", line (\d+)', output)
            fpath = file_match.group(1) if file_match else "unknown"
            line = int(file_match.group(2)) if file_match else 1
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-003",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"ModuleNotFoundError: No module named '{mod_name}'",
                    remediation=f"Add missing import or install '{mod_name}' package.",
                )
            )

        name_error = re.search(r"NameError: name ['\"]([^'\"]+)['\"] is not defined", output)
        if name_error:
            var_name = name_error.group(1)
            file_match = re.search(r'File "([^"]+)", line (\d+)', output) or re.search(r'([^\s:]+\.py):(\d+):', output)
            fpath = file_match.group(1) if file_match else "unknown"
            line = int(file_match.group(2)) if file_match else 1
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-003",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"NameError: name '{var_name}' is not defined",
                    remediation=f"Import or define '{var_name}' in {self._rel_path(fpath)}.",
                )
            )

        # 2. Missing pytest fixture
        fixture_missing = re.search(r"fixture ['\"]([^'\"]+)['\"] not found", output)
        if fixture_missing:
            fix_name = fixture_missing.group(1)
            file_match = re.search(r'([^:\s]+\.py):(\d+): in ', output)
            fpath = file_match.group(1) if file_match else "conftest.py"
            line = int(file_match.group(2)) if file_match else 1
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-003",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"Missing pytest fixture '{fix_name}'",
                    remediation=f"Define fixture '{fix_name}' in conftest.py or test file.",
                )
            )

        # 3. Syntax errors
        syntax_err = re.search(r'File "([^"]+)", line (\d+).*\n\s*(?:.*)\n\s*SyntaxError:\s*(.*)', output)
        if syntax_err:
            fpath = syntax_err.group(1)
            line = int(syntax_err.group(2))
            msg = syntax_err.group(3).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-002",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"SyntaxError: {msg}",
                    remediation="Fix Python syntax defect at line specified.",
                )
            )

        # 4. Pytest failure lines: FAILED tests/test_foo.py::test_bar - AssertionError: ...
        for match in re.finditer(r"FAILED\s+([^:\s]+)::([^\s]+)\s*(?:-\s*(.*))?", output):
            fpath = match.group(1)
            test_name = match.group(2)
            msg = match.group(3) or "AssertionError or unexpected exception"
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=self._rel_path(fpath),
                    line=1,
                    column=1,
                    message=f"Test failed in {test_name}: {msg.strip()}",
                    remediation="Adjust test expectation or fix implementation logic.",
                )
            )

        # 5. Unittest failure lines: FAIL: test_foo (__main__.TestClass)
        for match in re.finditer(r"(FAIL|ERROR):\s+([^\s]+)\s+\(([^)]+)\)", output):
            status = match.group(1)
            test_name = match.group(2)
            cls_name = match.group(3)
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=cls_name,
                    line=1,
                    column=1,
                    message=f"{status}: {test_name} in {cls_name}",
                    remediation="Resolve test failure or unhandled exception in test case.",
                )
            )

        return diagnostics

    def _parse_node_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # Vitest / Jest syntax: FAIL  path/to/test.ts
        fail_files = re.findall(r"FAIL\s+([^\s]+\.(?:ts|js|tsx|jsx))", output)
        for fpath in fail_files:
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=self._rel_path(fpath),
                    line=1,
                    column=1,
                    message="Test suite failed",
                    remediation="Review JavaScript/TypeScript test assertions.",
                )
            )

        # Cannot find module
        mod_err = re.search(r"Cannot find module ['\"]([^'\"]+)['\"]", output)
        if mod_err:
            mod_name = mod_err.group(1)
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-003",
                    file="package.json",
                    line=1,
                    column=1,
                    message=f"Cannot find module '{mod_name}'",
                    remediation=f"Install dependency '{mod_name}' or fix module path import.",
                )
            )

        return diagnostics

    def _parse_swift_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # Swift error format: /path/to/file.swift:line: error: ...
        for match in re.finditer(r"([^:\s]+\.swift):(\d+):(?:\d+:)?\s*error:\s*(.*)", output):
            fpath = match.group(1)
            line = int(match.group(2))
            msg = match.group(3).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001" if "XCTAssert" in msg else "CDM-VRF-002",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=msg,
                    remediation="Check Swift test assertion or compile error.",
                )
            )

        return diagnostics

    def _parse_rust_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # 1. Compiler error: error[E0425]: cannot find value ... \n  --> file.rs:line:col
        for match in re.finditer(
            r"error(?:\[([A-Z0-9]+)\])?:\s*([^\n]+)\n\s*-->\s*([^:\s]+\.rs):(\d+):(\d+)",
            output,
        ):
            err_code = match.group(1) or "CDM-VRF-002"
            msg = match.group(2).strip()
            fpath = match.group(3)
            line = int(match.group(4))
            col = int(match.group(5))
            diagnostics.append(
                VerifyDiagnostic(
                    code=err_code,
                    file=self._rel_path(fpath),
                    line=line,
                    column=col,
                    message=msg,
                    remediation=f"Resolve rustc error [{err_code}]: {msg}",
                    rule_id=f"rustc::{err_code}" if err_code != "CDM-VRF-002" else None,
                )
            )

        # 2. Test assertion panic: thread 'test_foo' panicked at tests/test_main.rs:8:5: assertion `left == right` failed
        for match in re.finditer(
            r"thread '([^']+)' panicked at ([^:\s]+\.rs):(\d+):(\d+):\s*([^\n]+)",
            output,
        ):
            test_name = match.group(1)
            fpath = match.group(2)
            line = int(match.group(3))
            col = int(match.group(4))
            msg = match.group(5).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=self._rel_path(fpath),
                    line=line,
                    column=col,
                    message=f"Test '{test_name}' failed: {msg}",
                    remediation="Adjust test assertion or update implementation logic.",
                )
            )

        return diagnostics

    def _parse_go_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # 1. Compilation/vet error: file.go:line:col: message
        for match in re.finditer(r"(?:^|\n)(?:\.\/)?([^:\s\n]+\.go):(\d+):(\d+):\s*([^\n]+)", output):
            fpath = match.group(1)
            line = int(match.group(2))
            col = int(match.group(3))
            msg = match.group(4).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-002",
                    file=self._rel_path(fpath),
                    line=line,
                    column=col,
                    message=msg,
                    remediation=f"Resolve Go compiler or vet diagnostic: {msg}",
                )
            )

        # 2. Go test failure: --- FAIL: TestName (0.00s)\n    file.go:line: msg
        for match in re.finditer(
            r"---\s+FAIL:\s+([^\s]+)\s+\([^\)]+\)\s*\n\s+(?:\.\/)?([^:\s\n]+\.go):(\d+):\s*([^\n]+)",
            output,
        ):
            test_name = match.group(1)
            fpath = match.group(2)
            line = int(match.group(3))
            msg = match.group(4).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"Test '{test_name}' failed: {msg}",
                    remediation="Update Go test expectation or implementation.",
                )
            )

        return diagnostics

    def _parse_cpp_output(self, output: str) -> List[VerifyDiagnostic]:
        diagnostics: List[VerifyDiagnostic] = []

        # 1. Compiler error: file.cpp:line:col: error: message
        for match in re.finditer(
            r"(?:^|\n)([^:\s\n]+\.(?:cpp|cc|cxx|c\+\+|h|hpp|c)):(\d+):(\d+):\s*(?:fatal )?error:\s*([^\n]+)",
            output,
        ):
            fpath = match.group(1)
            line = int(match.group(2))
            col = int(match.group(3))
            msg = match.group(4).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-002",
                    file=self._rel_path(fpath),
                    line=line,
                    column=col,
                    message=msg,
                    remediation=f"Resolve C/C++ compiler error: {msg}",
                )
            )

        # 2. GoogleTest / Catch2 failure: file.cpp:line: Failure\nmessage
        for match in re.finditer(
            r"(?:^|\n)([^:\s\n]+\.(?:cpp|cc|cxx|c)):(\d+):\s*Failure\s*\n\s*([^\n]+)",
            output,
        ):
            fpath = match.group(1)
            line = int(match.group(2))
            msg = match.group(3).strip()
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file=self._rel_path(fpath),
                    line=line,
                    column=1,
                    message=f"Assertion failed: {msg}",
                    remediation="Resolve C/C++ test assertion failure.",
                )
            )

        # 3. CTest failure summary: The following tests FAILED: \n 1 - TestName (Failed)
        for match in re.finditer(r"\s*\d+\s*-\s*([^\s]+)\s*\(Failed\)", output):
            test_name = match.group(1)
            diagnostics.append(
                VerifyDiagnostic(
                    code="CDM-VRF-001",
                    file="CMakeLists.txt",
                    line=1,
                    column=1,
                    message=f"CTest suite failure: {test_name}",
                    remediation="Inspect test log under Testing/Temporary/LastTest.log.",
                )
            )

        return diagnostics

    def _rel_path(self, path_str: str) -> str:
        try:
            p = Path(path_str)
            if p.is_absolute() and str(p).startswith(str(self.repo_dir)):
                return str(p.relative_to(self.repo_dir))
        except Exception:
            pass
        return path_str
