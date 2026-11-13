"""On-demand, consent-based Tree-sitter grammar installer for storage-friendly usage."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class GrammarSpec:
    lang_key: str
    display_name: str
    module_name: str
    pip_package: str
    approx_size_mb: float


GRAMMAR_SPECS: Dict[str, GrammarSpec] = {
    "rust": GrammarSpec("rust", "Rust", "tree_sitter_rust", "tree-sitter-rust>=0.21.0", 3.2),
    "go": GrammarSpec("go", "Go", "tree_sitter_go", "tree-sitter-go>=0.21.0", 2.8),
    "cpp": GrammarSpec("cpp", "C / C++", "tree_sitter_cpp", "tree-sitter-cpp>=0.22.0", 4.5),
    "java": GrammarSpec("java", "Java", "tree_sitter_java", "tree-sitter-java>=0.21.0", 2.9),
    "kotlin": GrammarSpec("kotlin", "Kotlin", "tree_sitter_kotlin", "tree-sitter-kotlin>=1.0.0", 3.1),
    "ruby": GrammarSpec("ruby", "Ruby", "tree_sitter_ruby", "tree-sitter-ruby>=0.21.0", 3.5),
}


class GrammarManager:
    """Manages lazy, user-consented installation of optional Tree-sitter language grammars."""

    def __init__(
        self,
        *,
        auto_install: bool = False,
        no_install: bool = False,
        input_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.auto_install = auto_install
        self.no_install = no_install
        self._input_fn = input_fn or input
        self._declined: Set[str] = set()

    @staticmethod
    def is_installed(lang_key: str) -> bool:
        """Return True if tree_sitter and the language grammar module are importable."""
        spec = GRAMMAR_SPECS.get(lang_key)
        if not spec:
            return False
        return (
            importlib.util.find_spec("tree_sitter") is not None
            and importlib.util.find_spec(spec.module_name) is not None
        )

    @staticmethod
    def list_status() -> List[Dict[str, object]]:
        """Return installation status and estimated footprint for all optional grammars."""
        rows: List[Dict[str, object]] = []
        for key, spec in GRAMMAR_SPECS.items():
            rows.append({
                "language": key,
                "display_name": spec.display_name,
                "package": spec.pip_package,
                "approx_size_mb": spec.approx_size_mb,
                "installed": GrammarManager.is_installed(key),
            })
        return rows

    @staticmethod
    def install_languages(
        lang_keys: List[str],
        *,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> Tuple[bool, str]:
        """Install tree-sitter core and the requested language grammar packages via pip."""
        packages: List[str] = ["tree-sitter>=0.22.0"]
        valid_keys: List[str] = []
        for key in lang_keys:
            norm = key.strip().lower()
            if norm == "c":
                norm = "cpp"
            spec = GRAMMAR_SPECS.get(norm)
            if not spec:
                return False, f"Unknown optional grammar '{key}'. Available: {', '.join(GRAMMAR_SPECS)}"
            if spec.pip_package not in packages:
                packages.append(spec.pip_package)
            if norm not in valid_keys:
                valid_keys.append(norm)

        exec_fn = runner or subprocess.run
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", *packages]
        proc = exec_fn(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "pip install failed").strip()
            return False, f"Failed to install {', '.join(valid_keys)}: {err}"

        return True, f"Installed optional grammar(s): {', '.join(valid_keys)}"

    def ensure_available(self, lang_key: str) -> Tuple[bool, Optional[str]]:
        """Ensure grammar is installed, prompting for consent in interactive terminals.

        Returns (available, reason_if_unavailable).
        """
        if self.is_installed(lang_key):
            return True, None

        spec = GRAMMAR_SPECS.get(lang_key)
        if not spec:
            return False, f"Unsupported grammar '{lang_key}'."

        if self.no_install or lang_key in self._declined:
            return False, self._missing_hint(spec)

        env_policy = os.environ.get("CODEME_AUTO_INSTALL", "ask").strip().lower()
        if env_policy == "never":
            return False, self._missing_hint(spec)

        should_install = self.auto_install or env_policy == "always"
        if not should_install:
            if not sys.stdin.isatty():
                return False, self._missing_hint(spec)

            prompt = (
                f"[Codeme] Detected {spec.display_name} files, but optional grammar "
                f"'{spec.pip_package}' (~{spec.approx_size_mb:.1f} MB) is not installed.\n"
                f"Install it now? [y/N]: "
            )
            try:
                sys.stderr.write(prompt)
                sys.stderr.flush()
                answer = self._input_fn("").strip().lower()
            except EOFError:
                answer = "n"

            if answer not in ("y", "yes"):
                self._declined.add(lang_key)
                return False, self._missing_hint(spec)

        ok, msg = self.install_languages([lang_key])
        if not ok:
            return False, msg
        return True, None

    @staticmethod
    def _missing_hint(spec: GrammarSpec) -> str:
        return (
            f"Optional {spec.display_name} grammar '{spec.pip_package}' (~{spec.approx_size_mb:.1f} MB) "
            f"is not installed. Run 'codeme toolchain install {spec.lang_key}' or pass '--auto-install'."
        )

    @staticmethod
    def cache_status() -> Dict[str, object]:
        """Return installed grammar cache footprint and per-language breakdown."""
        from pathlib import Path

        rows: List[Dict[str, object]] = []
        total_bytes = 0
        for key, spec in GRAMMAR_SPECS.items():
            installed = GrammarManager.is_installed(key)
            disk_bytes = 0
            if installed:
                mod_spec = importlib.util.find_spec(spec.module_name)
                if mod_spec and mod_spec.submodule_search_locations:
                    for loc in mod_spec.submodule_search_locations:
                        p = Path(loc)
                        if p.exists():
                            disk_bytes += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                total_bytes += disk_bytes
            rows.append({
                "language": key,
                "display_name": spec.display_name,
                "installed": installed,
                "disk_mb": round(disk_bytes / (1024 * 1024), 2) if installed else 0.0,
                "approx_size_mb": spec.approx_size_mb,
            })

        return {
            "total_installed": sum(1 for r in rows if r["installed"]),
            "total_disk_mb": round(total_bytes / (1024 * 1024), 2),
            "grammars": rows,
        }

    @staticmethod
    def prune_languages(
        *,
        keep_languages: Optional[List[str]] = None,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ) -> Tuple[bool, str, List[str]]:
        """Uninstall optional grammars not in keep_languages."""
        keep = {("cpp" if k.strip().lower() == "c" else k.strip().lower()) for k in (keep_languages or [])}
        to_remove: List[str] = []
        packages: List[str] = []
        for key, spec in GRAMMAR_SPECS.items():
            if key not in keep and GrammarManager.is_installed(key):
                to_remove.append(key)
                pkg_name = spec.pip_package.split(">=")[0].split("==")[0]
                packages.append(pkg_name)

        if not packages:
            return True, "No optional grammars to prune.", []

        exec_fn = runner or subprocess.run
        cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "--quiet", *packages]
        proc = exec_fn(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "pip uninstall failed").strip()
            return False, f"Failed to prune {', '.join(to_remove)}: {err}", []

        return True, f"Pruned optional grammar(s): {', '.join(to_remove)}", to_remove
