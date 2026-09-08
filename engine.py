"""
engine.py -- Power / Current / Predictive ranking orchestration.

Builds three team ratings from the same underlying models in ranking.py:

  * Power       -- how good the roster is in theory (bottom-up player value).
                   Available full-strength (ignores injuries) or
                   availability-adjusted (injuries/limited applied).
  * Current     -- Power blended with results so far. In the preseason (no known
                   games) it equals Power; it shifts toward results as games are
                   played.
  * Predictive  -- a forward projection: known results (through an optional
                   "as-of" week, plus any custom overrides) PLUS forecast
                   outcomes of every remaining game, fed back through the same
                   opponent-adjusted credits model. At season's end it equals
                   Current.

Everything is computed for a "world" = (availability mode, as-of week, custom
result overrides). A world with no cutoff and no overrides is the base/live
world. Scenarios (named saved worlds) simply supply a cutoff week + overrides.

Each rating also carries offense / defense / special-teams / overall variants,
and the Predictive world can be run through a Monte Carlo simulation for
playoff odds, win-total distributions, and championship odds.

This module reuses ranking.py's proven functions and never touches the network.
"""

import math
import statistics
import random
from collections import defaultdict

import config
import ranking

VIEWS = ("power", "current", "predictive")
UNITS = ("overall", "offense", "defense", "special")

# How much a full-season projected resume is trusted in the Predictive blend
# (mirrors ranking.MAX_RESULTS_WEIGHT so Predictive == Current at season end).
PRED_RESULTS_WEIGHT = ranking.MAX_RESULTS_WEIGHT
UNIT_CLAMP = 3.0


def _clamp(z, lim=UNIT_CLAMP):
    return max(-lim, min(lim, z))


def _rate(z):
    return round(50 + 15 * z, 1)


def _rate_unit(z):
    return round(50 + 15 * _clamp(z), 1)


# ---------------------------------------------------------------------------
# Scenario application: cutoff week + custom result overrides
# ---------------------------------------------------------------------------
def _game_week(g):
    w = g.get("week")
    try:
        return int(w)
    except (TypeError, ValueError):
        return None


def apply_scenario(teams, cutoff_week=None, overrides=None):
    """Return a shallow copy of `teams` whose games reflect the scenario:

      * a game id in `overrides` gets the supplied score (treated as played),
      * a game whose week is after `cutoff_week` is reset to unplayed,
      * everything else keeps its real result.

    Overrides are keyed by game id (str) -> {"homePoints", "awayPoints"} in the
    game's native home/away orientation.
    """
    overrides = overrides or {}
    over = {str(k): v for k, v in overrides.items()}

    # Build one modified game per id so both teams see the same version.
    mod_by_id = {}

    def modify(g):
        gid = str(g.get("id"))
        if gid in mod_by_id:
            return mod_by_id[gid]
        ng = dict(g)
        ov = over.get(gid)
        if ov is not None:
            ng["homePoints"] = ov.get("homePoints")
            ng["awayPoints"] = ov.get("awayPoints")
            ng["_override"] = True
        elif cutoff_week is not None:
            wk = _game_week(g)
            if wk is not None and wk > cutoff_week:
                ng["homePoints"] = None
                ng["awayPoints"] = None
        mod_by_id[gid] = ng
        return ng

    out = []
    for t in teams:
        nt = dict(t)
        nt["games"] = [modify(g) for g in t.get("games", [])]
        out.append(nt)
    return out


# ---------------------------------------------------------------------------
# Shim rows so ranking.py's helpers (predict/bracket/game detail) can be reused
# ---------------------------------------------------------------------------
def _shim(row, view):
    """A lightweight ranking-row view that the ranking.py helpers understand,
    projecting the chosen view's overall strength/rank/rating onto the flat
    keys those functions read."""
    return {
        "school": row["school"],
        "abbreviation": row["abbreviation"],
        "conference": row["conference"],
        "classification": row["classification"],
        "color": row["color"],
        "logo": row["logo"],
        "record": row["record"],
        "rank_blended": row["ranks"][view]["overall"],
        "rating_blended": row["ratings"][view]["overall"],
        "strength_blended": row["strength"][view],
    }


