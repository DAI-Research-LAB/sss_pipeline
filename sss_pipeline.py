"""Provenance-linked, segment-indexed side-scan sonar pipeline (reference implementation).

Stages (paper Section IV):
  1 preflight   XTF header check -> ingestion record (standard / repaired / unsupported)
  2 parse       pings.csv + raw_arrays/*.npy (positions taken from the header's NavUnits correctly)
  3 metadata    dataset_mgds.xml (ISO 19139) + sss_extended.xml (SSS companion record)
  4 segment     sss_index.geojson (Algorithm 1: length / time gap / jump / stall / max size)
  5 preview     previews/*.png + segment_preview_manifest.json
  6 stitch      mosaics/<variant>/*.png|.npy + segment_mosaic_manifest.json (slant none|flat x fusion)
  7 metrics     metrics_per_segment.csv + metrics_summary.csv (Eqs. 2-8 and seam proxy)
  8 viewer      sss_index_viewer.html (manifests checked against files before writing)
  run_record.json: config, library versions, input checksum, output checksums.

Usage:
  python sss_pipeline.py --xtf dataset/NBP050501A.XTF --dataset NBP0505 --out out/NBP0505
  python sss_pipeline.py --xtf ... --dataset ... --out ... --max-pings 2000   # quick smoke run
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import time
from importlib.metadata import version

import numpy as np
import pandas as pd
from lxml import etree
from PIL import Image
from pyproj import Transformer
from pyxtf import XTFHeaderType
from pyxtf.xtf_io import xtf_read_gen

PIPELINE_VERSION = "1.1.0"

# Parameters reported in the paper (Sections IV-C, IV-D). Override with --config <json>.
CONFIG = {
    "segment": {"target_length_m": 75.0, "time_gap_s": 10.0, "jump_m": 30.0,
                "stall_eps_m": 0.02, "stall_max_run": 400, "max_pings": 2000, "decimate_m": 2.0},
    "preview": {"width": 400, "height": 600},
    "stitch": {"pixel_m": 0.25, "fallback_range_m": 75.0, "sample_stride": 2,
               "target_max_pings": 180, "max_raster": 9000},
    "variants": [("rms_flat", "flat", "rms"), ("rms_none", "none", "rms"), ("mean_flat", "flat", "mean"),
                 ("distance_flat", "flat", "distance"), ("max_flat", "flat", "max")],
}

NAV_METRES, NAV_LATLON = 0, 3      # XTFFileHeader.NavUnits codes (pyxtf XTFNavUnits)
PORT, STBD = 1, 2                  # XTFChanInfo.TypeOfChannel codes


# ----------------------------------------------------------------------------- helpers
def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)


def now_utc():
    """Current UTC time, or SOURCE_DATE_EPOCH if set (reproducible-builds convention) so reruns are byte-identical."""
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    t = dt.datetime.fromtimestamp(int(epoch), dt.timezone.utc) if epoch else dt.datetime.now(dt.timezone.utc)
    return t.isoformat(timespec="seconds")


def normalize_u8(a, valid=None):
    """p2-p98 stretch to uint8 (display only)."""
    v = a[valid] if valid is not None else a.ravel()
    if v.size == 0:
        return np.zeros(a.shape, np.uint8)
    lo, hi = np.percentile(v, [2, 98])
    hi = hi if hi > lo else lo + 1
    return (np.clip((a - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)


# ----------------------------------------------------------------------------- 1 preflight
def pad_sonar_info(fh, n):
    """Parser-side repair: append in-memory copies of the last channel-info entry until n entries exist.
    The source file is never modified."""
    added = 0
    while len(fh.sonar_info) < n:
        fh.sonar_info.append(copy.copy(fh.sonar_info[-1]))
        added += 1
    return added


def open_xtf(path, repair_to=None):
    """Return (file_header, sonar-packet generator); applies the recorded repair if requested."""
    gen = xtf_read_gen(path, types=[XTFHeaderType.sonar])
    fh = next(gen)
    if repair_to:
        pad_sonar_info(fh, repair_to)
    return fh, gen


def preflight(path):
    fh, gen = open_xtf(path)
    declared, exposed = int(fh.NumberOfSonarChannels), len(fh.sonar_info)
    rec = {"source_file": os.path.basename(path), "source_bytes": os.path.getsize(path),
           "source_sha256": sha256(path), "nav_units": int(fh.NavUnits),
           "sonar_name": bytes(fh.SonarName).split(b"\0")[0].decode(errors="replace"),
           "declared_sonar_channels": declared, "exposed_sonar_info": exposed,
           "class": "unsupported", "repair": None, "source_modified": False, "checked_utc": now_utc()}
    if fh.NavUnits not in (NAV_METRES, NAV_LATLON):
        rec["reason"] = f"unknown NavUnits {fh.NavUnits}"
        return rec
    try:
        next(gen)
        rec["class"] = "standard" if declared == exposed else "unsupported"
        if declared != exposed:
            rec["reason"] = "declared/exposed channel mismatch although first packet decoded"
        return rec
    except StopIteration:
        rec["reason"] = "no sonar packets"
        return rec
    except (IndexError, RuntimeError) as e:
        first_error = f"{type(e).__name__}: {e}"
    if 0 < exposed < declared:                         # the recoverable pattern (e.g. NBP1001: 5 declared, 4 exposed)
        fh, gen = open_xtf(path, repair_to=declared)
        try:
            next(gen)
            rec["class"] = "repaired"
            rec["repair"] = {"action": "append in-memory copy of last sonar_info entry",
                             "entries_added": declared - exposed, "first_packet_error": first_error}
            return rec
        except Exception as e:                         # noqa: BLE001 - any failure means unsupported
            rec["reason"] = f"repair failed: {type(e).__name__}: {e}"
            return rec
    rec["reason"] = first_error
    return rec


# ----------------------------------------------------------------------------- 2 parse
def utm_transformer(lat, lon):
    zone = int((lon + 180) // 6) + 1
    epsg = (32700 if lat < 0 else 32600) + zone
    return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True), epsg


def to_latlon(x, y, nav_units):
    """NavUnits is a code, not a scale: 3 -> SensorX/Y are lon/lat degrees; 0 -> projected metres."""
    if nav_units == NAV_LATLON:
        return y, x
    raise ValueError("NavUnits=0 (projected metres) needs a source CRS; pass lat/lon conversion explicitly")


def nadir_at_start(profile):
    """The water column (lowest mean intensity) lies next to nadir; the end samples alone are unreliable because a
    bright nadir echo or attenuated far range can sit there. NBP0505 and OTech files: port far-first, stbd nadir-first."""
    smooth = np.convolve(profile, np.ones(5) / 5, mode="same")[2:-2]
    return bool(np.argmin(smooth) + 2 < len(profile) / 2)


def pick_pair(fh):
    """Port/starboard pair at the lowest frequency (NBP0505: 120 kHz, as in the paper)."""
    port = [(c.Frequency, i) for i, c in enumerate(fh.sonar_info) if c.TypeOfChannel == PORT]
    stbd = [(c.Frequency, i) for i, c in enumerate(fh.sonar_info) if c.TypeOfChannel == STBD]
    if not port or not stbd:
        raise ValueError("no port/starboard sonar channels")
    (fp, ip), (fs, is_) = min(port), min(stbd)
    return {"port": ip, "stbd": is_, "freq_khz": [float(fp), float(fs)]}


def parse(path, out, ingest, max_pings=None):
    repair_to = ingest["declared_sonar_channels"] if ingest["class"] == "repaired" else None
    fh, gen = open_xtf(path, repair_to)
    pair = pick_pair(fh)
    raw_dir = os.path.join(out, "raw_arrays")
    os.makedirs(raw_dir, exist_ok=True)
    rows, tf, epsg = [], None, None
    profile = {"port": np.zeros(100), "stbd": np.zeros(100)}   # mean intensity profile, 100 range bins, first 500 pings
    for i, p in enumerate(gen):
        if max_pings and i >= max_pings:
            break
        lat, lon = to_latlon(p.SensorXcoordinate, p.SensorYcoordinate, fh.NavUnits)
        if tf is None:
            tf, epsg = utm_transformer(lat, lon)
        ux, uy = tf.transform(lon, lat)
        raw_path = f"raw_arrays/ping_{i:06d}.npy"
        np.save(os.path.join(out, raw_path), np.array(p.data, dtype=object), allow_pickle=True)
        row = {"ping_id": i,
               "timestamp": dt.datetime(p.Year, p.Month, p.Day, p.Hour, p.Minute, p.Second, p.HSeconds * 10000),
               "sensor_x": p.SensorXcoordinate, "sensor_y": p.SensorYcoordinate, "lat": lat, "lon": lon,
               "utm_x": ux, "utm_y": uy, "depth": p.SensorDepth, "altitude": p.SensorPrimaryAltitude,
               "heading": p.SensorHeading, "pitch": p.SensorPitch, "roll": p.SensorRoll, "speed": p.ShipSpeed,
               "slant_range_port": p.ping_chan_headers[pair["port"]].SlantRange,
               "slant_range_stbd": p.ping_chan_headers[pair["stbd"]].SlantRange,
               "raw_array_path": raw_path}
        if i < 500:
            for side in ("port", "stbd"):
                v = np.asarray(p.data[pair[side]], float)
                profile[side] += [b.mean() for b in np.array_split(v, 100)]
        for c, a in enumerate(p.data):
            a = np.asarray(a, dtype=float)
            row.update({f"max_ch{c}": a.max(), f"mean_ch{c}": a.mean(), f"std_ch{c}": a.std(), f"samples_ch{c}": a.size})
        rows.append(row)
    df = pd.DataFrame(rows)
    alt = df.altitude.where(df.altitude > 0)
    df["height_used"] = alt.interpolate(limit_direction="both") if alt.notna().any() else df.depth
    df.to_csv(os.path.join(out, "pings.csv"), index=False)
    nadir_first = {side: nadir_at_start(prof) for side, prof in profile.items()}
    return df, {"utm_epsg": epsg, "channel_pair": {**pair, "nadir_first": nadir_first}, "nav_units": int(fh.NavUnits),
                "flat_bottom_height": "altitude above seabed, linearly interpolated where not recorded",
                "altitude_interpolated_pings": int(alt.isna().sum())}


# ----------------------------------------------------------------------------- 3 metadata
NS = {"gmd": "http://www.isotc211.org/2005/gmd", "gco": "http://www.isotc211.org/2005/gco",
      "gml": "http://www.opengis.net/gml", "sss": "https://example.org/sss"}   # replace sss URI with your schema URL
CL = "http://www.isotc211.org/2005/resources/codeList.xml#"


def X(q, text=None, **attrib):
    p, t = q.split(":")
    e = etree.Element(f"{{{NS[p]}}}{t}", attrib=attrib)
    if text is not None:
        e.text = str(text)
    return e


def S(parent, q, text=None, **attrib):
    e = X(q, text, **attrib)
    parent.append(e)
    return e


def cs(parent, q, text):
    S(S(parent, q), "gco:CharacterString", text)


def build_dataset_xml(df, ds):
    """ISO 19139 dataset record (structure of SSS_Research_Code/code/2mgds_builder.py, parameterized)."""
    root = etree.Element(f"{{{NS['gmd']}}}MD_Metadata", nsmap={k: NS[k] for k in ("gmd", "gco", "gml")})
    t0, t1 = df.timestamp.min(), df.timestamp.max()
    file_id = f"{ds['cruise_id']}_SSS_{t0:%Y-%m-%d}_{t1:%Y-%m-%d}"
    cs(root, "gmd:fileIdentifier", file_id)
    S(S(root, "gmd:language"), "gmd:LanguageCode", "eng", codeList="http://www.loc.gov/standards/iso639-2/")
    S(S(root, "gmd:characterSet"), "gmd:MD_CharacterSetCode", "utf8", codeList=CL + "MD_CharacterSetCode")
    S(S(root, "gmd:hierarchyLevel"), "gmd:MD_ScopeCode", "dataset", codeList=CL + "MD_ScopeCode")
    S(S(root, "gmd:dateStamp"), "gco:DateTime", now_utc())
    rp = S(S(root, "gmd:contact"), "gmd:CI_ResponsibleParty")
    cs(rp, "gmd:individualName", ds["contact_name"])
    addr = S(S(S(S(rp, "gmd:contactInfo"), "gmd:CI_Contact"), "gmd:address"), "gmd:CI_Address")
    cs(addr, "gmd:electronicMailAddress", ds["contact_email"])
    S(S(rp, "gmd:role"), "gmd:CI_RoleCode", "processor", codeList=CL + "CI_RoleCode")
    di = S(S(root, "gmd:identificationInfo"), "gmd:MD_DataIdentification")
    ci = S(S(di, "gmd:citation"), "gmd:CI_Citation")
    cs(ci, "gmd:title", ds["title"])
    cd = S(S(ci, "gmd:date"), "gmd:CI_Date")
    S(S(cd, "gmd:date"), "gco:Date", f"{t0:%Y-%m-%d}")
    S(S(cd, "gmd:dateType"), "gmd:CI_DateTypeCode", "creation", codeList=CL + "CI_DateTypeCode")
    cs(S(S(ci, "gmd:identifier"), "gmd:MD_Identifier"), "gmd:code", ds["doi"])
    for name, role in ds.get("investigators", []):
        party = S(S(ci, "gmd:citedResponsibleParty"), "gmd:CI_ResponsibleParty")
        cs(party, "gmd:individualName", name)
        S(S(party, "gmd:role"), "gmd:CI_RoleCode", role, codeList=CL + "CI_RoleCode")
    cs(di, "gmd:abstract", ds["abstract"])
    kw = S(S(di, "gmd:descriptiveKeywords"), "gmd:MD_Keywords")
    for k in ds["keywords"]:
        cs(kw, "gmd:keyword", k)
    ex = S(S(di, "gmd:extent"), "gmd:EX_Extent")
    bb = S(S(ex, "gmd:geographicElement"), "gmd:EX_GeographicBoundingBox")
    for tag, v in (("westBoundLongitude", df.lon.min()), ("eastBoundLongitude", df.lon.max()),
                   ("southBoundLatitude", df.lat.min()), ("northBoundLatitude", df.lat.max())):
        S(S(bb, f"gmd:{tag}"), "gco:Decimal", f"{v:.7f}")
    tp = S(S(S(S(ex, "gmd:temporalElement"), "gmd:EX_TemporalExtent"), "gmd:extent"), "gml:TimePeriod",
           **{f"{{{NS['gml']}}}id": "tp1"})
    S(tp, "gml:beginPosition", t0.isoformat())
    S(tp, "gml:endPosition", t1.isoformat())
    res = S(S(S(S(S(root, "gmd:distributionInfo"), "gmd:MD_Distribution"), "gmd:transferOptions"),
              "gmd:MD_DigitalTransferOptions"), "gmd:onLine")
    res = S(res, "gmd:CI_OnlineResource")
    S(S(res, "gmd:linkage"), "gmd:URL", f"https://doi.org/{ds['doi']}")
    return root, file_id


def build_sss_xml(df, file_id, ds, ingest, parse_info, seg_summary):
    """SSS companion record (structure of code/6 (parse3)sss_extended_builder_upgrade.py) + lineage."""
    root = etree.Element(f"{{{NS['gmd']}}}MD_Metadata", nsmap={k: NS[k] for k in ("gmd", "gco", "sss")})
    cs(root, "gmd:fileIdentifier", file_id + "_SSS_EXT")
    cs(root, "gmd:parentIdentifier", file_id)
    S(S(root, "gmd:dateStamp"), "gco:DateTime", now_utc())
    rp = S(S(root, "gmd:contact"), "gmd:CI_ResponsibleParty")
    cs(rp, "gmd:individualName", ds["contact_name"])
    S(S(rp, "gmd:role"), "gmd:CI_RoleCode", "processor", codeList=CL + "CI_RoleCode")
    cs(S(S(root, "gmd:identificationInfo"), "gmd:MD_DataIdentification"), "gmd:abstract",
       f"Extended SSS ping-level metadata derived from DOI {ds['doi']}")
    c = S(S(root, "gmd:contentInfo"), "sss:SSS_ExtendedContent")
    ps = S(c, "sss:PingSummary")
    for tag, v in (("numberOfPings", len(df)), ("startTime", df.timestamp.min()), ("endTime", df.timestamp.max()),
                   ("depthMin", df.depth.min()), ("depthMax", df.depth.max()),
                   ("altitudeMin", df.altitude[df.altitude > 0].min()), ("altitudeMax", df.altitude.max()),
                   ("speedMean", df.speed.mean())):
        S(ps, f"sss:{tag}", v)
    g = S(c, "sss:PingGeometry")
    for tag, v in (("latMin", df.lat.min()), ("latMax", df.lat.max()), ("lonMin", df.lon.min()), ("lonMax", df.lon.max()),
                   ("navUnits", parse_info["nav_units"]), ("projectedCRS", f"EPSG:{parse_info['utm_epsg']}")):
        S(g, f"sss:{tag}", v)
    rl = S(c, "sss:ChannelRadiometricSummaryList")
    for ch in range(sum(col.startswith("max_ch") for col in df.columns)):
        e = S(rl, "sss:ChannelSummary")
        for tag, v in (("channel", ch), ("max", df[f"max_ch{ch}"].max()), ("mean", df[f"mean_ch{ch}"].mean()),
                       ("std", df[f"std_ch{ch}"].mean()), ("meanSamples", df[f"samples_ch{ch}"].mean())):
            S(e, f"sss:{tag}", v)
    lin = S(c, "sss:ProcessingLineage")
    S(lin, "sss:pipelineVersion", PIPELINE_VERSION)
    S(lin, "sss:sourceFile", ingest["source_file"])
    S(lin, "sss:sourceSHA256", ingest["source_sha256"])
    S(lin, "sss:ingestionClass", ingest["class"])
    S(lin, "sss:ingestionRepair", json.dumps(ingest["repair"]) if ingest["repair"] else "none")
    S(lin, "sss:productChannelPair", json.dumps(parse_info["channel_pair"]))
    S(lin, "sss:flatBottomHeight", parse_info["flat_bottom_height"])
    S(lin, "sss:segmentation", json.dumps(seg_summary))
    return root


def write_xml(root, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    etree.ElementTree(root).write(path, pretty_print=True, xml_declaration=True, encoding="UTF-8")


# ----------------------------------------------------------------------------- 4 segment (Algorithm 1)
def segment(t, x, y, p):
    """Algorithm 1. t: seconds; x, y: projected metres. Returns list of (start, end) ping indices (inclusive)."""
    segs, start, d, s = [], 0, 0.0, 0
    for i in range(1, len(t)):
        if i == start:                    # first ping of a new segment: the step from the previous one is not counted
            continue
        step = math.hypot(x[i] - x[i - 1], y[i] - y[i - 1])
        if t[i] - t[i - 1] > p["time_gap_s"] or step > p["jump_m"]:
            segs.append((start, i - 1)); start, d, s = i, 0.0, 0
            continue
        s = s + 1 if step < p["stall_eps_m"] else 0
        if s > p["stall_max_run"]:
            segs.append((start, i - 1)); start, d, s = i, 0.0, 0
            continue
        d += step
        if d >= p["target_length_m"] or i - start + 1 >= p["max_pings"]:
            segs.append((start, i)); start, d, s = i + 1, 0.0, 0
    if start < len(t):
        segs.append((start, len(t) - 1))
    return segs


def decimate(lon, lat, x, y, step_m):
    keep, last = [0], 0
    for i in range(1, len(x)):
        if math.hypot(x[i] - x[last], y[i] - y[last]) >= step_m:
            keep.append(i); last = i
    if keep[-1] != len(x) - 1:
        keep.append(len(x) - 1)
    return [[float(lon[i]), float(lat[i])] for i in keep]


def build_index(df, ingest, p):
    t = (df.timestamp - df.timestamp.iloc[0]).dt.total_seconds().to_numpy()
    x, y, lon, lat = (df[c].to_numpy() for c in ("utm_x", "utm_y", "lon", "lat"))
    feats = [{"type": "Feature", "id": "trackline",
              "geometry": {"type": "LineString", "coordinates": decimate(lon, lat, x, y, p["decimate_m"])},
              "properties": {"kind": "trackline", "ping_start": 0, "ping_end": int(len(df) - 1)}}]
    for k, (a, b) in enumerate(segment(t, x, y, p)):
        sid = f"seg_{k:06d}"
        length = float(np.hypot(np.diff(x[a:b + 1]), np.diff(y[a:b + 1])).sum())
        coords = decimate(lon[a:b + 1], lat[a:b + 1], x[a:b + 1], y[a:b + 1], p["decimate_m"])
        if len(coords) < 2:
            coords = coords * 2
        feats.append({"type": "Feature", "id": sid, "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"kind": "segment", "segment_id": sid, "ping_start": int(a), "ping_end": int(b),
                                     "n_pings": int(b - a + 1), "time_start": str(df.timestamp.iloc[a]),
                                     "time_end": str(df.timestamp.iloc[b]), "length_m": round(length, 3),
                                     "source_file": ingest["source_file"], "source_sha256": ingest["source_sha256"],
                                     "ingestion_class": ingest["class"], "segmentation": p, "products": {}}})
    return {"type": "FeatureCollection", "pipeline_version": PIPELINE_VERSION, "features": feats}


def segments_of(index):
    return [f for f in index["features"] if f["properties"]["kind"] == "segment"]


# ----------------------------------------------------------------------------- 5 preview
def load_side(out, df, a, b, ch):
    return [np.asarray(np.load(os.path.join(out, r), allow_pickle=True)[ch], float)
            for r in df.raw_array_path.iloc[a:b + 1]]


def make_preview(out, df, seg, pair, p):
    a, b = seg["properties"]["ping_start"], seg["properties"]["ping_end"]
    port, stbd = load_side(out, df, a, b, pair["port"]), load_side(out, df, a, b, pair["stbd"])
    n = min(min(map(len, port)), min(map(len, stbd)))
    P, St = np.array([r[:n] for r in port]), np.array([r[:n] for r in stbd])
    if pair["nadir_first"]["port"]:
        P = P[:, ::-1]
    if not pair["nadir_first"]["stbd"]:
        St = St[:, ::-1]
    img = np.hstack([P, St])
    u8 = normalize_u8(img)
    rel = f"previews/{seg['id']}.png"
    os.makedirs(os.path.join(out, "previews"), exist_ok=True)
    Image.fromarray(u8).resize((p["width"], p["height"]), Image.BILINEAR).save(os.path.join(out, rel))
    return rel


# ----------------------------------------------------------------------------- 6 stitch
def ground_range(r, h, mode):
    """Eq. (1): g = sqrt(r^2 - h^2) in flat mode, falling back to r when not finite or zero."""
    if mode == "none":
        return r
    with np.errstate(invalid="ignore"):
        g = np.sqrt(r ** 2 - h ** 2)
    return np.where(np.isfinite(g) & (g > 0), g, r)


def fill_rows(rows, max_gap=8):
    """Spread each sample (ordered by range) over the raster rows up to the next sample, so sample spacing
    wider than a pixel leaves no empty rows. Jumps larger than max_gap (e.g. at the flat-mode nadir fold)
    are not filled. Returns (row index, sample index) pairs."""
    step = np.diff(rows, append=rows[-1])
    count = np.where((np.abs(step) >= 1) & (np.abs(step) <= max_gap), np.abs(step), 1)
    idx = np.repeat(np.arange(rows.size), count)
    offs = np.arange(idx.size) - np.repeat(np.cumsum(count) - count, count)
    return rows[idx] + np.sign(step)[idx] * offs, idx


def deposit(out, df, seg, pair, mode, p):
    """Deposit downsampled pings into a segment-centred raster; returns accumulators shared by all fusion rules."""
    a, b = seg["properties"]["ping_start"], seg["properties"]["ping_end"]
    x, y = df.utm_x.to_numpy()[a:b + 1], df.utm_y.to_numpy()[a:b + 1]
    along = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    pick = np.unique(np.linspace(0, b - a, min(p["target_max_pings"], b - a + 1)).round().astype(int))
    ranges = np.r_[df.slant_range_port.to_numpy()[a:b + 1], df.slant_range_stbd.to_numpy()[a:b + 1]]
    rmax = float(np.nanmax(ranges)) if np.nanmax(ranges) > 0 else p["fallback_range_m"]
    px = max(p["pixel_m"], (along[-1] + 1) / (p["max_raster"] - 1), 2 * rmax / (p["max_raster"] - 1))
    W, H = int(along[-1] / px) + 1, int(2 * rmax / px) + 1
    acc = {k: np.zeros((H, W)) for k in ("n", "sum", "sumsq", "wsum", "wval")}
    acc["max"] = np.full((H, W), -np.inf)
    for n_k, k in enumerate(pick):
        i = a + k
        # each ping covers the along-track span up to the next selected ping (no empty columns between pings)
        c0 = int(along[k] / px)
        c1 = int(along[pick[n_k + 1]] / px) if n_k + 1 < pick.size else c0 + 1
        cols = np.arange(c0, min(max(c1, c0 + 1), W))
        raw = np.load(os.path.join(out, df.raw_array_path.iloc[i]), allow_pickle=True)
        for ch, sign, rcol in ((pair["port"], -1, "slant_range_port"), (pair["stbd"], 1, "slant_range_stbd")):
            v = np.asarray(raw[ch], float)
            j = np.arange(0, v.size, p["sample_stride"])              # sample index in range order
            src = j if pair["nadir_first"]["port" if sign < 0 else "stbd"] else v.size - 1 - j
            R = df[rcol].iloc[i] if df[rcol].iloc[i] > 0 else p["fallback_range_m"]
            g = ground_range(j / v.size * R, df.height_used.iloc[i], mode)
            rows, k_s = fill_rows(np.clip(((sign * g + rmax) / px).round().astype(int), 0, H - 1))
            iy, ix = np.tile(rows, cols.size), np.repeat(cols, rows.size)
            vals = np.tile(v[src][k_s], cols.size)
            w = np.tile((1.0 / (1.0 + g))[k_s], cols.size)
            np.add.at(acc["n"], (iy, ix), 1)
            np.add.at(acc["sum"], (iy, ix), vals)
            np.add.at(acc["sumsq"], (iy, ix), vals ** 2)
            np.add.at(acc["wsum"], (iy, ix), w)
            np.add.at(acc["wval"], (iy, ix), w * vals)
            np.maximum.at(acc["max"], (iy, ix), vals)
    return acc, {"pixel_m": px, "range_m": rmax, "pings_used": int(pick.size), "raster": [H, W]}


def fuse(acc, rule):
    n = acc["n"]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = {"mean": acc["sum"] / n, "rms": np.sqrt(acc["sumsq"] / n),
               "distance": acc["wval"] / acc["wsum"], "max": acc["max"]}[rule]
    return np.where(n > 0, out, np.nan)


# ----------------------------------------------------------------------------- 7 metrics (Eqs. 2-8)
def metrics(I, n=None):
    valid = np.isfinite(I) if n is None else n > 0
    v = I[valid]
    hist, _ = np.histogram(v, bins=256)
    pk = hist[hist > 0] / v.size
    dx = np.diff(np.where(valid, I, np.nan), axis=1)
    dy = np.diff(np.where(valid, I, np.nan), axis=0)
    gx, gy = dx[:-1, :], dy[:, :-1]
    ag = np.sqrt((gx ** 2 + gy ** 2) / 2)
    m = {"entropy": float(-(pk * np.log2(pk)).sum()), "contrast_std": float(v.std()),
         "dynamic_range": float(np.subtract(*np.percentile(v, [98, 2]))),
         "average_gradient": float(np.nanmean(ag)) if np.isfinite(ag).any() else float("nan"),
         "spatial_frequency": float(np.sqrt(np.nanmean(dx ** 2) + np.nanmean(dy ** 2))),
         # seam proxy: std of all valid 4-neighbour differences (definition of code/5mosaic_stitch.py)
         "seam_proxy": float(np.nanstd(np.concatenate([dx.ravel(), dy.ravel()])))}
    if n is not None:
        over = n > 1
        m.update({"coverage": float(valid.mean()), "overlap_ratio": float(over.sum() / max(valid.sum(), 1)),
                  "mean_overlap_count": float(n[over].mean()) if over.any() else 0.0})
    return m


# ----------------------------------------------------------------------------- 8 viewer
def overlay_image(img, heading_deg, w_m, h_m, m_per_px=1.0):
    """Heading-up product image (port left, segment start at the bottom), rotated to the segment heading on a
    transparent background. Returns the RGBA image and its axis-aligned extent in metres (east, north)."""
    im = img.convert("RGBA").resize((max(1, round(w_m / m_per_px)), max(1, round(h_m / m_per_px))), Image.BILINEAR)
    im = im.transpose(Image.FLIP_TOP_BOTTOM).rotate(-heading_deg, Image.BILINEAR, expand=True)
    return im, im.size[0] * m_per_px, im.size[1] * m_per_px


VIEWER_CSS = """<style>
.folium-map { position: absolute !important; left: 340px !important; top: 0; bottom: 0;
              width: calc(100% - 340px) !important; height: 100% !important; }
