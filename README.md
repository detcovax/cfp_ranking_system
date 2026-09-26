# DAVE Rankings

A single-entry-point web app that rates college football teams three ways from
one set of models: a bottom-up **player rating** model (each player's
multi-season production, shrunk toward a recruiting prior, rolled up by depth
chart and snap share) and an opponent-adjusted **results solver** that uses the
roster rating as its Bayesian prior. **All team ratings are in points vs. an
average FBS team on a neutral field**, so a rating gap is a predicted spread.
Injury-aware, with team and player drill-downs, matchup prediction, a projected
playoff bracket, and Monte Carlo playoff odds.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Set your API key first (`CFBD_API_KEY` environment variable, or a one-line
`cfbd_key.txt` next to `config.py`). Then `python app.py` starts a local server (default http://127.0.0.1:5000) and opens
the dashboard. Three buttons at the top right run the pipeline in steps:

- **Fetch** — pulls the latest teams, games, stats, and player history from the
  CollegeFootballData API and saves it to `data/raw.json` (~45-60 API calls).
  The rankings on screen don't change yet.
- **Execute** — computes every rating (players, Power, Current, Predictive,
  bracket, conferences) from the saved data and the saved calibration. This is
  the only step that changes what you see.
- **Calibrate** — fits the model's parameters from the saved data (a few
  minutes; same as running `python calibrate.py`) and shows the report. It
  runs in a separate process from the built-in defaults, and takes effect on
  the next Execute.

After a Fetch or Calibrate, an orange dot on Execute and a banner show what's
waiting to be applied. A first-time run is Fetch → Execute. On restart the app
executes the saved data automatically.

## The three rankings

Every team gets three ratings, and each rating has **offense, defense,
special-teams, and overall** variants:

- **Power** — how good the roster is *in theory*: player ratings rolled up by
  depth chart, plus a program-continuity term from last season. Ignores this
  season's results.
- **Current** — the results solver with Power as its prior. Each team's prior
  weight is `K / (K + games)`, and opponent adjustment happens jointly (beating
  a team whose roster projects well counts more, even early). In the preseason
  **Current equals Power**.
- **Predictive** — the projected final **committee ranking**: strength of
  record (wins and losses vs. what a playoff-bubble team would do with the same
  schedule; margin ignored, per the protocol), projected conference
  championship games, and the committee's head-to-head and common-opponent
  tiebreaks between comparable teams. The CFP field and seeds come from this;
  game picks inside the bracket use Current.

  *Why not "forecast the rest and re-rate"?* Under a consistent model, the
  expected end-of-season rating equals today's rating, so that view would just
  duplicate Current. Résumé is the question a playoff projection actually asks.

### Availability toggle

A global **Available / Full strength** switch flips all three rankings between:

- **Available** — injuries and limited players are applied. An *out* player is
  removed and the next man up takes his snaps; a *limited* player plays half
  his share and the rest passes down the depth chart. The roster difference is
  applied to Current as a forward-looking delta, so an injured starter costs
  his team the same amount in week 12 as in week 1.
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

Six tabs across the top:

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
- **Click a game** — game popup. If played: box score and game-score
  breakdown. If not: predicted score, win probability, and a **season impact**
  meter. Every FBS-vs-FBS game also has a **What-if result** editor.

**Upcoming** — top upcoming matchups by week, ranked by season impact
(reflects the active what-if world).

**Conferences** — conference strength and comparisons, from Current ratings
(so it follows the availability toggle, as-of week, and what-ifs).
- **Table** (click headers to sort): average, best, top-half, worst, spread,
  *avg team wins* (the win % an average FBS team would post against every
  member — a top-to-bottom difficulty measure), non-conference record and
  margin vs. FBS, Group of 6 record vs. Power 4, top-25 teams, and projected CFP
  bids (plus expected bids once playoff odds are run).
- **Click a conference** — unit averages (offense/defense/special), movement
  vs. preseason Power, schedule strength, the projected title game, projected
  CFP teams, and every member with national rank, overall/conference/projected
  record, Current and Power ratings, and CFP seed. Click a team to open it.
- **Head-to-head matrix** — each conference's record against every other in
  completed games.
- **Independents** (Notre Dame, UConn, etc.) are listed individually rather
  than as a pseudo-conference, in the table and the matrix.

