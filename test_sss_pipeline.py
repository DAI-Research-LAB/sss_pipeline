"""Self-checks for the logic the paper relies on. Run: python test_sss_pipeline.py"""
import types

import numpy as np

import sss_pipeline as sp

P = {"target_length_m": 75.0, "time_gap_s": 10.0, "jump_m": 30.0, "stall_eps_m": 0.02,
     "stall_max_run": 400, "max_pings": 2000}


def straight(n, step=1.0, dt=0.1):
    return np.arange(n) * dt, np.arange(n) * step, np.zeros(n)


def test_coordinates_not_scaled():
    # the old parser divided by NavUnits (3); degrees must pass through unchanged
    assert sp.to_latlon(100.798, 12.950, sp.NAV_LATLON) == (12.950, 100.798)


def test_segment_length_split():
    t, x, y = straight(301)                       # 300 m at 1 m spacing
    assert sp.segment(t, x, y, P) == [(0, 75), (76, 151), (152, 227), (228, 300)]


def test_time_gap_and_jump_split():
    t, x, y = straight(50)
    t[25:] += 20                                  # 20 s gap > 10 s
    assert sp.segment(t, x, y, P) == [(0, 24), (25, 49)]
    t, x, y = straight(50)
    x[25:] += 100                                 # 100 m jump > 30 m
    assert sp.segment(t, x, y, P) == [(0, 24), (25, 49)]


def test_stall_and_max_size_split():
    n = 500
    t, x, y = straight(n, step=0.0)               # stationary: stall run exceeds 400
    assert sp.segment(t, x, y, P)[0] == (0, 400)
    t, x, y = straight(2500, step=0.03)
    segs = sp.segment(t, x, y, P)
    assert segs[0] == (0, 1999) and all(b - a + 1 <= 2000 for a, b in segs)


def test_ground_range():
    r = np.array([5.0, 10.0, 0.0])
    g = sp.ground_range(r, 6.0, "flat")
    assert np.allclose(g, [5.0, 8.0, 0.0])        # r < h falls back to r; 10 -> sqrt(100-36) = 8
    assert np.allclose(sp.ground_range(r, 6.0, "none"), r)


def test_fusion_rules():
    acc = {"n": np.array([[2.0, 0.0]]), "sum": np.array([[6.0, 0]]), "sumsq": np.array([[20.0, 0]]),
           "wsum": np.array([[1.0, 0]]), "wval": np.array([[2.5, 0]]), "max": np.array([[4.0, -np.inf]])}
    assert sp.fuse(acc, "mean")[0, 0] == 3.0 and np.isnan(sp.fuse(acc, "mean")[0, 1])
    assert np.isclose(sp.fuse(acc, "rms")[0, 0], np.sqrt(10.0))
    assert sp.fuse(acc, "max")[0, 0] == 4.0 and sp.fuse(acc, "distance")[0, 0] == 2.5


def test_metrics():
    I = np.array([[0.0, 1.0], [0.0, 1.0]])
    n = np.array([[1, 2], [1, 1]])
    m = sp.metrics(I, n)
    assert np.isclose(m["entropy"], 1.0) and m["coverage"] == 1.0
    assert m["overlap_ratio"] == 0.25 and m["mean_overlap_count"] == 2.0
    assert np.isclose(m["spatial_frequency"], 1.0)   # RF = 1 (all horizontal diffs 1), CF = 0


def test_fill_rows():
    rows, idx = sp.fill_rows(np.array([10, 12, 13, 40]))       # gap 2 filled, gap 27 (> 8) not filled
    assert rows.tolist() == [10, 11, 12, 13, 40] and idx.tolist() == [0, 0, 1, 2, 3]
    rows, _ = sp.fill_rows(np.array([10, 8]))                  # port side: rows decrease with range
    assert rows.tolist() == [10, 9, 8]


def test_nadir_detection():
    # OTech-like port profile: rises, water-column minimum near the end, bright nadir echo in the last bin
    port = np.r_[np.linspace(190, 575, 70), np.linspace(520, 60, 25), [300] * 5]
    stbd = np.r_[[230, 50, 60], np.linspace(240, 790, 20), np.linspace(780, 270, 77)]
    assert sp.nadir_at_start(port) is False and sp.nadir_at_start(stbd) is True


def test_reproducible_timestamp(monkeypatch=None):
    import os
    os.environ["SOURCE_DATE_EPOCH"] = "0"
    try:
        assert sp.now_utc() == "1970-01-01T00:00:00+00:00"
    finally:
        del os.environ["SOURCE_DATE_EPOCH"]


def test_repair_pads_channel_info():
    fh = types.SimpleNamespace(sonar_info=[types.SimpleNamespace(k=i) for i in range(4)])
    assert sp.pad_sonar_info(fh, 5) == 1 and len(fh.sonar_info) == 5 and fh.sonar_info[4].k == 3


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