#sss-panel { position: absolute; left: 0; top: 0; bottom: 0; width: 340px; box-sizing: border-box; overflow-y: auto;
             padding: 18px 16px; background: #fbf7f0; border-right: 1px solid #ddd5c8; color: #1f2a24;
             font-family: Georgia, serif; z-index: 1000; }
#sss-panel h1 { font-size: 27px; margin: 0 0 8px; }
#sss-panel p { font-size: 13px; line-height: 1.45; color: #4a5650; margin: 0 0 12px; }
#sss-panel .sss-card { background: #fffdf9; border: 1px solid #e6dfd3; border-radius: 12px; padding: 11px 14px;
                   margin-bottom: 12px; }
#sss-panel .k { font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; color: #5d6762; }
#sss-panel .v { font-size: 17px; margin-bottom: 6px; }
#sss-panel .grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; }
#sss-panel .row { font-size: 14px; margin: 4px 0; display: flex; align-items: center; }
#sss-panel .sw { display: inline-block; width: 26px; height: 4px; border-radius: 2px; margin-right: 10px; }
#sss-panel button { display: inline-block; width: auto; font: 13px Arial, sans-serif; color: #1f2a24; background: #fff; border: 1px solid #d5ccbf;
                    border-radius: 16px; padding: 6px 12px; margin: 3px 4px 3px 0; cursor: pointer; }