**CFP Bracket** — a projected 12-team playoff under the 2026-27 rules (see
`cfp.py`): the SEC, Big Ten, Big 12 and ACC champions, the highest-ranked team
from the American/CUSA/MAC/Mountain West/Pac-12/Sun Belt, Notre Dame if ranked
in the top 12, and seven at-large teams, all taken from the Predictive
(committee) ranking. Seeding is straight by rank: the top four ranked teams get
byes whether or not they won a conference, and automatic qualifiers ranked
outside the top 12 drop to the bottom seeds. Shows how each team got in, the
first four out, anyone bumped by a low-ranked automatic qualifier, and the
projected conference championship games. Reflects the active what-if scenario.

**Matchup Predictor** — pick any two teams (optionally neutral site) and a rating
basis (Current / Predictive / Power) to predict the result: projected score,
margin, and win probability.

## Starters, backups, and injuries

**Who starts comes from actual usage, not ratings.** Each player's *role* is
his usage relative to the position leader on his team (CFBD usage share or
plays for QB/RB/WR/TE, tackles + passes defended for defense, attempts for
K/P). This season's usage takes over within about three games; before that,
last season's role carries over (discounted at a new school). The depth chart
orders players by role first; rating only breaks near-ties and orders
newcomers. Offensive linemen have no individual usage data, so they're still
ordered by rating and experience.

**Snap shares** then follow the depth chart (e.g. QB1 100% / QB2 5%, RB 60/35,
WR 90/85/75/30), so a backup contributes very little to his team's rating.

**Coach's preference:** when a player clearly starts over a teammate (role gap
of 0.3+), the starter's effective rating is at least that teammate's. The
staff sees practice; the model's rating of two teammates is noisier than the
depth chart. This also guarantees losing a player never helps a team.

**Per-player numbers** (team drawer, Players tab, player popup):
- *Role* — Starter / Rotation / Backup / Reserve / Out.
- *Snaps* — projected share when healthy.
- *Value* — points above a replacement player at those snaps.
- *If out* — points the team loses without him, measured by re-running his
  position group without him. For an injured player: what his absence costs.
- *As full-time starter* — what he'd be worth if he took over the job.

