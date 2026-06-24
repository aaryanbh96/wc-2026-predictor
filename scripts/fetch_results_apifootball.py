#!/usr/bin/env python3
"""
Fetch 2026 World Cup matches from API-Football (api-football.com) and write results.json.

Why API-Football: football-data.org's free tier was too slow on live/finished status.
API-Football gives proper in-play status and faster updates.

Requires env var API_FOOTBALL_KEY (set as a GitHub Actions secret).

Free tier: 100 requests/day. We make ONE request per run. At a 15-min trigger that's
96 requests/day — just under the limit. If you hit the cap, widen the trigger interval
(e.g. every 20 min = 72/day) or upgrade the plan.

Endpoint (direct API-Football, not RapidAPI):
  GET https://v3.football.api-sports.io/fixtures?league=<WC_LEAGUE_ID>&season=2026
  Header: x-apisports-key: <API_FOOTBALL_KEY>

Status short codes:
  NS = not started; 1H/HT/2H/ET/BT/P/LIVE = in progress; FT/AET/PEN = finished.

Output shape is unchanged from before (matches / live / upcoming, each with frozen
predictions; plus a daily champion snapshot), so the page needs no changes.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

from model import Model

KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
# FIFA World Cup league id on API-Football is 1. Season 2026.
# If the field comes back empty, double-check these two values in your dashboard.
WC_LEAGUE_ID = "1"
SEASON = "2026"
# Genuine pre-match calls began when the live pipeline started freezing predictions
# for upcoming matches. Anything that kicked off before this is backfilled history
# (computed after the fact) and must not count toward the model's scored record.
GENUINE_FROM_UTC = "2026-06-22T17:00:00"
API_URL = f"https://v3.football.api-sports.io/fixtures?league={WC_LEAGUE_ID}&season={SEASON}"
OUT = "results.json"

LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}
UPCOMING_STATUSES = {"NS", "TBD"}

# API-Football team name -> the names used in the predictor page.
NAME_MAP = {
    "USA": "USA",
    "United States": "USA",
    "South Korea": "Korea Republic",
    "Korea Republic": "Korea Republic",
    "Iran": "IR Iran",
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye",
    "Ivory Coast": "Côte d'Ivoire",
    "Cape Verde": "Cabo Verde",
    "Cape Verde Islands": "Cabo Verde",
    "Cabo Verde": "Cabo Verde",
    "DR Congo": "Congo DR",
    "Congo DR": "Congo DR",
    "Czech Republic": "Czechia",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Bosnia": "Bosnia and Herzegovina",
    "Curacao": "Curaçao",
    "Cote d'Ivoire": "Côte d'Ivoire",
    "Ivory Coast": "Côte d'Ivoire",
}

VALID = {
    "Mexico", "Korea Republic", "Czechia", "South Africa", "Canada", "Switzerland",
    "Bosnia and Herzegovina", "Qatar", "Brazil", "Morocco", "Scotland", "Haiti", "USA",
    "Paraguay", "Australia", "Türkiye", "Germany", "Ecuador", "Côte d'Ivoire", "Curaçao",
    "Netherlands", "Japan", "Sweden", "Tunisia", "Egypt", "Belgium", "IR Iran", "New Zealand",
    "Spain", "Uruguay", "Cabo Verde", "Saudi Arabia", "France", "Norway", "Senegal", "Iraq",
    "Argentina", "Austria", "Algeria", "Jordan", "Colombia", "Congo DR", "Portugal",
    "Uzbekistan", "England", "Ghana", "Panama", "Croatia",
}


def norm(name):
    name = (name or "").strip()
    return NAME_MAP.get(name, name)


def fetch():
    if not KEY:
        print("ERROR: API_FOOTBALL_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    req = urllib.request.Request(API_URL, headers={"x-apisports-key": KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print(f"ERROR: HTTP {e.code} from API-Football: {body}", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(0)


def main():
    data = fetch()

    # API-Football wraps errors in a top-level "errors" object even on HTTP 200.
    if isinstance(data.get("errors"), dict) and data["errors"]:
        print(f"API-Football returned errors: {data['errors']}", file=sys.stderr)
        # don't clobber a good file on a transient API error
        sys.exit(0)

    fixtures = data.get("response", []) or []

    matches, live, upcoming = [], [], []
    unmatched = set()

    for fx in fixtures:
        fixture = fx.get("fixture") or {}
        teams = fx.get("teams") or {}
        goals = fx.get("goals") or {}
        status = ((fixture.get("status") or {}).get("short")) or ""
        fid = fixture.get("id")
        utc = fixture.get("date")  # ISO8601 with offset
        home = norm((teams.get("home") or {}).get("name"))
        away = norm((teams.get("away") or {}).get("name"))
        if not home or not away:
            continue

        if status in FINISHED_STATUSES:
            hg, ag = goals.get("home"), goals.get("away")
            if hg is None or ag is None:
                continue
            if home not in VALID:
                unmatched.add(home)
            if away not in VALID:
                unmatched.add(away)
            matches.append({"id": fid, "utc": utc, "home": home, "away": away,
                            "hg": int(hg), "ag": int(ag)})
        elif status in LIVE_STATUSES:
            if home in VALID and away in VALID:
                live.append({"id": fid, "utc": utc, "home": home, "away": away})
        elif status in UPCOMING_STATUSES:
            if home in VALID and away in VALID:
                upcoming.append({"id": fid, "utc": utc, "home": home, "away": away})

    matches.sort(key=lambda x: x.get("utc") or "")
    live.sort(key=lambda x: x.get("utc") or "")
    upcoming.sort(key=lambda x: x.get("utc") or "")

    # ---- freeze pre-match predictions (same logic as before) ----
    prev_pred = {}
    if os.path.exists(OUT):
        try:
            prev = json.load(open(OUT))
            for mm in (prev.get("matches", []) + prev.get("upcoming", []) + prev.get("live", [])):
                if mm.get("predicted") and mm.get("id") is not None:
                    prev_pred[mm["id"]] = mm["predicted"]
        except Exception:
            prev_pred = {}

    model = Model()
    for mm in matches:
        # A match counts as a genuine call only if it kicked off at/after the cutoff
        # AND its prediction was frozen earlier (while it was still upcoming/live).
        kicked_before_cutoff = (mm.get("utc") or "") < GENUINE_FROM_UTC
        if mm["home"] in model.rating and mm["away"] in model.rating:
            if mm["id"] in prev_pred and not kicked_before_cutoff:
                # genuine: frozen in an earlier run, before this (post-cutoff) match finished
                mm["predicted"] = prev_pred[mm["id"]]
                mm["backfilled"] = False
            else:
                # either it predates the genuine era, or we'd be computing it after the fact —
                # treat as backfilled history, shown but not scored
                src = prev_pred.get(mm["id"])
                if src:
                    mm["predicted"] = src
                elif not model.is_seed(mm["home"], mm["hg"], mm["ag"], mm["away"]):
                    p = model.predict(mm["home"], mm["away"], neutral=True)
                    if p:
                        mm["predicted"] = {"pA": round(p[0], 4), "pD": round(p[1], 4), "pB": round(p[2], 4)}
                if mm.get("predicted"):
                    mm["backfilled"] = True
            if not model.is_seed(mm["home"], mm["hg"], mm["ag"], mm["away"]):
                model.learn(mm["home"], mm["hg"], mm["ag"], mm["away"], neutral=True)
        if mm.get("predicted"):
            pr = mm["predicted"]
            top = max(pr["pA"], pr["pB"], pr["pD"])
            pick = "A" if top == pr["pA"] else ("B" if top == pr["pB"] else "D")
            outcome = "A" if mm["hg"] > mm["ag"] else ("B" if mm["hg"] < mm["ag"] else "D")
            mm["hit"] = (pick == outcome)

    for mm in upcoming:
        if mm["id"] in prev_pred:
            mm["predicted"] = prev_pred[mm["id"]]
        elif mm["home"] in model.rating and mm["away"] in model.rating:
            p = model.predict(mm["home"], mm["away"], neutral=True)
            if p:
                mm["predicted"] = {"pA": round(p[0], 4), "pD": round(p[1], 4), "pB": round(p[2], 4)}

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

    # ---- daily champion snapshot ----
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

    fc = model.forecast(20000)
    top8 = [{"team": t, "win": round(p, 4)} for t, p in fc[:8]]
    snapshot = {"date": pt_today, "games_played": len(matches), "top": top8}
    existing = next((d for d in daily if d.get("date") == pt_today), None)
    if existing:
        existing.update(snapshot)
    else:
        daily.append(snapshot)
    daily.sort(key=lambda d: d.get("date", ""))
    out["daily"] = daily

    # only rewrite if substantive data changed
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
    print(f"Wrote {len(matches)} finished + {len(live)} live + {len(upcoming)} upcoming to {OUT}.")
    if unmatched:
        print("WARNING: unmatched team names (add to NAME_MAP): "
              + ", ".join(sorted(unmatched)), file=sys.stderr)


if __name__ == "__main__":
    main()
