"""QC checks against a LAS/LAZ file."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import laspy
import numpy as np


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: Severity
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "severity": self.severity.value,
            "message": self.message,
            "detail": self.detail,
        }


# ASPRS Standard LiDAR Point Classes (LAS 1.4, point formats 6-10).
# Codes 0-18 are reserved; 19-63 reserved for ASPRS; 64-255 user definable.
ASPRS_CLASS_NAMES: dict[int, str] = {
    0: "Created, never classified",
    1: "Unclassified",
    2: "Ground",
    3: "Low Vegetation",
    4: "Medium Vegetation",
    5: "High Vegetation",
    6: "Building",
    7: "Low Point (noise)",
    8: "Reserved",
    9: "Water",
    10: "Rail",
    11: "Road Surface",
    12: "Reserved",
    13: "Wire - Guard (Shield)",
    14: "Wire - Conductor (Phase)",
    15: "Transmission Tower",
    16: "Wire-Structure Connector",
    17: "Bridge Deck",
    18: "High Noise",
}


def classification_name(code: int) -> str:
    if code in ASPRS_CLASS_NAMES:
        return ASPRS_CLASS_NAMES[code]
    if 19 <= code <= 63:
        return f"ASPRS Reserved ({code})"
    return f"User Defined ({code})"


@dataclass
class CheckOptions:
    quick: bool = False
    min_density: float | None = None
    max_unclassified_pct: float = 50.0
    bbox_tolerance_m: float = 1e-3


def _has_crs(header: laspy.LasHeader) -> tuple[bool, str | None]:
    """Detect whether the LAS file declares a CRS via WKT or GeoTIFF VLRs."""
    for vlr in header.vlrs:
        user_id = getattr(vlr, "user_id", "")
        record_id = getattr(vlr, "record_id", None)
        if user_id == "LASF_Projection" and record_id in (2111, 2112):
            return True, "WKT"
        if user_id == "LASF_Projection" and record_id == 34735:
            return True, "GeoTIFF"
    return False, None


def _check_file_opens(path: Path) -> tuple[CheckResult, laspy.LasReader | None]:
    try:
        reader = laspy.open(str(path))
    except Exception as exc:
        return (
            CheckResult(
                "file_opens",
                Severity.FAIL,
                f"Could not open file: {exc}",
                {"error": str(exc)},
            ),
            None,
        )
    return (
        CheckResult("file_opens", Severity.INFO, "File opened successfully."),
        reader,
    )


def _check_header(header: laspy.LasHeader) -> list[CheckResult]:
    results: list[CheckResult] = []

    version = f"{header.version.major}.{header.version.minor}"
    if header.version.major == 1 and 0 <= header.version.minor <= 4:
        results.append(
            CheckResult(
                "version_supported",
                Severity.INFO,
                f"LAS version {version}.",
                {"version": version},
            )
        )
    else:
        results.append(
            CheckResult(
                "version_supported",
                Severity.WARN,
                f"Unusual LAS version {version}.",
                {"version": version},
            )
        )

    pf = header.point_format.id
    if 0 <= pf <= 10:
        results.append(
            CheckResult(
                "point_format_valid",
                Severity.INFO,
                f"Point format {pf}.",
                {"point_format": pf},
            )
        )
    else:
        results.append(
            CheckResult(
                "point_format_valid",
                Severity.FAIL,
                f"Unknown point format {pf}.",
                {"point_format": pf},
            )
        )

    has_crs, crs_kind = _has_crs(header)
    if has_crs:
        results.append(
            CheckResult(
                "crs_present",
                Severity.INFO,
                f"CRS declared ({crs_kind}).",
                {"kind": crs_kind},
            )
        )
    else:
        results.append(
            CheckResult(
                "crs_present",
                Severity.WARN,
                "No CRS VLR found. Downstream tools may misplace this point cloud.",
            )
        )

    return results


def _check_points(header: laspy.LasHeader, reader: laspy.LasReader, opts: CheckOptions) -> list[CheckResult]:
    results: list[CheckResult] = []

    declared_count = header.point_count
    actual_count = 0

    x_min = y_min = z_min = math.inf
    x_max = y_max = z_max = -math.inf

    class_counts: dict[int, int] = {}
    bad_returns = 0
    intensity_sum = 0.0
    intensity_sumsq = 0.0
    intensity_n = 0

    for chunk in reader.chunk_iterator(1_000_000):
        n = len(chunk)
        if n == 0:
            continue
        actual_count += n

        x = chunk.x
        y = chunk.y
        z = chunk.z

        x_min = min(x_min, float(np.min(x)))
        y_min = min(y_min, float(np.min(y)))
        z_min = min(z_min, float(np.min(z)))
        x_max = max(x_max, float(np.max(x)))
        y_max = max(y_max, float(np.max(y)))
        z_max = max(z_max, float(np.max(z)))

        classes = np.asarray(chunk.classification)
        uniq, counts = np.unique(classes, return_counts=True)
        for c, k in zip(uniq.tolist(), counts.tolist()):
            class_counts[int(c)] = class_counts.get(int(c), 0) + int(k)

        rn = np.asarray(chunk.return_number)
        nr = np.asarray(chunk.number_of_returns)
        bad_returns += int(np.count_nonzero((rn < 1) | (rn > np.maximum(nr, 1))))

        intensity = np.asarray(chunk.intensity, dtype=np.float64)
        intensity_sum += float(intensity.sum())
        intensity_sumsq += float((intensity * intensity).sum())
        intensity_n += int(intensity.size)

    if declared_count == actual_count:
        results.append(
            CheckResult(
                "point_count_matches",
                Severity.INFO,
                f"Header point count matches records ({actual_count}).",
                {"declared": declared_count, "actual": actual_count},
            )
        )
    else:
        results.append(
            CheckResult(
                "point_count_matches",
                Severity.FAIL,
                f"Header declares {declared_count} points but file has {actual_count}.",
                {"declared": declared_count, "actual": actual_count},
            )
        )

    if actual_count == 0:
        results.append(
            CheckResult(
                "non_empty",
                Severity.FAIL,
                "File contains zero point records.",
            )
        )
        return results

    tol = opts.bbox_tolerance_m
    header_min = (float(header.mins[0]), float(header.mins[1]), float(header.mins[2]))
    header_max = (float(header.maxs[0]), float(header.maxs[1]), float(header.maxs[2]))
    actual_min = (x_min, y_min, z_min)
    actual_max = (x_max, y_max, z_max)
    bbox_ok = all(abs(a - b) <= tol for a, b in zip(header_min, actual_min)) and all(
        abs(a - b) <= tol for a, b in zip(header_max, actual_max)
    )
    if bbox_ok:
        results.append(
            CheckResult(
                "bbox_consistent",
                Severity.INFO,
                "Header bbox matches actual point extent.",
                {"min": list(actual_min), "max": list(actual_max)},
            )
        )
    else:
        results.append(
            CheckResult(
                "bbox_consistent",
                Severity.WARN,
                "Header bbox disagrees with actual extent.",
                {
                    "header_min": list(header_min),
                    "header_max": list(header_max),
                    "actual_min": list(actual_min),
                    "actual_max": list(actual_max),
                    "tolerance_m": tol,
                },
            )
        )

    unclassified = class_counts.get(0, 0) + class_counts.get(1, 0)
    pct_unclassified = 100.0 * unclassified / actual_count
    classification_breakdown = {
        int(c): {
            "name": classification_name(int(c)),
            "count": int(k),
            "pct": round(100.0 * k / actual_count, 3),
        }
        for c, k in sorted(class_counts.items())
    }
    if pct_unclassified <= opts.max_unclassified_pct:
        results.append(
            CheckResult(
                "classification_coverage",
                Severity.INFO,
                f"{100 - pct_unclassified:.1f}% of points are classified.",
                {
                    "pct_unclassified": round(pct_unclassified, 3),
                    "threshold_pct": opts.max_unclassified_pct,
                    "breakdown": classification_breakdown,
                },
            )
        )
    else:
        results.append(
            CheckResult(
                "classification_coverage",
                Severity.WARN,
                f"{pct_unclassified:.1f}% of points are unclassified (codes 0/1).",
                {
                    "pct_unclassified": round(pct_unclassified, 3),
                    "threshold_pct": opts.max_unclassified_pct,
                    "breakdown": classification_breakdown,
                },
            )
        )

    area = max((x_max - x_min) * (y_max - y_min), 1e-9)
    density = actual_count / area
    density_severity = Severity.INFO
    density_msg = f"~{density:.2f} pts/m² over {area:.0f} m²."
    if opts.min_density is not None and density < opts.min_density:
        density_severity = Severity.WARN
        density_msg = f"Density {density:.2f} pts/m² below threshold {opts.min_density}."
    results.append(
        CheckResult(
            "point_density",
            density_severity,
            density_msg,
            {
                "density_pts_per_m2": round(density, 4),
                "area_m2": round(area, 3),
                "min_density": opts.min_density,
            },
        )
    )

    if bad_returns == 0:
        results.append(
            CheckResult(
                "return_integrity",
                Severity.INFO,
                "All return numbers are within 1..num_returns.",
            )
        )
    else:
        results.append(
            CheckResult(
                "return_integrity",
                Severity.FAIL,
                f"{bad_returns} points have invalid return numbers.",
                {"bad_returns": bad_returns},
            )
        )

    if intensity_n > 0:
        mean = intensity_sum / intensity_n
        var = max(intensity_sumsq / intensity_n - mean * mean, 0.0)
        std = math.sqrt(var)
        if std < 1e-6:
            results.append(
                CheckResult(
                    "intensity_variance",
                    Severity.WARN,
                    "Intensity is constant across all points.",
                    {"mean": round(mean, 3), "stddev": round(std, 6)},
                )
            )
        else:
            results.append(
                CheckResult(
                    "intensity_variance",
                    Severity.INFO,
                    f"Intensity has variance (mean={mean:.1f}, σ={std:.1f}).",
                    {"mean": round(mean, 3), "stddev": round(std, 3)},
                )
            )

    return results


def run_checks(path: Path, opts: CheckOptions | None = None) -> list[CheckResult]:
    """Run all checks against a single LAS/LAZ file."""
    opts = opts or CheckOptions()

    open_result, reader = _check_file_opens(path)
    if reader is None:
        return [open_result]

    try:
        results: list[CheckResult] = [open_result]
        results.extend(_check_header(reader.header))
        if not opts.quick:
            results.extend(_check_points(reader.header, reader, opts))
        return results
    finally:
        reader.close()
