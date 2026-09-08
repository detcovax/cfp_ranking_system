"""
ranking.py -- the ranking model.

Combines three things into one blended, injury-aware ranking:
  1. Results model  -- opponent-adjusted "win credits" from completed games.
  2. Player value   -- bottom-up projection from each player's history, rolled
                       up onto the current roster, adjusted for availability.
  3. Blend          -- weights player value vs. results by how many games each
                       team has played (preseason = pure player value).

compute(raw, injuries) returns a dict with a ranking list and per-team drill-down
detail (season stats, players, schedule/results). Pure functions, no I/O except
optional injuries-file loading.
"""

import json
import math
import statistics
import datetime
from collections import defaultdict

import config

# ===========================================================================
# Results model parameters
# ===========================================================================
CLASSIFICATION_WEIGHTS = {"fbs": 1.0, "fcs": 0.5, "ii": 0.25, "iii": 0.1}
CONFERENCE_WEIGHTS = {
    "SEC": 1.2, "Big Ten": 1.2, "Big 12": 1.2, "ACC": 1.2,
    "Pac-12": 1.0, "American Athletic": 1.0, "Mountain West": 1.0,
    "Sun Belt": 1.0, "Conference USA": 1.0, "Mid-American": 1.0,
}
OTHER_WEIGHTS = {"Notre Dame": 1.2, "UConn": 1.0}
RESULTS_ITERATIONS = 25

# ===========================================================================
# Player-value model parameters
# ===========================================================================
POSITION_GROUP = {
    "QB": ("QB", "offense"),
    "RB": ("RB", "offense"), "FB": ("RB", "offense"), "TB": ("RB", "offense"),
    "WR": ("WR", "offense"), "TE": ("TE", "offense"),
    "OL": ("OL", "offense"), "OT": ("OL", "offense"), "OG": ("OL", "offense"),
    "C": ("OL", "offense"), "G": ("OL", "offense"), "T": ("OL", "offense"),
    "DL": ("DL", "defense"), "DE": ("DL", "defense"), "DT": ("DL", "defense"),
    "NT": ("DL", "defense"), "EDGE": ("DL", "defense"),
    "LB": ("LB", "defense"), "ILB": ("LB", "defense"), "OLB": ("LB", "defense"),
    "MLB": ("LB", "defense"),
    "DB": ("DB", "defense"), "CB": ("DB", "defense"), "S": ("DB", "defense"),
    "SAF": ("DB", "defense"), "FS": ("DB", "defense"), "SS": ("DB", "defense"),
    "NB": ("DB", "defense"),
    "K": ("K", "special"), "P": ("P", "special"), "PK": ("K", "special"),
    "LS": ("K", "special"),
}
POSITION_WEIGHT = {"QB": 3.5, "RB": 1.0, "WR": 1.3, "TE": 0.8, "OL": 1.6,
                   "DL": 1.6, "LB": 1.2, "DB": 1.3, "K": 0.3, "P": 0.2}
DEV_CURVE = {1: 1.15, 2: 1.12, 3: 1.06, 4: 1.01, 5: 1.00, 0: 1.05}
RECENCY_WEIGHTS = [0.65, 0.25, 0.10]
FRESHMAN_DISCOUNT = 0.35
STAR_BASE_VALUE = {5: 30.0, 4: 16.0, 3: 8.0, 2: 3.0, 1: 1.0, 0: 4.0}
DEF_STAT_WEIGHTS = {"TOT": 0.6, "SOLO": 0.4, "TACKLES": 0.6, "SACKS": 6.0,
                    "SACK": 6.0, "TFL": 3.0, "INT": 8.0, "PD": 2.5, "PBU": 2.5,
                    "QB HUR": 1.5, "HUR": 1.5, "FF": 4.0, "FUM": 2.0, "REC": 2.5,
                    "TD": 6.0}

# Availability / form
AUTO_INJURY_MIN_GAMES = 2
AUTO_INJURY_GAP_WEEKS = 2
LIMITED_FACTOR = 0.5
OUT_FACTOR = 0.0
APPLY_FORM = True
FORM_WEIGHT = 0.25
FORM_MIN, FORM_MAX = 0.70, 1.30
FORM_RAMP_GAMES = 5
GAMES_PER_SEASON = 12

# Blend
FULL_SEASON_GAMES = 12
MAX_RESULTS_WEIGHT = 0.85

# Strength of schedule (applied to each season's production before it feeds the
# player-value base). A player's season is scaled by how strong his team's
# schedule was that year, so production against tougher opponents is worth more.
SOS_WEIGHT = 0.15          # sensitivity: multiplier = 1 + SOS_WEIGHT * sos_z
SOS_MIN, SOS_MAX = 0.85, 1.15  # clamp so one extreme schedule can't dominate


def _depth_weight(rank):
    ladder = [1.0, 0.85, 0.55, 0.35, 0.2, 0.12, 0.08]
    return ladder[rank] if rank < len(ladder) else 0.04


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def as_float(x, default=0.0):
    try:
        return default if x is None else float(x)
    except (TypeError, ValueError):
        return default


def norm_pos(pos):
    if not pos:
        return ("UNK", "offense")
    return POSITION_GROUP.get(str(pos).upper(), ("UNK", "offense"))


def full_name(rec):
    n = rec.get("name")
    if n:
        return n
    return f"{rec.get('firstName','') or ''} {rec.get('lastName','') or ''}".strip()


