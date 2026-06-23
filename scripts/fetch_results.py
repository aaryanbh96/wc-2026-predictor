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

from model import Model

TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
# football-data.org competition code for the FIFA World Cup
COMP = "WC"
# No status filter: we want finished results AND upcoming fixtures in one call.
URL = f"https://api.football-data.org/v4/competitions/{COMP}/matches"
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
    "Cape Verde Islands": "Cabo Verde",
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
    matches = []        # finished, with scores
    upcoming = []       # scheduled/timed, no scores yet
    live = []           # in-progress (kicked off, not finished)
    unmatched = set()
    for m in data.get("matches", []):
        status = m.get("status")
        home = norm((m.get("homeTeam") or {}).get("name"))
        away = norm((m.get("awayTeam") or {}).get("name"))
        # Skip fixtures whose teams aren't set yet (e.g. "Winner Group A" placeholders).
        if not home or not away:
            continue
        if status == "FINISHED":
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
        elif status in ("IN_PLAY", "PAUSED", "SUSPENDED"):
            if home in VALID and away in VALID:
                live.append({
                    "id": m.get("id"),
                    "utc": m.get("utcDate"),
                    "home": home, "away": away,
                })
        elif status in ("SCHEDULED", "TIMED"):
            # Only include real team-vs-team fixtures the page knows about.
            if home in VALID and away in VALID:
                upcoming.append({
                    "id": m.get("id"),
                    "utc": m.get("utcDate"),
                    "home": home, "away": away,
                })

    matches.sort(key=lambda x: x.get("utc") or "")
    upcoming.sort(key=lambda x: x.get("utc") or "")
    live.sort(key=lambda x: x.get("utc") or "")

    # ---- freeze pre-match predictions using the ported model ----
    # Load any predictions already frozen in the previous results.json so a match
    # keeps the call the model made while it was still upcoming (no hindsight).
    prev_pred = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT))
            for mm in (prev.get("matches", []) + prev.get("upcoming", [])):
                if mm.get("predicted") and mm.get("id") is not None:
                    prev_pred[mm["id"]] = mm["predicted"]
        except Exception:
            prev_pred = {}

    model = Model()
    # Replay finished matches in date order. For each, the honest pre-match prediction
    # is the one computed from ratings BEFORE this match is learned.
    for mm in matches:
        if mm["home"] in model.rating and mm["away"] in model.rating:
            # prefer a prediction frozen earlier (while the match was upcoming)
            if mm["id"] in prev_pred:
                mm["predicted"] = prev_pred[mm["id"]]
            elif not model.is_seed(mm["home"], mm["hg"], mm["ag"], mm["away"]):
                p = model.predict(mm["home"], mm["away"], neutral=True)
                if p:
                    mm["predicted"] = {"pA": round(p[0], 4), "pD": round(p[1], 4), "pB": round(p[2], 4)}
            # learn it (skip seed dups so the page's seed isn't double-counted)
            if not model.is_seed(mm["home"], mm["hg"], mm["ag"], mm["away"]):
                model.learn(mm["home"], mm["hg"], mm["ag"], mm["away"], neutral=True)
        # grade the frozen prediction if present
        if mm.get("predicted"):
            pr = mm["predicted"]
            top = max(pr["pA"], pr["pB"], pr["pD"])
            pick = "A" if top == pr["pA"] else ("B" if top == pr["pB"] else "D")
            outcome = "A" if mm["hg"] > mm["ag"] else ("B" if mm["hg"] < mm["ag"] else "D")
            mm["hit"] = (pick == outcome)

    # Freeze predictions for upcoming fixtures at current (post-finished) ratings.
    for mm in upcoming:
        if mm["id"] in prev_pred:
            mm["predicted"] = prev_pred[mm["id"]]
        elif mm["home"] in model.rating and mm["away"] in model.rating:
            p = model.predict(mm["home"], mm["away"], neutral=True)
            if p:
                mm["predicted"] = {"pA": round(p[0], 4), "pD": round(p[1], 4), "pB": round(p[2], 4)}

    # Freeze predictions for live (in-progress) matches too. Prefer the prediction
    # frozen while the match was still upcoming, so the call is genuinely pre-match.
    for mm in live:
        if mm["id"] in prev_pred:
            mm["predicted"] = prev_pred[mm["id"]]
        elif mm["home"] in model.rating and mm["away"] in model.rating:
            p = model.predict(mm["home"], mm["away"], neutral=True)
            if p:
                mm["predicted"] = {"pA": round(p[0], 4), "pD": round(p[1], 4), "pB": round(p[2], 4)}

    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "matches": matches,
        "upcoming": upcoming,
        "live": live,
    }

    # ---- daily champion snapshot (locked once per PT day) ----
    # The day "closes" its pick the first time the Action runs after that PT day's
    # matches are done; we snapshot the current top-5 championship odds and keep one
    # entry per PT date. Earlier days are preserved unchanged.
    daily = []
    if os.path.exists(OUT):
        try:
            daily = json.load(open(OUT)).get("daily", []) or []
        except Exception:
            daily = []
    try:
        from zoneinfo import ZoneInfo
        pt_today = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")
    except Exception:
        pt_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # How many matches are finished as of now — used so the snapshot reflects the
    # day's completed results.
    fc = model.forecast(20000)
    top5 = [{"team": t, "win": round(p, 4)} for t, p in fc[:8]]
    snapshot = {"date": pt_today, "games_played": len(matches), "top": top5}

    existing = next((d for d in daily if d.get("date") == pt_today), None)
    if existing:
        # update today's entry as more of today's games finish
        existing.update(snapshot)
    else:
        daily.append(snapshot)
    daily.sort(key=lambda d: d.get("date", ""))
    out["daily"] = daily

    # Only rewrite if the substantive data changed (ignore the timestamp), so the
    # workflow's git-diff check doesn't commit noise every hour.
    old = None
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT))
            old = (prev.get("matches"), prev.get("upcoming"), prev.get("live"))
        except Exception:
            old = None
    if old == (matches, upcoming, live):
        print(f"No change: {len(matches)} finished, {len(live)} live, {len(upcoming)} upcoming.")
        return

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(matches)} finished + {len(upcoming)} upcoming matches to {OUT}.")
    if unmatched:
        print("WARNING: unmatched team names (add to NAME_MAP): "
              + ", ".join(sorted(unmatched)), file=sys.stderr)


if __name__ == "__main__":
    main()
