"""
ranking.py -- shared helpers for the DAVE engine.

The models themselves live in:
  model_players.py   player ratings + bottom-up roster roll-up (Power)
  model_results.py   opponent-adjusted results solver (points scale)
  engine.py          Power / Current / Predictive worlds + Monte Carlo

This module holds everything model-agnostic that the engine and the API reuse:
matchup prediction, game impact, schedules, game detail, the CFP bracket,
projected records, injuries, and player profiles.

All team strengths are in POINTS vs. an average FBS team on a neutral field,
so predicted margin = strength gap + home field.
"""

import json
import math
import statistics
from collections import defaultdict

import config
import model_players as mp

# Re-exported so existing imports keep working.
as_float = mp.as_float
norm_pos = mp.norm_pos
full_name = mp.full_name
parse_injuries = mp.parse_injuries

# ---------------------------------------------------------------------------
# Prediction constants (engine.prepare() overwrites HOME_FIELD / BASE_PPG
# with values fitted from the data).
# ---------------------------------------------------------------------------
HOME_FIELD = 2.5           # points
BASE_PPG = 28.0            # average points per team per game
MARGIN_SD = 15.5           # sd of actual margin around the prediction
MARGIN_LOGISTIC = MARGIN_SD * math.sqrt(3) / math.pi   # ~8.5
NON_FBS_WIN_PROB = 0.85    # fallback only when an opponent has no rating


def is_fbs(team):
    """Strict: only an explicit "fbs" classification counts. (A missing
    classification used to count as FBS, which let non-FBS teams in.)
    engine.fbs_membership() is the authoritative check."""
    return team.get("classification") == "fbs" if config.FBS_ONLY else True


def _zmap(values):
    vals = list(values.values())
    if len(vals) < 2:
        return {k: 0.0 for k in values}
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) or 1.0
    return {k: (v - mu) / sd for k, v in values.items()}


def _flatten_stats(d):
    if not isinstance(d, dict):
        return {}
    return {k: round(v, 2) for k, v in d.items() if isinstance(v, (int, float))}


def load_injuries(path=None):
    path = path or config.INJURIES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return set(), set(), set(), set()
    entries = payload.get("players", payload) if isinstance(payload, dict) else payload
    return parse_injuries(entries)


# ===========================================================================
# Matchup prediction + game impact
# ===========================================================================
def _logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def win_prob(margin):
    """P(win) for a predicted margin in points."""
    return _logistic(margin / MARGIN_LOGISTIC)


def predict_matchup(home, away, neutral=False):
    """Predict a game between two rows (home perspective). Rows need
    `strength_blended` (points); `off`/`def` (points) sharpen the score."""
    margin = (home.get("strength_blended", 0.0) - away.get("strength_blended", 0.0)
              + (0.0 if neutral else HOME_FIELD))
    p_home = win_prob(margin)
    total = 2 * BASE_PPG
    if all(k in r for r in (home, away) for k in ("off", "def")):
        total += (home["off"] - away["def"]) + (away["off"] - home["def"])
    total = max(total, 20.0)
    proj_home = max(0, round((total + margin) / 2))
    proj_away = max(0, round((total - margin) / 2))
    favorite = home["school"] if margin >= 0 else away["school"]
    return {
        "neutral": bool(neutral),
        "margin": round(margin, 1),
        "win_prob_home": round(p_home, 3),
        "win_prob_away": round(1 - p_home, 3),
        "proj_home": proj_home,
        "proj_away": proj_away,
        "favorite": favorite,
        "spread": f"{favorite} by {abs(round(margin, 1))}",
    }


def _impact_label(score):
    if score >= 78:
        return "Marquee"
    if score >= 60:
        return "Big"
    if score >= 40:
        return "Notable"
    if score >= 20:
        return "Minor"
    return "Irrelevant"


def game_impact(home, away, pred, n_teams):
    n = max(n_teams, 1)
    q_home = (n - home["rank_blended"] + 1) / n
    q_away = (n - away["rank_blended"] + 1) / n
    quality = (q_home + q_away) / 2
    competitiveness = 1 - abs(2 * pred["win_prob_home"] - 1)
    score = round(100 * (0.6 * quality + 0.4 * competitiveness))
    return {"score": score, "label": _impact_label(score),
            "quality": round(quality, 3), "competitiveness": round(competitiveness, 3)}


