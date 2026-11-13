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
        discoverers = (
            self._discover_swift,
            self._discover_cargo,
            self._discover_go,
            self._discover_cmake,
            self._discover_jvm,
            self._discover_dotnet,
            self._discover_ruby,
            self._discover_php,
            self._discover_node,
            self._discover_python,
        )
        for discover_fn in discoverers:
            proj = discover_fn(test_pattern)
            if proj:
                return proj
        return None

    def _discover_jvm(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers Java/Kotlin projects via Maven (pom.xml) or Gradle."""
        if (self.repo_dir / "pom.xml").is_file():
            cmd = ["mvn", "test", "-q"]
            if test_pattern:
                cmd.append(f"-Dtest={test_pattern}")
            test_files = list(self.repo_dir.glob("src/test/**/*.java")) + list(self.repo_dir.glob("src/test/**/*.kt"))
            return DiscoveredProject(
                ecosystem="jvm",
                framework="maven",
                command=cmd,
                root_dir=self.repo_dir,
                test_files=test_files,
            )

        if (self.repo_dir / "build.gradle").is_file() or (self.repo_dir / "build.gradle.kts").is_file():
            gradlew = self.repo_dir / "gradlew"
            gradle_bin = str(gradlew) if gradlew.is_file() else "gradle"
            cmd = [gradle_bin, "test"]
            if test_pattern:
                cmd.extend(["--tests", test_pattern])
            test_files = list(self.repo_dir.glob("src/test/**/*.java")) + list(self.repo_dir.glob("src/test/**/*.kt"))
            return DiscoveredProject(
                ecosystem="jvm",
                framework="gradle",
                command=cmd,
                root_dir=self.repo_dir,
                test_files=test_files,
            )
        return None

    def _discover_dotnet(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers C# / .NET projects via *.sln or *.csproj."""
        has_sln = any(self.repo_dir.glob("*.sln"))
        has_csproj = any(self.repo_dir.glob("*.csproj"))
        if not (has_sln or has_csproj):
            return None

        cmd = ["dotnet", "test"]
        if test_pattern:
            cmd.extend(["--filter", test_pattern])
        test_files = list(self.repo_dir.glob("**/*Tests.cs")) + list(self.repo_dir.glob("**/*Test.cs"))
        return DiscoveredProject(
            ecosystem="dotnet",
            framework="dotnet",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )

    def _discover_ruby(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers Ruby projects via RSpec or Rake."""
        if (self.repo_dir / "spec").is_dir() or (self.repo_dir / ".rspec").is_file():
            cmd = ["bundle", "exec", "rspec"] if (self.repo_dir / "Gemfile").is_file() else ["rspec"]
            if test_pattern:
                cmd.extend(["-e", test_pattern])
            test_files = list(self.repo_dir.glob("spec/**/*_spec.rb"))
            return DiscoveredProject(
                ecosystem="ruby",
                framework="rspec",
                command=cmd,
                root_dir=self.repo_dir,
                test_files=test_files,
            )
        if (self.repo_dir / "Rakefile").is_file() and (self.repo_dir / "test").is_dir():
            cmd = ["bundle", "exec", "rake", "test"] if (self.repo_dir / "Gemfile").is_file() else ["rake", "test"]
            test_files = list(self.repo_dir.glob("test/**/*_test.rb"))
            return DiscoveredProject(
                ecosystem="ruby",
                framework="rake",
                command=cmd,
                root_dir=self.repo_dir,
                test_files=test_files,
            )
        return None

    def _discover_php(self, test_pattern: Optional[str]) -> Optional[DiscoveredProject]:
        """Discovers PHP projects via phpunit.xml or composer.json."""
        has_phpunit = (self.repo_dir / "phpunit.xml").is_file() or (self.repo_dir / "phpunit.xml.dist").is_file()
        if not has_phpunit:
            return None

        vendor_phpunit = self.repo_dir / "vendor" / "bin" / "phpunit"
        cmd = [str(vendor_phpunit) if vendor_phpunit.is_file() else "phpunit"]
        if test_pattern:
            cmd.extend(["--filter", test_pattern])
        test_files = list(self.repo_dir.glob("tests/**/*Test.php"))
        return DiscoveredProject(
            ecosystem="php",
            framework="phpunit",
            command=cmd,
            root_dir=self.repo_dir,
            test_files=test_files,
        )

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
