"""Command-line interface for codeme-quality."""

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence
from codeme.quality.config import QualityConfig
from codeme.quality.runner import QualityRunner


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeme-quality",
        description="Codeme deterministic quality gate and architectural boundary engine.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # 'run' subcommand
    run_parser = subparsers.add_parser("run", help="Run quality verification")
    _add_runner_arguments(run_parser)

    # Also top-level arguments
    _add_runner_arguments(parser)

    return parser


def _add_runner_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", "-r", type=str, default=None, help="Repository root path to scan")
    p.add_argument("--file", "-f", type=str, default=None, help="Specific file to verify")
    p.add_argument("--fix", action="store_true", help="Apply deterministic fixes (unused imports, trailing whitespace)")
    p.add_argument("--config", "-c", type=str, default=None, help="Path to custom quality config JSON")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable verbose diagnostics")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else None
    base_dir = Path(args.repo) if args.repo else None
    config = QualityConfig.load(config_path=config_path, base_dir=base_dir)

    runner = QualityRunner(config=config, fix=args.fix, verbose=args.verbose)
    code = runner.run(repo_path=args.repo, file_path=args.file)
    return code


if __name__ == "__main__":
    sys.exit(main())