def _ppa_all(rec):
    for key in ("averagePPA", "avgPPA", "ppa"):
        v = rec.get(key)
        if isinstance(v, dict):
            return as_float(v.get("all"))
        if isinstance(v, (int, float)):
            return as_float(v)
    return 0.0


def is_fbs(team):
    return (team.get("classification") in (None, "fbs")) if config.FBS_ONLY else True


# ===========================================================================
# Results model
# ===========================================================================
def compute_results(teams):
    """Return (results_by_school, credits_by_game). Only completed games count."""
    ranked = [t for t in teams if t.get("games")]
    by_school = {t["school"]: t for t in ranked}
    state = {t["school"]: {"winCredits": 0.0, "power_rank": i + 1}
             for i, t in enumerate(ranked)}
    n = len(ranked)
    credits_by_game = defaultdict(dict)  # school -> {game_id: credit}
    credit_detail = defaultdict(dict)    # game_id -> {school: {breakdown}}

    def iterate(record=False):
        order = sorted(ranked, key=lambda t: state[t["school"]]["winCredits"],
                       reverse=True)
        for i, t in enumerate(order):
            state[t["school"]]["power_rank"] = i + 1
        results = {}
        for t in order:
            school = t["school"]
            record_wl = [0, 0]
            total_margin = 0.0
            total_credits = 0.0
            points_for = 0.0
            points_against = 0.0
            for g in t.get("games", []):
                hp, ap = g.get("homePoints"), g.get("awayPoints")
                if hp is None or ap is None:
                    continue
                is_home = g.get("homeTeam") == school
                margin = (hp - ap) if is_home else (ap - hp)
                tp = hp if is_home else ap
                op = ap if is_home else hp
                points_for += tp
                points_against += op
                opp_name = g.get("awayTeam") if is_home else g.get("homeTeam")
                win = margin > 0
                record_wl[0 if win else 1] += 1

                opp = by_school.get(opp_name)
                if opp is not None:
                    opp_class = opp.get("classification")
                    opp_conf = opp.get("conference")
                    opp_rank = state[opp_name]["power_rank"]
                    opp_credits = state[opp_name]["winCredits"]
                else:
                    opp_class = (g.get("awayClassification") if is_home
                                 else g.get("homeClassification"))
                    opp_conf = None
                    opp_rank = n
                    opp_credits = 0.0

                class_w = CLASSIFICATION_WEIGHTS.get(opp_class, 0.1)
                conf_w = CONFERENCE_WEIGHTS.get(opp_conf, 1.0)
                other_w = OTHER_WEIGHTS.get(opp_name, 1.0)
                base = class_w * conf_w * other_w + opp_credits / 100.0
                mult = 1.055 ** (((n + 1 - opp_rank) / max(n, 1)) - 1)
                if win:
                    scale = base * mult
                else:
                    scale = (1.0 / base) / mult if base else 0.0
                credit = math.asinh(margin) * scale
                credits_by_game[school][g.get("id")] = credit
                total_margin += margin
                total_credits += credit
                if record:
                    credit_detail[g.get("id")][school] = {
                        "margin": margin, "opponent": opp_name, "opp_rank": opp_rank,
                        "win": win, "class_w": round(class_w, 3),
                        "conf_w": round(conf_w, 3), "other_w": round(other_w, 3),
                        "opp_bonus": round(opp_credits / 100.0, 3),
                        "quality_mult": round(mult, 3), "scale": round(scale, 3),
                        "credit": round(credit, 3),
                    }
            gp = record_wl[0] + record_wl[1]
            results[school] = {
                "record": record_wl, "margin": total_margin,
                "winCredits": total_credits,
                "games": gp,
                "points_for": points_for, "points_against": points_against,
                "off_ppg": (points_for / gp) if gp else 0.0,
                "def_ppg": (points_against / gp) if gp else 0.0,
            }
        return results

    results = {s: {"record": [0, 0], "margin": 0.0, "winCredits": 0.0, "games": 0,
                   "points_for": 0.0, "points_against": 0.0,
                   "off_ppg": 0.0, "def_ppg": 0.0}
               for s in by_school}
    for _ in range(RESULTS_ITERATIONS):
        new_results = iterate()
        for s, r in new_results.items():
            state[s]["winCredits"] = r["winCredits"]
        if new_results == results:
            break
        results = new_results

    results = iterate(record=True)  # final pass captures per-game breakdowns
    for s, r in results.items():
        r["results_metric"] = (r["winCredits"] / r["games"]) if r["games"] else 0.0
    return results, credits_by_game, credit_detail


# ===========================================================================
# Player-value model
# ===========================================================================
def load_injuries(path=None):
    path = path or config.INJURIES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return set(), set(), set(), set()
    entries = payload.get("players", payload) if isinstance(payload, dict) else payload
    return parse_injuries(entries)


def parse_injuries(entries):
    """Turn a list of {id|name, team, status} dicts into lookup sets.
    Accepts either a raw list or an already-parsed 4-tuple (passed through)."""
    if isinstance(entries, tuple) and len(entries) == 4:
        return entries
    out_ids, lim_ids, out_names, lim_names = set(), set(), set(), set()
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        status = (e.get("status") or "out").lower()
        pid = e.get("id")
        nt = (str(e.get("name", "")).lower(), str(e.get("team", "")).lower())
        if status == "out":
            if pid is not None:
                out_ids.add(str(pid))
            if nt[0]:
                out_names.add(nt)
        elif status in ("limited", "questionable", "doubtful"):
            if pid is not None:
                lim_ids.add(str(pid))
            if nt[0]:
                lim_names.add(nt)
    return out_ids, lim_ids, out_names, lim_names


