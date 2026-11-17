#!/usr/bin/env python3
"""Pick one vivid key color per team logo -> data/processed/logo_colors.json {"year|Owner": "#rrggbb"}.
SVGs are rasterized with macOS qlmanage. Logos with no vivid color (black/white/grey) are omitted,
so the dashboard falls back to the owner's palette color."""
import colorsys, json, re, subprocess, sys, tempfile, warnings
warnings.filterwarnings('ignore')
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LOGO_DIR = ROOT / "dashboard" / "logos"
OUT = ROOT / "data" / "processed" / "logo_colors.json"
META = json.load(open(ROOT / "data" / "processed" / "meta.json"))
slug = lambda o: re.sub(r"[^a-z0-9]+", "-", o.lower()).strip("-")
by_slug = {slug(o): o for o in META["owners"]}

def load(f, tmp):
    if f.suffix.lower() == ".svg":
        subprocess.run(["qlmanage", "-t", "-s", "256", "-o", str(tmp), str(f)], capture_output=True)
        f = tmp / (f.name + ".png")
        if not f.exists(): return None
    return Image.open(f).convert("RGBA").resize((64, 64))

def key_color(im):
    bins = {}
    for r, g, b, a in im.getdata():
        if a < 200: continue
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.35 or v < 0.25: continue
        k = int(h * 24) % 24
        w = s * v
        t = bins.setdefault(k, [0, 0, 0, 0])
        t[0] += w; t[1] += h * w; t[2] += s * w; t[3] += v * w
    if not bins: return None
    w, h, s, v = max(bins.values(), key=lambda t: t[0])
    h, s, v = h / w, s / w, v / w
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.6), max(v, 0.78))   # keep readable on the dark theme
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

out = {}
with tempfile.TemporaryDirectory() as t:
    tmp = Path(t)
    for f in sorted(LOGO_DIR.glob("*/*")):
        owner = by_slug.get(f.stem)
        if not owner or not f.parent.name.isdigit(): continue
        im = load(f, tmp)
        c = key_color(im) if im else None
        if c: out[f"{f.parent.name}|{owner}"] = c
        else: print("no vivid color:", f.parent.name, f.name, file=sys.stderr)
json.dump(out, open(OUT, "w"), indent=0, sort_keys=True)
print(f"{len(out)} colors -> {OUT}")