# ===========================================================================
# Schedules / game detail
# ===========================================================================
def _build_schedule(team, school, scores_for_team):
    """scores_for_team: {game_id: game score (points)} for completed games."""
    sched = []
    for g in team.get("games", []):
        is_home = g.get("homeTeam") == school
        opp = g.get("awayTeam") if is_home else g.get("homeTeam")
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        tp = hp if is_home else ap
        op = ap if is_home else hp
        completed = tp is not None and op is not None
        result = None
        if completed:
            result = "W" if tp > op else ("L" if tp < op else "T")
        gs = scores_for_team.get(g.get("id")) if completed else None
        sched.append({
            "id": g.get("id"), "week": g.get("week"), "opponent": opp,
            "home_away": "vs" if is_home else "@",
            "team_points": tp, "opp_points": op,
            "completed": bool(completed), "result": result,
            "neutral": bool(g.get("neutralSite")),
            "credit": round(gs, 1) if gs is not None else None,   # game score, points
        })
    sched.sort(key=lambda s: (s["week"] is None, s["week"] or 0))
    return sched


def _team_ref(row, school):
    if not row:
        return {"school": school, "fbs": False, "rank": None, "rating": None,
                "record": None, "color": "#556070", "logo": None, "abbreviation": ""}
    return {"school": school, "fbs": True, "abbreviation": row["abbreviation"],
            "rank": row["rank_blended"], "rating": row["rating_blended"],
            "record": row["record"], "color": row["color"], "logo": row["logo"],
            "conference": row["conference"]}


def _stats_compare(dh, da):
    empty = {"offense": [], "defense": []}
    if not dh or not da:
        return empty
    def cmp(side):
        sh = dh["team_stats"].get(side, {})
        sa = da["team_stats"].get(side, {})
        keys = [k for k in sh if k in sa][:10]
        return [{"stat": k, "home": sh[k], "away": sa[k]} for k in keys]
    return {"offense": cmp("offense"), "defense": cmp("defense")}



def _stats_compare(dh, da):
    empty = {"offense": [], "defense": []}
    if not dh or not da:
        return empty

    def cmp(side):
        sh = dh["team_stats"].get(side, {})
        sa = da["team_stats"].get(side, {})
        keys = [k for k in sh if k in sa][:10]
        return [{"stat": k, "home": sh[k], "away": sa[k]} for k in keys]
    return {"offense": cmp("offense"), "defense": cmp("defense")}


def build_game_detail(g, hr, ar, home, away, completed, gscores, detail, n_teams):
    """gscores: {school: game-score breakdown} from model_results.solve_margin."""
    entry = {"id": g.get("id"), "week": g.get("week"),
             "neutral": bool(g.get("neutralSite")), "completed": completed,
             "start_date": g.get("startDate"),
             "home": _team_ref(hr, home), "away": _team_ref(ar, away),
             "stats_compare": _stats_compare(detail.get(home), detail.get(away))}
    if completed:
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        entry["box"] = {"home_points": hp, "away_points": ap,
                        "home_line": g.get("homeLineScores"),
                        "away_line": g.get("awayLineScores")}
        entry["winner"] = home if hp > ap else (away if ap > hp else None)
        credit = {}
        for side, school, row_opp, tp, op in (("home", home, ar, hp, ap),
                                              ("away", away, hr, ap, hp)):
            gs = gscores.get(school)
            if gs:
                credit[side] = dict(gs, margin=tp - op, win=tp > op,
                                    opp_rank=(row_opp or {}).get("rank_blended"),
                                    credit=gs["game_score"])
        entry["credit"] = credit or None
    elif hr and ar:
        pred = predict_matchup(hr, ar, neutral=bool(g.get("neutralSite")))
        entry["prediction"] = pred
        entry["impact"] = game_impact(hr, ar, pred, n_teams)
    return entry