#sss-panel button.on { background: #cfe5d8; border-color: #3d7a5a; font-weight: bold; }
#sss-panel button:disabled { color: #a9a9a9; cursor: default; }
</style>"""


def build_viewer(out, index, variants, df, epsg):
    import folium
    segs = segments_of(index)
    missing = [f["properties"]["products"][k] for f in segs for k in f["properties"]["products"]
               if not os.path.exists(os.path.join(out, f["properties"]["products"][k]))]
    if missing:
        raise FileNotFoundError(f"viewer not written, {len(missing)} product files missing, e.g. {missing[:3]}")
    track = index["features"][0]["geometry"]["coordinates"]
    m = folium.Map(location=[np.mean([c[1] for c in track]), np.mean([c[0] for c in track])], zoom_start=14,
                   tiles=None)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer("Esri.WorldImagery", name="Esri World Imagery").add_to(m)
    tl = folium.FeatureGroup(name="Trackline").add_to(m)
    folium.PolyLine([[c[1], c[0]] for c in track], color="#555", weight=2, tooltip="trackline").add_to(tl)
    fg = folium.FeatureGroup(name="Segment lines").add_to(m)
    for n_seg, f in enumerate(segs):
        pr = f["properties"]
        colour = "#00629B" if n_seg % 2 == 0 else "#E87722"
        imgs = "".join(f'<div style="display:inline-block;margin:2px;text-align:center"><img src="{pr["products"][k]}" '
                       f'style="height:140px"><br>{k}</div>' for k in ["preview"] + [v[0] for v in variants])
        html = (f"<b>{pr['segment_id']}</b> pings {pr['ping_start']}&ndash;{pr['ping_end']} "
                f"({pr['n_pings']}), {pr['length_m']:.1f} m<br>{pr['time_start']} &ndash; {pr['time_end']}<br>"
                f"source {pr['source_file']} sha256 {pr['source_sha256'][:12]}&hellip; ({pr['ingestion_class']})<br>{imgs}")
        folium.GeoJson(f, style_function=lambda _, c=colour: {"color": c, "weight": 5},
                       popup=folium.Popup(html, max_width=900), tooltip=pr["segment_id"]).add_to(fg)

    # image modes: each segment's preview or stitched product placed at the segment centre, rotated to the heading
    # ponytail: straight chord first-to-last ping per segment; curved segments are approximated, not georectified
    to_ll = Transformer.from_crs(epsg, 4326, always_xy=True)
    with open(os.path.join(out, "segment_mosaic_manifest.json"), encoding="utf-8") as fh:
        geo = {(e["segment_id"], e["product"]): e["params"] for e in json.load(fh)}
    names = ["preview"] + [v[0] for v in variants]
    groups = {k: folium.FeatureGroup(name=k, show=False, control=False).add_to(m) for k in names}
    x, y = df.utm_x.to_numpy(), df.utm_y.to_numpy()
    for f in segs:
        pr, sid = f["properties"], f["id"]
        a, b = pr["ping_start"], pr["ping_end"]
        heading = math.degrees(math.atan2(x[b] - x[a], y[b] - y[a])) % 360
        cx, cy = (x[a] + x[b]) / 2, (y[a] + y[b]) / 2
        for k in names:
            g = geo[(sid, "rms_flat" if k == "preview" else k)]   # preview drawn on the RMS-flat footprint
            img = Image.open(os.path.join(out, pr["products"][k]))
            if k != "preview":
                img = img.transpose(Image.TRANSPOSE)    # stored along-track horizontal; make across-track horizontal
            im, ex, ny = overlay_image(img, heading, g["raster"][0] * g["pixel_m"], g["raster"][1] * g["pixel_m"])
            rel = f"viewer/{k}/{sid}.png"
            os.makedirs(os.path.join(out, "viewer", k), exist_ok=True)
            im.save(os.path.join(out, rel))
            (w_, s_), (e_, n_) = to_ll.transform(cx - ex / 2, cy - ny / 2), to_ll.transform(cx + ex / 2, cy + ny / 2)
            ov = folium.raster_layers.ImageOverlay("https://x", bounds=[[s_, w_], [n_, e_]])
            ov.url = rel                                # link the file; folium would embed a local path as base64
            ov.add_to(groups[k])
    folium.LayerControl(collapsed=False).add_to(m)

    # side panel: summary, legend, image mode and mosaic variant selection
    p0 = segs[0]["properties"]
    label = {v[0]: f"{v[2].upper()} | {v[1]}" for v in variants}
    var_btns = "".join(f'<button data-variant="{k}">{label[k]}</button>' for k in names[1:])
    panel = f"""<div id="sss-panel">