**Injuries.**
- *Auto* — a player who started this season (usage leader at QB/RB/WR/TE in
  2+ games) and then misses 2 straight **team** games is marked out (bye weeks
  don't count). Backups and last year's starters who simply aren't playing are
  never flagged; their role falls on its own. A returning starter clears
  automatically. Defense and OL injuries must be entered manually (CFBD has no
  per-game data for them).
- *Manual* — edit `injuries.json`, or use a player popup, to mark a player
  `out` (removed; the next man up takes his snaps) or `limited` (plays half
  his share; the rest passes down the depth chart), by CFBD athlete `id` or by
  `name` + `team`.
- Availability is applied to Current as a forward-looking change, so an
  injured starter costs his team the same in week 12 as in week 1.

## Configuration

Everything tunable lives in `config.py`:

- `YEAR` — the season to rank (also settable via the `CFP_YEAR` env var).
- `CFBD_API_KEY` — read from the env var or `cfbd_key.txt` (never commit it).
- `MC_SIMS` — Monte Carlo simulations per run (default 2000; `CFP_MC_SIMS`).
- `PORT` / `HOST` — server binding.

Player-model parameters (season decay, prior strength, development curve,
snap shares, position weights) are at the top of `model_players.py`; results
solver parameters in `model_results.py`; blend/Power/Monte Carlo parameters in
`engine.PARAMS`.

## Calibration

```bash
python calibrate.py            # after at least one Fetch (or use the Calibrate button)
```

Fits parameters from your cached data, point-in-time (nothing is fit on data
it then predicts), and writes `data/calibration.json`, which the engine loads
automatically. Delete the file to return to defaults.

1. **Results solver** — walk-forward inside each history season: rate teams on
   games before week *w*, predict week *w*. Grid-searches `PRIOR_GAMES` (K) and
   `MARGIN_DAMP`, and fits `MARGIN_SD` (win-probability spread).
2. **Power** — rebuilds each team's roster as it stood the preseason before a
   history season (that season's roster, earlier production only) and
   regresses the final rating on position-group strength and last season's
   rating. Gives `GROUP_WEIGHT` (ridge-shrunk toward defaults, strength chosen
   by leave-one-season-out CV), `ROSTER_COEF`, and `PRIOR_COEF`.

Safeguards: the walk-forward scores only FBS-vs-FBS games (CFBD's feed
includes every division, which otherwise dominates and drags K to its
minimum); position weights use team-grouped 10-fold CV with the
one-standard-error rule, stay within 0.5x-2x of their defaults, and the
defaults are kept unless fitted weights beat them by more than 1 SE. The
report also shows the QB/WR overlap (CFBD credits a pass play's PPA to both
passer and receiver) and each position group's partial correlation with the
final rating. Calibration files from the first version of calibrate.py are
ignored by the engine with a message to re-run.

Re-run it each off-season.

## Project layout

```
app.py            single entry point: Flask server + API + opens the dashboard
config.py         season, API key, Monte Carlo, paths, server settings
cfbd_client.py    all CollegeFootballData API calls -> one normalized dataset
model_players.py  player ratings + depth-chart roll-up
model_results.py  opponent-adjusted results solver (points scale)
cfp.py            CFP selection + seeding rules, conference title race, tiebreaks
ranking.py        prediction, bracket, schedules, profiles, injuries helpers
engine.py         Power/Current/Predictive worlds, scenarios, Monte Carlo
calibrate.py      fits parameters from cached data -> data/calibration.json
tests/            synthetic CFBD-shaped fixture + accuracy and API smoke tests
dashboard.html    the front end (rankings, drill-downs, bracket, predictor)
injuries.json     manual availability overrides
scenarios.json    saved named what-if scenarios (created on first save)
data/             cached raw + computed data (created on first update)
```

## How the ratings are built

1. **Season z-scores** — each player-season gets a rate and sample size:
   PPA per play (QB/RB/WR/TE, n = plays), weighted box-score events (DL/LB/DB,
   n = tackles + passes defended), FG% (K) or yards per punt (P). The rate is
   z-scored against qualified players at the position that season, then
   shifted by schedule strength (`+0.30 z` per SD), which also discounts
   production from weaker conferences for transfers.
2. **Player rating** — a Bayesian blend across seasons:

   `R = (Σ λ^k · t_k · n_k · (z_k + dev_k) + m · z_prior) / (Σ λ^k · t_k · n_k + m)`

   λ = season decay, t = transfer trust, dev = class-year development,
   z_prior = recruiting composite + class shift, m = prior strength by
   position. Big samples dominate; thin samples lean on the prior. OL has no
   individual data, so it's recruiting prior + years of experience.
3. **Roll-up** — players fill depth slots with expected snap shares (e.g. WR
   0.90/0.85/0.75/0.30), ordered by rating plus a current-season usage
   tiebreak. Empty snaps are played at replacement level.
   `unit = Σ_groups weight_g · Σ_slots share · availability · R`.
4. **Power (points)** — `a · sd · z(unit) + b · last_season_unit`, where sd is
   the spread of last season's opponent-adjusted ratings.
5. **Results solver** — ridge regression on damped margins
   (`20·asinh(m/20)`) with fitted home field and classification priors for
   non-FBS opponents; a parallel points-for/against model gives offense and
   defense. Current uses Power as the prior.
6. **Monte Carlo** — each simulation draws every team's "true" rating around
   Current (uncertainty shrinks with games played), plays out the schedule,
   plays each conference championship game between the top two teams in the
   simulated standings, builds the committee ranking, selects and seeds the
   field with the same `cfp.py` rules, and plays the bracket.

Player **value** is points above a replacement-level player at full snaps;
**grade** is 50 + 15·R within the position.

## A "world" and scenarios

A **world** is a combination of (availability mode, as-of week, custom result
overrides). The live world has no cutoff and no overrides. A saved **scenario**
is just a named world (a timeline + overrides) stored in `scenarios.json`. The
whole dashboard — rankings, bracket, predictor, odds — always reflects the
active world.

## Notes

- Scoped to FBS. Membership comes from CFBD's `/teams/fbs` list for the season
  (saved by Fetch); with older cached data it falls back to teams
  explicitly classified FBS. Non-FBS opponents still count in results (with a
  lower-division prior) but are never ranked or listed.
- Requires network access to `api.collegefootballdata.com` when updating.
- The free CFBD tier allows 1,000 calls/month; one full update uses ~45-60 calls
  (kicking/punting stats and two extra recruiting classes were added).
- No new runtime dependencies beyond Flask and Requests; the engine is pure
  Python.
```
