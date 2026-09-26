"""
engine.py -- Power / Current / Predictive ranking orchestration.

All ratings are in POINTS vs. an average FBS team on a neutral field.

  * Power       -- bottom-up roster rating (model_players), mapped to points:
                     unit_pts = a * sd_unit * z(roster_raw) + b * last_season_unit
                   sd_unit comes from last season's opponent-adjusted ratings.
                   a < 1 keeps a projection less spread out than reality; b is
                   the program-continuity term (coaching, scheme, depth the
                   roster data misses). calibrate.py fits a and b.
                   Available (injuries applied) or Full strength.
  * Current     -- the results solver with Power as its Bayesian prior:
                     r_i = (K * power_i + sum game evidence) / (K + games_i)
                   Opponent adjustment happens jointly, so early wins over
                   rosters that project well count more. Preseason: == Power.
  * Predictive  -- projected end-of-season RESUME (strength of record): actual
                   results + win probabilities for the rest, measured against
                   what a playoff-bubble team would do with the same schedule.
                   Blended lightly with Current and put on the points scale.
                   The CFP bracket seeds from this; game picks use Current.

Everything is computed for a "world" = (availability, as-of week, overrides).
Monte Carlo simulates the rest of the season with rating uncertainty that
shrinks as games are played.
"""

import json
import math
import os
import random
import statistics
from collections import defaultdict

import config
import ranking
import model_players as mp
import model_results as mr
import cfp

VIEWS = ("power", "current", "predictive")
UNITS = ("overall", "offense", "defense", "special")

# --- Calibration parameters (calibrate.py can overwrite via data/calibration.json)
PARAMS = {
    "PRIOR_GAMES": 5.0,        # K: pseudo-games of Power in the Current solve
    "ROSTER_COEF": 0.60,       # a: SDs of rating per SD of roster strength
    "PRIOR_COEF": 0.16,        # b: weight on last season's rating
    "PROGRAM_REGRESS": 0.65,   # year-over-year slope (diagnostic)
    "ST_SD": 1.5,              # points spread of special teams (no results signal)
    "RESUME_WEIGHT": 0.80,     # Predictive: resume vs. Current
    "BUBBLE_RANK": 12,         # benchmark team for strength of record
    "MC_RATING_SD": 6.0,       # preseason rating uncertainty (points)
    "MARGIN_DAMP": mr.MARGIN_DAMP,
    "MARGIN_SD": ranking.MARGIN_SD,
}
DEFAULT_SD = {"overall": 13.0, "offense": 7.5, "defense": 7.5}
FULL_SEASON_WEEKS = 13
CALIBRATION_FILE = os.path.join(config.DATA_DIR, "calibration.json")


CALIBRATION_MIN_VERSION = 2
_DEFAULT_GROUP_WEIGHT = dict(mp.GROUP_WEIGHT)
CALIBRATION_STATUS = {"loaded": False, "message": "defaults (no calibration.json)"}


