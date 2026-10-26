"""Collect the numbers and figures the paper reports from finished runs (no reprocessing).
Usage: python paper_numbers.py ../runs/NBP0505 [../runs/NBP1001 ...]  -> <run>/paper_numbers.json, fig_*.png"""
import json
import os
import sys

import numpy as np
import pandas as pd
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

import sss_pipeline as sp

SENSITIVITY = [("Baseline", {}), ("Shorter segments", {"target_length_m": 50.0}),
               ("Longer segments", {"target_length_m": 100.0}), ("Stricter time gap", {"time_gap_s": 5.0}),
               ("Looser time gap", {"time_gap_s": 20.0}), ("Stricter jump", {"jump_m": 15.0}),
               ("Looser jump", {"jump_m": 60.0})]


def xml_paths(path):
    root = etree.parse(path).getroot()
    out = set()
    for e in root.iter():
        if isinstance(e.tag, str):
            parts = []
            while e is not None:
                parts.append(etree.QName(e).localname)
                e = e.getparent()
            out.add("/".join(reversed(parts)))
    return out


def sensitivity(df, base):
    t = (pd.to_datetime(df.timestamp) - pd.to_datetime(df.timestamp.iloc[0])).dt.total_seconds().to_numpy()
    x, y = df.utm_x.to_numpy(), df.utm_y.to_numpy()
    rows = []
    for label, change in SENSITIVITY:
        p = {**base, **change}
        segs = sp.segment(t, x, y, p)
        lens = [float(np.hypot(np.diff(x[a:b + 1]), np.diff(y[a:b + 1])).sum()) for a, b in segs]
        n = [b - a + 1 for a, b in segs]
        rows.append({"setting": label, "target_length_m": p["target_length_m"], "time_gap_s": p["time_gap_s"],
                     "jump_m": p["jump_m"], "segments": len(segs), "mean_length_m": np.mean(lens),
                     "median_length_m": np.median(lens), "mean_pings": np.mean(n), "min_pings": min(n),
                     "max_pings": max(n)})
    return rows


def lineage(run, df, index, prev_man, mos_man):
    segs = sp.segments_of(index)
    ids = {f["id"] for f in segs}
    raw_ok = sum(os.path.exists(os.path.join(run, r)) for r in df.raw_array_path)
    by_variant = {}
    for m in mos_man:
        by_variant.setdefault(m["product"], []).append(m)
    return {"features": len(index["features"]), "segments": len(segs),
            "preview_entries": len(prev_man), "preview_match": sum(m["segment_id"] in ids and
                                                                  os.path.exists(os.path.join(run, m["file"])) for m in prev_man),
            "variants": {k: [len(v), sum(m["segment_id"] in ids and os.path.exists(os.path.join(run, m["file"]))
                                       and os.path.exists(os.path.join(run, m["grid"])) for m in v)]
                         for k, v in by_variant.items()},
            "raw_links": [len(df), int(raw_ok)],
            "segment_ping_coverage": int(sum(f["properties"]["n_pings"] for f in segs))}


def montage(run, seg_ids, variants, path, h=260):
    """Rows = segments, columns = variants; label each column."""
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    tiles = []
    for sid in seg_ids:
        row = []
        for v in variants:
            f = os.path.join(run, "previews" if v == "preview" else os.path.join("mosaics", v), sid + ".png")
            im = Image.open(f).convert("RGBA")
            im = Image.alpha_composite(Image.new("RGBA", im.size, "white"), im).convert("RGB")
            if v != "preview":
                im = im.transpose(Image.ROTATE_90)          # along-track horizontal -> vertical, like the preview
            row.append(im.resize((max(1, int(im.width * h / im.height)), h)))
        tiles.append(row)
    colw = [max(r[c].width for r in tiles) for c in range(len(variants))]
    W, H = sum(colw) + 10 * (len(colw) + 1) + 140, len(tiles) * (h + 10) + 34
    out = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(out)
    x = 140
    for c, v in enumerate(variants):
        d.text((x + colw[c] // 2 - 6 * len(v), 2), v, fill="black", font=font)
        x += colw[c] + 10
    for r, row in enumerate(tiles):
        y = 34 + r * (h + 10)
        d.text((5, y + h // 2), seg_ids[r], fill="black", font=font)
        x = 140
        for c, im in enumerate(row):
            out.paste(im, (x, y)); x += colw[c] + 10
    out.save(path)


def main(run):
    df = pd.read_csv(os.path.join(run, "pings.csv"))
    index = json.load(open(os.path.join(run, "sss_index.geojson"), encoding="utf-8"))
    prev_man = json.load(open(os.path.join(run, "segment_preview_manifest.json"), encoding="utf-8"))
    mos_man = json.load(open(os.path.join(run, "segment_mosaic_manifest.json"), encoding="utf-8"))
    rec = json.load(open(os.path.join(run, "run_record.json"), encoding="utf-8"))
    summ = pd.read_csv(os.path.join(run, "metrics_summary.csv"))
    segs = sp.segments_of(index)
    base = rec["config"]["segment"]
    out = {"pings": len(df), "segments": len(segs), "ingestion": rec["ingestion"], "parse": rec["parse"],
           "time_start": str(df.timestamp.min()), "time_end": str(df.timestamp.max()),
           "lat_range": [df.lat.min(), df.lat.max()], "lon_range": [df.lon.min(), df.lon.max()],
           "depth_range": [df.depth.min(), df.depth.max()],
           "altitude_recorded": int((df.altitude > 0).sum()),
           "slant_range_port": sorted(set(df.slant_range_port.round(1))),
           "track_length_m": float(np.hypot(np.diff(df.utm_x), np.diff(df.utm_y)).sum()),
           "sensitivity": sensitivity(df, base), "lineage": lineage(run, df, index, prev_man, mos_man),
           "metrics": summ.to_dict(orient="records"),
           "xml_paths": {f: len(xml_paths(os.path.join(run, "metadata", f)))
                         for f in ("dataset_mgds.xml", "sss_extended.xml")},
           "stitch_geometry": mos_man[0]["params"] if mos_man else None,
           "segment_examples": {}}
    pick = [f["id"] for f in segs]
    ex = [pick[0], pick[len(pick) // 2], pick[-1]] if len(pick) >= 3 else pick
    for sid in ex:
        p = next(f for f in segs if f["id"] == sid)["properties"]
        out["segment_examples"][sid] = {k: p[k] for k in ("ping_start", "ping_end", "n_pings", "time_start",
                                                          "time_end", "length_m")}
    montage(run, ex, ["preview", "rms_flat"], os.path.join(run, "fig_cmp_preview_rmsflat.png"))
    montage(run, ex, ["rms_none", "rms_flat"], os.path.join(run, "fig_cmp_slant.png"))
    montage(run, ex, ["rms_flat", "mean_flat", "max_flat", "distance_flat"], os.path.join(run, "fig_cmp_fusion.png"))
    with open(os.path.join(run, "paper_numbers.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(json.dumps({k: out[k] for k in ("pings", "segments", "lineage", "xml_paths")}, default=str))


if __name__ == "__main__":
    for r in sys.argv[1:]:
        main(r)
