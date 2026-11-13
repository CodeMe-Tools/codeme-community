"""Tests for newly added syntax languages (C, JSON, TOML, Shell) and verify ecosystems (JVM, .NET, Ruby, PHP)."""

from pathlib import Path
from codeme.syntax.config_parser import ConfigAndShellParser
from codeme.syntax.treesitter_parser import TreeSitterParser
from codeme.verify.discovery import ProjectDiscovery


def test_json_parse_and_trailing_comma_repair():
    parser = ConfigAndShellParser()
    bad_json = '{"name": "codeme", "active": true,}\n'
    diag = parser.parse(bad_json, file_path="config.json")
    assert diag is not None
    assert diag.code == "CDM-SYN-016"

    repaired, new_source, post_diag = parser.repair(bad_json, file_path="config.json")
    assert repaired is True
    assert post_diag is None
    assert '"active": true\n' in new_source or '"active": true}' in new_source


def test_toml_parse_valid_and_invalid():
    parser = ConfigAndShellParser()
    assert parser.parse('[project]\nname = "codeme"\n', file_path="pyproject.toml") is None
    diag = parser.parse('[project]\nname = \n', file_path="pyproject.toml")
    assert diag is not None
    assert diag.code == "CDM-SYN-017"


def test_shell_parse_valid_and_invalid():
    parser = ConfigAndShellParser()
    assert parser.parse('#!/bin/sh\necho "ok"\n', file_path="run.sh") is None
    diag = parser.parse('#!/bin/sh\nif [ -f foo ]; then\n  echo "missing fi"\n', file_path="broken.sh")
    assert diag is not None
    assert diag.code == "CDM-SYN-018"


def test_c_language_treesitter_extension():
    ts = TreeSitterParser()
    assert ts.get_language_for_extension(".c") == "cpp"
    assert ts.parse("int main(void) { return 0; }\n", file_path="main.c") is None
    assert ts.parse("int main(void) { return 0 \n", file_path="bad.c") is not None


def test_verify_discovery_jvm_dotnet_ruby_php(tmp_path: Path):
    # Maven
    mvn_dir = tmp_path / "mvn_app"
    mvn_dir.mkdir()
    (mvn_dir / "pom.xml").write_text("<project/>", encoding="utf-8")
    assert ProjectDiscovery(mvn_dir).discover().framework == "maven"

    # .NET
    net_dir = tmp_path / "net_app"
    net_dir.mkdir()
    (net_dir / "App.csproj").write_text("<Project/>", encoding="utf-8")
    assert ProjectDiscovery(net_dir).discover().framework == "dotnet"

    # Ruby RSpec
    rb_dir = tmp_path / "rb_app"
    rb_dir.mkdir()
    (rb_dir / "spec").mkdir()
    (rb_dir / "Gemfile").write_text("source 'https://rubygems.org'", encoding="utf-8")
    assert ProjectDiscovery(rb_dir).discover().framework == "rspec"

    # PHPUnit
    php_dir = tmp_path / "php_app"
    php_dir.mkdir()
    (php_dir / "phpunit.xml").write_text("<phpunit/>", encoding="utf-8")
    assert ProjectDiscovery(php_dir).discover().framework == "phpunit"
