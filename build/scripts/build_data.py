#!/usr/bin/env python3
"""
Merge all data sources into clean processed JSON files for the dashboard.

Sources (in priority order):
  1. Excel WL Matrix 2  → matchups 2011-2025 (primary)
  2. Excel AllData       → season stats 2009-2025 (primary)
  3. ESPN API            → matchups 2019-2025 (fills any ESPN-only data; cross-validates)
  Coverage gap: 2009-2010 matchup data not available (season stats only)

Outputs:
  data/processed/seasons.json   — season-level stats per owner per year
  data/processed/matchups.json  — per-owner-per-week game rows
  data/processed/h2h.json       — head-to-head record matrix (all-time)
  data/processed/meta.json      — league metadata (owners, years, coverage)
"""

import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

import openpyxl

ROOT      = Path(__file__).parent.parent
EXCEL     = ROOT / "JMML Finishes - Sheets (1).xlsx"
ESPN_DIR  = ROOT / "data" / "raw" / "espn"
OUT_DIR   = ROOT / "data" / "processed"
TEMPLATE  = ROOT / "dashboard" / "template.html"
DASHBOARD = ROOT / "dashboard" / "index.html"
LOGO_DIR  = ROOT / "dashboard" / "logos"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _num(v, cast=float):
    try:
        return cast(v) if v is not None else None
    except (ValueError, TypeError):
        return None


# ── Load Excel ────────────────────────────────────────────────────────────────

def load_excel():
    print("Loading Excel workbook...")
    wb = openpyxl.load_workbook(str(EXCEL), data_only=True)

    # Season stats (AllData)
    ws_all = wb["AllData"]
    headers = [c.value for c in ws_all[1]]
    seasons_raw = []
    for row in ws_all.iter_rows(min_row=2, values_only=True):
        d = dict(zip(headers, row))
        if not d.get("Season"):
            continue
        seasons_raw.append({
            "season":             int(d["Season"]),
            "owner":              str(d["Owner"] or "").strip(),
            "team_name":          str(d["Team Name"] or "").strip(),
            "current_owner":      str(d.get("Current Owner") or "") == "Current Owner",
            "wins":               _num(d.get("Wins"), int),
            "losses":             _num(d.get("Losses"), int),
            "points_for":         _num(d.get("Final Points For")),
            "points_against":     _num(d.get("Final Points Against")),
            "finish":             _num(d.get("Finish"), int),
            "reg_season_finish":  _num(d.get("Reg Season Finish"), int),
            "playoff_finish":     _num(d.get("Playoff Finish"), int),
            "championships":      _num(d.get("Championships"), int),
            "playoff_appearances":_num(d.get("Playoff Appearances"), int),
            "reg_season_1s":      _num(d.get("Reg Season #1s"), int),
            "buy_in":             _num(d.get("Buy In")),
            "won":                _num(d.get("$ Won")),
            "profit":             _num(d.get("Profit")),
            "qb":                 str(d.get("QB") or "").strip(),
            "top_rb":             str(d.get("Top RB") or "").strip(),
            "top_wr":             str(d.get("Top WR") or "").strip(),
            "te":                 str(d.get("TE") or "").strip(),
            "rules":              str(d.get("Rules") or "").strip(),
            "pts_for_index":      _num(d.get("Points For Index")),
            "pts_against_index":  _num(d.get("Points Against Index")),
            "reg_season_pts_rank":_num(d.get("Regular Season Pts Rank"), int),
            "weekly_top6_scores": _num(d.get("Weekly Top 6 Scores")),
        })
    print(f"  AllData: {len(seasons_raw)} season rows, "
          f"{sorted(set(r['season'] for r in seasons_raw))[0]}–"
          f"{sorted(set(r['season'] for r in seasons_raw))[-1]}")

    # Matchups (WL Matrix 2)
    ws_wl = wb["WL Matrix 2"]
    wl_headers = [c.value for c in ws_wl[1]]
    matchups_raw = []
    for row in ws_wl.iter_rows(min_row=2, values_only=True):
        d = dict(zip(wl_headers, row))
        if not d.get("Year"):
            continue
        matchups_raw.append({
            "year":        int(d["Year"]),
            "week":        _num(d.get("Week Number"), int),
            "owner":       str(d.get("Owner") or "").strip(),
            "opponent":    str(d.get("Mapped Opponent") or "").strip(),
            "score":       _num(d.get("Owner's Score")),
            "opp_score":   _num(d.get("Opponent's Score")),
            "result":      _num(d.get("Result"), int),   # 1=win, 0=loss
            "game_type":   str(d.get("Game Type") or "").strip(),
            "score_rank":  _num(d.get("Weekly Score Rank"), int),
            "avg_score":   _num(d.get("Annual avg score")),
            "score_index": _num(d.get("Score Index")),
            "source":      "excel",
        })
    wl_years = sorted(set(m["year"] for m in matchups_raw))
    print(f"  WL Matrix 2: {len(matchups_raw)} matchup rows, "
          f"{wl_years[0]}–{wl_years[-1]}")

    return seasons_raw, matchups_raw