def build_history(players):
    hist = defaultdict(lambda: {"name": None, "position": None,
                                "ppa_by_year": {}, "def_by_year": {},
                                "team_by_year": {}})
    for year, rows in players.get("ppa", {}).items():
        for r in rows:
            pid = str(r.get("id"))
            if pid == "None":
                continue
            h = hist[pid]
            h["name"] = h["name"] or r.get("name")
            h["position"] = h["position"] or r.get("position")
            h["ppa_by_year"][int(year)] = as_float((r.get("totalPPA") or {}).get("all"))
            if r.get("team"):
                h["team_by_year"][int(year)] = r.get("team")
    for year, rows in players.get("player_stats", {}).items():
        agg = defaultdict(lambda: defaultdict(float))
        names = {}
        teams = {}
        for r in rows:
            pid = str(r.get("playerId") or r.get("id"))
            if pid == "None":
                continue
            if r.get("team"):
                teams.setdefault(pid, r.get("team"))
            cat = (r.get("category") or "").lower()
            if cat not in ("defensive", "interceptions", "fumbles"):
                continue
            agg[pid][(r.get("statType") or "").upper()] += as_float(r.get("stat"))
            names[pid] = r.get("player") or r.get("name")
        for pid, team in teams.items():
            hist[pid]["team_by_year"].setdefault(int(year), team)
        for pid, stats in agg.items():
            score = sum(DEF_STAT_WEIGHTS.get(k, 0.0) * v for k, v in stats.items())
            h = hist[pid]
            h["name"] = h["name"] or names.get(pid)
            h["def_by_year"][int(year)] = score
    # Usage rows also carry the player's team for that season; fill any gaps.
    for year, rows in players.get("usage", {}).items():
        for r in rows:
            pid = str(r.get("id") or r.get("playerId"))
            if pid == "None" or not r.get("team"):
                continue
            hist[pid]["team_by_year"].setdefault(int(year), r.get("team"))
    return hist


def build_recruits(players):
    idx = {}
    for year, rows in players.get("recruits", {}).items():
        for r in rows:
            key = (full_name(r).lower(),
                   (r.get("committedTo") or r.get("school") or "").lower())
            cand = {"stars": int(as_float(r.get("stars"))),
                    "rating": as_float(r.get("rating")), "year": int(as_float(year))}
            if key not in idx or cand["year"] > idx[key]["year"]:
                idx[key] = cand
    return idx


def recruit_value(rec):
    if not rec:
        return STAR_BASE_VALUE[0] * FRESHMAN_DISCOUNT
    base = STAR_BASE_VALUE.get(rec.get("stars", 0), STAR_BASE_VALUE[0])
    rating = rec.get("rating", 0.0)
    if rating:
        base *= (0.85 + 0.3 * min(max(rating - 0.80, 0.0) / 0.20, 1.0))
    return base * FRESHMAN_DISCOUNT


def build_availability(players, manual, apply_availability=True):
    """Return (status_by_id, form_by_id, latest_week).

    When apply_availability is False we produce a *full-strength* roster: no
    manual/auto injury statuses are applied (everyone counts as active), but
    in-season form is still measured, so the only difference from the
    availability-adjusted run is that injured/limited players are restored to
    full value. This backs the UI's full-strength vs. available toggle.
    """
    out_ids, lim_ids, out_names, lim_names = manual
    games = players.get("current_games", []) or []
    appearances = defaultdict(list)
    name_team = {}
    latest_week = 0
    for r in games:
        pid = str(r.get("id") or r.get("playerId"))
        if pid == "None":
            continue
        wk = int(as_float(r.get("week")))
        latest_week = max(latest_week, wk)
        appearances[pid].append((wk, _ppa_all(r)))
        name_team[pid] = (str(r.get("name", "")).lower(), str(r.get("team", "")).lower())

    status_by_id, form_by_id = {}, {}
    if apply_availability:
        for pid in out_ids:
            status_by_id[pid] = "out"
        for pid in lim_ids:
            status_by_id.setdefault(pid, "limited")

    for pid, apps in appearances.items():
        weeks = sorted(w for w, _ in apps)
        nt = name_team.get(pid)
        if apply_availability:
            if nt in out_names:
                status_by_id[pid] = "out"
            elif nt in lim_names and pid not in status_by_id:
                status_by_id[pid] = "limited"
            if (pid not in status_by_id and latest_week > 0
                    and len(weeks) >= AUTO_INJURY_MIN_GAMES
                    and (latest_week - weeks[-1]) >= AUTO_INJURY_GAP_WEEKS):
                status_by_id[pid] = "limited"
        if APPLY_FORM and apps:
            cur_rate = sum(p for _, p in apps) / len(apps)
            trust = min(len(apps) / FORM_RAMP_GAMES, 1.0)
            form_by_id[pid] = (cur_rate, trust)
    return status_by_id, form_by_id, latest_week


def _form_multiplier(pid, form_by_id, hist):
    entry = form_by_id.get(pid)
    if not entry:
        return 1.0
    cur_rate, trust = entry
    h = hist.get(pid)
    if not h or not h["ppa_by_year"]:
        return 1.0
    base = h["ppa_by_year"][max(h["ppa_by_year"])] / GAMES_PER_SEASON
    if base <= 0:
        return 1.0
    factor = 1.0 + FORM_WEIGHT * trust * (cur_rate / base - 1.0)
    return max(FORM_MIN, min(FORM_MAX, factor))