def load_calibration(path=CALIBRATION_FILE):
    """Apply data/calibration.json if it came from a current calibrate.py.
    Files from the first version (no "version" key) are ignored: that
    version scored lower-division games and could zero out position weights."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            cal = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if int(cal.get("version", 1)) < CALIBRATION_MIN_VERSION:
        msg = ("calibration.json is from an older calibrate.py and was ignored; "
               "re-run: python calibrate.py")
        print("NOTE:", msg)
        CALIBRATION_STATUS.update(loaded=False, message=msg)
        return {}
    fitted = cal.get("params", {})
    for k, v in fitted.items():
        if k in PARAMS and isinstance(v, (int, float)):
            PARAMS[k] = v
    mr.MARGIN_DAMP = PARAMS["MARGIN_DAMP"]
    ranking.MARGIN_SD = PARAMS["MARGIN_SD"]
    ranking.MARGIN_LOGISTIC = PARAMS["MARGIN_SD"] * math.sqrt(3) / math.pi
    for g, v in (cal.get("group_weight") or {}).items():
        if g in mp.GROUP_WEIGHT and isinstance(v, (int, float)) and v > 0:
            d = _DEFAULT_GROUP_WEIGHT[g]
            mp.GROUP_WEIGHT[g] = min(max(v, 0.5 * d), 2.0 * d)   # safety bounds
    CALIBRATION_STATUS.update(loaded=True, message="calibrated")
    return fitted


def _rd(x):
    return round(x, 1)


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
# Shim rows so ranking.py helpers (predict/bracket/game detail) can be reused
# ---------------------------------------------------------------------------
def _shim(row, view):
    u = row["units"][view]
    return {
        "school": row["school"], "abbreviation": row["abbreviation"],
        "conference": row["conference"], "classification": row["classification"],
        "color": row["color"], "logo": row["logo"], "record": row["record"],
        "rank_blended": row["ranks"][view]["overall"],
        "rating_blended": row["ratings"][view]["overall"],
        "strength_blended": row["strength"][view],
        "off": u["offense"], "def": u["defense"],
    }


# ---------------------------------------------------------------------------
# Preparation shared across every world
# ---------------------------------------------------------------------------
def _fbs_values(d, classes):
    return [v for t, v in d.items() if classes.get(t) == "fbs"]


def _fit_season(game_rows, classes):
    games = mr.played_games([{"games": game_rows}])
    if len(games) < 50:
        return None
    cls = dict(classes)
    cls.update(mr.class_map([{"games": game_rows}]))
    fit = mr.solve_margin(games, cls)
    units = mr.solve_units(games, cls, hfa=fit["hfa"])
    return {"ratings": fit["ratings"], "offense": units["offense"],
            "defense": units["defense"], "mu": units["mu"], "hfa": fit["hfa"],
            "n_games": len(games), "classes": cls,
            "sched": mr.schedule_strength(games, fit["ratings"])}


def fbs_membership(raw, classes):
    """The season's FBS teams.

    1. CFBD's /teams/fbs list for the season (fetched on update), if present.
    2. Otherwise teams explicitly classified "fbs" (in /teams or in this
       season's game rows). Missing classification = not FBS.
    """
    listed = [s for s in (raw.get("fbs_teams") or []) if s]
    if listed:
        return set(listed), "cfbd /teams/fbs"
    return {t for t, c in classes.items() if c == "fbs"}, "classification"


def _sched_z(sched, classes):
    vals = {t: v for t, v in sched.items() if classes.get(t) == "fbs"}
    return ranking._zmap(vals)


def prepare(raw, injuries=None):
    """Season-invariant pieces: fitted history seasons, schedule strength,
    player ratings for both availability modes, and the raw->points mapping."""
    load_calibration()
    manual = ranking.load_injuries() if injuries is None else ranking.parse_injuries(injuries)
    teams = raw.get("teams", [])
    players = raw.get("players", {})
    year = int(raw.get("meta", {}).get("year", config.YEAR))
    classes = mr.class_map(teams)
    for t in teams:     # this season's game rows override stale /teams labels
        for g in t.get("games", []):
            for side in ("home", "away"):
                sch, c = g.get(side + "Team"), g.get(side + "Classification")
                if sch and c:
                    classes[sch] = c
    fbs, fbs_source = fbs_membership(raw, classes)
    if fbs_source == "cfbd /teams/fbs":
        for sch in fbs:
            classes[sch] = "fbs"
        for sch, c in list(classes.items()):
            if c == "fbs" and sch not in fbs:
                classes[sch] = "fcs"

    # Opponent-adjusted fits for each history season + the current season so far.
    fits = {}
    for y, rows in (raw.get("history_games") or {}).items():
        f = _fit_season(rows, classes)
        if f:
            fits[int(y)] = f
    cur_rows = []
    seen = set()
    for t in teams:
        for g in t.get("games", []):
            if g.get("id") not in seen:
                seen.add(g.get("id"))
                cur_rows.append(g)
    cur_fit = _fit_season(cur_rows, classes)
    if cur_fit:
        fits[year] = cur_fit

    sched_pts = {y: f["sched"] for y, f in fits.items()}
    sched_z = {y: _sched_z(f["sched"], f["classes"]) for y, f in fits.items()}

    _, latest_played = season_weeks(teams)
    year_frac = min(1.0, latest_played / FULL_SEASON_WEEKS)

    # Home field and scoring level: current season once it has enough games,
    # otherwise last season.
    ref = cur_fit if cur_fit and cur_fit["n_games"] >= 150 else fits.get(year - 1) or cur_fit
    hfa = ref["hfa"] if ref else mr.HFA_DEFAULT
    ranking.HOME_FIELD = hfa
    ranking.BASE_PPG = ref["mu"] if ref else ranking.BASE_PPG

    prior = fits.get(year - 1)
    sd = dict(DEFAULT_SD)
    if prior:
        for unit, key in (("overall", "ratings"), ("offense", "offense"), ("defense", "defense")):
            vals = _fbs_values(prior[key], prior["classes"])
            if len(vals) > 20:
                sd[unit] = statistics.pstdev(vals)

    team_games = {}
    for t in teams:
        team_games[t["school"]] = sum(1 for g in t.get("games", [])
                                      if g.get("homePoints") is not None and g.get("awayPoints") is not None)
    pv_modes = {}
    for mode, apply in (("avail", True), ("full", False)):
        pv, extras = mp.compute_player_value(players, manual, sched_z, year, year_frac,
                                             apply_availability=apply, team_games=team_games)
        # Drop non-FBS rosters; give FBS teams with no roster data a median
        # roster so they still get ranked (their Power leans on last season).
        for sch in [x for x in pv if x not in fbs]:
            del pv[sch]
        if pv:
            med = {u: sorted(d["raw"][u] for d in pv.values())[len(pv) // 2]
                   for u in ("offense", "defense", "special")}
            for sch in fbs:
                if sch not in pv:
                    pv[sch] = {"raw": dict(med), "groups": {}, "impaired": 0,
                               "returning_pct": 0.0, "players": [], "no_roster": True}
        extras["by_id"] = {k: v for k, v in extras["by_id"].items() if v["team"] in fbs}
        _to_points(pv, prior, sd, teams)
        pv_modes[mode] = (pv, extras)

    return {"manual": manual, "classes": classes, "fbs": fbs, "fbs_source": fbs_source,
            "fits_years": sorted(fits),
            "sched_pts": sched_pts, "sos_mult": sched_pts,  # sos_mult: legacy name
            "hfa": hfa, "sd": sd, "year": year, "year_frac": year_frac,
            "prior_year": ({s: prior["ratings"][s] for s in prior["ratings"]} if prior else {}),
            "pv_modes": pv_modes, "params": dict(PARAMS),
            "calibration": dict(CALIBRATION_STATUS)}


def _to_points(pv, prior, sd, teams):
    """Map each team's raw roster units to points and rescale player values."""
    P = PARAMS
    fbs = list(pv)          # prepare() already restricted pv to FBS teams
    a, b = P["ROSTER_COEF"], P["PRIOR_COEF"]
    scale = {}
    zs = {}
    for unit in ("offense", "defense", "special"):
        vals = {s: pv[s]["raw"][unit] for s in fbs}
        raw_sd = statistics.pstdev(vals.values()) if len(vals) > 1 else 1.0
        raw_sd = raw_sd or 1.0
        zs[unit] = ranking._zmap(vals)
        scale[unit] = (P["ST_SD"] if unit == "special" else a * sd[unit]) / raw_sd
    for s in pv:
        pts = {}
        for unit in ("offense", "defense"):
            roster = a * sd[unit] * zs[unit].get(s, 0.0)
            pts[unit] = roster + b * (prior[unit].get(s, 0.0) if prior else 0.0)
        pts["special"] = P["ST_SD"] * zs["special"].get(s, 0.0)
        pts["overall"] = pts["offense"] + pts["defense"] + pts["special"]
        pv[s]["power"] = pts
        pv[s]["roster_only"] = {u: a * sd[u] * zs[u].get(s, 0.0) for u in ("offense", "defense")}
        for p in pv[s]["players"]:
            k = scale.get(p["side"], scale["offense"])
            w = mp.GROUP_WEIGHT.get(p["group"], 0.0)
            above_repl = max(0.0, w * (p.get("R_eff", p["R"]) - mp.REPL_Z) * k)
            p["contrib"] = round(p["team_contrib"] * k, 2)
            # value       = points above replacement at the snaps he'll actually
            #               play when healthy (a backup's is small)
            # value_now   = same, at his current availability (0 if out)
            # value_full  = if he were a full-time starter
            # impact      = points his team loses if he's out (for an injured
            #               player: what his absence is costing right now)
            p["value"] = above_repl * p.get("healthy_share", p["snap_share"])
            p["value_now"] = above_repl * p["snap_share"]
            p["value_full"] = above_repl
            p["impact"] = round(p.get("impact_raw", 0.0) * k, 2)


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
# Build one world
# ---------------------------------------------------------------------------
def _outcome(g, school):
    hp, ap = g.get("homePoints"), g.get("awayPoints")
    if hp is None or ap is None:
        return None
    tp, op = (hp, ap) if g.get("homeTeam") == school else (ap, hp)
    return 1.0 if tp > op else (0.0 if tp < op else 0.5)


def _site(g, school):
    if g.get("neutralSite"):
        return 0
    return 1 if g.get("homeTeam") == school else -1


def build_world(raw, prep, avail="avail", cutoff_week=None, overrides=None):
    P = prep.get("params", PARAMS)
    teams = raw.get("teams", [])
    pv, _extras = prep["pv_modes"][avail]
    classes = prep["classes"]
    hfa = prep["hfa"]
    team_by_school = {t["school"]: t for t in teams}

    fbs_schools = sorted(s for s in pv if s in prep["fbs"])
    power = {s: pv[s]["power"] for s in fbs_schools}
    # Results were earned mostly at full strength, so the solve uses the
    # full-strength roster as its prior; availability is then applied as a
    # forward-looking delta (an injured QB costs his team in every future game,
    # no matter how many games have been played).
    pv_full = prep["pv_modes"]["full"][0]
    power_full = {s: pv_full.get(s, pv[s])["power"] for s in fbs_schools}
    avail_delta = {s: {u: power[s][u] - power_full[s][u] for u in UNITS} for s in fbs_schools}

    # --- Known results (cutoff + overrides) and the Current solve ---
    known_teams = apply_scenario(teams, cutoff_week, overrides)
    known_by_school = {t["school"]: t for t in known_teams}
    games = mr.played_games(known_teams)
    recs = mr.team_records(games)
    K = P["PRIOR_GAMES"]
    cur = mr.solve_margin(games, classes, prior={s: power_full[s]["overall"] for s in fbs_schools},
                          lam=K, hfa=hfa, damp_c=P["MARGIN_DAMP"])
    units = mr.solve_units(games, classes,
                           prior_off={s: power_full[s]["offense"] for s in fbs_schools},
                           prior_def={s: power_full[s]["defense"] for s in fbs_schools},
                           lam=K, hfa=hfa)
    all_ratings = dict(cur["ratings"])
    any_games = bool(games)

    current = {}
    for s in fbs_schools:
        d = avail_delta[s]
        current[s] = {"overall": all_ratings.get(s, power_full[s]["overall"]) + d["overall"],
                      "offense": units["offense"].get(s, power_full[s]["offense"]) + d["offense"],
                      "defense": units["defense"].get(s, power_full[s]["defense"]) + d["defense"],
                      "special": power[s]["special"]}
        all_ratings[s] = current[s]["overall"]

    def strength(s):
        if s in current:
            return current[s]["overall"]
        if s in all_ratings:
            return all_ratings[s]
        return mr.CLASS_PRIOR.get(classes.get(s), mr.UNKNOWN_CLASS_PRIOR)

    # --- Predictive: projected committee ranking ---
    # 1. Conference title race (who plays in each championship game, who wins).
    conf_of = {s: team_by_school.get(s, {}).get("conference") for s in fbs_schools}
    race = cfp.conference_race(known_by_school, conf_of, fbs_schools, strength,
                               ranking.win_prob, hfa)
    # 2. Strength of record: wins and losses against the schedule, relative to
    #    what a playoff-bubble team would do with it. Margin doesn't enter
    #    (the protocol says not to reward it). Unplayed championship games in
    #    the data are skipped; the projected one from step 1 is added instead.
    ordered = sorted(fbs_schools, key=lambda s: current[s]["overall"], reverse=True)
    bubble = current[ordered[min(len(ordered), int(P["BUBBLE_RANK"])) - 1]]["overall"] if ordered else 0.0
    sor = {}
    beat, record_vs = {}, {}      # head-to-head + common opponents (played + projected picks)
    seen_h2h = set()
    for s in fbs_schools:
        total = 0.0
        for g in known_by_school.get(s, {}).get("games", []):
            out = _outcome(g, s)
            if out is None and cfp.is_ccg(g, conf_of):
                continue
            opp = g.get("awayTeam") if g.get("homeTeam") == s else g.get("homeTeam")
            site = _site(g, s) * hfa
            p_team = ranking.win_prob(strength(s) - strength(opp) + site)
            p_bub = ranking.win_prob(bubble - strength(opp) + site)
            total += (p_team if out is None else out) - p_bub
            gid = g.get("id")
            if gid not in seen_h2h and out != 0.5:
                seen_h2h.add(gid)
                won = (out == 1.0) if out is not None else (p_team >= 0.5)
                cfp.add_result(beat, record_vs, s if won else opp, opp if won else s)
        sor[s] = total
    for conf, info in race.items():
        if info["decided"] or len(info["teams"]) < 2:
            continue
        a, b = info["teams"]
        p = info["p_a"]
        sor[a] += p - ranking.win_prob(bubble - strength(b))
        sor[b] += (1 - p) - ranking.win_prob(bubble - strength(a))
        w = info["champion"]
        cfp.add_result(beat, record_vs, w, b if w == a else a)
    # 3. Committee score = mostly resume, a little quality. Then the protocol's
    #    tiebreaks (head-to-head, common opponents) among comparable teams.
    sor_mu = statistics.mean(sor.values()) if sor else 0.0
    sor_sd = (statistics.pstdev(sor.values()) if len(sor) > 1 else 1.0) or 1.0
    cur_sd = statistics.pstdev([current[s]["overall"] for s in fbs_schools]) if len(fbs_schools) > 1 else 1.0
    rw = P["RESUME_WEIGHT"]
    committee_score = {s: rw * cur_sd * (sor[s] - sor_mu) / sor_sd + (1 - rw) * current[s]["overall"]
                       for s in fbs_schools}
    committee = cfp.committee_order(committee_score, beat, record_vs)
    field = cfp.select_field(committee, conf_of,
                             {c: v["champion"] for c, v in race.items()})
    predictive = {s: {"overall": committee_score[s],
                      "offense": current[s]["offense"], "defense": current[s]["defense"],
                      "special": current[s]["special"]} for s in fbs_schools}

    by_view = {"power": power, "current": current, "predictive": predictive}

    # --- Rows ---
    rankings = []
    for s in fbs_schools:
        t = team_by_school.get(s, {})
        r = recs.get(s, {"record": [0, 0], "games": 0})
        pvd = pv.get(s, {})
        logos = t.get("logos") or []
        g = r.get("games", 0)
        rankings.append({
            "school": s,
            "abbreviation": t.get("abbreviation", ""),
            "conference": t.get("conference"),
            "classification": t.get("classification"),
            "color": t.get("color") or "#444444",
            "logo": logos[0] if logos else None,
            "record": r["record"],
            "games": g,
            "prior_share": round(K / (K + g), 2),
            "sor": round(sor.get(s, 0.0), 2),
            "impaired": pvd.get("impaired", 0),
            "returning_pct": pvd.get("returning_pct", 0.0),
            "ratings": {v: {u: _rd(by_view[v][s][u]) for u in UNITS} for v in VIEWS},
            "units": {v: {"offense": by_view[v][s]["offense"],
                          "defense": by_view[v][s]["defense"]} for v in VIEWS},
            "ranks": {v: {} for v in VIEWS},
            "strength": {v: by_view[v][s]["overall"] for v in VIEWS},
        })
    for v in VIEWS:
        for u in UNITS:
            key = (lambda x, v=v, u=u: by_view[v][x["school"]][u])
            for i, row in enumerate(sorted(rankings, key=key, reverse=True), 1):
                row["ranks"][v][u] = i
    committee_rank = {sch: i for i, sch in enumerate(committee, 1)}
    cfp_seed = {sd["school"]: sd for sd in field["seeds"]}
    for row in rankings:
        row["ranks"]["predictive"]["overall"] = committee_rank[row["school"]]
        sd = cfp_seed.get(row["school"])
        row["cfp_seed"] = sd["seed"] if sd else None
        row["cfp_bid"] = sd["bid"] if sd else None
    rankings.sort(key=lambda x: x["ranks"]["current"]["overall"])

    row_by_school = {r["school"]: r for r in rankings}
    n_teams = len(rankings)
    other_strength = {t: round(v, 2) for t, v in all_ratings.items() if t not in row_by_school}

    # --- Projections from Current ---
    cur_shim_by_school = {r["school"]: _shim(r, "current") for r in rankings}
    projections = {}
    for row in rankings:
        s = row["school"]
        proj = ranking.project_record(known_by_school.get(s, {}), s, cur_shim_by_school,
                                      other_strength)
        row["proj_record"] = proj["projected"]
        row["expected_wins"] = proj["expected_wins"]
        row["remaining"] = proj["remaining"]
        projections[s] = proj

    # --- Per-team detail ---
    game_scores = cur["game_scores"]
    detail = {}
    for row in rankings:
        s = row["school"]
        t = team_by_school.get(s, {})
        pvd = pv.get(s, {})
        stats = t.get("stats", {}) or {}
        detail[s] = {
            "school": s, "abbreviation": row["abbreviation"],
            "conference": row["conference"], "classification": row["classification"],
            "color": row["color"], "logo": row["logo"], "record": row["record"],
            "ranks": {v: row["ranks"][v]["overall"] for v in VIEWS},
            "ratings": {v: row["ratings"][v]["overall"] for v in VIEWS},
            "unit_ranks": {v: {u: row["ranks"][v][u] for u in ("offense", "defense", "special")} for v in VIEWS},
            "unit_ratings": {v: {u: row["ratings"][v][u] for u in ("offense", "defense", "special")} for v in VIEWS},
            "power_breakdown": {"roster_offense": _rd(pvd.get("roster_only", {}).get("offense", 0.0)),
                                "roster_defense": _rd(pvd.get("roster_only", {}).get("defense", 0.0)),
                                "last_season": _rd(prep["prior_year"].get(s, 0.0))},
            "prior_share": row["prior_share"],
            "returning_pct": pvd.get("returning_pct", 0.0),
            "impaired": pvd.get("impaired", 0),
            "team_stats": {"offense": ranking._flatten_stats(stats.get("offense")),
                           "defense": ranking._flatten_stats(stats.get("defense"))},
            "players": [
                {"id": p["id"], "name": p["name"], "position": p["position"],
                 "group": p["group"], "side": p["side"], "class": p["class"],
                 "value": round(p["value"], 1), "contrib": p.get("contrib", 0.0),
                 "grade": p["grade"], "snap_share": p.get("snap_share"),
                 "healthy_share": p.get("healthy_share"), "role": p.get("role_label"),
                 "impact": p.get("impact", 0.0), "value_full": round(p.get("value_full", 0.0), 1),
                 "status_source": p.get("status_source"), "missed_games": p.get("missed_games"),
                 "depth_rank": p.get("depth_rank"),
                 "status": p["status"], "basis": p["basis"], "ppa_recent": p["ppa_recent"]}
                for p in pvd.get("players", [])
            ],
            "schedule": ranking._build_schedule(
                known_by_school.get(s, {}), s,
                {gid: sc[s]["game_score"] for gid, sc in game_scores.items() if s in sc}),
            "projection": projections[s],
        }

    # --- Game details + upcoming ---
    games_map, upcoming, seen = {}, defaultdict(list), set()
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
                                           game_scores.get(gid, {}), detail, n_teams)
            gd["override"] = bool(g.get("_override"))
            games_map[str(gid)] = gd
            if not completed and hr and ar:
                upcoming[g.get("week")].append({
                    "id": gid, "week": g.get("week"), "home": home, "away": away,
                    "home_rank": hr["rank_blended"], "away_rank": ar["rank_blended"],
                    "home_color": hr["color"], "away_color": ar["color"],
                    "home_logo": hr["logo"], "away_logo": ar["logo"],
                    "impact": gd.get("impact"), "prediction": gd.get("prediction"),
                    "neutral": bool(g.get("neutralSite")),
                })
    upcoming_by_week = {}
    for wk, lst in upcoming.items():
        lst.sort(key=lambda x: (x["impact"]["score"] if x.get("impact") else 0), reverse=True)
        upcoming_by_week[str(wk)] = lst[:20]

    # --- Bracket: committee selection + seeding; games picked with Current ---
    bracket_rows = {}
    for r in rankings:
        b = _shim(r, "current")
        b["rank_blended"] = r["ranks"]["predictive"]["overall"]
        b["rating_blended"] = r["ratings"]["predictive"]["overall"]
        bracket_rows[r["school"]] = b
    bracket = ranking.build_bracket(bracket_rows, field, race)

    return {
        "avail": avail,
        "cutoff_week": cutoff_week,
        "has_games": any_games,
        "hfa": round(hfa, 2),
        "rankings": rankings,
        "teams": detail,
        "games": games_map,
        "upcoming": upcoming_by_week,
        "bracket": bracket,
        "other_strength": other_strength,
        "conferences": _conference_summary(rankings, known_by_school, conf_of, race, field, hfa),
        "committee": {"bubble": bubble, "sor_mu": sor_mu, "sor_sd": sor_sd,
                      "cur_sd": cur_sd, "decided_champions":
                      {c: v["champion"] for c, v in race.items() if v["decided"]}},
    }


