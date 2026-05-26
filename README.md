# lascheck

**Quality-assurance CLI for LAS/LAZ LiDAR point clouds.**

`lascheck` is a fast, dependency-light command-line tool that runs a battery of
QC checks against `.las` / `.laz` files and prints a clear pass/warn/fail report.
It is designed to drop into batch PDAL pipelines and CI gates: results are also
emitted as JSON, and exit codes are scripting-friendly.

## Why

Point clouds frequently fail downstream — DTM/DSM generation, classification,
hydro-flattening, tile mosaics — for reasons that were *visible in the source
file all along*: missing CRS, header bbox out of sync with the actual points,
classification never populated, return numbers that violate the LAS spec.
`lascheck` catches those before the pipeline burns hours of compute.

## Install

```bash
pip install lascheck
```

Or from source:

```bash
git clone https://github.com/pythonlidar-com/lascheck
cd lascheck
pip install -e .
```

`lascheck` only requires Python 3.9+, `laspy[lazrs]`, `numpy`, and `rich`.
LAZ support is provided by `lazrs` (bundled). No GDAL, no PDAL, no native build
toolchain.

## Quick start

```bash
lascheck cloud.laz
```

Sample output:

```
cloud.laz  WARN
   Check                    Message
 ✓ file_opens               File opened successfully.
 ✓ version_supported        LAS version 1.4.
 ✓ point_format_valid       Point format 6.
 ! crs_present              No CRS VLR found. Downstream tools may misplace this point cloud.
 ✓ point_count_matches      Header point count matches records (5184320).
 ✓ bbox_consistent          Header bbox matches actual point extent.
 ✓ classification_coverage  87.3% of points are classified.
 ✓ point_density            ~12.45 pts/m² over 416400 m².
 ✓ return_integrity         All return numbers are within 1..num_returns.
 ✓ intensity_variance       Intensity has variance (mean=14823.1, σ=8104.6).
```

## What it checks

| Check                     | Severity on failure | What it means                                                          |
|---------------------------|---------------------|-------------------------------------------------------------------------|
| `file_opens`              | FAIL                | File is unreadable or corrupt.                                          |
| `version_supported`       | WARN                | LAS version is outside 1.0–1.4.                                         |
| `point_format_valid`      | FAIL                | Point format ID is not in the 0–10 range.                               |
| `crs_present`             | WARN                | No `LASF_Projection` WKT or GeoTIFF VLR is present.                     |
| `point_count_matches`     | FAIL                | Header point count disagrees with the number of point records.         |
| `bbox_consistent`         | WARN                | Header `min`/`max` does not match the actual XYZ extent.                |
| `classification_coverage` | WARN                | Too many points fall in ASPRS class 0 or 1.                             |
| `point_density`           | WARN (with `--min-density`) | Density (pts/m²) is below the supplied threshold.               |
| `return_integrity`        | FAIL                | A point has `return_number < 1` or `> number_of_returns`.               |
| `intensity_variance`      | WARN                | Intensity is constant across the file.                                  |

## CLI

```
lascheck FILE [FILE ...] [--json] [--strict] [--quick]
         [--min-density PTS_PER_M2]
         [--max-unclassified PCT]
         [--bbox-tolerance UNITS]
```

| Flag                  | Default | Notes                                                              |
|-----------------------|---------|---------------------------------------------------------------------|
| `--json`              | off     | Print structured JSON instead of the human-readable table.          |
| `--strict`            | off     | Treat warnings as failures for the process exit code.               |
| `--quick`             | off     | Skip per-point checks (header / VLR only).                          |
| `--min-density`       | —       | Warn if measured density falls below this value.                    |
| `--max-unclassified`  | 50      | Percent of class-0/1 points allowed before warning.                 |
| `--bbox-tolerance`    | 0.001   | Allowed bbox mismatch (in CRS units) between header and points.     |

### Exit codes

| Code | Meaning                                       |
|------|-----------------------------------------------|
| 0    | All checks INFO.                              |
| 1    | At least one WARN, no FAIL (without `--strict`). |
| 2    | At least one FAIL, or any WARN with `--strict`. |

### CI usage

```yaml
- name: QC LiDAR tile
  run: lascheck --strict --min-density 8 tiles/*.laz
```

### Programmatic use

```python
from pathlib import Path
from lascheck import run_checks
from lascheck.checks import CheckOptions, Severity

results = run_checks(Path("cloud.laz"), CheckOptions(min_density=8.0))
failed = [r for r in results if r.severity is Severity.FAIL]
```

## Development

```bash
pip install -e .[dev]
pytest
```

## Background reading

This tool was built alongside <https://www.pythonlidar.com>, which covers
PDAL pipeline design, ground filtering, DTM/DSM generation, batch automation
and point-cloud QC in more depth.

## License

MIT. See [LICENSE](LICENSE).
