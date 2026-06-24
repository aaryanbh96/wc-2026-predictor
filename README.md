# World Cup 2026 Predictor

**A self-updating model that calls the World Cup before it happens — and grades itself in the open.**

🔗 **Live:** [wc2026.rearyan.com](https://wc2026.rearyan.com)

Most World Cup sites show you the schedule. This one answers the only question that matters during a tournament: **who's actually going to win?** It runs a statistical model over the entire remaining tournament, simulates it 20,000 times, and names a favorite — then, after every real match, it pulls the result, re-rates every team, and publicly scores how well its own pre-match predictions held up.

No human touches it during the tournament. It runs itself.

---

## What it does

- **Predicts the champion.** A Monte Carlo simulation plays the rest of the tournament forward 20,000 times from current team strength, producing each team's odds to win the cup, reach the final, the semis, and so on.
- **Calls every match in advance.** Before each kickoff, the model's win/draw/loss prediction is frozen server-side — tamper-proof and identical for everyone.
- **Grades itself honestly.** Once a match finishes, the frozen prediction is scored (hit rate + Brier score). Predictions made *before* the model had a genuine pre-match read are flagged and excluded, so the track record reflects real calls only — not hindsight.
- **Knows who's alive.** A qualification engine computes, provably, which teams have clinched a knockout spot and which are mathematically eliminated — and removes dead teams from the championship odds.
- **Updates on its own.** Live results flow in automatically through a scheduled data pipeline; the page reflects new results within minutes of full-time.
- **Lets you play.** Predict any matchup (even hypothetical ones), keep a private prediction scratchpad, or "shock" a team's rating and watch the odds re-simulate live.

---

## How the model works

### Ratings — Elo with momentum

Every team carries an Elo-style rating. The expected result of a match is the standard logistic:

```
P(A beats B) = 1 / (1 + 10^((Rb - Ra) / 400))
```

After each match, ratings update by the textbook Elo rule, scaled by margin of victory (a 4-0 win moves ratings more than a 1-0, but the effect is bounded so blowouts can't run away):

```
delta = K * margin_multiplier * (actual - expected)
```

The update is **zero-sum** — the winner gains exactly what the loser drops — so total rating in the system is conserved, with no drift or inflation. A recency-weighted, opponent-adjusted **form** term nudges each rating up or down based on recent results, so a team on a hot streak is treated as stronger than its base rating alone suggests.

The result behaves the way it should: beating a team you were expected to beat barely moves your rating; a genuine upset moves it a lot.

### Forecast — Monte Carlo simulation

To turn ratings into tournament odds, the model simulates the entire remaining tournament 20,000 times. Each simulation plays out the group stage and knockouts match-by-match using the rating-derived probabilities, then tallies how often each team reaches each stage. Championship odds sum to 100%, and eliminated teams are held at 0% with the remainder renormalized.

### Qualification — provably correct, never overclaims

A dedicated engine brute-forces the remaining group fixtures to determine each team's status:

- **Qualified** — top-2 in *every* possible remaining scenario (mathematically clinched).
- **Eliminated** — cannot reach the top 3 of its group in *any* scenario.
- **Alive** — everything in between.

It never claims certainty it doesn't have. The moment a group finishes, the scenarios collapse to one and the verdicts become exact.

---

## Architecture

A static front end backed by a serverless data pipeline — no servers to run, nothing to babysit.

```
API-Football (paid, live data)
        |
        v
 GitHub Action  -->  Python pipeline
 (scheduled)         - fetch results
        |            - re-rate every team (model.py)
        |            - freeze pre-match predictions
        |            - run 20,000-sim forecast
        |            - compute qualification status
        v            - write results.json
 results.json  (committed back to the repo)
        |
        v
 GitHub Pages  -->  index.html (single-file app)
        |            reads results.json, renders client-side
        v
 wc2026.rearyan.com  (custom domain via Cloudflare DNS)
```

Plus a small **Cloudflare Worker** powering the public visitor counter (KV-backed).

### Why this shape

- **No backend to operate.** The "server" is a scheduled GitHub Action. It wakes up, does the work, commits the output, and goes away. Cost is essentially zero.
- **Predictions can't be faked.** Because pre-match calls are frozen into a committed `results.json`, the track record is auditable — anyone can check the git history.
- **The front end is dumb on purpose.** All the intelligence lives in the pipeline; the page just renders the latest `results.json`. That keeps it fast and resilient.

---

## Repo layout

| Path | What it is |
|------|-----------|
| `index.html` | The entire front-end app — model, Monte Carlo, and UI in one file (mirrors the Python model exactly). |
| `scripts/model.py` | Python port of the rating + form model and the Monte Carlo forecast. |
| `scripts/qualify.py` | Qualification engine (clinched / eliminated / alive). |
| `scripts/fetch_results_apifootball.py` | The live data pipeline — fetches results, freezes predictions, computes everything, writes `results.json`. |
| `.github/workflows/update-results.yml` | The scheduled GitHub Action that runs the pipeline. |
| `worker/visitor-counter.js` | Cloudflare Worker reference copy for the visitor counter. |
| `assets/` | Favicon and background image. |


---

*Built and operated by Aryan Bhardwaj. More at [rearyan.com](https://rearyan.com).*
