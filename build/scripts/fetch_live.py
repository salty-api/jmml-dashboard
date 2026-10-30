#!/usr/bin/env python3
"""
Pull the in-progress week's live scores from ESPN (league 88024) -> data/processed/live.json
  {year, week, updated, games: [{a, b, a_pts, b_pts, a_proj, b_proj}]}   (a/b are owner names)
Rerun any time during the week, then rerun build_data.py.
"""
import json, re, sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import requests

ROOT = Path(__file__).parent.parent
YEAR = 2026
API = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/segments/0/leagues/88024"
norm = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())

d = requests.get(API, params={"view": ["mMatchupScore", "mTeam"]}, timeout=60).json()
week = d['status']['currentMatchupPeriod']
seasons = json.load(open(ROOT / "data/processed/seasons.json"))
matchups = json.load(open(ROOT / "data/processed/matchups.json"))
sheet = {norm(r['team_name']): r['owner'] for r in seasons if r['season'] == YEAR}
owner = {}
for t in d['teams']:
    n = norm(t.get('name'))
    o = sheet.get(n) or next((v for k, v in sheet.items() if k and (k in n or n in k)), None)
    if o: owner[t['id']] = o
# unmatched teams: resolve by elimination against the sheet's schedule for this week
sched = {frozenset((m['owner'], m['opponent'])) for m in matchups if m['year'] == YEAR and m['week'] == week and m['opponent']}
games = []
for s in d['schedule']:
    if s['matchupPeriodId'] != week or 'away' not in s: continue
    h, a = s['home'], s['away']
    games.append((h, a))
missing = [t['id'] for t in d['teams'] if t['id'] not in owner]
if len(missing) == 1:   # one team renamed on ESPN: it is the one owner left over
    left = set(sheet.values()) - set(owner.values())
    if len(left) == 1:
        owner[missing[0]] = left.pop(); missing = []
if missing:
    sys.exit(f"could not map ESPN teams to owners: {missing}")
out = []
for h, a in games:
    pair = frozenset((owner[h['teamId']], owner[a['teamId']]))
    if pair not in sched: sys.exit(f"ESPN pairing {sorted(pair)} not in sheet schedule for week {week}")
    out.append({'a': owner[h['teamId']], 'b': owner[a['teamId']],
                'a_pts': round(h.get('totalPointsLive', h.get('totalPoints', 0)), 2),
                'b_pts': round(a.get('totalPointsLive', a.get('totalPoints', 0)), 2)})
res = {'year': YEAR, 'week': week, 'updated': datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M PT'), 'games': out}
# Final scores for past weeks the sheet hasn't been filled in for: ESPN rolls to the next matchup
# period Monday night, so carry ESPN's final scores so the recap and standings stay current.
finals = []
for prev in range(1, week):
    prev_rows = [m for m in matchups if m['year'] == YEAR and m['week'] == prev]
    # rows already patched from ESPN (source espn-final) don't count as the sheet being filled in
    if prev_rows and not any(((m['score'] or 0) or (m['opp_score'] or 0)) and m.get('source') != 'espn-final' for m in prev_rows):
        pg = [s for s in d['schedule'] if s['matchupPeriodId'] == prev and 'away' in s]
        if pg and all(s.get('winner') in ('HOME', 'AWAY', 'TIE') for s in pg):
            finals.append({'week': prev, 'games': [
                {'a': owner[s['home']['teamId']], 'b': owner[s['away']['teamId']],
                 'a_pts': round(s['home'].get('totalPoints', 0), 2), 'b_pts': round(s['away'].get('totalPoints', 0), 2)} for s in pg]})
if finals:
    res['prev_final'] = finals[-1]   # latest, kept for the recap
    res['prev_finals'] = finals
(ROOT / "data/processed/live.json").write_text(json.dumps(res, indent=2))
print(f"week {week}: {len(out)} games"); [print(f"  {g['a']} {g['a_pts']} - {g['b_pts']} {g['b']}") for g in out]
