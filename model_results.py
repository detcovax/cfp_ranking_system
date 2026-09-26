"""
model_results.py -- opponent-adjusted results model, on a points scale.

Replaces the old "win credits" model (asinh margin x hand-set conference
multipliers). Every rating here is in points relative to an average FBS team on
a neutral field, so a rating gap *is* a predicted margin.

Overall (margin) model, solved as a ridge regression by Gauss-Seidel:

    damp(margin_ij) = r_i - r_j + h * site_ij + noise

    r_i = ( lam * prior_i + sum_games [ damp(m_ig) - h*site_ig + r_opp ] )
          / ( lam + games_i )

  * damp() = C * asinh(m / C) softens blowouts without ignoring them.
  * prior_i is the Bayesian prior mean: 0 for a results-only fit, or the
    team's Power rating for the Current view. lam = pseudo-games of prior, so
    the prior's share is lam / (lam + games) -- the g/(g+k) blend, but done
    *inside* the opponent adjustment (opponents are also prior-informed).
  * h (home field) is estimated from the data, shrunk toward HFA_DEFAULT.
  * Non-FBS teams get a classification prior (FCS ~ -18) so beating them
    isn't treated as beating an average FBS team.

Unit (points) model:

    pts_i_vs_j = mu + o_i - d_j + site * h/2

giving offense (points scored above average) and defense (points prevented
below average), both in points, with the same prior mechanism.

Pure Python, no I/O.
"""

import math
from collections import defaultdict

MARGIN_DAMP = 20.0         # C in C*asinh(m/C); 21 -> 18.7, 42 -> 29.7
HFA_DEFAULT = 2.5          # home field prior, points
HFA_PSEUDO_GAMES = 60      # shrink the fitted HFA toward the default
POINTS_CAP = 63            # cap single-game points in the unit model
CLASS_PRIOR = {"fbs": 0.0, "fcs": -18.0, "ii": -30.0, "iii": -38.0}
UNKNOWN_CLASS_PRIOR = -30.0
RIDGE_RESULTS = 1.0        # pseudo-games toward the class prior (results-only)
SOLVE_ITERS = 60
OUTER_ITERS = 4
TOL = 1e-4


def damp(m, c=MARGIN_DAMP):
    return c * math.asinh(m / c) if c else m


def class_map(teams):
    """school -> classification, from team records and game rows."""
    out = {}
    for t in teams:
        if t.get("classification"):
            out[t["school"]] = t["classification"]
        for g in t.get("games", []):
            for side in ("home", "away"):
                s, c = g.get(side + "Team"), g.get(side + "Classification")
                if s and c and s not in out:
                    out[s] = c
    return out


def played_games(teams):
    """Unique completed games as flat dicts."""
    seen, out = set(), []
    for t in teams:
        for g in t.get("games", []):
            gid = g.get("id")
            if gid in seen:
                continue
            hp, ap = g.get("homePoints"), g.get("awayPoints")
            if hp is None or ap is None:
                continue
            seen.add(gid)
            out.append({"id": gid, "home": g.get("homeTeam"), "away": g.get("awayTeam"),
                        "hp": float(hp), "ap": float(ap),
                        "neutral": bool(g.get("neutralSite")), "week": g.get("week")})
    return out


def _prior_mean(team, prior, classes, scale=1.0):
    if team in prior:
        return prior[team]
    return scale * CLASS_PRIOR.get(classes.get(team), UNKNOWN_CLASS_PRIOR)


def _recenter(r, classes):
    fbs = [v for t, v in r.items() if classes.get(t) == "fbs"]
    if not fbs:
        return r
    mu = sum(fbs) / len(fbs)
    return {t: v - mu for t, v in r.items()}


