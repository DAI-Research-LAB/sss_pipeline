"""Screenshots of sss_index_viewer.html for the paper (headless Chrome).
Usage: python viewer_shots.py ../runs/NBP0505 seg_000014 [seg_a,seg_b,... to zoom the image modes on]"""
import json
import os
import re
import subprocess
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

JS = """<script>
window.addEventListener("load", function () { setTimeout(function () {
  var m = %(map)s, sid = %(sid)s;
  m.options.zoomSnap = 0.1;
  sssSetMode(%(mode)s);
  var focus = %(focus)s, fb = null;
  m.eachLayer(function (l) {
    if (sid === null && !focus.length && l instanceof L.Polyline && !l.feature && l.getBounds) { m.fitBounds(l.getBounds(), {padding: [20, 20]}); }
    if (l.feature && focus.indexOf(l.feature.id) >= 0) { fb = fb ? fb.extend(l.getBounds()) : L.latLngBounds(l.getBounds().getSouthWest(), l.getBounds().getNorthEast()); }
    if (sid !== null && l.getLayers) {
      var inner = l.getLayers()[0];
      if (inner && inner.feature && inner.feature.id === sid) {
        m.fitBounds(inner.getBounds(), {padding: [180, 180], maxZoom: 17});
        setTimeout(function () { l.openPopup(inner.getBounds().getCenter()); }, 800);
      }
    }
  });
  if (fb) { m.fitBounds(fb.pad(0.35)); }
  if (%(hide)s) { m.removeLayer(%(seglines)s); }
}, 1500); });
</script>"""


def shot(run, sid, name, size="1280,760", mode="line", focus=()):
    html = open(os.path.join(run, "sss_index_viewer.html"), encoding="utf-8").read()
    map_var = re.search(r"var (map_[0-9a-f]+) = L\.map", html).group(1)
    seglines = re.search(r'"Segment lines" : (feature_group_[0-9a-f]+)', html).group(1)
    page = os.path.join(run, f"_{name}.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(html.replace("</html>", JS % {"map": map_var, "sid": f'"{sid}"' if sid else "null", "mode": json.dumps(mode), "hide": "true" if mode != "line" else "false", "seglines": seglines, "focus": json.dumps(list(focus))} + "</html>"))
    png = os.path.abspath(os.path.join(run, f"{name}.png"))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", f"--window-size={size}",
                    "--virtual-time-budget=15000", "--allow-file-access-from-files", f"--screenshot={png}",
                    "file:///" + os.path.abspath(page).replace("\\", "/")], check=True, capture_output=True)
    os.remove(page)
    print(png)


if __name__ == "__main__":
    run, sid = sys.argv[1], sys.argv[2]
    focus = sys.argv[3].split(",") if len(sys.argv) > 3 else ()          # zoom for the image modes
    shot(run, None, "fig_viewer_overview")
    shot(run, sid, "fig_viewer_segment")
    for mode in ("preview", "stitched"):                                 # image modes: segment lines off
        shot(run, None, f"fig_viewer_mode_{mode}", mode=mode, focus=focus)
    # 2 x 2 figure of full viewer windows: (a) line only, (b) preview, (c) stitched, (d) segment panel
    from PIL import Image, ImageDraw, ImageFont
    cells = [("fig_viewer_overview", "(a) Line only"), ("fig_viewer_mode_preview", "(b) Preview strips"),
             ("fig_viewer_mode_stitched", "(c) Stitched mosaic, RMS | flat"), ("fig_viewer_segment", "(d) Segment panel")]
    ims = [Image.open(os.path.join(run, f + ".png")).convert("RGB") for f, _ in cells]
    w, h = ims[0].size
    lab, gap, font = 56, 24, ImageFont.truetype("arial.ttf", 40)
    fig = Image.new("RGB", (2 * w + gap, 2 * (h + lab) + gap), "white")
    d = ImageDraw.Draw(fig)
    for k, (im, (_, label)) in enumerate(zip(ims, cells)):
        x, y = (k % 2) * (w + gap), (k // 2) * (h + lab + gap)
        d.text((x, y + 6), label, fill="black", font=font)
        fig.paste(im, (x, y + lab)); d.rectangle((x, y + lab, x + w - 1, y + lab + h - 1), outline="#999999", width=2)
    fig.save(os.path.join(run, "fig_viewer_modes.png")); print(os.path.join(run, "fig_viewer_modes.png"), fig.size)