# ---------------------------------------------------------------------------
# Forecast remaining games from Current ratings
# ---------------------------------------------------------------------------
def _forecast_full_teams(known_teams, current_shims):
    """Fill every unplayed game with a predicted scoreline (from Current
    ratings) so the completed+forecast season can be scored by the credits
    model. Returns new team objects with all games 'played'."""
    by_school = {r["school"]: r for r in current_shims}
    mod_by_id = {}

    def fill(g):
        gid = str(g.get("id"))
        if gid in mod_by_id:
            return mod_by_id[gid]
        if g.get("homePoints") is not None and g.get("awayPoints") is not None:
            mod_by_id[gid] = g
            return g
        ng = dict(g)
        home, away = g.get("homeTeam"), g.get("awayTeam")
        hr, ar = by_school.get(home), by_school.get(away)
        if hr and ar:
            pred = ranking.predict_matchup(hr, ar, neutral=bool(g.get("neutralSite")))
            ng["homePoints"] = pred["proj_home"]
            ng["awayPoints"] = pred["proj_away"]
        else:
            # One side unranked: give the ranked side a generic comfortable win.
            if hr and not ar:
                ng["homePoints"], ng["awayPoints"] = 31, 17
            elif ar and not hr:
                ng["homePoints"], ng["awayPoints"] = 17, 31
            else:
                ng["homePoints"], ng["awayPoints"] = None, None
        ng["_forecast"] = True
        mod_by_id[gid] = ng
        return ng

    out = []
    for t in known_teams:
        nt = dict(t)
        nt["games"] = [fill(g) for g in t.get("games", [])]
        out.append(nt)
    return out


# ---------------------------------------------------------------------------
# Preparation shared across every world (network-free, computed once)
# ---------------------------------------------------------------------------
def prepare(raw, injuries=None):
    """Compute the season-invariant pieces once: strength-of-schedule, injury
    parse, and player value for both availability modes."""
    manual = ranking.load_injuries() if injuries is None else ranking.parse_injuries(injuries)
    sos_mult = ranking.build_sos(raw.get("teams", []), raw.get("history_games", {}))
    players = raw.get("players", {})
    pv_modes = {
        "avail": ranking.compute_player_value(players, manual, sos_mult, apply_availability=True),
        "full": ranking.compute_player_value(players, manual, sos_mult, apply_availability=False),
    }
    return {"manual": manual, "sos_mult": sos_mult, "pv_modes": pv_modes}


def season_weeks(teams):
    """All distinct scheduled weeks (sorted) and the latest week with a played
    game, used to drive the Predictive as-of-week control."""
    weeks = set()
    latest_played = 0
    for t in teams:
        for g in t.get("games", []):
            wk = _game_week(g)
            if wk is None:
                continue
            weeks.add(wk)
            if g.get("homePoints") is not None and g.get("awayPoints") is not None:
                latest_played = max(latest_played, wk)
    return sorted(weeks), latest_played