def _sos_factor(sos_mult, year, team):
    if not sos_mult or not team:
        return 1.0
    return (sos_mult.get(year) or {}).get(team, 1.0)


def project_player(entry, hist, recruits, status_by_id, form_by_id, sos_mult=None):
    pid = str(entry.get("id"))
    group, side = norm_pos(entry.get("position"))
    class_year = int(as_float(entry.get("year"), 0))
    name = full_name(entry)
    team = entry.get("team")

    h = hist.get(pid)
    raw, basis, ppa_recent = 0.0, "none", None
    if h and (h["ppa_by_year"] or h["def_by_year"]):
        years = sorted(set(list(h["ppa_by_year"]) + list(h["def_by_year"])), reverse=True)
        team_years = h.get("team_by_year", {})
        weighted, wsum = 0.0, 0.0
        for i, yr in enumerate(years[:len(RECENCY_WEIGHTS)]):
            w = RECENCY_WEIGHTS[i]
            val = (h["def_by_year"].get(yr, 0.0) if side == "defense"
                   else h["ppa_by_year"].get(yr, h["def_by_year"].get(yr, 0.0)))
            # Reward production earned against a tougher schedule that season.
            val *= _sos_factor(sos_mult, yr, team_years.get(yr))
            weighted += w * val
            wsum += w
        raw = weighted / wsum if wsum else 0.0
        basis = "history"
        if h["ppa_by_year"]:
            ppa_recent = round(h["ppa_by_year"][max(h["ppa_by_year"])], 2)
    else:
        rec = recruits.get((name.lower(), (team or "").lower()))
        raw = recruit_value(rec)
        basis = "recruit" if rec else "unknown"

    raw *= DEV_CURVE.get(class_year, DEV_CURVE[0])
    raw = max(raw, 0.0)
    raw *= _form_multiplier(pid, form_by_id, hist)

    status = status_by_id.get(pid)
    avail = OUT_FACTOR if status == "out" else (LIMITED_FACTOR if status == "limited" else 1.0)
    value = raw * POSITION_WEIGHT.get(group, 0.5) * avail
    return {"id": pid, "name": name, "team": team, "position": entry.get("position"),
            "group": group, "side": side, "class": class_year, "raw": round(raw, 2),
            "value": value, "basis": basis, "status": status or "active",
            "ppa_recent": ppa_recent}


def compute_player_value(players, manual, sos_mult=None, apply_availability=True):
    sos_mult = sos_mult or {}
    year = int((players.get("meta", {}) or {}).get("year", config.YEAR)) \
        if players.get("meta") else config.YEAR
    roster = players.get("rosters", {}).get(str(config.YEAR), [])
    hist = build_history(players)
    recruits = build_recruits(players)
    status_by_id, form_by_id, _ = build_availability(
        players, manual, apply_availability=apply_availability)

    by_team = defaultdict(list)
    by_id = {}
    for entry in roster:
        p = project_player(entry, hist, recruits, status_by_id, form_by_id, sos_mult)
        if p["team"]:
            by_team[p["team"]].append(p)
            by_id[p["id"]] = p

    returning = {r.get("team"): as_float(r.get("percentPPA"))
                 for r in players.get("returning", [])}

    out = {}
    for team, plist in by_team.items():
        buckets = defaultdict(list)
        for p in plist:
            buckets[p["group"]].append(p)
        off = dfn = st = 0.0
        impaired = 0
        for group, gl in buckets.items():
            gl.sort(key=lambda x: x["value"], reverse=True)
            for rank, p in enumerate(gl):
                contrib = p["value"] * _depth_weight(rank)
                p["team_contrib"] = round(contrib, 2)
                p["depth_rank"] = rank + 1
                if p["status"] in ("out", "limited"):
                    impaired += 1
                if p["side"] == "offense":
                    off += contrib
                elif p["side"] == "defense":
                    dfn += contrib
                else:
                    st += contrib
        plist.sort(key=lambda x: x["value"], reverse=True)
        out[team] = {"pv_rating": round(off + dfn + 0.5 * st, 2),
                     "offense": round(off, 2), "defense": round(dfn, 2),
                     "special": round(st, 2),
                     "impaired": impaired, "returning_pct": round(returning.get(team, 0.0), 3),
                     "players": plist}
    extras = {"by_id": by_id, "hist": hist, "recruits": recruits,
              "status_by_id": status_by_id}
    return out, extras


# ===========================================================================
# Blend + assemble
# ===========================================================================
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


def _build_schedule(team, school, credits_for_team):
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
        sched.append({
            "id": g.get("id"),
            "week": g.get("week"), "opponent": opp,
            "home_away": "vs" if is_home else "@",
            "team_points": tp, "opp_points": op,
            "completed": bool(completed), "result": result,
            "neutral": bool(g.get("neutralSite")),
            "credit": round(credits_for_team.get(g.get("id"), 0.0), 3) if completed else None,
        })
    sched.sort(key=lambda s: (s["week"] is None, s["week"] or 0))
    return sched