<h1>SSS Segment Viewer</h1>
<p>Segment products of {p0['source_file']} from sss_pipeline {PIPELINE_VERSION}. The trackline and segments are
geolocated from the ping table. Each segment image is placed at its segment centre and rotated to the segment
heading as a visual aid; it is not a georectified swath. Click a segment line for its lineage and all products.</p>
<div class="sss-card grid">
<div><div class="k">Segments</div><div class="v">{len(segs)}</div></div>
<div><div class="k">Trackline pings</div><div class="v">{len(df):,}</div></div>
<div><div class="k">Preview strips</div><div class="v">{len(segs)}</div></div>
<div><div class="k">Stitched products</div><div class="v">{len(segs) * len(variants)}</div></div>
<div style="grid-column: span 2"><div class="k">Source SHA-256 &middot; ingestion</div>
<div class="v" style="font-size:13px">{p0['source_sha256'][:16]}&hellip; &middot; {p0['ingestion_class']}</div></div>
</div>
<div class="sss-card"><div class="k">Legend</div>
<div class="row"><span class="sw" style="background:#555"></span>Trackline</div>
<div class="row"><span class="sw" style="background:linear-gradient(90deg,#00629B 50%,#E87722 50%)"></span>Segment lines (alternating)</div>
<div class="row"><span class="sw" style="height:10px;background:linear-gradient(90deg,#111,#eee)"></span>SSS segment imagery</div>
</div>
<div class="sss-card"><div class="k">Image mode</div>
<button data-mode="line">Line Only</button><button data-mode="preview">Preview Strip</button><button data-mode="stitched">Stitched Mosaic</button>
<div class="k" style="margin-top:10px">Mosaic variant</div>{var_btns}
</div></div>"""
    grp_js = ", ".join(f'"{k}": {g.get_name()}' for k, g in groups.items())
    js = f"""
