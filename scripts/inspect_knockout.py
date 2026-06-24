#!/usr/bin/env python3
"""
One-off diagnostic: inspect what API-Football returns for the 2026 World Cup,
specifically the round labels and knockout structure, so we build the bracket
logic against the REAL data shape rather than assumptions.

Run via the workflow (same secret) once; read the printed output.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from collections import Counter, defaultdict

KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
WC_LEAGUE_ID = "1"
SEASON = "2026"
API_URL = f"https://v3.football.api-sports.io/fixtures?league={WC_LEAGUE_ID}&season={SEASON}"


def main():
    if not KEY:
        print("ERROR: API_FOOTBALL_KEY not set."); sys.exit(1)
    req = urllib.request.Request(API_URL, headers={"x-apisports-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        print("ERROR:", e); sys.exit(0)

    if isinstance(data.get("errors"), dict) and data["errors"]:
        print("API errors:", data["errors"]); sys.exit(0)

    fixtures = data.get("response", []) or []
    print(f"Total fixtures returned: {len(fixtures)}\n")

    # 1) What round labels exist, and how many fixtures + statuses in each?
    rounds = defaultdict(lambda: {"count": 0, "statuses": Counter()})
    for fx in fixtures:
        rnd = (fx.get("league") or {}).get("round") or "(none)"
        st = ((fx.get("fixture") or {}).get("status") or {}).get("short") or "?"
        rounds[rnd]["count"] += 1
        rounds[rnd]["statuses"][st] += 1

    print("=== ROUND LABELS (exact strings) ===")
    for rnd in sorted(rounds):
        info = rounds[rnd]
        sts = ", ".join(f"{k}:{v}" for k, v in info["statuses"].items())
        print(f"  '{rnd}'  -> {info['count']} fixtures  [{sts}]")

    # 2) Show a few knockout-looking fixtures in detail (anything not 'Group')
    print("\n=== SAMPLE NON-GROUP FIXTURES ===")
    shown = 0
    for fx in fixtures:
        rnd = (fx.get("league") or {}).get("round") or ""
        if "group" in rnd.lower():
            continue
        teams = fx.get("teams") or {}
        h = (teams.get("home") or {}).get("name")
        a = (teams.get("away") or {}).get("name")
        st = ((fx.get("fixture") or {}).get("status") or {}).get("short")
        date = (fx.get("fixture") or {}).get("date")
        print(f"  [{rnd}] {h} vs {a}  status={st}  {date}")
        shown += 1
        if shown >= 20:
            break
    if shown == 0:
        print("  (no non-group fixtures yet — knockout bracket may not be populated)")


if __name__ == "__main__":
    main()
