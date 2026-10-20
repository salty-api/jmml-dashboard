#!/usr/bin/env python3
"""
Build shareable stub pages with their own link previews (Open Graph cards).

Social apps read a page's HTML once, ignore the #fragment, and don't run JavaScript, so a single
page can only ever show one preview. This writes a tiny page per tab and per owner, each with its
own title/description/1200x630 card, that sends visitors on to the dashboard view.

  python3 scripts/build_share_pages.py [--out ../jmml-site]

Output (relative to --out):  <tab>/index.html, owner/<slug>/index.html, share/<name>.png
"""
import argparse, html, json, re, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
SITE = "https://jmml.whohashim.com"
import itertools
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
esc = html.escape

seasons = json.load(open(ROOT / "data/processed/seasons.json"))
matchups = json.load(open(ROOT / "data/processed/matchups.json"))
meta = json.load(open(ROOT / "data/processed/meta.json"))
LOGO_DIR = ROOT.parent / "logos"   # site-level logos (build/ lives inside the site repo)

played = [m for m in matchups if (m.get("score") or 0) > 0]
YEAR = max(m["year"] for m in played)
WEEK = max(m["week"] for m in played if m["year"] == YEAR and m["game_type"] != "Playoffs")

PILLS = {
    "alltime": ["Leaderboard", "Finish heatmap", "Head-to-head matrix"],
    "history": ["Scoring landscape", "Season cards", "Bad luck"],
    "records": ["Blowouts", "Streaks", "All-time luck", "Title rates"],
    "rivalry": ["Series record", "Margin by meeting", "Every game"],
    "whohashim": ["Draft prices", "Every owner", "Points per game"],
    "season": ["Standings", "Playoff odds", "Week preview", "Scoreboards"],
}
TABS = [  # (key, path, hash, title, description)
    ("alltime", "all-time", "#alltime", "All-Time Standings",
     "Every owner's record, titles and profit since 2009, plus finish history and the head-to-head matrix."),
    ("history", "team-history", "#history", "Team History",
     "Every team since 2009: scoring landscape, season cards and the unluckiest finishes."),
    ("records", "records", "#records", "Records",
     "Single-game highs and lows, longest streaks, all-time luck and playoff performance."),
    ("rivalry", "rivalry", "#rivalry", "Rivalry",
     "Pick any two owners and see their full head-to-head history."),
    ("whohashim", "who-has-him", "#whohashim", "Who Has Him",
     "Search any player: who drafted him, for how much, and who finished each season with him."),
    ("season", "season", "#season", f"{YEAR} Season",
     f"Through week {WEEK}: standings, playoff odds, next week's preview and weekly scoreboards."),
]


def owner_stats(owner):
    rows = sorted([s for s in seasons if s["owner"] == owner], key=lambda s: s["season"])
    done = [s for s in rows if s["finish"] is not None]
    w = sum(s["wins"] or 0 for s in rows); l = sum(s["losses"] or 0 for s in rows)
    fins = [s["reg_season_finish"] for s in done if s["reg_season_finish"]]
    return {
        "rows": rows, "w": w, "l": l, "pct": w / ((w + l) or 1),
        "titles": sum(1 for s in done if s["finish"] == 1),
        "r1": sum((s.get("reg_season_1s") or 0) for s in done),
        "avg": sum(fins) / len(fins) if fins else None,
        "team": rows[-1]["team_name"], "since": rows[0]["season"], "last": rows[-1]["season"],
    }