# ===========================================================================
# CFP bracket (12-team) + selected bowls
# ===========================================================================
def build_bracket(rows_by_school, field, race=None):
    """Play out the 12-team bracket.

    rows_by_school: prediction rows (strength etc.) keyed by school.
    field: cfp.select_field() output -- selection and seeding already follow
           the committee rules, so this function only handles pairings.
    race:  cfp.conference_race() output, echoed for the UI.
    """
    if not field or len(field["seeds"]) < 12:
        return None
    seeds = []
    for sd in field["seeds"]:
        r = dict(rows_by_school[sd["school"]])
        r["_seed"] = sd["seed"]
        seeds.append(r)
    S = {r["_seed"]: r for r in seeds}

    def play(a, b, neutral, rnd):
        pred = predict_matchup(a, b, neutral=neutral)
        home_wins = pred["win_prob_home"] >= 0.5
        return {"round": rnd, "neutral": neutral,
                "high": a["school"], "low": b["school"],
                "high_seed": a["_seed"], "low_seed": b["_seed"],
                "prediction": pred,
                "winner": a["school"] if home_wins else b["school"],
                "winner_row": a if home_wins else b}

    # First round on the higher seed's campus.
    first = [play(S[5], S[12], False, "First Round"),
             play(S[8], S[9], False, "First Round"),
             play(S[6], S[11], False, "First Round"),
             play(S[7], S[10], False, "First Round")]
    w = [m["winner_row"] for m in first]
    # Quarterfinals: 1 v 8/9, 4 v 5/12, 3 v 6/11, 2 v 7/10.
    qf = [play(S[1], w[1], True, "Quarterfinal"),
          play(S[4], w[0], True, "Quarterfinal"),
          play(S[3], w[2], True, "Quarterfinal"),
          play(S[2], w[3], True, "Quarterfinal")]
    qw = [m["winner_row"] for m in qf]

    def seed_order(a, b):
        return (a, b) if a["_seed"] < b["_seed"] else (b, a)
    # Semifinals: the 1 and 4 paths meet; the 2 and 3 paths meet.
    sf = [play(*seed_order(qw[0], qw[1]), True, "Semifinal"),
          play(*seed_order(qw[2], qw[3]), True, "Semifinal")]
    sw = [m["winner_row"] for m in sf]
    final = play(*seed_order(sw[0], sw[1]), True, "Championship")

    def strip(m):
        m = dict(m)
        m.pop("winner_row", None)
        return m

    info = {sd["school"]: sd for sd in field["seeds"]}

    def brief(school):
        r = rows_by_school.get(school, {})
        return {"school": school, "rank": r.get("rank_blended"),
                "record": r.get("record"), "conference": r.get("conference")}

    return {
        "seeds": [{"seed": r["_seed"], "school": r["school"],
                   "abbreviation": r["abbreviation"], "conference": r["conference"],
                   "rank": info[r["school"]]["committee_rank"],
                   "rating": r["rating_blended"],
                   "record": r["record"], "color": r["color"], "logo": r["logo"],
                   "bye": info[r["school"]]["bye"],
                   "bid": info[r["school"]]["bid"],
                   "auto_bid": info[r["school"]]["bid"] != "At-large"}
                  for r in seeds],
        "first_four_out": [brief(s) for s in field["first_four_out"]],
        "displaced": [brief(s) for s in field["displaced"]],
        "conference_title_games": [
            {"conference": c, "teams": v["teams"], "p_first": round(v["p_a"], 3),
             "champion": v["champion"], "decided": v["decided"]}
            for c, v in sorted((race or {}).items())],
        "first_round": [strip(m) for m in first],
        "quarterfinals": [strip(m) for m in qf],
        "semifinals": [strip(m) for m in sf],
        "final": strip(final),
        "champion": final["winner"],
    }


def predict_pair(rankings, home_school, away_school, neutral=False):
    row_by_school = {r["school"]: r for r in rankings}
    hr, ar = row_by_school.get(home_school), row_by_school.get(away_school)
    if not hr or not ar:
        return {"error": "unknown team"}
    pred = predict_matchup(hr, ar, neutral=neutral)
    return {"home": _team_ref(hr, home_school), "away": _team_ref(ar, away_school),
            "prediction": pred, "impact": game_impact(hr, ar, pred, len(rankings)),
            "stats_compare": None}