# ---------------------------------------------------------------------------
# Conference comparison
# ---------------------------------------------------------------------------
def _median(v):
    v = sorted(v)
    n = len(v)
    return (v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2) if n else 0.0


def _conference_summary(rankings, known_by_school, conf_of, race, field, hfa):
    """Per-conference strength, depth, non-conference results, head-to-head
    between conferences, and playoff outlook for the current world."""
    rows = {r["school"]: r for r in rankings}
    fbs = set(rows)

    # Independents are not a conference: each one is its own entry, so e.g.
    # Notre Dame can be compared directly with a whole league.
    def group(s):
        c = conf_of.get(s)
        return s if (not c or c == cfp.INDEPENDENTS) else c

    members = defaultdict(list)
    for s in fbs:
        members[group(s)].append(s)

    cur = {s: rows[s]["strength"]["current"] for s in fbs}
    ordered = sorted(fbs, key=lambda s: cur[s], reverse=True)
    top25_line = cur[ordered[min(24, len(ordered) - 1)]] if ordered else 0.0
    seeds = {sd["school"]: sd for sd in field["seeds"]}

    # Game-level tallies from completed games (each game once).
    nonconf = defaultdict(lambda: {"w": 0, "l": 0, "margin": 0.0, "n": 0,
                                   "p4_w": 0, "p4_l": 0, "fcs_w": 0, "fcs_l": 0})
    matrix = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    conf_rec = {s: [0, 0] for s in fbs}
    seen = set()
    for s in fbs:
        for g in known_by_school.get(s, {}).get("games", []):
            gid = g.get("id")
            if gid in seen:
                continue
            seen.add(gid)
            h, a = g.get("homeTeam"), g.get("awayTeam")
            hp, ap = g.get("homePoints"), g.get("awayPoints")
            if hp is None or ap is None or hp == ap:
                continue
            ch, ca = conf_of.get(h), conf_of.get(a)
            if h in fbs and a in fbs and ch == ca and ch != cfp.INDEPENDENTS:
                if cfp.is_conf_game(g, conf_of):
                    w, l = (h, a) if hp > ap else (a, h)
                    conf_rec[w][0] += 1
                    conf_rec[l][1] += 1
                continue
            for team, opp, tp, op in ((h, a, hp, ap), (a, h, ap, hp)):
                if team not in fbs:
                    continue
                c = group(team)
                rec = nonconf[c]
                won = tp > op
                if opp in fbs:
                    rec["w" if won else "l"] += 1
                    rec["margin"] += tp - op
                    rec["n"] += 1
                    oc = group(opp)
                    matrix[c][oc][0 if won else 1] += 1
                    if oc in cfp.P4_CONFS and c not in cfp.P4_CONFS:
                        rec["p4_w" if won else "p4_l"] += 1
                else:
                    rec["fcs_w" if won else "fcs_l"] += 1

    # Full-season schedule strength: average Current rating of FBS opponents.
    sched = {}
    for s in fbs:
        opps = [cur[g.get("awayTeam") if g.get("homeTeam") == s else g.get("homeTeam")]
                for g in known_by_school.get(s, {}).get("games", [])
                if (g.get("awayTeam") if g.get("homeTeam") == s else g.get("homeTeam")) in fbs]
        sched[s] = sum(opps) / len(opps) if opps else 0.0

    out = []
    for conf, teams in members.items():
        independent = conf in fbs and group(conf) == conf
        teams.sort(key=lambda s: cur[s], reverse=True)
        vals = [cur[s] for s in teams]
        pw = [rows[s]["strength"]["power"] for s in teams]
        half = vals[:max(1, (len(vals) + 1) // 2)]
        nc = nonconf[conf]
        info = race.get(conf)
        out.append({
            "conference": conf,
            "tier": ("Power 4" if conf in cfp.P4_CONFS else
                     "Group of 6" if conf in cfp.G6_CONFS else "Independent"),
            "independent": independent,
            "teams": len(teams),
            "avg": _rd(statistics.mean(vals)), "median": _rd(_median(vals)),
            "top": _rd(vals[0]), "top_half": _rd(statistics.mean(half)),
            "bottom": _rd(vals[-1]),
            "spread": _rd(statistics.pstdev(vals)) if len(vals) > 1 else 0.0,
            "power_avg": _rd(statistics.mean(pw)),
            "delta_vs_power": _rd(statistics.mean(vals) - statistics.mean(pw)),
            # Neutral-site win % an average FBS team (0.0) / a top-25-caliber
            # team would post against every member: a "how hard is this
            # league" number that accounts for depth, not just the top.
            "avg_team_win_pct": round(statistics.mean(ranking.win_prob(-v) for v in vals), 3),
            "top25_team_win_pct": round(statistics.mean(ranking.win_prob(top25_line - v) for v in vals), 3),
            "units": {u: _rd(statistics.mean(rows[s]["ratings"]["current"][u] for s in teams))
                      for u in ("offense", "defense", "special")},
            "returning_pct": round(statistics.mean(rows[s].get("returning_pct", 0.0) for s in teams), 3),
            "schedule_strength": _rd(statistics.mean(sched[s] for s in teams)),
            "nonconf": {"w": nc["w"], "l": nc["l"],
                        "avg_margin": _rd(nc["margin"] / nc["n"]) if nc["n"] else None,
                        "vs_p4": [nc["p4_w"], nc["p4_l"]],
                        "vs_fcs": [nc["fcs_w"], nc["fcs_l"]]},
            "top25": sum(1 for s in teams if rows[s]["ranks"]["predictive"]["overall"] <= 25),
            "cfp_bids": sum(1 for s in teams if s in seeds),
            "cfp_teams": [{"school": s, "seed": seeds[s]["seed"], "bid": seeds[s]["bid"]}
                          for s in sorted((t for t in teams if t in seeds),
                                          key=lambda t: seeds[t]["seed"])],
            "title_game": (None if independent else
                           {"teams": info["teams"], "p_first": round(info["p_a"], 3),
                            "champion": info["champion"], "decided": info["decided"]}
                           if info else None),
            "members": [{
                "school": s, "color": rows[s]["color"], "logo": rows[s]["logo"],
                "current": rows[s]["ratings"]["current"]["overall"],
                "power": rows[s]["ratings"]["power"]["overall"],
                "rank": rows[s]["ranks"]["current"]["overall"],
                "committee_rank": rows[s]["ranks"]["predictive"]["overall"],
                "record": rows[s]["record"], "conf_record": conf_rec[s],
                "proj_record": rows[s].get("proj_record"),
                "cfp_seed": rows[s].get("cfp_seed"),
            } for s in teams],
        })
    out.sort(key=lambda c: c["avg"], reverse=True)
    for i, c in enumerate(out, 1):
        c["rank"] = i
    confs = [c["conference"] for c in out]
    return {
        "conferences": out,
        "matrix": {"order": confs,
                   "records": {a: {b: matrix[a][b] for b in confs if sum(matrix[a][b])}
                               for a in confs}},
        "top25_line": _rd(top25_line),
    }


def predict_pair(rankings, home_school, away_school, neutral=False, basis="current"):
    """Predict a matchup using the chosen view's ratings."""
    row_by_school = {r["school"]: r for r in rankings}
    hr, ar = row_by_school.get(home_school), row_by_school.get(away_school)
    if not hr or not ar:
        return {"error": "unknown team"}
    hs, as_ = _shim(hr, basis), _shim(ar, basis)
    pred = ranking.predict_matchup(hs, as_, neutral=neutral)
    return {"home": ranking._team_ref(hs, home_school),
            "away": ranking._team_ref(as_, away_school),
            "prediction": pred, "impact": ranking.game_impact(hs, as_, pred, len(rankings)),
            "basis": basis, "stats_compare": None}


# ---------------------------------------------------------------------------
# Monte Carlo
# ---------------------------------------------------------------------------
def _remaining_games(known_teams):
    seen, out = set(), []
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
    """Simulate the rest of the season. Each sim first draws every team's
    'true' rating around Current, with uncertainty sd = MC_RATING_SD *
    sqrt(K / (K + games)), then plays each game from that draw. This keeps a
    team's games correlated within a sim (a team that's secretly better wins
    more of them), which fixed per-game probabilities miss."""
    P = prep.get("params", PARAMS)
    rng = random.Random(seed)
    rankings = world["rankings"]
    row_by_school = {r["school"]: r for r in rankings}
    fbs = list(row_by_school)
    other = world.get("other_strength", {})
    hfa = prep["hfa"]
    K = P["PRIOR_GAMES"]
    base = {s: row_by_school[s]["strength"]["current"] for s in fbs}
    base.update({t: v for t, v in other.items() if t not in base})
    sig = {s: P["MC_RATING_SD"] * math.sqrt(K / (K + row_by_school[s]["games"])) for s in fbs}

    known_teams = apply_scenario(raw.get("teams", []), cutoff_week, overrides)
    known_by_school = {t["school"]: t for t in known_teams}
    team_meta = {t["school"]: t for t in raw.get("teams", [])}
    conf_of = {s: (team_meta.get(s, {}).get("conference") or "") for s in fbs}
    L = ranking.MARGIN_LOGISTIC
    wp = ranking.win_prob

    # Committee-score constants from the deterministic world, so every sim is
    # scored on the same scale the Predictive ranking uses.
    cm = world.get("committee") or {}
    bubble = cm.get("bubble", 0.0)
    sor_mu, sor_sd = cm.get("sor_mu", 0.0), cm.get("sor_sd", 1.0) or 1.0
    cur_sd = cm.get("cur_sd", 1.0)
    rw = P["RESUME_WEIGHT"]
    decided = cm.get("decided_champions", {})

    # Known results: wins, strength of record, conference record, head-to-head.
    base_wins = {s: 0 for s in fbs}
    base_sor = {s: 0.0 for s in fbs}
    base_cw = {s: [0, 0] for s in fbs}          # conference W-L (regular season)
    base_beat, base_rec = {}, {}
    rem = []
    seen = set()
    for s in fbs:
        for g in known_by_school.get(s, {}).get("games", []):
            gid = g.get("id")
            h, a = g.get("homeTeam"), g.get("awayTeam")
            out = _outcome(g, s)
            opp = a if h == s else h
            if out is not None:
                base_sor[s] += out - wp(bubble - base.get(opp, -30.0) + _site(g, s) * hfa)
                if out == 1.0:
                    base_wins[s] += 1
            if gid in seen:
                continue
            seen.add(gid)
            ccg = cfp.is_ccg(g, conf_of)
            if out is None:
                if ccg or h not in base or a not in base:
                    continue            # CCGs are simulated from standings below
                site = 0.0 if g.get("neutralSite") else hfa
                rem.append((h, a, base[h] - base[a] + site,
                            wp(bubble - base[a] + site), wp(bubble - base[h] - site),
                            cfp.is_conf_game(g, conf_of)))
                continue
            if out == 0.5:
                continue
            w, l = (s, opp) if out == 1.0 else (opp, s)
            cfp.add_result(base_beat, base_rec, w, l)
            if not ccg and cfp.is_conf_game(g, conf_of):
                if w in base_cw:
                    base_cw[w][0] += 1
                if l in base_cw:
                    base_cw[l][1] += 1

    members = defaultdict(list)
    for s_ in fbs:
        if conf_of[s_] in cfp.P4_CONFS or conf_of[s_] in cfp.G6_CONFS:
            members[conf_of[s_]].append(s_)

    tally = {s: {"playoff": 0, "bye": 0, "conf_title": 0, "final": 0, "champ": 0,
                 "wins_sum": 0, "wins_sq": 0, "wins_hist": defaultdict(int),
                 "seed_hist": defaultdict(int)} for s in fbs}

    for _ in range(n_sims):
        e = {s: rng.gauss(0.0, sig[s]) for s in fbs}
        true = {s: base[s] + e[s] for s in fbs}
        wins = dict(base_wins)
        sor = dict(base_sor)
        cw = {s: list(v) for s, v in base_cw.items()}
        beat = dict(base_beat)
        rec = {k: {o: list(v) for o, v in d.items()} for k, d in base_rec.items()}

        # Regular season.
        for h, a, m, pb_h, pb_a, is_conf in rem:
            mm = m + e.get(h, 0.0) - e.get(a, 0.0)
            hw = rng.random() < 1.0 / (1.0 + math.exp(-mm / L))
            w, l = (h, a) if hw else (a, h)
            if w in wins:
                wins[w] += 1
            if h in sor:
                sor[h] += (1.0 if hw else 0.0) - pb_h
            if a in sor:
                sor[a] += (0.0 if hw else 1.0) - pb_a
            cfp.add_result(beat, rec, w, l)
            if is_conf:
                if w in cw:
                    cw[w][0] += 1
                if l in cw:
                    cw[l][1] += 1

        # Conference championship games: top two by conference win %.
        champions = dict(decided)
        for conf, teams in members.items():
            if conf in champions:
                continue
            ranked = sorted(teams, key=lambda t: ((cw[t][0] / sum(cw[t])) if sum(cw[t]) else 0.0,
                                                  true[t]), reverse=True)
            if len(ranked) < 2:
                continue
            a, b = ranked[0], ranked[1]
            aw = rng.random() < 1.0 / (1.0 + math.exp(-(true[a] - true[b]) / L))
            w, l = (a, b) if aw else (b, a)
            champions[conf] = w
            wins[w] += 1
            sor[a] += (1.0 if aw else 0.0) - wp(bubble - base[b])
            sor[b] += (0.0 if aw else 1.0) - wp(bubble - base[a])
            cfp.add_result(beat, rec, w, l)
        for c, w in champions.items():
            if w in tally:
                tally[w]["conf_title"] += 1

        # Committee ranking -> selection -> straight seeding.
        score = {s: rw * cur_sd * (sor[s] - sor_mu) / sor_sd + (1 - rw) * base[s] for s in fbs}
        order = cfp.committee_order(score, beat, rec, depth=cfp.MC_TIEBREAK_DEPTH)
        field = cfp.select_field(order, conf_of, champions)
        seeds = [sd["school"] for sd in field["seeds"]]
        for i, s_ in enumerate(seeds, 1):
            tally[s_]["playoff"] += 1
            tally[s_]["seed_hist"][i] += 1
            if i <= cfp.BYES:
                tally[s_]["bye"] += 1

        if len(seeds) >= 12:
            S = {i + 1: seeds[i] for i in range(12)}

            def game(hi, lo, home=False):
                m = true[hi] - true[lo] + (hfa if home else 0.0)
                return hi if rng.random() < 1.0 / (1.0 + math.exp(-m / L)) else lo
            w5 = game(S[5], S[12], True); w8 = game(S[8], S[9], True)
            w6 = game(S[6], S[11], True); w7 = game(S[7], S[10], True)
            q1, q2 = game(S[1], w8), game(S[4], w5)
            q3, q4 = game(S[3], w6), game(S[2], w7)
            s1, s2 = game(q1, q2), game(q3, q4)
            champ = game(s1, s2)
            tally[s1]["final"] += 1
            tally[s2]["final"] += 1
            tally[champ]["champ"] += 1

        for s_ in fbs:
            w = wins[s_]
            tally[s_]["wins_sum"] += w
            tally[s_]["wins_sq"] += w * w
            tally[s_]["wins_hist"][w] += 1

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
            "seed_dist": {str(k): round(v / n_sims, 4) for k, v in sorted(t["seed_hist"].items())},
        }
    return {"n_sims": n_sims, "teams": out}
