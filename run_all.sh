#!/usr/bin/env bash
# Reproduce every run reported in the paper, then repeat each run and compare checksums.
# Usage: bash run_all.sh <python> <dataset_dir> <out_dir>   (dataset_dir holds the MGDS XTF files)
set -e
PY=${1:-python}; D=${2:-../SSS_Research_Code/dataset}; OUT=${3:-../runs}
export SOURCE_DATE_EPOCH=1792972800          # 2026-10-26T00:00:00Z: fixed metadata date for byte-identical reruns
declare -A XTF=( [NBP0505]="NBP050501A.XTF" [NBP1001]="SS01-snip-2030-to-2045.XTF" )   # MGDS file names
declare -A DOI=( [NBP0505]="https://doi.org/10.1594/IEDA/306159" [NBP1001]="https://doi.org/10.1594/IEDA/316265" )
$PY test_sss_pipeline.py
for ds in NBP0505 NBP1001; do
  for pass in run repeat; do
    dir="$OUT/$ds"; [ $pass = repeat ] && dir="$OUT/_repeat/$ds"
    rm -rf "$dir"
    $PY -u sss_pipeline.py --xtf "$D/${XTF[$ds]}" --dataset $ds --out "$dir" | grep -v "preview + "
  done
  lic=CC-BY-NC-SA-4.0
  $PY to_stac.py "$OUT/$ds" --license $lic ${DOI[$ds]:+--source-href ${DOI[$ds]}}
  $PY paper_numbers.py "$OUT/$ds"
done
$PY check_unsupported.py "$D/NBP050501A.XTF" "$OUT/unsupported"
$PY - "$OUT" <<'EOF'
import json, sys
out = sys.argv[1]
res = {}
for ds in ("NBP0505", "NBP1001"):
    a = json.load(open(f"{out}/{ds}/run_record.json")); b = json.load(open(f"{out}/_repeat/{ds}/run_record.json"))
    res[ds] = {"outputs_identical": a["outputs_sha256"] == b["outputs_sha256"],
               "products_identical": a["products_tree_sha256"] == b["products_tree_sha256"],
               "timings_run_s": a["timings_s"], "timings_repeat_s": b["timings_s"]}
json.dump(res, open(f"{out}/reproducibility.json", "w"), indent=2)
print(json.dumps(res, indent=2))
EOF
