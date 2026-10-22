#!/usr/bin/env python3
"""
Weekly player scores by team from ESPN (league 88024, public, 2019+) -> ../weekly/<year>.json (served at /weekly/<year>.json)

Usage: fetch_weekly_players.py [--current | year ...]   (default: 2019 through the current season)

One file per season:
  {season, generated_utc, weeks: [..], cols: [week, owner, player, position, slot, started, points, nfl_team], rows: [[...], ...]}
slot is the lineup slot that week (QB, RB, WR, TE, FLEX, D/ST, K, Bench, IR); started = 1 if the player counted toward the score.
Owner names come from data/processed/final_rosters.csv (ESPN team id -> owner). Each team-week's started players are
checked against the team's ESPN week total. Only the regular season and the winners bracket are included.
"""
import csv, json, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

LEAGUE = 88024
ROOT = Path(__file__).parent.parent
OUT = ROOT.parent / "weekly"
CURRENT = 2026
API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{y}/segments/0/leagues/%d" % LEAGUE
POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "Bench", 21: "IR", 23: "FLEX", 3: "RB/WR", 5: "WR/TE", 7: "OP", 24: "RB/WR/TE"}
PRO = {0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC",
       13: "LV", 14: "LAR", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
       25: "SF", 26: "SEA", 27: "TB", 28: "WSH", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}
NOT_STARTED = {"Bench", "IR"}
COLS = ["week", "owner", "player", "position", "slot", "started", "points", "nfl_team"]


def owners_for(year):
    m = {}
    for r in csv.DictReader(open(ROOT / "data" / "processed" / "final_rosters.csv")):
        if r["season"] == str(year):
            m[int(r["espn_team_id"])] = r["owner"]
    return m


def fetch_season(year):
    own = owners_for(year)
    url = API.format(y=year)
    head = requests.get(url, params={"view": "mMatchupScore"}, timeout=90)
    head.raise_for_status()
    last = head.json()["status"]["currentMatchupPeriod"] if year == CURRENT else 18
    rows, weeks, bad = [], [], 0
    for wk in range(1, last + 1):
        r = requests.get(url, params=[("view", "mBoxscore"), ("view", "mMatchupScore"), ("scoringPeriodId", wk), ("matchupPeriodId", wk)], timeout=120)
        r.raise_for_status()
        games = [g for g in r.json().get("schedule", [])
                 if g.get("matchupPeriodId") == wk and "away" in g and g.get("playoffTierType") in ("NONE", "WINNERS_BRACKET")]
        got = 0
        for g in games:
            for side in ("home", "away"):
                t = g[side]
                entries = (t.get("rosterForCurrentScoringPeriod") or {}).get("entries") or []
                if t["teamId"] not in own:
                    sys.exit(f"{year} wk{wk}: no owner for ESPN team {t['teamId']}")
                started = 0.0
                for e in entries:
                    p = e["playerPoolEntry"]["player"]
                    slot = SLOT.get(e["lineupSlotId"], str(e["lineupSlotId"]))
                    pts = round(e["playerPoolEntry"].get("appliedStatTotal") or 0, 2)
                    st = 0 if slot in NOT_STARTED else 1
                    started += pts if st else 0
                    rows.append([wk, own[t["teamId"]], p["fullName"], POS.get(p["defaultPositionId"], str(p["defaultPositionId"])), slot, st, pts,
                                 PRO.get(p.get("proTeamId"), str(p.get("proTeamId")))])
                    got += 1
                if entries and abs(started - (t.get("totalPoints") or 0)) > 0.06:
                    bad += 1
                    print(f"  {year} wk{wk} {own[t['teamId']]}: started {started:.2f} vs ESPN {t.get('totalPoints')}", file=sys.stderr)
        if got and any(r[0] == wk and r[5] and r[6] for r in rows):
            weeks.append(wk)
        elif year == CURRENT:
            rows = [x for x in rows if x[0] != wk]  # week not played yet
    out = {"season": year, "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "weeks": weeks, "cols": COLS, "rows": rows}
    OUT.mkdir(exist_ok=True)
    (OUT / f"{year}.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"{year}: weeks {weeks[0]}-{weeks[-1]}, {len(rows)} rows, {bad} team-weeks off by more than 0.06", file=sys.stderr)


if __name__ == "__main__":
    args = sys.argv[1:]
    years = [CURRENT] if "--current" in args else [int(a) for a in args] or list(range(2019, CURRENT + 1))
    for y in years:
        fetch_season(y)
