"""Command-line interface for lascheck."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console

from lascheck import __version__
from lascheck.checks import CheckOptions, Severity, run_checks
from lascheck.report import FileReport, render_report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lascheck",
        description="Quality-assurance checks for LAS/LAZ LiDAR point clouds.",
    )
    p.add_argument("paths", nargs="+", type=Path, help="LAS or LAZ files to check.")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures for the exit code.",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="Skip per-point checks; inspect header/VLRs only.",
    )
    p.add_argument(
        "--min-density",
        type=float,
        default=None,
        help="Fail/warn if point density (pts/m²) falls below this value.",
    )
    p.add_argument(
        "--max-unclassified",
        type=float,
        default=50.0,
        help="Maximum percent of unclassified points before warning (default: 50).",
    )
    p.add_argument(
        "--bbox-tolerance",
        type=float,
        default=1e-3,
        help="Allowed difference (in CRS units) between header and actual bbox (default: 1e-3).",
    )
    p.add_argument("--version", action="version", version=f"lascheck {__version__}")
    return p


def _exit_code(reports: list[FileReport], strict: bool) -> int:
    worst = Severity.INFO
    order = {Severity.INFO: 0, Severity.WARN: 1, Severity.FAIL: 2}
    for r in reports:
        if order[r.worst] > order[worst]:
            worst = r.worst
    if worst is Severity.FAIL:
        return 2
    if worst is Severity.WARN:
        return 2 if strict else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    opts = CheckOptions(
        quick=args.quick,
        min_density=args.min_density,
        max_unclassified_pct=args.max_unclassified,
        bbox_tolerance_m=args.bbox_tolerance,
    )

    reports: list[FileReport] = []
    for path in args.paths:
        if not path.exists():
            reports.append(
                FileReport(
                    path=path,
                    results=[
                        run_checks_missing(path),
                    ],
                )
            )
            continue
        results = run_checks(path, opts)
        reports.append(FileReport(path=path, results=results))

    if args.json:
        payload = {"reports": [r.to_dict() for r in reports]}
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        console = Console()
        for r in reports:
            render_report(console, r)

    return _exit_code(reports, args.strict)


def run_checks_missing(path: Path):
    from lascheck.checks import CheckResult

    return CheckResult(
        "file_opens",
        Severity.FAIL,
        "File does not exist.",
        {"path": str(path)},
    )
