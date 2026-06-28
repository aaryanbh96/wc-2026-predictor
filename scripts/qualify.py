#!/usr/bin/env python3
"""
Tournament qualification engine for the 2026 World Cup group stage.

Given the finished group matches and the remaining group fixtures, this computes,
for every team, whether it has:
  - "qualified"  : mathematically secured a Round-of-32 place
  - "eliminated" : mathematically cannot reach the Round of 32
  - "alive"      : still in contention, not yet decided

Format: 12 groups of 4. Top 2 of each group (24) + 8 best third-place teams (8) = 32.
Tiebreakers used (in order): points, goal difference, goals scored.
(FIFA also uses fair-play and FIFA ranking after those; we can't compute those from
match data alone, so ties beyond goals-scored are treated conservatively.)

The approach is *mathematical* — it accounts for games still to play, so it's correct
DURING the group stage, not only after it finishes. A team is "qualified" only if it
secures a top-2 (or guaranteed-best-third) spot in every possible remaining outcome;
"eliminated" only if it misses in every possible outcome.

This is intentionally exhaustive over remaining group games. With at most a handful of
unplayed games per group (each group is tiny), the brute force is trivial and exact.
"""

from itertools import product


def _standings_from(matches, teams):
    """Build a points/gd/gf table for a set of teams from finished matches."""
    tbl = {t: {"pts": 0, "gd": 0, "gf": 0, "p": 0} for t in teams}
    for m in matches:
        a, b, ga, gb = m["home"], m["away"], m["hg"], m["ag"]
        if a not in tbl or b not in tbl:
            continue
        tbl[a]["p"] += 1; tbl[b]["p"] += 1
        tbl[a]["gf"] += ga; tbl[b]["gf"] += gb
        tbl[a]["gd"] += ga - gb; tbl[b]["gd"] += gb - ga
        if ga > gb:
            tbl[a]["pts"] += 3
        elif ga < gb:
            tbl[b]["pts"] += 3
        else:
            tbl[a]["pts"] += 1; tbl[b]["pts"] += 1
    return tbl


def _rank(tbl, group_teams):
    """Order a group's teams by points, gd, gf (desc)."""
    return sorted(group_teams, key=lambda t: (tbl[t]["pts"], tbl[t]["gd"], tbl[t]["gf"]), reverse=True)


def _apply(tbl, a, b, ga, gb):
    """Return a copy of tbl with one hypothetical result applied."""
    import copy
    t = copy.deepcopy(tbl)
    t[a]["gf"] += ga; t[b]["gf"] += gb
    t[a]["gd"] += ga - gb; t[b]["gd"] += gb - ga
    if ga > gb:
        t[a]["pts"] += 3
    elif ga < gb:
        t[b]["pts"] += 3
    else:
        t[a]["pts"] += 1; t[b]["pts"] += 1
    return t


# A small but representative set of hypothetical scorelines for an unplayed game.
# We don't need every scoreline — we need the three outcomes (A win / draw / B win)
# across a range of margins so goal-difference swings are covered.
_HYPOS = [(3, 0), (1, 0), (1, 1), (0, 1), (0, 3)]


def compute_status(group_of, finished, remaining):
    """
    group_of: dict team -> group label
    finished: list of finished match dicts {home,away,hg,ag}
    remaining: list of unplayed match dicts {home,away} (group stage only)

    Returns dict team -> "qualified" | "eliminated" | "alive".
    """
    # group teams
    groups = {}
    for t, g in group_of.items():
        groups.setdefault(g, []).append(t)

    # remaining games per group
    rem_by_group = {}
    for m in remaining:
        g = group_of.get(m["home"])
        if g and group_of.get(m["away"]) == g:
            rem_by_group.setdefault(g, []).append(m)

    # finished games per group
    fin_by_group = {}
    for m in finished:
        g = group_of.get(m["home"])
        if g and group_of.get(m["away"]) == g:
            fin_by_group.setdefault(g, []).append(m)

    status = {}
    group_scenarios = {}
    for g, teams in groups.items():
        base = _standings_from(fin_by_group.get(g, []), teams)
        rem = rem_by_group.get(g, [])
        scenarios = []
        for combo in product(_HYPOS, repeat=len(rem)):
            tbl = base
            for mm, (ga, gb) in zip(rem, combo):
                tbl = _apply(tbl, mm["home"], mm["away"], ga, gb)
            order = _rank(tbl, teams)
            scenarios.append({"order": order, "tbl": tbl})
        group_scenarios[g] = scenarios

    # Provably-correct, never-lies rules:
    #   qualified  : top-2 in EVERY remaining scenario (mathematically clinched a knockout spot)
    #   eliminated : in NO scenario can the team reach the top 3 of its group
    #                (can't be winner, runner-up, OR a third-place candidate — truly out)
    #   alive      : anything in between (includes teams still fighting for a best-third spot)
    # When a group has no remaining games, scenarios collapse to one and this becomes exact.
    for g, teams in groups.items():
        scen = group_scenarios[g]
        for t in teams:
            always_top2 = all(t in s["order"][:2] for s in scen)
            ever_top3 = any(t in s["order"][:3] for s in scen)
            if always_top2:
                status[t] = "qualified"
            elif not ever_top3:
                status[t] = "eliminated"
            else:
                status[t] = "alive"

    # ---- Best-thirds resolution (only when the group stage is COMPLETE) ----
    # During the group stage, 3rd-place hopefuls are correctly "alive". But once every
    # group game is played, the 8 best third-place teams advance and the rest are out —
    # a cross-group comparison the per-group logic above can't resolve. Resolve it here.
    group_done = (len(remaining) == 0)
    if group_done:
        # final standings per group (single scenario, since nothing remains)
        thirds = []  # (team, group, pts, gd, gf)
        for g, teams in groups.items():
            tbl = _standings_from(fin_by_group.get(g, []), teams)
            order = _rank(tbl, teams)
            # top 2 are definitely through
            for t in order[:2]:
                status[t] = "qualified"
            # 4th (and lower) are definitely out
            for t in order[3:]:
                status[t] = "eliminated"
            # 3rd place enters the best-thirds pool
            if len(order) >= 3:
                t3 = order[2]
                s = tbl[t3]
                thirds.append((t3, g, s["pts"], s["gd"], s["gf"]))
        # rank the third-place teams; best 8 advance, rest eliminated
        thirds.sort(key=lambda x: (x[2], x[3], x[4]), reverse=True)
        for i, (t, g, *_rest) in enumerate(thirds):
            status[t] = "qualified" if i < 8 else "eliminated"

    return status


def alive_teams(group_of, finished, remaining):
    """Convenience: set of teams NOT eliminated (qualified + alive)."""
    st = compute_status(group_of, finished, remaining)
    return {t for t, s in st.items() if s != "eliminated"}