# ===========================================================================
# Projected record: actual results + predicted remaining games
# ===========================================================================
def project_record(team, school, row_by_school, other_strength=None):
    """other_strength: {school: points} for opponents outside row_by_school
    (e.g. FCS teams rated by the results solver)."""
    other_strength = other_strength or {}
    row = row_by_school.get(school)
    current, added = [0, 0], [0, 0]
    expected_wins = 0.0
    games = []
    for g in team.get("games", []):
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        is_home = g.get("homeTeam") == school
        opp = g.get("awayTeam") if is_home else g.get("homeTeam")
        if hp is not None and ap is not None:
            tp, op = (hp, ap) if is_home else (ap, hp)
            win = tp > op
            current[0 if win else 1] += 1
            expected_wins += 1.0 if win else 0.0
            games.append({"week": g.get("week"), "opponent": opp,
                          "home_away": "vs" if is_home else "@", "completed": True,
                          "result": "W" if win else ("L" if tp < op else "T"),
                          "team_points": tp, "opp_points": op})
            continue
        opp_row = row_by_school.get(opp)
        if opp_row is None and opp in other_strength:
            opp_row = {"school": opp, "strength_blended": other_strength[opp]}
        neutral = bool(g.get("neutralSite"))
        proj_for = proj_opp = None
        if opp_row and row:
            home_row, away_row = (row, opp_row) if is_home else (opp_row, row)
            pred = predict_matchup(home_row, away_row, neutral=neutral)
            p = pred["win_prob_home"] if is_home else pred["win_prob_away"]
            proj_for = pred["proj_home"] if is_home else pred["proj_away"]
            proj_opp = pred["proj_away"] if is_home else pred["proj_home"]
        else:
            p = NON_FBS_WIN_PROB
        pick_win = p >= 0.5
        added[0 if pick_win else 1] += 1
        expected_wins += p
        games.append({"week": g.get("week"), "opponent": opp,
                      "home_away": "vs" if is_home else "@", "completed": False,
                      "win_prob": round(p, 3), "pick": "W" if pick_win else "L",
                      "proj_for": proj_for, "proj_opp": proj_opp})
    games.sort(key=lambda s: (s["week"] is None, s["week"] or 0))
    return {"current": current,
            "projected": [current[0] + added[0], current[1] + added[1]],
            "expected_wins": round(expected_wins, 1),
            "remaining": added[0] + added[1],
            "games": games}


# ===========================================================================
# Player profiles
# ===========================================================================
def build_stat_lines(players):
    lines = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for year, rows in players.get("player_stats", {}).items():
        for r in rows:
            pid = str(r.get("playerId") or r.get("id"))
            if pid == "None":
                continue
            cat = (r.get("category") or "").lower()
            st = (r.get("statType") or "").upper()
            lines[pid][int(year)][cat][st] = as_float(r.get("stat"))
    return lines


def build_usage(players):
    usage = defaultdict(dict)
    for year, rows in players.get("usage", {}).items():
        for r in rows:
            pid = str(r.get("id") or r.get("playerId"))
            if pid == "None":
                continue
            usage[pid][int(year)] = as_float((r.get("usage") or {}).get("overall"))
    return usage


def build_current_form(players):
    form = defaultdict(list)
    for r in players.get("current_games", []) or []:
        pid = str(r.get("id") or r.get("playerId"))
        if pid == "None":
            continue
        form[pid].append((int(as_float(r.get("week"))), mp._ppa_all(r)))
    return form