# ── Load ESPN ─────────────────────────────────────────────────────────────────

def load_espn():
    espn_matchups = []
    for f in sorted(ESPN_DIR.glob("*.json")):
        data = json.loads(f.read_text())
        year = data["year"]
        # Build team_name → owner lookup (ESPN team names = sheet team names)
        for m in data.get("matchups", []):
            espn_matchups.append({
                "year":       year,
                "week":       m.get("week"),
                "home_team":  m.get("home_team_name"),
                "away_team":  m.get("away_team_name"),
                "home_score": m.get("home_score"),
                "away_score": m.get("away_score"),
                "is_playoff": m.get("is_playoff", False),
            })
    if espn_matchups:
        espn_years = sorted(set(m["year"] for m in espn_matchups))
        print(f"  ESPN: {len(espn_matchups)} matchup rows, "
              f"{espn_years[0]}–{espn_years[-1]}")
    return espn_matchups


# ── Build head-to-head matrix ─────────────────────────────────────────────────

def build_h2h(matchups):
    """All-time head-to-head record: {owner: {opponent: {wins, losses, pf, pa}}}"""
    h2h = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0, "pf": 0.0, "pa": 0.0}))
    for m in matchups:
        o, opp = m["owner"], m["opponent"]
        if not o or not opp or opp == "":
            continue
        if not m["score"]:   # unplayed (future) games have no score; don't count them as losses
            continue
        rec = h2h[o][opp]
        rec["wins"]   += m["result"] or 0
        rec["losses"] += 1 - (m["result"] or 0)
        rec["pf"]     += m["score"] or 0
        rec["pa"]     += m["opp_score"] or 0
    # Flatten to list for JSON
    out = []
    for owner, opponents in h2h.items():
        for opp, rec in opponents.items():
            out.append({"owner": owner, "opponent": opp, **rec})
    return out


# ── Build meta ────────────────────────────────────────────────────────────────

def build_meta(seasons, matchups):
    owners = sorted(set(s["owner"] for s in seasons if s["owner"]))
    years  = sorted(set(s["season"] for s in seasons))
    current_owners = sorted(set(
        s["owner"] for s in seasons if s["current_owner"] and s["season"] == max(years)
    ))
    matchup_years = sorted(set(m["year"] for m in matchups))
    return {
        "owners":         owners,
        "current_owners": current_owners,
        "years":          years,
        "matchup_years":  matchup_years,
        "coverage_note":  "Season stats: 2009-2026. Game-level matchups: 2011-2026 (Excel). ESPN supplement: 2019-2025.",
    }


# ── Player history (from fetch_rosters.py) ───────────────────────────────────

PLAYERS_CSV = OUT_DIR / "player_seasons.csv"
PLAYER_COLS = ["season", "player", "espn_player_id", "position", "nfl_team", "drafted_by", "drafted_team",
               "draft_price", "draft_pick", "final_owner", "final_team", "lineup_slot", "acquired", "season_points", "points_per_game"]
_INT = {"season", "espn_player_id", "draft_price", "draft_pick"}


def load_players():
    rows = []
    if PLAYERS_CSV.exists():
        for r in csv.DictReader(open(PLAYERS_CSV)):
            row = []
            for c in PLAYER_COLS:
                v = r.get(c, "")
                if c in _INT:
                    row.append(int(float(v)) if v != "" else None)
                elif c in ("season_points", "points_per_game"):
                    row.append(float(v) if v != "" else None)
                else:
                    row.append(v)
            rows.append(row)
    return {"cols": PLAYER_COLS, "rows": rows}