# ===========================================================================
# Matchup prediction + game impact
# ===========================================================================
POINTS_PER_SIGMA = 11.0    # rating gap (in std devs) -> points of margin
HOME_FIELD = 2.4           # home-field advantage, points
MARGIN_LOGISTIC = 8.5      # controls how margin maps to win probability
BASE_TOTAL = 48.0          # baseline combined points for score projection


def _logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def predict_matchup(home, away, neutral=False):
    """Predict a game between two ranking rows (home perspective)."""
    diff = home.get("strength_blended", 0.0) - away.get("strength_blended", 0.0)
    margin = POINTS_PER_SIGMA * diff + (0.0 if neutral else HOME_FIELD)
    p_home = _logistic(margin / MARGIN_LOGISTIC)
    proj_home = max(0, round((BASE_TOTAL + margin) / 2))
    proj_away = max(0, round((BASE_TOTAL - margin) / 2))
    favorite = home["school"] if margin >= 0 else away["school"]
    return {
        "neutral": bool(neutral),
        "margin": round(margin, 1),
        "win_prob_home": round(p_home, 3),
        "win_prob_away": round(1 - p_home, 3),
        "proj_home": proj_home,
        "proj_away": proj_away,
        "favorite": favorite,
        "spread": f"{favorite} by {abs(round(margin,1))}",
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
        form[pid].append((int(as_float(r.get("week"))), _ppa_all(r)))
    return form


def build_player_profiles(by_id, hist, recruits, stat_lines, usage, form, fbs_set,
                          sos_mult=None):
    sos_mult = sos_mult or {}
    # National rank within position group (by projected value).
    groups = defaultdict(list)
    for pid, p in by_id.items():
        if p["team"] in fbs_set:
            groups[p["group"]].append(p)
    pos_rank = {}
    for grp, plist in groups.items():
        for i, p in enumerate(sorted(plist, key=lambda x: x["value"], reverse=True), 1):
            pos_rank[p["id"]] = i

    profiles = {}
    for pid, p in by_id.items():
        if p["team"] not in fbs_set:
            continue
        h = hist.get(pid, {})
        ppa_years = h.get("ppa_by_year", {}) or {}
        def_years = h.get("def_by_year", {}) or {}
        team_years = h.get("team_by_year", {}) or {}
        years = sorted(set(list(ppa_years) + list(def_years) + list(stat_lines.get(pid, {}))))
        seasons = []
        for y in years:
            sy = team_years.get(y)
            seasons.append({
                "year": y,
                "school": sy,
                "sos": round((sos_mult.get(y) or {}).get(sy, 1.0), 3),
                "ppa_total": round(ppa_years[y], 2) if y in ppa_years else None,
                "def_score": round(def_years[y], 2) if y in def_years else None,
                "usage": round(usage.get(pid, {}).get(y), 3) if usage.get(pid, {}).get(y) else None,
                "stats": {cat: {k: round(v, 1) for k, v in sd.items()}
                          for cat, sd in stat_lines.get(pid, {}).get(y, {}).items()},
            })
        cur = sorted(form.get(pid, []))
        current = {"games": len(cur),
                   "ppa_per_game": round(sum(v for _, v in cur) / len(cur), 3) if cur else None,
                   "log": [{"week": w, "ppa": round(v, 3)} for w, v in cur]}
        rec = recruits.get((p["name"].lower(), (p["team"] or "").lower()))
        pr = pos_rank.get(pid)
        bits = [f"#{pr} {p['group']} nationally by projected value" if pr else None,
                f"{len([s for s in seasons if s['ppa_total'] is not None])} season(s) of PPA history"
                if any(s["ppa_total"] is not None for s in seasons) else None]
        if current["games"]:
            bits.append(f"averaging {current['ppa_per_game']} PPA/game across "
                        f"{current['games']} game(s) this year")
        if p["status"] != "active":
            bits.append(f"currently {p['status'].upper()}")
        summary = "; ".join(b for b in bits if b) + "."
        profiles[pid] = {
            "id": pid, "name": p["name"], "team": p["team"], "position": p["position"],
            "group": p["group"], "side": p["side"], "class": p["class"],
            "status": p["status"], "basis": p["basis"], "value": round(p["value"], 1),
            "ppa_recent": p["ppa_recent"], "pos_rank": pr,
            "depth_rank": p.get("depth_rank"),
            "recruiting": ({"stars": rec["stars"], "rating": rec["rating"]} if rec else None),
            "seasons": seasons, "current": current, "summary": summary,
        }
    return profiles


# ===========================================================================
# Game detail
# ===========================================================================
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


def build_game_detail(g, hr, ar, home, away, completed, cdet, detail, n_teams):
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
        entry["credit"] = {"home": cdet.get(home), "away": cdet.get(away)}
    elif hr and ar:
        pred = predict_matchup(hr, ar, neutral=bool(g.get("neutralSite")))
        entry["prediction"] = pred
        entry["impact"] = game_impact(hr, ar, pred, n_teams)
    return entry


# ===========================================================================
# CFP bracket (12-team) + selected bowls
# ===========================================================================
def build_bracket(rankings):
    if len(rankings) < 12:
        return None
    order = sorted(rankings, key=lambda r: r["rank_blended"])
    champ = {}
    for r in order:
        conf = r.get("conference")
        if not conf or conf == "FBS Independents":
            continue
        champ.setdefault(conf, r)
    champs_sorted = sorted(champ.values(), key=lambda r: r["rank_blended"])
    auto = champs_sorted[:5]
    byes = auto[:4]
    fifth = auto[4] if len(auto) >= 5 else None
    bye_set = {r["school"] for r in byes}

    seeds5_12 = []
    if fifth:
        seeds5_12.append(fifth)
    for r in order:
        if r["school"] in bye_set or (fifth and r["school"] == fifth["school"]):
            continue
        seeds5_12.append(r)
        if len(seeds5_12) >= 8:
            break
    seeds = (byes + seeds5_12)[:12]
    auto_set = {r["school"] for r in auto}

    def play(a, b, neutral, rnd):
        pred = predict_matchup(a, b, neutral=neutral)
        home_wins = pred["win_prob_home"] >= 0.5
        return {"round": rnd, "neutral": neutral,
                "high": a["school"], "low": b["school"],
                "high_seed": a["_seed"], "low_seed": b["_seed"],
                "prediction": pred,
                "winner": a["school"] if home_wins else b["school"],
                "winner_row": a if home_wins else b}
    for i, r in enumerate(seeds):
        r["_seed"] = i + 1
    S = {r["_seed"]: r for r in seeds}

    first = [play(S[5], S[12], False, "First Round"),
             play(S[8], S[9], False, "First Round"),
             play(S[6], S[11], False, "First Round"),
             play(S[7], S[10], False, "First Round")]
    w = [m["winner_row"] for m in first]
    qf = [play(S[1], w[1], True, "Quarterfinal"),
          play(S[4], w[0], True, "Quarterfinal"),
          play(S[3], w[2], True, "Quarterfinal"),
          play(S[2], w[3], True, "Quarterfinal")]
    qw = [m["winner_row"] for m in qf]
    def seed_order(a, b):
        return (a, b) if a["_seed"] < b["_seed"] else (b, a)
    sf = [play(*seed_order(qw[0], qw[1]), True, "Semifinal"),
          play(*seed_order(qw[2], qw[3]), True, "Semifinal")]
    sw = [m["winner_row"] for m in sf]
    final = play(*seed_order(sw[0], sw[1]), True, "Championship")

    def strip(m):
        m = dict(m)
        m.pop("winner_row", None)
        return m

    # A few "selected bowls" from the next tier.
    next_tier = [r for r in order if r["school"] not in {s["school"] for s in seeds}][:8]
    bowls = []
    bowl_names = ["Cotton Bowl", "Gator Bowl", "Sun Bowl", "Music City Bowl"]
    for i in range(0, min(len(next_tier) - 1, 8), 2):
        a, b = next_tier[i], next_tier[i + 1]
        a.setdefault("_seed", None); b.setdefault("_seed", None)
        pred = predict_matchup(a, b, neutral=True)
        bowls.append({"name": bowl_names[i // 2] if i // 2 < len(bowl_names) else "Bowl",
                      "home": a["school"], "away": b["school"],
                      "home_rank": a["rank_blended"], "away_rank": b["rank_blended"],
                      "prediction": pred,
                      "winner": a["school"] if pred["win_prob_home"] >= 0.5 else b["school"]})

    return {
        "seeds": [{"seed": r["_seed"], "school": r["school"],
                   "abbreviation": r["abbreviation"], "conference": r["conference"],
                   "rank": r["rank_blended"], "rating": r["rating_blended"],
                   "record": r["record"], "color": r["color"], "logo": r["logo"],
                   "bye": r["_seed"] <= 4, "auto_bid": r["school"] in auto_set}
                  for r in seeds],
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
    n = len(rankings)
    return {"home": _team_ref(hr, home_school), "away": _team_ref(ar, away_school),
            "prediction": pred, "impact": game_impact(hr, ar, pred, n),
            "stats_compare": None}


# ===========================================================================
# Projected record: actual results + predicted remaining games
# ===========================================================================
NON_FBS_WIN_PROB = 0.85    # assumed win prob vs an unranked / lower-division foe


def project_record(team, school, row_by_school):
    row = row_by_school.get(school)
    current = [0, 0]
    added = [0, 0]
    expected_wins = 0.0
    games = []
    for g in team.get("games", []):
        hp, ap = g.get("homePoints"), g.get("awayPoints")
        is_home = g.get("homeTeam") == school
        opp = g.get("awayTeam") if is_home else g.get("homeTeam")
        if hp is not None and ap is not None:            # played
            tp, op = (hp, ap) if is_home else (ap, hp)
            win = tp > op
            current[0 if win else 1] += 1
            expected_wins += 1.0 if win else 0.0
            games.append({"week": g.get("week"), "opponent": opp,
                          "home_away": "vs" if is_home else "@", "completed": True,
                          "result": "W" if win else ("L" if tp < op else "T"),
                          "team_points": tp, "opp_points": op})
        else:                                            # remaining -> predict
            opp_row = row_by_school.get(opp)
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


def _teams_for_year(games, meta):
    """Group a flat list of games into per-team objects shaped like the current
    team dicts (school/classification/conference/games) so compute_results can
    rate that season's teams."""
    by_school = {}
    for g in games:
        for side in ("homeTeam", "awayTeam"):
            s = g.get(side)
            if not s:
                continue
            t = by_school.get(s)
            if t is None:
                m = meta.get(s, {})
                cls = (g.get("homeClassification") if side == "homeTeam"
                       else g.get("awayClassification")) or m.get("classification")
                conf = (g.get("homeConference") if side == "homeTeam"
                        else g.get("awayConference")) or m.get("conference")
                t = {"school": s, "classification": cls, "conference": conf,
                     "games": []}
                by_school[s] = t
            t["games"].append(g)
    return list(by_school.values())


def build_sos(teams, history_games):
    """Return {year:int -> {school -> multiplier}}. The multiplier scales a
    season's production by how strong that team's schedule was that year:
    each team's schedule strength is the average opponent quality (from the
    opponent-adjusted results model) over its completed games, z-scored across
    the league and mapped to a clamped multiplier around 1.0."""
    meta = {t["school"]: t for t in teams}

    # year -> flat games list. Current year comes from the live team schedules;
    # history years come from the fetched history_games.
    year_games = defaultdict(list)
    seen = set()
    for t in teams:
        for g in t.get("games", []):
            gid = g.get("id")
            key = (g.get("season"), gid)
            if gid is not None and key in seen:
                continue
            seen.add(key)
            year_games[int(g.get("season", 0))].append(g)
    for y, games in (history_games or {}).items():
        year_games[int(y)] = list(games)

    sos_mult = {}
    for year, games in year_games.items():
        if not games:
            continue
        teams_year = _teams_for_year(games, meta)
        results, _, _ = compute_results(teams_year)
        strength = {s: results[s]["results_metric"] for s in results
                    if results[s].get("games", 0) > 0}
        if len(strength) < 2:
            continue
        opp_z = _zmap(strength)  # opponent quality per team, this season
        sched = {}
        for t in teams_year:
            s = t["school"]
            vals = []
            for g in t["games"]:
                if not g.get("completed"):
                    continue
                opp = g.get("awayTeam") if g.get("homeTeam") == s else g.get("homeTeam")
                if opp in opp_z:
                    vals.append(opp_z[opp])
            if vals:
                sched[s] = statistics.mean(vals)
        if len(sched) < 2:
            continue
        sched_z = _zmap(sched)  # how tough was each team's schedule, normalized
        sos_mult[year] = {
            s: max(SOS_MIN, min(SOS_MAX, 1.0 + SOS_WEIGHT * z))
            for s, z in sched_z.items()
        }
    return sos_mult


def compute(raw, injuries=None):
    teams = raw.get("teams", [])
    players = raw.get("players", {})
    year = int(raw.get("meta", {}).get("year", config.YEAR))
    manual = load_injuries() if injuries is None else parse_injuries(injuries)

    results, credits_by_game, credit_detail = compute_results(teams)
    sos_mult = build_sos(teams, raw.get("history_games", {}))
    pv, pv_extras = compute_player_value(players, manual, sos_mult)

    team_by_school = {t["school"]: t for t in teams}
    fbs_schools = [s for s in pv if is_fbs(team_by_school.get(s, {"classification": None}))]
    # Fall back to results universe if roster/pv is empty.
    if not fbs_schools:
        fbs_schools = [t["school"] for t in teams if t.get("games") and is_fbs(t)]

    pv_z = _zmap({s: pv[s]["pv_rating"] for s in fbs_schools if s in pv})
    off_z = _zmap({s: pv[s]["offense"] for s in fbs_schools if s in pv})
    def_z = _zmap({s: pv[s]["defense"] for s in fbs_schools if s in pv})
    st_z = _zmap({s: pv[s]["special"] for s in fbs_schools if s in pv})
    res_metric = {s: results[s]["results_metric"] for s in fbs_schools
                  if s in results and results[s]["games"] > 0}
    res_z = _zmap(res_metric)

    any_games = any(results.get(s, {}).get("games", 0) > 0 for s in fbs_schools)

    rankings = []
    for s in fbs_schools:
        t = team_by_school.get(s, {})
        r = results.get(s, {"record": [0, 0], "games": 0, "winCredits": 0.0,
                            "margin": 0.0, "results_metric": 0.0})
        g = r["games"]
        w_res = min(g / FULL_SEASON_GAMES, 1.0) * MAX_RESULTS_WEIGHT
        z_pv = pv_z.get(s, 0.0)
        z_res = res_z.get(s, 0.0)
        z_blend = (1 - w_res) * z_pv + w_res * z_res
        pvd = pv.get(s, {})
        logos = t.get("logos") or []
        rankings.append({
            "school": s,
            "abbreviation": t.get("abbreviation", ""),
            "conference": t.get("conference"),
            "classification": t.get("classification"),
            "color": t.get("color") or "#444444",
            "logo": logos[0] if logos else None,
            "record": r["record"],
            "games": g,
            "w_res": round(w_res, 2),
            "impaired": pvd.get("impaired", 0),
            "offense": pvd.get("offense", 0.0),
            "defense": pvd.get("defense", 0.0),
            "special": pvd.get("special", 0.0),
            "returning_pct": pvd.get("returning_pct", 0.0),
            "rating_blended": round(50 + 15 * z_blend, 1),
            "rating_pv": round(50 + 15 * z_pv, 1),
            "rating_results": round(50 + 15 * z_res, 1) if g > 0 else None,
            # Unit z-scores can have heavy outliers (esp. thinly modeled special
            # teams), so clamp to keep ratings on a readable ~0-100 scale.
            "rating_offense": round(50 + 15 * max(-3.0, min(3.0, off_z.get(s, 0.0))), 1),
            "rating_defense": round(50 + 15 * max(-3.0, min(3.0, def_z.get(s, 0.0))), 1),
            "rating_special": round(50 + 15 * max(-3.0, min(3.0, st_z.get(s, 0.0))), 1),
            # strength = z-scores, kept for the prediction/impact model.
            "strength_blended": z_blend, "strength_pv": z_pv, "strength_results": z_res,
            "strength_offense": off_z.get(s, 0.0), "strength_defense": def_z.get(s, 0.0),
            "strength_special": st_z.get(s, 0.0),
        })

    # Rank indices per view.
    def assign_ranks(key, into):
        ordered = sorted(rankings, key=lambda x: x[key], reverse=True)
        for i, row in enumerate(ordered, start=1):
            row[into] = i
    assign_ranks("strength_blended", "rank_blended")
    assign_ranks("strength_pv", "rank_pv")
    assign_ranks("strength_results", "rank_results")
    assign_ranks("strength_offense", "rank_offense")
    assign_ranks("strength_defense", "rank_defense")
    assign_ranks("strength_special", "rank_special")
    rankings.sort(key=lambda x: x["rank_blended"])

    # Per-team drill-down detail.
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
            "ranks": {"blended": row["rank_blended"], "pv": row["rank_pv"],
                      "results": row["rank_results"]},
            "ratings": {"blended": row["rating_blended"], "pv": row["rating_pv"],
                        "results": row["rating_results"]},
            "returning_pct": pvd.get("returning_pct", 0.0),
            "impaired": pvd.get("impaired", 0),
            "team_stats": {"offense": _flatten_stats(stats.get("offense")),
                           "defense": _flatten_stats(stats.get("defense"))},
            "players": [
                {"id": p["id"], "name": p["name"], "position": p["position"],
                 "group": p["group"], "side": p["side"], "class": p["class"],
                 "value": round(p["value"], 1), "contrib": p.get("team_contrib", 0.0),
                 "status": p["status"], "basis": p["basis"], "ppa_recent": p["ppa_recent"]}
                for p in pvd.get("players", [])
            ],
            "schedule": _build_schedule(t, s, credits_by_game.get(s, {})),
        }

    # ---- Player profiles (keyed by athlete id) ----
    fbs_set = set(detail.keys())
    profiles = build_player_profiles(
        pv_extras["by_id"], pv_extras["hist"], pv_extras["recruits"],
        build_stat_lines(players), build_usage(players), build_current_form(players),
        fbs_set, sos_mult)
    conf_by_team = {t["school"]: t.get("conference") for t in teams}
    for prof in profiles.values():
        prof["conference"] = conf_by_team.get(prof["team"])

    # ---- Player rankings (sorted by projected value) ----
    player_rankings = []
    for i, p in enumerate(sorted(profiles.values(), key=lambda x: x["value"],
                                 reverse=True), start=1):
        player_rankings.append({
            "overall_rank": i, "id": p["id"], "name": p["name"], "team": p["team"],
            "conference": p["conference"], "position": p["position"],
            "group": p["group"], "side": p["side"], "class": p["class"],
            "value": p["value"], "status": p["status"],
            "ppa_recent": p["ppa_recent"], "pos_rank": p["pos_rank"],
        })

    # ---- Game details + upcoming matchups ----
    row_by_school = {r["school"]: r for r in rankings}
    n_teams = len(rankings)

    # ---- Projected records (actual + predicted remaining) ----
    for s in detail:
        proj = project_record(team_by_school.get(s, {}), s, row_by_school)
        detail[s]["projection"] = proj
        r = row_by_school.get(s)
        if r is not None:
            r["proj_record"] = proj["projected"]
            r["expected_wins"] = proj["expected_wins"]
            r["remaining"] = proj["remaining"]
    games_map = {}
    upcoming = defaultdict(list)
    seen = set()
    for s in detail:
        for g in team_by_school.get(s, {}).get("games", []):
            gid = g.get("id")
            if gid in seen:
                continue
            seen.add(gid)
            home, away = g.get("homeTeam"), g.get("awayTeam")
            hr, ar = row_by_school.get(home), row_by_school.get(away)
            completed = g.get("homePoints") is not None and g.get("awayPoints") is not None
            gd = build_game_detail(g, hr, ar, home, away, completed,
                                   credit_detail.get(gid, {}), detail, n_teams)
            games_map[str(gid)] = gd
            if not completed and hr and ar:
                upcoming[g.get("week")].append({
                    "id": gid, "week": g.get("week"), "home": home, "away": away,
                    "home_rank": hr["rank_blended"], "away_rank": ar["rank_blended"],
                    "home_color": hr["color"], "away_color": ar["color"],
                    "home_logo": hr["logo"], "away_logo": ar["logo"],
                    "impact": gd["impact"], "prediction": gd["prediction"],
                    "neutral": bool(g.get("neutralSite")),
                })
    upcoming_by_week = {}
    for wk, lst in upcoming.items():
        lst.sort(key=lambda x: x["impact"]["score"], reverse=True)
        upcoming_by_week[str(wk)] = lst[:20]

    bracket = build_bracket(rankings)

    # Strip helper fields not needed by the client.
    for r in rankings:
        for k in ("strength_pv", "strength_results", "_seed"):
            r.pop(k, None)

    mode = "in-season" if any_games else "preseason"
    return {
        "meta": {
            "year": year,
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "mode": mode,
            "team_count": len(rankings),
            "source_generated": raw.get("meta", {}).get("generated"),
        },
        "rankings": rankings,
        "teams": detail,
        "players": profiles,
        "player_rankings": player_rankings,
        "games": games_map,
        "upcoming": upcoming_by_week,
        "bracket": bracket,
    }