CARD_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1200px;height:630px;background:#0c0f18;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;position:relative;overflow:hidden}
.bar{position:absolute;left:0;top:0;bottom:0;width:14px;background:#fcd34d}
.brand{position:absolute;left:70px;top:52px;font-size:22px;font-weight:800;letter-spacing:.22em;color:#64748b}
.url{position:absolute;right:60px;top:52px;font-size:22px;color:#475569}
.main{position:absolute;left:70px;right:60px;top:118px;display:flex;gap:40px;align-items:center}
.main.tab{top:190px}
h1{font-size:88px;line-height:1.02;font-weight:900;color:#f8fafc;letter-spacing:-.02em}
.sub{font-size:34px;color:#94a3b8;margin-top:14px;line-height:1.35;max-width:980px}
.team{font-style:italic}
.logo{width:200px;height:200px;border-radius:26px;background:#111520;object-fit:contain;flex-shrink:0}
.fb{width:200px;height:200px;border-radius:26px;background:#fcd34d;color:#3b2800;font-size:96px;font-weight:900;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.stats{position:absolute;left:70px;right:60px;bottom:56px;display:flex;gap:22px}
.stat{flex:1;background:#111520;border:2px solid #1e293b;border-radius:16px;padding:18px 24px;height:128px;white-space:nowrap}
.stat .k{font-size:17px;font-weight:700;letter-spacing:.12em;color:#64748b;text-transform:uppercase}
.stat .v{font-size:56px;font-weight:800;color:#fcd34d;margin-top:8px}
.pills{position:absolute;left:70px;right:60px;bottom:64px;display:flex;gap:14px;flex-wrap:wrap}
.pill{font-size:26px;font-weight:600;color:#cbd5e1;background:#111520;border:2px solid #1e293b;border-radius:40px;padding:12px 28px}
"""


def logo_html(owner, size=None):
    f = next(iter(sorted(LOGO_DIR.glob(f"{YEAR}/{slug(owner)}.*"))), None)
    st = f' style="width:{size}px;height:{size}px"' if size else ""
    return (f'<img class="logo" src="file://{f}"{st}>' if f else f'<div class="fb"{st}>{esc(owner.split("/")[0][:2])}</div>')


def card_html(kind, title, sub, owner=None, stats=None, pills=None, owner2=None):
    logo = ""
    if owner and owner2: logo = logo_html(owner, 150) + logo_html(owner2, 150)
    elif owner: logo = logo_html(owner)
    pl = "".join(f'<span class="pill">{esc(x)}</span>' for x in (pills or []))
    st = "".join(f'<div class="stat"><div class="k">{esc(k)}</div><div class="v">{esc(str(v))}</div></div>' for k, v in (stats or []))
    return (f"<!doctype html><meta charset='utf-8'><style>{CARD_CSS}</style><body><div class='bar'></div>"
            f"<div class='brand'>JMML FANTASY FOOTBALL</div><div class='url'>jmml.whohashim.com</div>"
            f"<div class='main {kind}'>{logo}<div><h1>{esc(title)}</h1><div class='sub'>{sub}</div></div></div>"
            f"<div class='stats'>{st}</div><div class='pills'>{pl}</div></body>")


def render(htm, out_png, tmp):
    f = tmp / (out_png.stem + ".html"); f.write_text(htm)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--window-size=1200,630", f"--screenshot={out_png}", f"file://{f}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def stub(out_dir, title, desc, img_name, path, js_dest):
    url = f"{SITE}/{path}/" if path else f"{SITE}/"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#0c0f18">
<meta property="og:type" content="website">
<meta property="og:site_name" content="JMML Fantasy Football">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/share/{img_name}.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<noscript><meta http-equiv="refresh" content="0;url=/"></noscript>
<script>{js_dest}</script>
</head><body style="background:#0c0f18;color:#94a3b8;font-family:system-ui,sans-serif;padding:40px">
<a href="/" style="color:#fcd34d">Open the JMML dashboard</a></body></html>
"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default=str(ROOT.parent)); out = Path(ap.parse_args().out)
    tmp = Path(tempfile.mkdtemp()); n = 0
    for key, path, hsh, title, desc in TABS:
        js = f"var q=new URLSearchParams(location.search),h='{hsh}';"
        if key == "whohashim": js += "if(q.get('p'))h+='/'+encodeURIComponent(q.get('p'));"
        if key == "rivalry": js += "if(q.get('a')&&q.get('b'))h+='/'+encodeURIComponent(q.get('a'))+'/'+encodeURIComponent(q.get('b'));"
        js += "location.replace('/'+h);"
        render(card_html("tab", title, esc(desc), pills=PILLS[key]), out / "share" / f"{path}.png", tmp)
        stub(out / path, f"{title} · JMML Fantasy Football", desc, path, path, js); n += 1
    for owner in meta["current_owners"]:
        s = owner_stats(owner); sl = slug(owner)
        stats = [("Record", f"{s['w']}–{s['l']}"), ("Win %", f"{s['pct']*100:.1f}%"), ("Titles", s["titles"]),
                 ("Reg Szn #1", s["r1"]), ("Avg Finish", f"{s['avg']:.1f}" if s["avg"] else "—")]
        sub = f"<span class='team'>{esc(s['team'])}</span> · in the league since {s['since']}"
        desc = (f"{owner}: {s['w']}–{s['l']} all-time ({s['pct']*100:.1f}%), {s['titles']} title{'s' if s['titles'] != 1 else ''}, "
                f"{s['r1']} regular-season #1{'s' if s['r1'] != 1 else ''}. Seasons, head-to-head and profit.")
        render(card_html("owner", owner, sub, owner=owner, stats=stats), out / "share" / f"owner-{sl}.png", tmp)
        js = f"location.replace('/#owner/{owner.replace('/', '%2F')}');"
        stub(out / "owner" / sl, f"{owner} · JMML Fantasy Football", desc, f"owner-{sl}", f"owner/{sl}", js); n += 1
    # one page + card per rivalry pair among current owners: rivalry/<a>/<b>/ (slug-sorted)
    cur = sorted(meta["current_owners"], key=slug)
    for a, b in itertools.combinations(cur, 2):
        g = [m for m in played if m["owner"] == a and m["opponent"] == b and m.get("opp_score") is not None]
        w = sum(1 for m in g if m["result"] == 1); l = len(g) - w
        pa = sum(m["score"] for m in g) / (len(g) or 1); pb = sum(m["opp_score"] for m in g) / (len(g) or 1)
        lead = f"{a} leads {w}\u2013{l}" if w > l else f"{b} leads {l}\u2013{w}" if l > w else f"Tied {w}\u2013{l}"
        stats = [("Series", f"{w}\u2013{l}"), ("Games", len(g)), (f"{a.split('/')[0]} avg", f"{pa:.1f}"), (f"{b.split('/')[0]} avg", f"{pb:.1f}")]
        title = f"{a} vs {b}"
        desc = f"{title}: {lead} over {len(g)} games, averaging {pa:.1f}\u2013{pb:.1f}. Every meeting, margin by game."
        name = f"rivalry-{slug(a)}-{slug(b)}"
        render(card_html("owner", title, "Head-to-head history", owner=a, owner2=b, stats=stats), out / "share" / f"{name}.png", tmp)
        js = f"location.replace('/#rivalry/{a.replace('/', '%2F')}/{b.replace('/', '%2F')}');"
        stub(out / "rivalry" / slug(a) / slug(b), f"{title} \u00b7 JMML Fantasy Football", desc, name, f"rivalry/{slug(a)}/{slug(b)}", js); n += 1
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {n} pages + cards to {out}")


if __name__ == "__main__":
    main()