def build_player_profiles(pv_extras, players, fbs_set, sched_pts=None):
    """Profiles keyed by athlete id. sched_pts: {year: {school: avg opp rating}}."""
    sched_pts = sched_pts or {}
    by_id, obs = pv_extras["by_id"], pv_extras["obs"]
    stat_lines, usage = build_stat_lines(players), build_usage(players)
    form = build_current_form(players)

    groups = defaultdict(list)
    for p in by_id.values():
        if p["team"] in fbs_set:
            groups[p["group"]].append(p)
    pos_rank = {}
    for plist in groups.values():
        for i, p in enumerate(sorted(plist, key=lambda x: x["R"], reverse=True), 1):
            pos_rank[p["id"]] = i

    profiles = {}
    for pid, p in by_id.items():
        if p["team"] not in fbs_set:
            continue
        seasons_obs = obs.get(pid, {})
        years = sorted(set(seasons_obs) | set(stat_lines.get(pid, {})))
        weight_by_year = {u["year"]: u for u in p["seasons_used"]}
        seasons = []
        for y in years:
            o = seasons_obs.get(y, {})
            school = o.get("team")
            sp = (sched_pts.get(y) or {}).get(school)
            u = weight_by_year.get(y)
            seasons.append({
                "year": y, "school": school,
                "sos": round(sp, 1) if sp is not None else None,
                "ppa_avg": round(o["ppa_avg"], 3) if o.get("plays") else None,
                "plays": int(o["plays"]) if o.get("plays") else None,
                "def_score": round(o["def_score"], 1) if o.get("def_score") is not None else None,
                "z": round(o["z"], 2) if o.get("z") is not None else None,
                "weight": u["weight"] if u else None,
                "usage": round(usage.get(pid, {}).get(y), 3) if usage.get(pid, {}).get(y) else None,
                "stats": {cat: {k: round(v, 1) for k, v in sd.items()}
                          for cat, sd in stat_lines.get(pid, {}).get(y, {}).items()},
            })
        cur = sorted(form.get(pid, []))
        current = {"games": len(cur),
                   "ppa_per_game": round(sum(v for _, v in cur) / len(cur), 3) if cur else None,
                   "log": [{"week": w, "ppa": round(v, 3)} for w, v in cur]}
        pr = pos_rank.get(pid)
        bits = [f"#{pr} {p['group']} nationally (grade {p['grade']})" if pr else None]
        if p["seasons_used"]:
            bits.append(f"rating built from {len(p['seasons_used'])} season(s) of production "
                        f"with the recruiting prior carrying {int(round(100 * p['prior_share']))}%")
        else:
            bits.append("no qualifying production yet; rating is the recruiting/class prior")
        if p["status"] != "active":
            why = (f" (auto: missed {p.get('missed_games')} straight games)"
                   if p.get("status_source") == "auto" else "")
            bits.append(f"currently {p['status'].upper()}{why}; "
                        f"his absence costs the team {p.get('impact', 0):.1f} pts"
                        + (f" (would be {p['group']} at {int(round(100 * p['healthy_share']))}% of snaps)"
                           if p.get("healthy_share") else ""))
        elif p.get("snap_share"):
            bits.append(f"{p.get('role_label', '').lower()}: {p['group']}{p['depth_rank']} at "
                        f"{int(round(100 * p['snap_share']))}% of snaps; team loses "
                        f"{p.get('impact', 0):.1f} pts if he's out")
        elif p["group"] in mp.SLOT_SHARES:
            bits.append(f"reserve ({p['group']}{p.get('depth_rank') or '—'}); plays only if others "
                        f"are out — worth {p.get('value_full', 0):.1f} pts as a full-time starter")
        profiles[pid] = {
            "id": pid, "name": p["name"], "team": p["team"], "position": p["position"],
            "group": p["group"], "side": p["side"], "class": p["class"],
            "status": p["status"], "status_source": p.get("status_source"),
            "basis": p["basis"], "value": round(p["value"], 1),
            "value_now": round(p.get("value_now", 0.0), 1),
            "value_full": round(p.get("value_full", 0.0), 1),
            "impact": p.get("impact", 0.0), "role": p.get("role_label"),
            "role_score": p.get("role"), "cur_role": p.get("cur_role"), "prev_role": p.get("prev_role"),
            "healthy_share": p.get("healthy_share"),
            "grade": p["grade"], "prior_z": p["prior_z"], "prior_share": p["prior_share"],
            "snap_share": p.get("snap_share"), "contrib": p.get("contrib", 0.0),
            "ppa_recent": p["ppa_recent"], "pos_rank": pr,
            "depth_rank": p.get("depth_rank"),
            "recruiting": p.get("recruit"),
            "seasons": seasons, "current": current,
            "summary": "; ".join(b for b in bits if b) + ".",
        }
    return profiles