# ---------------------------------------------------------------------------
# Build one world (a mode + scenario) -> rankings + detail + games + bracket
# ---------------------------------------------------------------------------
def build_world(raw, prep, avail="avail", cutoff_week=None, overrides=None):
    teams = raw.get("teams", [])
    pv, pv_extras = prep["pv_modes"][avail]
    team_by_school = {t["school"]: t for t in teams}

    fbs_schools = [s for s in pv if ranking.is_fbs(team_by_school.get(s, {"classification": None}))]
    if not fbs_schools:
        fbs_schools = [t["school"] for t in teams if t.get("games") and ranking.is_fbs(t)]

    # --- Player-value z-scores (Power) ---
    pv_overall_z = ranking._zmap({s: pv[s]["pv_rating"] for s in fbs_schools if s in pv})
    pv_off_z = ranking._zmap({s: pv[s]["offense"] for s in fbs_schools if s in pv})
    pv_def_z = ranking._zmap({s: pv[s]["defense"] for s in fbs_schools if s in pv})
    pv_st_z = ranking._zmap({s: pv[s]["special"] for s in fbs_schools if s in pv})

    # --- Known results (respecting cutoff + overrides) ---
    known_teams = apply_scenario(teams, cutoff_week, overrides)
    known_by_school = {t["school"]: t for t in known_teams}
    res_known, credits_known, credit_detail = ranking.compute_results(known_teams)

    def _res_z(metric_key, invert=False):
        vals = {}
        for s in fbs_schools:
            r = res_known.get(s)
            if r and r.get("games", 0) > 0:
                v = r[metric_key]
                vals[s] = -v if invert else v
        return ranking._zmap(vals), vals

    res_known_z, _ = _res_z("results_metric")
    off_known_z, _ = _res_z("off_ppg")
    def_known_z, _ = _res_z("def_ppg", invert=True)

    games_played = {s: res_known.get(s, {}).get("games", 0) for s in fbs_schools}
    any_games = any(v > 0 for v in games_played.values())

    # --- Current = Power blended with known results ---
    def _wres(s):
        return min(games_played.get(s, 0) / ranking.FULL_SEASON_GAMES, 1.0) * ranking.MAX_RESULTS_WEIGHT

    cur_overall = {}
    cur_off = {}
    cur_def = {}
    cur_st = {}
    for s in fbs_schools:
        w = _wres(s)
        zpv = pv_overall_z.get(s, 0.0)
        cur_overall[s] = (1 - w) * zpv + w * res_known_z.get(s, 0.0)
        cur_off[s] = (1 - w) * pv_off_z.get(s, 0.0) + w * off_known_z.get(s, 0.0)
        cur_def[s] = (1 - w) * pv_def_z.get(s, 0.0) + w * def_known_z.get(s, 0.0)
        cur_st[s] = pv_st_z.get(s, 0.0)  # no results signal for special teams

    # Current shim rows (used to forecast remaining games + predictions).
    cur_rows = [{"school": s, "strength_blended": cur_overall.get(s, 0.0),
                 "rank_blended": 1} for s in fbs_schools]
    # rank_blended needed by game_impact; assign from current overall.
    for i, r in enumerate(sorted(cur_rows, key=lambda x: x["strength_blended"], reverse=True), 1):
        r["rank_blended"] = i

    # --- Predictive = known + forecast remaining, scored through credits ---
    full_teams = _forecast_full_teams(known_teams, cur_rows)
    res_proj, _, _ = ranking.compute_results(full_teams)

    def _proj_z(metric_key, invert=False):
        vals = {}
        for s in fbs_schools:
            r = res_proj.get(s)
            if r and r.get("games", 0) > 0:
                v = r[metric_key]
                vals[s] = -v if invert else v
        return ranking._zmap(vals)

    proj_overall_z = _proj_z("results_metric")
    proj_off_z = _proj_z("off_ppg")
    proj_def_z = _proj_z("def_ppg", invert=True)

    wp = PRED_RESULTS_WEIGHT
    pred_overall = {}
    pred_off = {}
    pred_def = {}
    pred_st = {}
    for s in fbs_schools:
        zpv = pv_overall_z.get(s, 0.0)
        pred_overall[s] = (1 - wp) * zpv + wp * proj_overall_z.get(s, 0.0)
        pred_off[s] = (1 - wp) * pv_off_z.get(s, 0.0) + wp * proj_off_z.get(s, 0.0)
        pred_def[s] = (1 - wp) * pv_def_z.get(s, 0.0) + wp * proj_def_z.get(s, 0.0)
        pred_st[s] = pv_st_z.get(s, 0.0)

    strength = {
        "power": {"overall": pv_overall_z, "offense": pv_off_z, "defense": pv_def_z, "special": pv_st_z},
        "current": {"overall": cur_overall, "offense": cur_off, "defense": cur_def, "special": cur_st},
        "predictive": {"overall": pred_overall, "offense": pred_off, "defense": pred_def, "special": pred_st},
    }

    # --- Assemble ranking rows ---
    rankings = []
    for s in fbs_schools:
        t = team_by_school.get(s, {})
        r = res_known.get(s, {"record": [0, 0], "games": 0})
        pvd = pv.get(s, {})
        logos = t.get("logos") or []
        ratings = {}
        ranks = {}
        strength_ov = {}
        for v in VIEWS:
            ratings[v] = {
                "overall": _rate(strength[v]["overall"].get(s, 0.0)),
                "offense": _rate_unit(strength[v]["offense"].get(s, 0.0)),
                "defense": _rate_unit(strength[v]["defense"].get(s, 0.0)),
                "special": _rate_unit(strength[v]["special"].get(s, 0.0)),
            }
            ranks[v] = {}
            strength_ov[v] = strength[v]["overall"].get(s, 0.0)
        rankings.append({
            "school": s,
            "abbreviation": t.get("abbreviation", ""),
            "conference": t.get("conference"),
            "classification": t.get("classification"),
            "color": t.get("color") or "#444444",
            "logo": logos[0] if logos else None,
            "record": r["record"],
            "games": r.get("games", 0),
            "impaired": pvd.get("impaired", 0),
            "returning_pct": pvd.get("returning_pct", 0.0),
            "ratings": ratings,
            "ranks": ranks,
            "strength": strength_ov,
        })

    # Assign ranks for every view/unit.
    for v in VIEWS:
        for u in UNITS:
            ordered = sorted(rankings, key=lambda x: x["ratings"][v][u], reverse=True)
            for i, row in enumerate(ordered, 1):
                row["ranks"][v][u] = i
    rankings.sort(key=lambda x: x["ranks"]["current"]["overall"])

    row_by_school = {r["school"]: r for r in rankings}
    n_teams = len(rankings)

    # --- Projections (record + per-game picks) from Current ratings ---
    cur_shim_rows = [_shim(r, "current") for r in rankings]
    cur_shim_by_school = {r["school"]: r for r in cur_shim_rows}
    for row in rankings:
        s = row["school"]
        proj = ranking.project_record(known_by_school.get(s, {}), s, cur_shim_by_school)
        row["proj_record"] = proj["projected"]
        row["expected_wins"] = proj["expected_wins"]
        row["remaining"] = proj["remaining"]
        row["_projection"] = proj  # kept for the team drawer; stripped from list API

    # --- Per-team detail (drawer) ---
    detail = {}
    for row in rankings:
        s = row["school"]
        t = team_by_school.get(s, {})
        pvd = pv.get(s, {})
        stats = t.get("stats", {}) or {}
        detail[s] = {
            "school": s,
            "abbreviation": row["abbreviation"],
            "conference": row["conference"],
            "classification": row["classification"],
            "color": row["color"],
            "logo": row["logo"],
            "record": row["record"],
            "ranks": {v: row["ranks"][v]["overall"] for v in VIEWS},
            "ratings": {v: row["ratings"][v]["overall"] for v in VIEWS},
            "unit_ranks": {v: {u: row["ranks"][v][u] for u in ("offense", "defense", "special")} for v in VIEWS},
            "unit_ratings": {v: {u: row["ratings"][v][u] for u in ("offense", "defense", "special")} for v in VIEWS},
            "returning_pct": pvd.get("returning_pct", 0.0),
            "impaired": pvd.get("impaired", 0),
            "team_stats": {"offense": ranking._flatten_stats(stats.get("offense")),
                           "defense": ranking._flatten_stats(stats.get("defense"))},
            "players": [
                {"id": p["id"], "name": p["name"], "position": p["position"],
                 "group": p["group"], "side": p["side"], "class": p["class"],
                 "value": round(p["value"], 1), "contrib": p.get("team_contrib", 0.0),
                 "status": p["status"], "basis": p["basis"], "ppa_recent": p["ppa_recent"]}
                for p in pvd.get("players", [])
            ],
            "schedule": ranking._build_schedule(known_by_school.get(s, {}), s, credits_known.get(s, {})),
            "projection": row["_projection"],
        }

    # --- Game details + upcoming (predictions from Current ratings) ---
    games_map = {}
    upcoming = defaultdict(list)
    seen = set()
    for s in detail:
        for g in known_by_school.get(s, {}).get("games", []):
            gid = g.get("id")
            if gid in seen:
                continue
            seen.add(gid)
            home, away = g.get("homeTeam"), g.get("awayTeam")
            hr, ar = cur_shim_by_school.get(home), cur_shim_by_school.get(away)
            completed = g.get("homePoints") is not None and g.get("awayPoints") is not None
            gd = ranking.build_game_detail(g, hr, ar, home, away, completed,
                                           credit_detail.get(gid, {}), detail, n_teams)
            gd["override"] = bool(g.get("_override"))
            games_map[str(gid)] = gd
            if not completed and hr and ar:
                upcoming[g.get("week")].append({
                    "id": gid, "week": g.get("week"), "home": home, "away": away,
                    "home_rank": hr["rank_blended"], "away_rank": ar["rank_blended"],
                    "home_color": row_by_school[home]["color"], "away_color": row_by_school[away]["color"],
                    "home_logo": row_by_school[home]["logo"], "away_logo": row_by_school[away]["logo"],
                    "impact": gd.get("impact"), "prediction": gd.get("prediction"),
                    "neutral": bool(g.get("neutralSite")),
                })
    upcoming_by_week = {}
    for wk, lst in upcoming.items():
        lst.sort(key=lambda x: (x["impact"]["score"] if x.get("impact") else 0), reverse=True)
        upcoming_by_week[str(wk)] = lst[:20]

    # --- Bracket from the Predictive ranking ---
    pred_shim = [_shim(r, "predictive") for r in rankings]
    pred_shim.sort(key=lambda x: x["rank_blended"])
    bracket = ranking.build_bracket(pred_shim)

    # Strip internal fields from the list payload.
    for r in rankings:
        r.pop("_projection", None)

    return {
        "avail": avail,
        "cutoff_week": cutoff_week,
        "has_games": any_games,
        "rankings": rankings,
        "teams": detail,
        "games": games_map,
        "upcoming": upcoming_by_week,
        "bracket": bracket,
    }


