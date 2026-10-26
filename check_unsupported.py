"""Exercise the 'unsupported' ingestion class with deliberately damaged copies of a valid XTF file.
Usage: python check_unsupported.py <valid.xtf> <workdir>  -> <workdir>/unsupported_cases.json
The original file is only read; damaged copies are written to <workdir>."""
import json
import os
import sys

from pyxtf.xtf_ctypes import XTFFileHeader

import sss_pipeline as sp


def cases(src, work):
    raw = open(src, "rb").read()
    header = XTFFileHeader.create_from_buffer(open(src, "rb"))
    hsize = 1024 * max(1, (header.NumberOfSonarChannels + header.NumberOfBathymetryChannels + 5) // 6)
    nav = XTFFileHeader.NavUnits.offset
    yield "truncated after file header", raw[:hsize + 64]           # first ping packet cut off
    bad = bytearray(raw[:2 * 1024 * 1024]); bad[nav:nav + 2] = (7).to_bytes(2, "little")
    yield "invalid NavUnits code (7)", bytes(bad)                    # position units not defined in XTF
    bad = bytearray(raw[:2 * 1024 * 1024]); bad[hsize:hsize + 64] = b"\0" * 64
    yield "corrupted first packet header", bytes(bad)                # packet magic number destroyed
    yield "header only (no packets)", raw[:hsize]


def main(src, work):
    os.makedirs(work, exist_ok=True)
    out = []
    for k, (name, data) in enumerate(cases(src, work)):
        path = os.path.join(work, f"damaged_{k}.xtf")
        open(path, "wb").write(data)
        try:
            rec = sp.preflight(path)
            out.append({"case": name, "class": rec["class"], "reason": rec.get("reason"), "bytes": len(data)})
        except Exception as e:                                       # noqa: BLE001 - report, do not hide
            out.append({"case": name, "class": "error", "reason": f"{type(e).__name__}: {e}", "bytes": len(data)})
        os.remove(path)
    json.dump({"source": os.path.basename(src), "cases": out}, open(os.path.join(work, "unsupported_cases.json"), "w"),
              indent=2)
    for o in out:
        print(o)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
