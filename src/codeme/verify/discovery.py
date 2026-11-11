"""Multi-ecosystem build and test discovery for codeme-verify."""

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
from typing import List, Optional


@dataclass
class DiscoveredProject:
    ecosystem: str  # "python", "node", "swift"
    framework: str  # "pytest", "unittest", "vitest", "jest", "npm", "swift"
    command: List[str]
    root_dir: Path
    test_files: List[Path] = field(default_factory=list)


class ProjectDiscovery:
    """Discovers project ecosystem, test frameworks, and execution commands."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir.resolve()

    def discover(self, test_pattern: Optional[str] = None) -> Optional[DiscoveredProject]:
        """Discovers the primary test project in the repository."""
        # 1. Swift
        swift_proj = self._discover_swift(test_pattern)
        if swift_proj:
            return swift_proj

        # 2. Rust (Cargo)
        rust_proj = self._discover_cargo(test_pattern)
        if rust_proj:
            return rust_proj

        # 3. Go (go test)
        go_proj = self._discover_go(test_pattern)
        if go_proj:
            return go_proj

        # 4. C/C++ (CMake / CTest)
        cmake_proj = self._discover_cmake(test_pattern)
        if cmake_proj:
            return cmake_proj

        # 5. Node / TypeScript
        node_proj = self._discover_node(test_pattern)
        if node_proj:
            return node_proj

        # 6. Python
        python_proj = self._discover_python(test_pattern)
        if python_proj:
            return python_proj

        return None

    def _discover_cargo(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers Rust project via Cargo.toml."""
        cargo_toml = self.repo_dir / "Cargo.toml"
        if not cargo_toml.is_file():
            return None

        test_files = list(self.repo_dir.glob("tests/**/*.rs")) + list(self.repo_dir.glob("src/**/*.rs"))
        cmd = ["cargo", "test"]
        if test_pattern:
            cmd.extend(["--", test_pattern])

        return DiscoveredProject(
            ecosystem="rust",
            framework="cargo",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )

    def _discover_go(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers Go project via go.mod."""
        go_mod = self.repo_dir / "go.mod"
        if not go_mod.is_file():
            return None

        test_files = [f for f in self.repo_dir.glob("**/*_test.go") if "vendor" not in f.parts]
        cmd = ["go", "test", "-v", "./..."]
        if test_pattern:
            cmd.extend(["-run", test_pattern])

        return DiscoveredProject(
            ecosystem="go",
            framework="go",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )

    def _discover_cmake(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers C/C++ project via CMakeLists.txt or Makefile."""
        has_cmake = (self.repo_dir / "CMakeLists.txt").is_file()
        has_makefile = (self.repo_dir / "Makefile").is_file()
        if not (has_cmake or has_makefile):
            return None

        test_files: List[Path] = []
        for pat in ("**/*test*.cpp", "**/*test*.cc", "**/*Test*.cpp", "**/*test*.c"):
            test_files.extend(self.repo_dir.glob(pat))

        cmd = ["ctest", "--output-on-failure"]
        if test_pattern:
            cmd.extend(["-R", test_pattern])

        return DiscoveredProject(
            ecosystem="cpp",
            framework="ctest",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=[f for f in test_files if "build" not in f.parts],
        )

    def _discover_swift(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        package_swift = self.repo_dir / "Package.swift"
        if not package_swift.is_file():
            return None

        test_files = list(self.repo_dir.glob("Tests/**/*.swift"))
        cmd = ["swift", "test"]
        if test_pattern:
            cmd.extend(["--filter", test_pattern])

        return DiscoveredProject(
            ecosystem="swift",
            framework="swift",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )

    def _discover_node(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        pkg_json_path = self.repo_dir / "package.json"
        if not pkg_json_path.is_file():
            return None

        framework = "npm"
        test_cmd: List[str] = []

        try:
            with open(pkg_json_path, "r", encoding="utf-8") as f:
                pkg_data = json.load(f)
        except Exception:
            pkg_data = {}

        deps = pkg_data.get("dependencies", {})
        dev_deps = pkg_data.get("devDependencies", {})
        scripts = pkg_data.get("scripts", {})
        test_script = scripts.get("test", "")

        all_dep_names = set(deps.keys()).union(set(dev_deps.keys()))

        if "vitest" in all_dep_names or "vitest" in test_script or (self.repo_dir / "vitest.config.ts").exists() or (self.repo_dir / "vitest.config.js").exists():
            framework = "vitest"
            test_cmd = ["npx", "vitest", "run"]
            if test_pattern:
                test_cmd.extend(["-t", test_pattern])
        elif "jest" in all_dep_names or "jest" in test_script or (self.repo_dir / "jest.config.js").exists() or (self.repo_dir / "jest.config.ts").exists():
            framework = "jest"
            test_cmd = ["npx", "jest"]
            if test_pattern:
                test_cmd.extend(["-t", test_pattern])
        elif "test" in scripts:
            framework = "npm"
            test_cmd = ["npm", "test", "--"]
            if test_pattern:
                test_cmd.append(test_pattern)
        else:
            framework = "npm"
            test_cmd = ["npm", "test"]

        # Collect node test files
        test_files: List[Path] = []
        for ext in ("*.test.ts", "*.test.js", "*.spec.ts", "*.spec.js"):
            test_files.extend(self.repo_dir.glob(f"**/{ext}"))

        return DiscoveredProject(
            ecosystem="node",
            framework=framework,
            command=test_cmd,
            root_dir=self.repo_dir,
            test_files=[f for f in test_files if "node_modules" not in f.parts],
        )

    def _discover_python(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        pyproject_path = self.repo_dir / "pyproject.toml"
        setup_py_path = self.repo_dir / "setup.py"
        pytest_ini_path = self.repo_dir / "pytest.ini"
        requirements_path = self.repo_dir / "requirements.txt"
        tests_dir = self.repo_dir / "tests"

        test_files: List[Path] = []
        if tests_dir.is_dir():
            test_files.extend(tests_dir.glob("**/test_*.py"))
            test_files.extend(tests_dir.glob("**/*_test.py"))
        else:
            test_files.extend(self.repo_dir.glob("**/test_*.py"))
            test_files.extend(self.repo_dir.glob("**/*_test.py"))

        is_python = (
            pyproject_path.exists()
            or setup_py_path.exists()
            or pytest_ini_path.exists()
            or requirements_path.exists()
            or bool(test_files)
        )
        if not is_python:
            return None

        # Check whether to use pytest or unittest
        use_pytest = True
        if pytest_ini_path.exists():
            use_pytest = True
        elif pyproject_path.exists():
            try:
                content = pyproject_path.read_text(encoding="utf-8")
                if "pytest" in content:
                    use_pytest = True
            except Exception:
                pass

        python_bin = sys.executable
        if use_pytest:
            cmd = [python_bin, "-m", "pytest"]
            if test_pattern:
                cmd.extend(["-k", test_pattern])
            framework = "pytest"
        else:
            cmd = [python_bin, "-m", "unittest"]
            if test_pattern:
                cmd.extend(["-k", test_pattern])
            framework = "unittest"

        return DiscoveredProject(
            ecosystem="python",
            framework=framework,
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )
