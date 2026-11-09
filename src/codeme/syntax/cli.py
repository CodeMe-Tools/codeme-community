"""Command-line interface for codeme-syntax."""

import argparse
import sys
from typing import Optional, Sequence
from codeme.syntax.runner import SyntaxRunner


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeme-syntax",
        description="Codeme deterministic syntax parsing and repair engine.",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # 'run' subcommand
    run_parser = subparsers.add_parser("run", help="Run syntax verification")
    _add_runner_arguments(run_parser)

    # Also add runner arguments to top-level parser so user can run:
    # `codeme-syntax --file ...` or `codeme-syntax run --file ...`
    _add_runner_arguments(parser)

    return parser


def _add_runner_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", "-r", type=str, default=None, help="Repository root path to scan")
    p.add_argument("--file", "-f", type=str, default=None, help="Specific file to verify")
    p.add_argument("--fix", action="store_true", help="Apply deterministic repairs where possible")
    p.add_argument("--verbose", "-v", action="store_true", help="Enable verbose diagnostics")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    runner = SyntaxRunner(fix=args.fix, verbose=args.verbose)
    code = runner.run(repo_path=args.repo, file_path=args.file)
    return code


if __name__ == "__main__":
    sys.exit(main())
