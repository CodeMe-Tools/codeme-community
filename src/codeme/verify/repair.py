"""Mechanical repair engine for codeme-verify."""

from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

from codeme.verify.diagnostics import VerifyDiagnostic


KNOWN_SYMBOL_IMPORTS = {
    "pytest": "import pytest\n",
    "unittest": "import unittest\n",
    "os": "import os\n",
    "sys": "import sys\n",
    "json": "import json\n",
    "re": "import re\n",
    "Path": "from pathlib import Path\n",
    "dataclass": "from dataclasses import dataclass\n",
    "MagicMock": "from unittest.mock import MagicMock\n",
    "patch": "from unittest.mock import patch\n",
}

KNOWN_RUST_IMPORTS = {
    "HashMap": "use std::collections::HashMap;\n",
    "HashSet": "use std::collections::HashSet;\n",
    "BTreeMap": "use std::collections::BTreeMap;\n",
    "Duration": "use std::time::Duration;\n",
    "Path": "use std::path::Path;\n",
    "PathBuf": "use std::path::PathBuf;\n",
}

KNOWN_GO_PACKAGES = {
    "fmt": 'import "fmt"\n',
    "strings": 'import "strings"\n',
    "time": 'import "time"\n',
    "os": 'import "os"\n',
    "bytes": 'import "bytes"\n',
    "errors": 'import "errors"\n',
    "sync": 'import "sync"\n',
}

KNOWN_CPP_INCLUDES = {
    "vector": "#include <vector>\n",
    "string": "#include <string>\n",
    "iostream": "#include <iostream>\n",
    "cout": "#include <iostream>\n",
    "endl": "#include <iostream>\n",
    "map": "#include <map>\n",
    "set": "#include <set>\n",
    "memory": "#include <memory>\n",
    "unique_ptr": "#include <memory>\n",
    "shared_ptr": "#include <memory>\n",
}