def predict_pair(rankings, home_school, away_school, neutral=False, basis="current"):
    """Predict a matchup using the chosen view's ratings."""
    row_by_school = {r["school"]: r for r in rankings}
    hr, ar = row_by_school.get(home_school), row_by_school.get(away_school)
    if not hr or not ar:
        return {"error": "unknown team"}
    hs, as_ = _shim(hr, basis), _shim(ar, basis)
    pred = ranking.predict_matchup(hs, as_, neutral=neutral)
    n = len(rankings)
    return {"home": ranking._team_ref(hs, home_school),
            "away": ranking._team_ref(as_, away_school),
            "prediction": pred, "impact": ranking.game_impact(hs, as_, pred, n),
            "basis": basis, "stats_compare": None}


# ---------------------------------------------------------------------------
# Monte Carlo: playoff odds, win-total & seed distributions, title odds
# ---------------------------------------------------------------------------
def _remaining_games(known_teams):
    """Unique unplayed games between two ranked teams, as (id, home, away,
    neutral, week)."""
    seen = set()
    out = []
    for t in known_teams:
        for g in t.get("games", []):
            gid = g.get("id")
            if gid in seen:
                continue
            seen.add(gid)
            if g.get("homePoints") is None or g.get("awayPoints") is None:
                out.append({"id": gid, "home": g.get("homeTeam"), "away": g.get("awayTeam"),
                            "neutral": bool(g.get("neutralSite")), "week": g.get("week")})
    return out


