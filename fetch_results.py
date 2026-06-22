#!/usr/bin/env python3
"""
Fetch finished 2026 World Cup matches from football-data.org and write results.json.

Requires env var FOOTBALL_DATA_TOKEN (set as a GitHub Actions secret).
Free tier: 10 requests/minute. We make one request, so we're well within limits.

Output shape (results.json):
{
  "updated": "2026-06-22T18:00:00Z",
  "matches": [
    {"id": 537001, "utc": "2026-06-13T16:00:00Z",
     "home": "Canada", "away": "Qatar", "hg": 6, "ag": 0}
  ]
}

The page is responsible for matching these to its team names (it has its own
normalization map) and for skipping matches it has already settled (by id).
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
# football-data.org competition code for the FIFA World Cup
COMP = "WC"
URL = f"https://api.football-data.org/v4/competitions/{COMP}/matches?status=FINISHED"
OUT = "results.json"

# Normalize football-data.org names -> the names used in the predictor page.
# Extend this if the Action logs an "unmatched" warning for a team.
NAME_MAP = {
    "Iran": "IR Iran",
    "South Korea": "Korea Republic",
    "Republic of Korea": "Korea Republic",
    "Turkey": "Türkiye",
    "Ivory Coast": "Côte d'Ivoire",
    "Cape Verde": "Cabo Verde",
    "DR Congo": "Congo DR",
    "Curacao": "Curaçao",
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Czech Republic": "Czechia",
    "United States": "USA",
    "USMNT": "USA",
}

# The 48 valid team names in the predictor, for a sanity warning.
VALID = {
    "Mexico","Korea Republic","Czechia","South Africa","Canada","Switzerland",
    "Bosnia and Herzegovina","Qatar","Brazil","Morocco","Scotland","Haiti","USA",
    "Paraguay","Australia","Türkiye","Germany","Ecuador","Côte d'Ivoire","Curaçao",
    "Netherlands","Japan","Sweden","Tunisia","Egypt","Belgium","IR Iran","New Zealand",
    "Spain","Uruguay","Cabo Verde","Saudi Arabia","France","Norway","Senegal","Iraq",
    "Argentina","Austria","Algeria","Jordan","Colombia","Congo DR","Portugal",
    "Uzbekistan","England","Ghana","Panama","Croatia",
}


def norm(name: str) -> str:
    name = (name or "").strip()
    return NAME_MAP.get(name, name)


def fetch():
    if not TOKEN:
        print("ERROR: FOOTBALL_DATA_TOKEN is not set.", file=sys.stderr)
        sys.exit(1)
    req = urllib.request.Request(URL, headers={"X-Auth-Token": TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print(f"ERROR: HTTP {e.code} from football-data.org: {body}", file=sys.stderr)
        # Don't fail the whole workflow on a transient API hiccup; exit 0 with no change.
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(0)


def main():
    data = fetch()
    matches = []
    unmatched = set()
    for m in data.get("matches", []):
        if m.get("status") != "FINISHED":
            continue
        home = norm((m.get("homeTeam") or {}).get("name"))
        away = norm((m.get("awayTeam") or {}).get("name"))
        ft = (m.get("score") or {}).get("fullTime") or {}
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None or ag is None:
            continue
        if home not in VALID:
            unmatched.add(home)
        if away not in VALID:
            unmatched.add(away)
        matches.append({
            "id": m.get("id"),
            "utc": m.get("utcDate"),
            "home": home, "away": away,
            "hg": int(hg), "ag": int(ag),
        })

    matches.sort(key=lambda x: x.get("utc") or "")
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matches": matches,
    }

    # Only rewrite if the match data actually changed (ignore the timestamp),
    # so the workflow's git-diff check doesn't commit noise every hour.
    old_matches = None
    if os.path.exists(OUT):
        try:
            old_matches = json.load(open(OUT)).get("matches")
        except Exception:
            old_matches = None
    if old_matches == matches:
        print(f"No change: {len(matches)} finished matches.")
        return

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(matches)} finished matches to {OUT}.")
    if unmatched:
        print("WARNING: unmatched team names (add to NAME_MAP): "
              + ", ".join(sorted(unmatched)), file=sys.stderr)


if __name__ == "__main__":
    main()