class MechanicalRepair:
    """Applies deterministic, minimal mechanical repairs to source and config files."""

    def __init__(self, repo_dir: Path):
        self.repo_dir = repo_dir.resolve()

    def plan_and_apply(self, diagnostics: List[VerifyDiagnostic]) -> Tuple[bool, Dict[Path, str]]:
        """Plans and applies mechanical repairs.

        Returns:
            Tuple of (repairs_applied, original_file_snapshots)
        """
        snapshots: Dict[Path, str] = {}
        applied_any = False

        for diag in diagnostics:
            # 1. Missing Import: NameError
            name_match = re.search(r"NameError:\s*name\s*['\"]([^'\"]+)['\"]\s*is not defined", diag.message)
            if name_match:
                symbol = name_match.group(1)
                file_path = self._resolve_file(diag.file)
                if file_path and file_path.is_file() and symbol in KNOWN_SYMBOL_IMPORTS:
                    if file_path not in snapshots:
                        snapshots[file_path] = file_path.read_text(encoding="utf-8")
                    if self._inject_import(file_path, KNOWN_SYMBOL_IMPORTS[symbol]):
                        applied_any = True

            # 2. Missing pytest fixture
            fixture_match = re.search(r"Missing pytest fixture ['\"]([^'\"]+)['\"]", diag.message)
            if fixture_match:
                fix_name = fixture_match.group(1)
                conftest_path = self.repo_dir / "tests" / "conftest.py"
                if not conftest_path.parent.exists():
                    conftest_path = self.repo_dir / "conftest.py"
                if conftest_path.exists():
                    if conftest_path not in snapshots:
                        snapshots[conftest_path] = conftest_path.read_text(encoding="utf-8")
                else:
                    snapshots[conftest_path] = ""

                fixture_code = f"\nimport pytest\n\n@pytest.fixture\ndef {fix_name}():\n    return None\n"
                current_text = snapshots[conftest_path]
                if f"def {fix_name}" not in current_text:
                    conftest_path.parent.mkdir(parents=True, exist_ok=True)
                    conftest_path.write_text(current_text + fixture_code, encoding="utf-8")
                    applied_any = True

            # 3. Configuration syntax: package.json trailing commas
            if diag.file.endswith("package.json"):
                pkg_path = self.repo_dir / diag.file
                if pkg_path.is_file():
                    if pkg_path not in snapshots:
                        snapshots[pkg_path] = pkg_path.read_text(encoding="utf-8")
                    fixed = self._fix_json_syntax(snapshots[pkg_path])
                    if fixed != snapshots[pkg_path]:
                        pkg_path.write_text(fixed, encoding="utf-8")
                        applied_any = True

            # 4. Rust: missing standard import
            if diag.file.endswith(".rs"):
                rust_match = re.search(r"cannot find (?:value|type) ['`\"]([^'`\"]+)['`\"] in this scope", diag.message)
                if rust_match:
                    symbol = rust_match.group(1)
                    if symbol in KNOWN_RUST_IMPORTS:
                        file_path = self._resolve_file(diag.file)
                        if file_path and file_path.is_file():
                            if file_path not in snapshots:
                                snapshots[file_path] = file_path.read_text(encoding="utf-8")
                            stmt = KNOWN_RUST_IMPORTS[symbol]
                            content = snapshots[file_path]
                            if stmt.strip() not in content:
                                file_path.write_text(stmt + content, encoding="utf-8")
                                applied_any = True

            # 5. Go: missing standard package import
            if diag.file.endswith(".go"):
                go_match = re.search(r"undefined:\s*(?:([a-zA-Z0-9]+)\.)?([a-zA-Z0-9]+)", diag.message)
                if go_match:
                    pkg_candidate = go_match.group(1) or go_match.group(2)
                    if pkg_candidate in KNOWN_GO_PACKAGES:
                        file_path = self._resolve_file(diag.file)
                        if file_path and file_path.is_file():
                            if file_path not in snapshots:
                                snapshots[file_path] = file_path.read_text(encoding="utf-8")
                            stmt = KNOWN_GO_PACKAGES[pkg_candidate]
                            content = snapshots[file_path]
                            if stmt.strip() not in content:
                                lines = content.splitlines(keepends=True)
                                pkg_line_idx = 0
                                for idx, l in enumerate(lines):
                                    if l.startswith("package "):
                                        pkg_line_idx = idx + 1
                                        break
                                lines.insert(pkg_line_idx, "\n" + stmt)
                                file_path.write_text("".join(lines), encoding="utf-8")
                                applied_any = True

            # 6. C/C++: missing standard header include
            if any(diag.file.endswith(ext) for ext in (".cpp", ".cc", ".cxx", ".hpp", ".h", ".c")):
                cpp_match = re.search(r"['`](?:std::)?([a-zA-Z0-9_]+)['`]\s*(?:was not declared|is not a member|does not name a type)", diag.message)
                if cpp_match:
                    sym = cpp_match.group(1)
                    if sym in KNOWN_CPP_INCLUDES:
                        file_path = self._resolve_file(diag.file)
                        if file_path and file_path.is_file():
                            if file_path not in snapshots:
                                snapshots[file_path] = file_path.read_text(encoding="utf-8")
                            include_stmt = KNOWN_CPP_INCLUDES[sym]
                            content = snapshots[file_path]
                            if include_stmt.strip() not in content:
                                file_path.write_text(include_stmt + content, encoding="utf-8")
                                applied_any = True

        return applied_any, snapshots

    def rollback(self, snapshots: Dict[Path, str]) -> None:
        """Rolls back all modified files to original snapshots."""
        for file_path, original_content in snapshots.items():
            if original_content == "":
                if file_path.exists():
                    file_path.unlink()
            else:
                file_path.write_text(original_content, encoding="utf-8")

    def _resolve_file(self, file_str: str) -> Optional[Path]:
        p = Path(file_str)
        if p.is_absolute() and p.exists():
            return p
        candidate = self.repo_dir / file_str
        if candidate.exists():
            return candidate
        # Search for file basename
        matches = list(self.repo_dir.glob(f"**/{p.name}"))
        if matches:
            return matches[0]
        return None

    def _inject_import(self, file_path: Path, import_stmt: str) -> bool:
        content = file_path.read_text(encoding="utf-8")
        if import_stmt.strip() in content:
            return False

        lines = content.splitlines(keepends=True)
        # Determine insertion index: after future imports or module docstring
        insert_idx = 0
        in_docstring = False
        docstring_delim = None

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    docstring_delim = stripped[:3]
                    if stripped.count(docstring_delim) == 1 or stripped == docstring_delim:
                        in_docstring = True
                    else:
                        insert_idx = idx + 1
                    continue
                elif stripped.startswith("#"):
                    continue
                elif stripped.startswith("from __future__"):
                    insert_idx = idx + 1
                    continue
                else:
                    break
            else:
                if docstring_delim and docstring_delim in stripped:
                    in_docstring = False
                    insert_idx = idx + 1
                    break

        lines.insert(insert_idx, import_stmt)
        file_path.write_text("".join(lines), encoding="utf-8")
        return True

    def _fix_json_syntax(self, content: str) -> str:
        # Strip trailing commas before } or ]
        fixed = re.sub(r",\s*([}\]])", r"\1", content)
        return fixed