def solve_margin(games, classes, prior=None, lam=RIDGE_RESULTS,
                 damp_c=MARGIN_DAMP, hfa=None, recenter=True):
    """Opponent-adjusted margin ratings.

    Returns {"ratings": {team: pts}, "hfa": h, "game_scores": {gid: {team: {...}}},
             "resid_sd": sd of (actual damped margin - predicted)}.
    If `hfa` is given it is held fixed instead of estimated.
    """
    prior = prior or {}
    adj = defaultdict(list)   # team -> [(opp, damped margin, site sign, gid)]
    for g in games:
        m = damp(g["hp"] - g["ap"], damp_c)
        s = 0 if g["neutral"] else 1
        adj[g["home"]].append((g["away"], m, s, g["id"]))
        adj[g["away"]].append((g["home"], -m, -s, g["id"]))
    teams = set(adj) | set(prior)
    pm = {t: _prior_mean(t, prior, classes) for t in teams}
    r = dict(pm)
    h = HFA_DEFAULT if hfa is None else hfa

    for _ in range(OUTER_ITERS if hfa is None else 1):
        for _ in range(SOLVE_ITERS):
            delta = 0.0
            for t in teams:
                num, den = lam * pm[t], lam
                for opp, m, s, _gid in adj.get(t, ()):
                    num += m - s * h + r[opp]
                    den += 1
                new = num / den if den else pm[t]
                delta = max(delta, abs(new - r[t]))
                r[t] = new
            if delta < TOL:
                break
        if hfa is None:
            res = [damp(g["hp"] - g["ap"], damp_c) - (r[g["home"]] - r[g["away"]])
                   for g in games if not g["neutral"]]
            h = (HFA_DEFAULT * HFA_PSEUDO_GAMES + sum(res)) / (HFA_PSEUDO_GAMES + len(res))

    if recenter:
        r = _recenter(r, classes)

    # Per-game "game score": the rating this single game implies for the team
    # (damped margin, site-adjusted, plus the opponent's rating).
    game_scores = defaultdict(dict)
    sq, cnt = 0.0, 0
    for t, lst in adj.items():
        for opp, m, s, gid in lst:
            game_scores[gid][t] = {
                "opponent": opp, "opp_rating": round(r.get(opp, 0.0), 1),
                "damped_margin": round(m, 1), "hfa_adj": round(-s * h, 1),
                "game_score": round(m - s * h + r.get(opp, 0.0), 1),
            }
            if s >= 0:  # count each game once (home or neutral-listed side)
                e = m - (r[t] - r.get(opp, 0.0) + s * h)
                sq += e * e
                cnt += 1
    resid_sd = math.sqrt(sq / cnt) if cnt else None
    return {"ratings": r, "hfa": h, "game_scores": dict(game_scores), "resid_sd": resid_sd}


def solve_units(games, classes, prior_off=None, prior_def=None, lam=RIDGE_RESULTS,
                hfa=HFA_DEFAULT, recenter=True):
    """Offense / defense ratings in points. Higher defense = fewer points allowed."""
    prior_off, prior_def = prior_off or {}, prior_def or {}
    rows = defaultdict(list)  # team -> [(opp, pts_for, pts_against, site)]
    tot, n = 0.0, 0
    for g in games:
        hp, ap = min(g["hp"], POINTS_CAP), min(g["ap"], POINTS_CAP)
        s = 0 if g["neutral"] else 1
        rows[g["home"]].append((g["away"], hp, ap, s))
        rows[g["away"]].append((g["home"], ap, hp, -s))
        tot += hp + ap
        n += 2
    mu = tot / n if n else 28.0
    teams = set(rows) | set(prior_off) | set(prior_def)
    po = {t: _prior_mean(t, prior_off, classes, 0.5) for t in teams}
    pd = {t: _prior_mean(t, prior_def, classes, 0.5) for t in teams}
    o, d = dict(po), dict(pd)
    half = hfa / 2.0
    for _ in range(SOLVE_ITERS):
        delta = 0.0
        for t in teams:
            lst = rows.get(t, ())
            num_o, num_d, den = lam * po[t], lam * pd[t], lam
            for opp, pf, pa, s in lst:
                num_o += pf - mu - s * half + d.get(opp, 0.0)
                num_d += mu + o.get(opp, 0.0) - s * half - pa
                den += 1
            no, nd = num_o / den, num_d / den
            delta = max(delta, abs(no - o[t]), abs(nd - d[t]))
            o[t], d[t] = no, nd
        if delta < TOL:
            break
    if recenter:
        o, d = _recenter(o, classes), _recenter(d, classes)
    return {"offense": o, "defense": d, "mu": mu}


def team_records(games):
    """school -> record/points summary from played games."""
    out = defaultdict(lambda: {"record": [0, 0], "games": 0, "points_for": 0.0,
                               "points_against": 0.0})
    for g in games:
        for t, pf, pa in ((g["home"], g["hp"], g["ap"]), (g["away"], g["ap"], g["hp"])):
            r = out[t]
            r["games"] += 1
            r["points_for"] += pf
            r["points_against"] += pa
            if pf > pa:
                r["record"][0] += 1
            elif pf < pa:
                r["record"][1] += 1
    return out


def schedule_strength(games, ratings):
    """school -> average rating of opponents faced (points)."""
    acc = defaultdict(list)
    for g in games:
        acc[g["home"]].append(ratings.get(g["away"], 0.0))
        acc[g["away"]].append(ratings.get(g["home"], 0.0))
    return {t: sum(v) / len(v) for t, v in acc.items() if v}
