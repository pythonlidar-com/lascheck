"""Tests for lascheck. Uses laspy to synthesize tiny LAS files."""

from __future__ import annotations

from pathlib import Path

import laspy
import numpy as np
import pytest

from lascheck import Severity, run_checks
from lascheck.checks import CheckOptions, _has_crs, classification_name


def _make_las(
    path: Path,
    n: int = 1000,
    classified: bool = True,
    bbox_correct: bool = True,
    add_crs: bool = True,
) -> None:
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = [0.001, 0.001, 0.001]
    header.offsets = [0.0, 0.0, 0.0]

    if add_crs:
        wkt = (
            'PROJCS["NAD83 / UTM zone 18N",GEOGCS["NAD83",'
            'DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
            'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",-75],PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],'
            'UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
        )
        header.vlrs.append(laspy.vlrs.known.WktCoordinateSystemVlr(wkt))

    las = laspy.LasData(header=header)
    rng = np.random.default_rng(42)
    las.x = rng.uniform(0.0, 100.0, n)
    las.y = rng.uniform(0.0, 100.0, n)
    las.z = rng.uniform(0.0, 50.0, n)
    las.intensity = rng.integers(0, 65535, n, dtype=np.uint16)
    las.return_number = np.ones(n, dtype=np.uint8)
    las.number_of_returns = np.ones(n, dtype=np.uint8)
    las.classification = (
        np.full(n, 2, dtype=np.uint8) if classified else np.zeros(n, dtype=np.uint8)
    )

    las.write(str(path))

    if not bbox_correct:
        # Re-open and corrupt the header bbox to test detection.
        with laspy.open(str(path), mode="r+") as f:
            f.header.maxs = [9999.0, 9999.0, 9999.0]


def _by_name(results, name) -> object:
    for r in results:
        if r.name == name:
            return r
    raise AssertionError(f"no result named {name!r}")


@pytest.fixture
def good_las(tmp_path: Path) -> Path:
    p = tmp_path / "good.las"
    _make_las(p)
    return p


def test_classification_name_known():
    assert classification_name(2) == "Ground"
    assert classification_name(6) == "Building"


def test_classification_name_reserved_range():
    assert "Reserved" in classification_name(30)


def test_classification_name_user_defined():
    assert "User Defined" in classification_name(200)


def test_good_file_passes(good_las: Path):
    results = run_checks(good_las)
    assert _by_name(results, "file_opens").severity is Severity.INFO
    assert _by_name(results, "crs_present").severity is Severity.INFO
    assert _by_name(results, "point_count_matches").severity is Severity.INFO
    assert _by_name(results, "classification_coverage").severity is Severity.INFO
    assert _by_name(results, "return_integrity").severity is Severity.INFO


def test_missing_crs_warns(tmp_path: Path):
    p = tmp_path / "nocrs.las"
    _make_las(p, add_crs=False)
    results = run_checks(p)
    assert _by_name(results, "crs_present").severity is Severity.WARN


def test_unclassified_warns(tmp_path: Path):
    p = tmp_path / "unc.las"
    _make_las(p, classified=False)
    results = run_checks(p, CheckOptions(max_unclassified_pct=10.0))
    cov = _by_name(results, "classification_coverage")
    assert cov.severity is Severity.WARN
    assert cov.detail["pct_unclassified"] > 90.0


def test_quick_mode_skips_point_checks(good_las: Path):
    results = run_checks(good_las, CheckOptions(quick=True))
    names = {r.name for r in results}
    assert "point_count_matches" not in names
    assert "crs_present" in names


def test_missing_file_fails(tmp_path: Path):
    p = tmp_path / "does-not-exist.las"
    results = run_checks(p)
    assert results[0].severity is Severity.FAIL
    assert results[0].name == "file_opens"


def test_min_density_threshold(good_las: Path):
    # ~1000 pts over 100x100 area = 0.1 pts/m². Set threshold above that.
    results = run_checks(good_las, CheckOptions(min_density=10.0))
    assert _by_name(results, "point_density").severity is Severity.WARN


def test_has_crs_helper(good_las: Path):
    import laspy as _laspy

    with _laspy.open(str(good_las)) as f:
        ok, kind = _has_crs(f.header)
    assert ok
    assert kind == "WKT"
