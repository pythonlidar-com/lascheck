"""Aggregation and rendering of check results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from lascheck.checks import CheckResult, Severity


@dataclass
class FileReport:
    path: Path
    results: list[CheckResult]

    @property
    def worst(self) -> Severity:
        order = {Severity.INFO: 0, Severity.WARN: 1, Severity.FAIL: 2}
        return max(self.results, key=lambda r: order[r.severity]).severity

    @property
    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for r in self.results:
            out[r.severity.value] += 1
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "worst": self.worst.value,
            "counts": self.counts,
            "results": [r.to_dict() for r in self.results],
        }


_SEV_STYLE = {
    Severity.INFO: "green",
    Severity.WARN: "yellow",
    Severity.FAIL: "red",
}

_SEV_SYMBOL = {
    Severity.INFO: "✓",
    Severity.WARN: "!",
    Severity.FAIL: "✗",
}


def render_report(console: Console, report: FileReport) -> None:
    header = Text()
    header.append(str(report.path), style="bold cyan")
    header.append("  ")
    header.append(report.worst.value.upper(), style=f"bold {_SEV_STYLE[report.worst]}")
    console.print(header)

    table = Table(show_header=True, header_style="bold", pad_edge=False, box=None)
    table.add_column("", width=2)
    table.add_column("Check", style="bold")
    table.add_column("Message")

    for r in report.results:
        symbol = Text(_SEV_SYMBOL[r.severity], style=_SEV_STYLE[r.severity])
        table.add_row(symbol, r.name, r.message)

    console.print(table)
    console.print()
