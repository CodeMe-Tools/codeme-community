"""CLI entrypoint for codeme-verify."""

import argparse
from pathlib import Path
import sys
import time
import uuid

from codeme.verify.diagnostics import VerifyDiagnostic, format_diagnostics_json
from codeme.verify.repair import MechanicalRepair
from codeme.verify.runner import TestRunner


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="codeme-verify",
        description="Multi-ecosystem build and test verification engine for Codeme.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    run_parser = subparsers.add_parser("run", help="Run verification and test suite")
    for p in (parser, run_parser):
        p.add_argument(
            "--repo",
            default=".",
            help="Path to repository root (default: current directory)",
        )
        p.add_argument(
            "--test",
            dest="test_pattern",
            default=None,
            help="Test pattern or filter to select specific tests",
        )
        p.add_argument(
            "--incremental",
            action="store_true",
            help="Only run tests affected by uncommitted or recent changes",
        )
        p.add_argument(
            "--fix",
            action="store_true",
            help="Attempt mechanical repairs on deterministic failures with revalidation loop",
        )
        p.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="Emit verbose logs and command output",
        )
        p.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Output formatting (default: text)",
        )

    return parser.parse_args(argv)


def run_verification(args) -> int:
    repo_dir = Path(args.repo).resolve()
    if not repo_dir.exists():
        diag = VerifyDiagnostic(
            code="CDM-VRF-005",
            file=str(args.repo),
            line=0,
            column=0,
            message=f"Repository path does not exist: {args.repo}",
            remediation="Provide a valid directory path to --repo.",
        )
        if args.format == "json":
            print(format_diagnostics_json(str(uuid.uuid4()), "configuration_error", 2, [diag]))
        else:
            sys.stderr.write(diag.format_text() + "\n")
        return 2

    start_time = time.time()
    runner = TestRunner(repo_dir)
    success, diagnostics, stdout, stderr = runner.run(
        test_pattern=args.test_pattern,
        incremental=args.incremental,
    )

    # Mechanical repair and revalidation loop if --fix is set and tests failed
    if not success and args.fix and diagnostics:
        repairer = MechanicalRepair(repo_dir)
        applied, snapshots = repairer.plan_and_apply(diagnostics)
        if applied:
            # Revalidate!
            reval_success, reval_diags, reval_stdout, reval_stderr = runner.run(
                test_pattern=args.test_pattern,
                incremental=args.incremental,
            )
            if reval_success:
                success = True
                diagnostics = []
                stdout = reval_stdout
                stderr = reval_stderr
            else:
                # Rollback if repair did not make tests pass
                repairer.rollback(snapshots)
                diagnostics = reval_diags
                stdout = reval_stdout
                stderr = reval_stderr

    duration_ms = (time.time() - start_time) * 1000.0

    if success:
        if args.format == "json":
            print(
                format_diagnostics_json(
                    str(uuid.uuid4()),
                    "success",
                    0,
                    [],
                    duration_ms=duration_ms,
                    raw_output_bytes=len((stdout + stderr).encode("utf-8")),
                    suppressed_bytes=len((stdout + stderr).encode("utf-8")),
                )
            )
        elif args.verbose:
            sys.stdout.write("Test verification succeeded.\n")
            if stdout:
                sys.stdout.write(stdout)
        # ADR-0002: Default success is SILENT (0 bytes stdout/stderr)
        return 0

    # Failure
    exit_code = 1
    raw_bytes = len((stdout + stderr).encode("utf-8"))
    if args.format == "json":
        print(
            format_diagnostics_json(
                str(uuid.uuid4()),
                "violation",
                exit_code,
                diagnostics,
                duration_ms=duration_ms,
                raw_output_bytes=raw_bytes,
                suppressed_bytes=max(0, raw_bytes - 100),
            )
        )
    else:
        for d in diagnostics:
            sys.stderr.write(d.format_text() + "\n")
        if args.verbose and (stdout or stderr):
            sys.stderr.write("\n--- Test Output ---\n")
            if stdout:
                sys.stderr.write(stdout + "\n")
            if stderr:
                sys.stderr.write(stderr + "\n")

    return exit_code


def main(argv=None):
    args = parse_args(argv)
    exit_code = run_verification(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
