# sss_pipeline

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23657574.svg)](https://doi.org/10.5281/zenodo.23657574)

A reference implementation of a **provenance-linked, segment-indexed data model for side-scan sonar (SSS) data**, accompanying the paper:

> P. Chaisiriprasert, N. Natthakunlanan, and K. Yongsiriwit, "A Provenance-Linked, Segment-Indexed Data Model for Analysis-Ready Side-Scan Sonar Data," *IEEE Access* (submitted).

The pipeline reads raw XTF files and produces:
- an ingestion record;
- a ping table with raw channel arrays;
- ISO 19115/19139 dataset metadata and an SSS companion metadata record;
- an acquisition-aware segment index (GeoJSON);
- preview strips, and locally stitched products under two slant-range modes and four fusion rules;
- descriptive metrics;
- an interactive map viewer with a side panel (run summary, legend, image-mode and mosaic-variant buttons) and line-only, preview-strip and stitched-mosaic display modes.

Every product is linked back to its segment, its pings, their raw arrays, and the SHA-256 of the source file.

## Repository contents

| Path | Content |
|---|---|
| `sss_pipeline.py` | The pipeline (8 stages: preflight, parse, metadata, segment, preview, stitch, metrics, viewer) |
| `test_sss_pipeline.py` | Self-checks for segmentation (Algorithm 1), coordinates, ground range (Eq. 1), fusion rules, metrics (Eqs. 2–9), gap filling, nadir detection and header repair |
| `datasets.json` | Dataset descriptions used for the metadata records (NBP0505, NBP1001) |
| `run_all.sh` | Reproduces every public run twice (fixed `SOURCE_DATE_EPOCH`), exports and validates STAC, runs the damaged-file checks, and compares checksums |
| `to_stac.py` | Exports a run as a STAC 1.1.0 Collection (one Item per segment) and validates it |
| `check_unsupported.py` | Builds damaged copies of a valid XTF file and confirms the preflight check classifies them as *unsupported* |
| `paper_numbers.py` | Collects the numbers reported in the paper from a finished run (`paper_numbers.json`) and builds the comparison figures |
| `viewer_shots.py` | Headless-Chrome screenshots of the viewer and the 2 x 2 display-mode figure (`python viewer_shots.py ../runs/NBP0505 seg_000014 seg_000043,...,seg_000053`) |
| `figures/` | Scripts that draw Figs. 1, 2, 3 and 6 of the paper |
| `results/NBP0505`, `results/NBP1001` | Run records, ingestion records, segment index, manifests, metadata records, metrics and `paper_numbers.json` from the runs reported in the paper |
| `results/<dataset>/stac/` | Validated STAC catalog of each run |
| `results/reproducibility.json`, `results/unsupported_cases.json` | Rerun comparison and damaged-file preflight results |
| `results/fuji/` | F-UJI 4.0.1 (metrics v0.5) reports for the two MGDS source records |

Large regenerable outputs (raw arrays, stitched rasters, preview images, viewer HTML and its map overlays in `viewer/`) are not stored here. Rerun the pipeline to regenerate them; `run_record.json` holds the SHA-256 checksums of the main outputs for comparison.

## Installation

Python 3.11 with the pinned versions in `requirements.txt` (or `environment.yml` for conda):

```bash
pip install -r requirements.txt
```

`viewer_shots.py` also needs Google Chrome; the figure scripts need matplotlib.

## Reproducing the paper's runs

1. Download the source XTF files from the Marine Geoscience Data System (MGDS):

   | Dataset | DOI | File |
   |---|---|---|
   | NBP0505 (primary) | 10.1594/IEDA/306159 | `NBP050501A.XTF` |
   | NBP1001 | 10.1594/IEDA/316265 | `SS01-snip-2030-to-2045.XTF` |

2. Run everything (self-checks, both data sets twice, STAC export and validation, damaged-file checks):

```bash
bash run_all.sh python <folder with the XTF files> runs
```

or step by step:

```bash
python test_sss_pipeline.py
python sss_pipeline.py --xtf NBP050501A.XTF --dataset NBP0505 --out runs/NBP0505
python to_stac.py runs/NBP0505 --source-href https://doi.org/10.1594/IEDA/306159
python paper_numbers.py runs/NBP0505
```

3. With `SOURCE_DATE_EPOCH=1792972800` (as in `run_all.sh`), `outputs_sha256` and `products_tree_sha256` in `runs/<dataset>/run_record.json` should match `results/<dataset>/run_record.json` byte for byte (same library versions). The viewer HTML is excluded, because Folium assigns random element identifiers.

Expected values:
- **NBP0505:** 17,104 pings, 78 segments, ingestion class *standard*.
- **NBP1001:** 9,520 pings, 17 segments, ingestion class *repaired* (5 sonar channels declared, 4 exposed).

## Data availability

- **NBP0505 and NBP1001 source data:** publicly available from MGDS under CC BY-NC-SA 3.0 (DOIs above). The source XTF files are not redistributed here.
- **Chonburi survey (2024, self-collected, OTech 1502):** used in the paper as a second standard-pass dataset. The raw XTF data and its derived outputs are **available from the corresponding author on reasonable request** and are not included in this repository.

## Licences

- **Code** (`*.py`, `figures/*.py`): MIT License, see `LICENSE`.
- **Results** (`results/`): derived from MGDS data licensed CC BY-NC-SA 3.0, so they are released under **CC BY-NC-SA 4.0** (see `LICENSE-DATA`). Cite the original data sets and MGDS when reusing them.

## Citation

See `CITATION.cff`. When using the results, also cite the MGDS data sets:
- J. Anderson *et al.*, NBP0505 sidescan sonar data, MGDS, doi:10.1594/IEDA/306159.
- E. Domack, NBP1001 sidescan sonar data, MGDS, doi:10.1594/IEDA/316265.