# ── Team logos ────────────────────────────────────────────────────────────────

def build_logos(owners):
    """{ "2026|Owner": "logos/2026/owner.png" } for every logo file on disk."""
    slug = lambda o: re.sub(r"[^a-z0-9]+", "-", o.lower()).strip("-")
    by_slug = {slug(o): o for o in owners}
    out = {}
    for f in sorted(LOGO_DIR.glob("*/*")):
        owner = by_slug.get(f.stem)
        if owner and f.parent.name.isdigit():
            out[f"{f.parent.name}|{owner}"] = f"logos/{f.parent.name}/{f.name}"
    return out


def apply_final_live(matchups):
    """If live.json is flagged final and the sheet still has 0-0 rows for that week, fill in ESPN's scores."""
    f = OUT_DIR / "live.json"
    if not f.exists(): return
    live = json.load(open(f))
    if live.get("prev_final"):
        live = {"year": live["year"], "final": True, **live["prev_final"]}
    if not live.get("final"): return
    rows = [m for m in matchups if m["year"] == live["year"] and m["week"] == live["week"]]
    if not rows or any((m["score"] or 0) or (m["opp_score"] or 0) for m in rows): return
    pts = {}
    for g in live["games"]:
        pts[(g["a"], g["b"])] = (g["a_pts"], g["b_pts"])
        pts[(g["b"], g["a"])] = (g["b_pts"], g["a_pts"])
    for m in rows:
        if (m["owner"], m["opponent"]) in pts:
            m["score"], m["opp_score"] = pts[(m["owner"], m["opponent"])]
            m["result"] = 1 if m["score"] > m["opp_score"] else 0
            m["source"] = "espn-final"
    print(f"  Applied final ESPN scores for {live['year']} week {live['week']}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seasons, matchups = load_excel()
    espn = load_espn()
    apply_final_live(matchups)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # seasons.json
    (OUT_DIR / "seasons.json").write_text(json.dumps(seasons, indent=2, default=str))
    print(f"  → seasons.json ({len(seasons)} rows)")

    # matchups.json (Excel WL Matrix 2 is authoritative)
    (OUT_DIR / "matchups.json").write_text(json.dumps(matchups, indent=2))
    print(f"  → matchups.json ({len(matchups)} rows)")

    # h2h.json
    h2h = build_h2h(matchups)
    (OUT_DIR / "h2h.json").write_text(json.dumps(h2h, indent=2))
    print(f"  → h2h.json ({len(h2h)} owner-opponent pairs)")

    # meta.json
    meta = build_meta(seasons, matchups)
    (OUT_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"  → meta.json ({len(meta['owners'])} owners, {len(meta['years'])} seasons)")

    # Coverage summary
    print("\nCoverage:")
    print(f"  Season stats:  {meta['years'][0]}–{meta['years'][-1]}")
    print(f"  Matchup data:  {meta['matchup_years'][0]}–{meta['matchup_years'][-1]}")
    print(f"  Current owners ({len(meta['current_owners'])}): {', '.join(meta['current_owners'])}")

    # Embed data into dashboard
    print("\nBuilding dashboard...")
    if TEMPLATE.exists():
        html = TEMPLATE.read_text()
        html = html.replace("__SEASONS__",  json.dumps(seasons,  separators=(",", ":")))
        html = html.replace("__MATCHUPS__", json.dumps(matchups, separators=(",", ":")))
        html = html.replace("__H2H__",      json.dumps(h2h,      separators=(",", ":")))
        html = html.replace("__META__",     json.dumps(meta,     separators=(",", ":")))
        html = html.replace("__PLAYERS__",  json.dumps(load_players(), separators=(",", ":")))
        html = html.replace("__LOGOS__",    json.dumps(build_logos(meta["owners"]), separators=(",", ":")))
        live_f = OUT_DIR / "live.json"
        html = html.replace("__LIVE__",     json.dumps(json.load(open(live_f)) if live_f.exists() else None, separators=(",", ":")))
        html = html.replace("__UPDATED__",  date.today().isoformat())
        DASHBOARD.write_text(html)
        print(f"  → dashboard/index.html ({DASHBOARD.stat().st_size // 1024} KB)")
    else:
        print(f"  WARNING: template not found at {TEMPLATE}")


if __name__ == "__main__":
    main()