def montecarlo(raw, prep, world, avail="avail", cutoff_week=None, overrides=None,
               n_sims=2000, seed=None):
    """Simulate the remaining schedule `n_sims` times from Current win
    probabilities and tally playoff/championship odds and win distributions.

    Returns {school: {...odds...}} plus meta. Pure Python; ~2000 sims over a
    full season runs in a couple of seconds.
    """
    rng = random.Random(seed)
    rankings = world["rankings"]
    row_by_school = {r["school"]: r for r in rankings}
    fbs = set(row_by_school)
    cur_shim = {r["school"]: _shim(r, "current") for r in rankings}

    teams = raw.get("teams", [])
    known_teams = apply_scenario(teams, cutoff_week, overrides)
    known_by_school = {t["school"]: t for t in known_teams}

    # Known wins/losses per team (respecting the scenario).
    base_wins = {s: 0 for s in fbs}
    for s in fbs:
        for g in known_by_school.get(s, {}).get("games", []):
            hp, ap = g.get("homePoints"), g.get("awayPoints")
            if hp is None or ap is None:
                continue
            is_home = g.get("homeTeam") == s
            tp, op = (hp, ap) if is_home else (ap, hp)
            if tp > op:
                base_wins[s] += 1

    # Precompute win prob (home perspective) for each remaining game.
    rem = _remaining_games(known_teams)
    sim_games = []
    for g in rem:
        h, a = g["home"], g["away"]
        hr, ar = cur_shim.get(h), cur_shim.get(a)
        if not hr or not ar:
            continue  # games vs unranked don't affect the FBS-only odds board
        pred = ranking.predict_matchup(hr, ar, neutral=g["neutral"])
        sim_games.append((h, a, pred["win_prob_home"]))

    # Conference membership for auto-bid logic.
    conf_of = {s: (row_by_school[s].get("conference") or "") for s in fbs}
    # Fixed "quality" ordering used to seed the playoff each sim: Current
    # overall strength as a tiebreaker-stable proxy (updated by simulated wins).
    base_strength = {s: row_by_school[s]["strength"]["current"] for s in fbs}

    tally = {s: {"playoff": 0, "bye": 0, "conf_title": 0, "final": 0, "champ": 0,
                 "wins_sum": 0, "wins_sq": 0, "wins_hist": defaultdict(int),
                 "seed_hist": defaultdict(int)} for s in fbs}

    indep = "FBS Independents"

    for _ in range(n_sims):
        wins = dict(base_wins)
        for h, a, ph in sim_games:
            if rng.random() < ph:
                wins[h] += 1
            else:
                wins[a] += 1
        # Season score: wins dominate, strength breaks ties.
        score = {s: wins[s] + 0.01 * base_strength[s] for s in fbs}
        order = sorted(fbs, key=lambda s: score[s], reverse=True)

        # Conference champions = top team in each conference by score.
        champ_by_conf = {}
        for s in order:
            c = conf_of[s]
            if not c or c == indep:
                continue
            if c not in champ_by_conf:
                champ_by_conf[c] = s
                tally[s]["conf_title"] += 1
        champs = sorted(champ_by_conf.values(), key=lambda s: score[s], reverse=True)
        auto = champs[:5]
        byes = auto[:4]
        bye_set = set(byes)
        auto_set = set(auto)

        # At-large fill to 12 by score.
        field = list(auto)
        for s in order:
            if len(field) >= 12:
                break
            if s not in auto_set:
                field.append(s)
        field = field[:12]
        # Seed: byes 1-4 (by score), then rest by score.
        seeds = sorted(byes, key=lambda s: score[s], reverse=True)
        rest = sorted([s for s in field if s not in bye_set], key=lambda s: score[s], reverse=True)
        seeds = seeds + rest
        for i, s in enumerate(seeds, 1):
            tally[s]["playoff"] += 1
            tally[s]["seed_hist"][i] += 1
            if i <= 4:
                tally[s]["bye"] += 1

        # Simulate the 12-team bracket with the same win-prob model.
        S = {i + 1: seeds[i] for i in range(len(seeds))}
        if len(seeds) >= 12:
            def game(hi, lo):
                hr, ar = cur_shim[hi], cur_shim[lo]
                pred = ranking.predict_matchup(hr, ar, neutral=True)
                return hi if rng.random() < pred["win_prob_home"] else lo
            w5_12 = game(S[5], S[12]); w8_9 = game(S[8], S[9])
            w6_11 = game(S[6], S[11]); w7_10 = game(S[7], S[10])
            q1 = game(S[1], w8_9); q2 = game(S[4], w5_12)
            q3 = game(S[3], w6_11); q4 = game(S[2], w7_10)
            s1 = game(q1, q2); s2 = game(q3, q4)
            champ = game(s1, s2)
            tally[s1]["final"] += 1   # reached the national championship game
            tally[s2]["final"] += 1
            tally[champ]["champ"] += 1

        for s in fbs:
            w = wins[s]
            tally[s]["wins_sum"] += w
            tally[s]["wins_sq"] += w * w
            tally[s]["wins_hist"][w] += 1

    out = {}
    for s in fbs:
        t = tally[s]
        avg = t["wins_sum"] / n_sims
        var = max(0.0, t["wins_sq"] / n_sims - avg * avg)
        out[s] = {
            "playoff_pct": round(t["playoff"] / n_sims, 4),
            "bye_pct": round(t["bye"] / n_sims, 4),
            "conf_title_pct": round(t["conf_title"] / n_sims, 4),
            "final_pct": round(t["final"] / n_sims, 4),
            "champ_pct": round(t["champ"] / n_sims, 4),
            "avg_wins": round(avg, 2),
            "wins_sd": round(math.sqrt(var), 2),
            "wins_hist": {str(k): round(v / n_sims, 4) for k, v in sorted(t["wins_hist"].items())},
            "top_seed_pct": round(t["seed_hist"].get(1, 0) / n_sims, 4),
        }
    return {"n_sims": n_sims, "teams": out}