window.addEventListener("load", function () {{   // folium defines the map and groups after this script
var sssMap = {m.get_name()}, sssGroups = {{{grp_js}}};
var sssState = {{mode: "line", variant: "{names[1]}"}};
window.sssSetMode = function (mode, variant) {{
  if (mode) sssState.mode = mode; if (variant) sssState.variant = variant;
  for (var k in sssGroups) sssMap.removeLayer(sssGroups[k]);
  if (sssState.mode === "preview") sssMap.addLayer(sssGroups.preview);
  if (sssState.mode === "stitched") sssMap.addLayer(sssGroups[sssState.variant]);
  document.querySelectorAll("#sss-panel button[data-mode]").forEach(function (b) {{
    b.classList.toggle("on", b.dataset.mode === sssState.mode); }});
  document.querySelectorAll("#sss-panel button[data-variant]").forEach(function (b) {{
    b.classList.toggle("on", b.dataset.variant === sssState.variant && sssState.mode === "stitched");
    b.disabled = sssState.mode !== "stitched"; }});
}};
document.querySelectorAll("#sss-panel button").forEach(function (b) {{
  b.onclick = function () {{ sssSetMode(b.dataset.mode, b.dataset.variant); }}; }});
sssSetMode();
}});
"""
    m.get_root().header.add_child(folium.Element(VIEWER_CSS))
    m.get_root().html.add_child(folium.Element(panel))
    m.get_root().script.add_child(folium.Element(js))
    m.save(os.path.join(out, "sss_index_viewer.html"))


# ----------------------------------------------------------------------------- run
def tree_sha256(out, dirs):
    """One SHA-256 over the sorted (path, file SHA-256) pairs of all files in the given output folders."""
    h = hashlib.sha256()
    for d in dirs:
        for root, _, files in sorted(os.walk(os.path.join(out, d))):
            for f in sorted(files):
                p = os.path.join(root, f)
                h.update(f"{os.path.relpath(p, out).replace(os.sep, '/')} {sha256(p)}\n".encode())
    return h.hexdigest()


def run(xtf, out, ds, cfg=CONFIG, max_pings=None):
    os.makedirs(out, exist_ok=True)
    t_mark, timings = [time.perf_counter()], {}

    def lap(name):
        now = time.perf_counter(); timings[name] = round(now - t_mark[0], 2); t_mark[0] = now
    rec = {"pipeline_version": PIPELINE_VERSION, "started_utc": now_utc(), "config": cfg, "dataset": ds,
           "libraries": {k: version(k) for k in ("pyxtf", "numpy", "pandas", "pyproj", "lxml", "pillow", "folium")},
           "max_pings": max_pings}
    ingest = preflight(xtf)
    write_json(os.path.join(out, "ingestion_record.json"), ingest)
    rec["ingestion"] = ingest
    lap("1_preflight"); print(f"[1] preflight: {ingest['class']}")
    if ingest["class"] == "unsupported":
        write_json(os.path.join(out, "run_record.json"), rec)
        raise SystemExit(f"unsupported input: {ingest.get('reason')}")

    df, info = parse(xtf, out, ingest, max_pings)
    rec["parse"] = info
    lap("2_parse"); print(f"[2] parse: {len(df)} pings, EPSG:{info['utm_epsg']}, pair {info['channel_pair']}")

    index = build_index(df, ingest, cfg["segment"])
    segs = segments_of(index)
    seg_summary = {"n_segments": len(segs), "parameters": cfg["segment"]}
    lap("4_segment"); print(f"[4] segment: {len(segs)} segments")

    root, file_id = build_dataset_xml(df, ds)
    write_xml(root, os.path.join(out, "metadata", "dataset_mgds.xml"))
    write_xml(build_sss_xml(df, file_id, ds, ingest, info, seg_summary),
              os.path.join(out, "metadata", "sss_extended.xml"))
    lap("3_metadata"); print("[3] metadata written")

    pair, prev_man, mos_man, rows = info["channel_pair"], [], [], []
    for f in segs:
        sid, pr = f["id"], f["properties"]
        lineage = {"segment_id": sid, "ping_start": pr["ping_start"], "ping_end": pr["ping_end"],
                   "source_sha256": ingest["source_sha256"]}
        rel = make_preview(out, df, f, pair, cfg["preview"])
        pr["products"]["preview"] = rel
        prev_man.append({**lineage, "product": "preview", "file": rel, "params": cfg["preview"]})
        prev_img = np.asarray(Image.open(os.path.join(out, rel)), float)
        rows.append({"segment_id": sid, "variant": "preview", **metrics(prev_img)})
        for mode in sorted({v[1] for v in cfg["variants"]}):
            acc, geo = deposit(out, df, f, pair, mode, cfg["stitch"])
            for name, m_, rule in cfg["variants"]:
                if m_ != mode:
                    continue
                grid = fuse(acc, rule)
                base = f"mosaics/{name}/{sid}"
                os.makedirs(os.path.join(out, "mosaics", name), exist_ok=True)
                np.save(os.path.join(out, base + ".npy"), grid)
                u8 = normalize_u8(np.nan_to_num(grid), acc["n"] > 0)
                Image.fromarray(np.dstack([u8, u8, u8, np.where(acc["n"] > 0, 255, 0).astype(np.uint8)])) \
                     .save(os.path.join(out, base + ".png"))
                pr["products"][name] = base + ".png"
                mos_man.append({**lineage, "product": name, "file": base + ".png", "grid": base + ".npy",
                                "params": {**cfg["stitch"], "slant_range_mode": mode, "fusion": rule, **geo}})
                rows.append({"segment_id": sid, "variant": name, **metrics(grid, acc["n"])})
        print(f"    {sid}: preview + {len(cfg['variants'])} variants")
    write_json(os.path.join(out, "segment_preview_manifest.json"), prev_man)
    write_json(os.path.join(out, "segment_mosaic_manifest.json"), mos_man)
    write_json(os.path.join(out, "sss_index.geojson"), index)
    per = pd.DataFrame(rows)
    per.to_csv(os.path.join(out, "metrics_per_segment.csv"), index=False)
    per.drop(columns="segment_id").groupby("variant", sort=False).mean().to_csv(os.path.join(out, "metrics_summary.csv"))
    lap("5-7_products_metrics"); print("[5-7] products, manifests and metrics written")

    build_viewer(out, index, cfg["variants"], df, info["utm_epsg"])
    lap("8_viewer"); print("[8] viewer written")

    outputs = ["pings.csv", "sss_index.geojson", "segment_preview_manifest.json", "segment_mosaic_manifest.json",
               "metadata/dataset_mgds.xml", "metadata/sss_extended.xml", "metrics_summary.csv"]
    rec["outputs_sha256"] = {o: sha256(os.path.join(out, o)) for o in outputs}
    rec["products_tree_sha256"] = tree_sha256(out, ["raw_arrays", "previews", "mosaics"])
    rec["timings_s"] = timings
    rec["finished_utc"] = now_utc()
    write_json(os.path.join(out, "run_record.json"), rec)
    print("[done] run_record.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--xtf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dataset", required=True, help="key in datasets.json")
    ap.add_argument("--datasets", default=os.path.join(os.path.dirname(__file__), "datasets.json"))
    ap.add_argument("--config", help="JSON file overriding CONFIG")
    ap.add_argument("--max-pings", type=int, help="limit pings (smoke test)")
    a = ap.parse_args()
    cfg = CONFIG
    if a.config:
        with open(a.config, encoding="utf-8") as f:
            cfg = {**CONFIG, **json.load(f)}
    with open(a.datasets, encoding="utf-8") as f:
        ds = json.load(f)[a.dataset]
    run(a.xtf, a.out, ds, cfg, a.max_pings)
