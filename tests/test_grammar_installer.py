"""Tests for on-demand, user-consented optional Tree-sitter grammar installation."""

from unittest.mock import patch
from codeme.syntax.grammar_installer import GrammarManager
from codeme.syntax.treesitter_parser import TreeSitterParser


def test_grammar_manager_declined_interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    mgr = GrammarManager(input_fn=lambda _: "n")

    with patch.object(GrammarManager, "is_installed", return_value=False):
        with patch.object(GrammarManager, "install_languages") as mock_install:
            ok, reason = mgr.ensure_available("rust")
            assert ok is False
            assert "tree-sitter-rust" in (reason or "")
            mock_install.assert_not_called()

            # Second call in same session should not re-prompt because it's declined
            ok2, _ = mgr.ensure_available("rust")
            assert ok2 is False


def test_grammar_manager_approved_interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    mgr = GrammarManager(input_fn=lambda _: "y")

    with patch.object(GrammarManager, "is_installed", return_value=False):
        with patch.object(GrammarManager, "install_languages", return_value=(True, "Installed rust")) as mock_install:
            ok, reason = mgr.ensure_available("rust")
            assert ok is True
            assert reason is None
            mock_install.assert_called_once_with(["rust"])


def test_grammar_manager_non_interactive_never_installs_silently(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    mgr = GrammarManager(auto_install=False)

    with patch.object(GrammarManager, "is_installed", return_value=False):
        with patch.object(GrammarManager, "install_languages") as mock_install:
            ok, reason = mgr.ensure_available("go")
            assert ok is False
            assert "codeme toolchain install go" in (reason or "")
            mock_install.assert_not_called()


def test_treesitter_parser_returns_cdm_syn_008_when_grammar_missing():
    mgr = GrammarManager(no_install=True)
    parser = TreeSitterParser(grammar_manager=mgr)
    with patch.object(GrammarManager, "is_installed", return_value=False):
        diag = parser.parse("fn main() {}", file_path="main.rs")
        assert diag is not None
        assert diag.code == "CDM-SYN-008"
        assert "codeme toolchain install rust" in diag.recommendation


def test_grammar_manager_list_status():
    rows = GrammarManager.list_status()
    langs = {r["language"] for r in rows}
    assert {"rust", "go", "cpp", "java", "kotlin", "ruby"}.issubset(langs)
