# DAVE Rankings

A single-entry-point web app that rates college football teams three ways from
one set of models: a bottom-up **player-value projection** (built from each
player's history and availability) and an opponent-adjusted **results model**.
Injury-aware, with team and player drill-downs, matchup prediction, a projected
playoff bracket, and Monte Carlo playoff odds.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

`python app.py` starts a local server (default http://127.0.0.1:5000) and opens
the dashboard. Click **Update data** to pull the latest teams, stats, and player
history from the CollegeFootballData API and compute the rankings. Data is cached
in `data/`, so it loads instantly next time.

## The three rankings

Every team gets three ratings, and each rating has **offense, defense,
special-teams, and overall** variants:

- **Power** — how good the roster is *in theory*: the bottom-up player-value
  projection only. It ignores results. Best in the preseason.
- **Current** — Power blended with results so far, weighting results more as the
  season progresses. In the preseason (no games) **Current equals Power**.
- **Predictive** — a forward projection: known results (through a chosen week,
  plus any custom what-if results) **plus a forecast of every remaining game**,
  fed back through the same opponent-adjusted credits model. At the end of the
  season, when nothing is left to forecast, **Predictive equals Current**.

### Availability toggle

A global **Available / Full strength** switch flips all three rankings between:

- **Available** — injuries and limited players are applied (value removed or
  halved), reflecting who can actually play.
- **Full strength** — the theoretical ceiling, ignoring injuries.

### Predictive controls (Current & Predictive views)

- **Timeline / as-of week** — pick any week to see the rankings as they would
  stand with results known only through that week and the rest forecast.
- **What-ifs** — open any FBS-vs-FBS game (from Upcoming, a team's schedule, or
  the bracket) and set a hypothetical score. The custom result ripples through
  the rankings, projected records, bracket, and odds. Save a timeline + set of
  what-ifs as a **named scenario** to revisit later.
- **Playoff odds** — on the Predictive view, switch to *Playoff odds* to run a
  Monte Carlo simulation of the remaining schedule and show each team's playoff
  %, championship %, first-round-bye %, average wins, and win-total distribution.

## Using the dashboard

Five tabs across the top:

**Rankings** — the ranked table.
- **Unit toggle** — Overall, Offense, Defense, or Special teams.
- **View toggle** — Power, Current, or Predictive (see above).
- **Availability toggle** — Available or Full strength.
- **Proj** column — projected final record (actual results + predicted remaining
  games). Hover for expected wins.
- **Timeline / What-ifs** controls appear for Current and Predictive.
- **Click any team** — drill down into Players, Schedule/results, a
  **Projection** tab (game-by-game picks, win probabilities, and Monte Carlo
  playoff odds + win distribution), a **Units** tab (off/def/ST by view), and
  season stats.

**Players** — every FBS player ranked by projected value, with filters for
position, conference, side of the ball, and availability, plus search.
- **Click a player** — profile popup with season-by-season stats, current-season
  form, recruiting, a production summary, and buttons to set availability
  (Active / Limited / Out) that update `injuries.json` and recompute live.
- **Click a game** — game popup. If played: box score and credit-award
  breakdown. If not: predicted score, win probability, and a **season impact**
  meter. Every FBS-vs-FBS game also has a **What-if result** editor.

**Upcoming** — top upcoming matchups by week, ranked by season impact
(reflects the active what-if world).

**CFP Bracket** — a projected 12-team playoff built from the **Predictive**
ranking (top-4 conference-champ byes) with predicted winners through to a
champion. Reflects the active what-if scenario.

**Matchup Predictor** — pick any two teams (optionally neutral site) and a rating
basis (Current / Predictive / Power) to predict the result: projected score,
margin, and win probability.

## Injuries / availability

- **Auto** — a regular contributor who stops appearing in recent games is
  flagged (conservatively) and his value reduced (Available mode only).
- **Manual** — edit `injuries.json`, or use a player popup, to mark a player
  `out` (value removed) or `limited` (halved), by CFBD athlete `id` or by
  `name` + `team`.

## Configuration

Everything tunable lives in `config.py`:

- `YEAR` — the season to rank (also settable via the `CFP_YEAR` env var).
- `CFBD_API_KEY` — your API key (set the `CFBD_API_KEY` env var to override).
- `MC_SIMS` — Monte Carlo simulations per run (default 2000; `CFP_MC_SIMS`).
- `PORT` / `HOST` — server binding.

Model weights (position importance, development curve, injury thresholds, blend
ramp, SOS, etc.) live at the top of `ranking.py`; the Power/Current/Predictive
blend and Monte Carlo live in `engine.py`.

## Project layout

```
app.py            single entry point: Flask server + API + opens the dashboard
config.py         season, API key, Monte Carlo, paths, server settings
cfbd_client.py    all CollegeFootballData API calls -> one normalized dataset
ranking.py        results model + player-value model + injuries + helpers
engine.py         Power/Current/Predictive worlds, scenarios, Monte Carlo
dashboard.html    the front end (rankings, drill-downs, bracket, predictor)
injuries.json     manual availability overrides
scenarios.json    saved named what-if scenarios (created on first save)
data/             cached raw + computed data (created on first update)
```

## How the ratings are built

1. **Player value (Power)** — each player is projected from PPA history (skill
   players), box-score production (defense), or recruiting (newcomers), adjusted
   for class-year development, in-season form, strength of schedule, and
   availability; players roll up onto the current roster with depth and position
   weighting into offense / defense / special / overall.
2. **Results** — each completed (or custom/forecast) game is scored by margin
   (via `asinh`) and opponent quality, iterated until stable, giving win credits
   and opponent-adjusted scoring/defense signals per team.
3. **Current** — Power and results are put on the same scale (z-scores) and
   blended per team, weighting results by `min(games/12, 1) * 0.85`.
4. **Predictive** — remaining games are forecast from Current ratings and added
   to the resume; the full-season credits are blended with Power at the
   season-end weight (0.85), so Predictive projects where Current will land.
5. **Monte Carlo** — the remaining schedule is simulated many times from Current
   win probabilities to produce playoff, seeding, and championship odds.

## A "world" and scenarios

A **world** is a combination of (availability mode, as-of week, custom result
overrides). The live world has no cutoff and no overrides. A saved **scenario**
is just a named world (a timeline + overrides) stored in `scenarios.json`. The
whole dashboard — rankings, bracket, predictor, odds — always reflects the
active world.

## Notes

- Scoped to FBS (other divisions have sparse player data).
- Requires network access to `api.collegefootballdata.com` when updating.
- The free CFBD tier allows 1,000 calls/month; one full update uses ~30-50 calls.
- No new runtime dependencies beyond Flask and Requests; the engine is pure
  Python.
```
