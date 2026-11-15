#!/usr/bin/env python3
"""Sanity-check the freshly built dashboard/data.json before it is published. Exits 1 on any problem."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
YEAR = 2026
errs = []
new = json.load(open(ROOT / "dashboard/data.json"))
if (ROOT / "dashboard/index.html").stat().st_size < 500_000: errs.append("dashboard/index.html is suspiciously small")

owners26 = {r['owner'] for r in new['seasons'] if r['season'] == YEAR}
if len(owners26) != 12: errs.append(f"expected 12 owners in {YEAR} seasons, found {len(owners26)}")

live = new.get('live') or {}
games = live.get('games', [])
if live.get('year') != YEAR: errs.append(f"live year is {live.get('year')}, expected {YEAR}")
if not 1 <= (live.get('week') or 0) <= 18: errs.append(f"live week out of range: {live.get('week')}")
if len(games) != 6: errs.append(f"expected 6 live games, found {len(games)}")
in_games = [o for g in games for o in (g['a'], g['b'])]
if sorted(in_games) != sorted(owners26): errs.append(f"live games do not cover each owner exactly once: {sorted(in_games)}")

# never publish a dataset that lost rows vs. what is live now
try:
    old = json.load(open(ROOT.parent / "data.json"))
    for k in ('seasons', 'matchups'):
        if len(new[k]) < len(old[k]): errs.append(f"{k} shrank: {len(old[k])} -> {len(new[k])}")
except FileNotFoundError:
    pass

if errs:
    print("::error title=Build validation failed::" + "; ".join(errs))
    sys.exit(1)
print(f"validation ok: {len(owners26)} owners, {len(games)} games, week {live['week']}")
