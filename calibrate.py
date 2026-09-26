"""
calibrate.py -- fit the model's parameters from your cached data.

    python calibrate.py                 # uses data/raw.json
    python calibrate.py path/to/raw.json

Writes data/calibration.json, which engine.prepare() loads automatically.
Delete that file to go back to the built-in defaults.

What it fits (all point-in-time: nothing is fit on data it then predicts):

1. Results solver (walk-forward inside each history season)
   For week w, fit ratings on games before w, with last season's rating
   (regressed) as the prior, then predict week w. Grid-searches
     PRIOR_GAMES  (K, pseudo-games of prior)
     MARGIN_DAMP  (blowout damping)
   and fits MARGIN_SD (win-probability spread) from out-of-sample residuals.
   Also measures PROGRAM_REGRESS (year-over-year slope of team ratings).

2. Power (preseason roster -> end-of-season rating)
   For target season T in the history window, rebuild every team's roster as
   of that preseason (roster T, production from seasons < T only), then
   regress T's final opponent-adjusted rating on
     - position-group totals (sum of share x R)   -> GROUP_WEIGHT
     - last season's rating                        -> PRIOR_COEF
   Group weights are ridge-shrunk toward the defaults (strength picked by
   leave-one-season-out CV), since ~130 teams per season can't pin down 10
   weights on their own. ROSTER_COEF is how many SDs of final rating one SD
   of roster strength is worth, holding last season fixed.

Guards against over-fitting (added in v2):
  * Only FBS-vs-FBS games are scored in the walk-forward. CFBD's /games feed
    includes every division; lower-division games have no informative prior
    and swamp the FBS signal (they push K to its minimum).
  * Position weights use team-grouped 10-fold CV and the one-standard-error
    rule: the most-shrunk fit within 1 SE of the best is chosen, and the
    defaults are kept unless fitted weights beat them by more than 1 SE.
    Each fitted weight is bounded to 0.5x-2x its default.
  * Passing-game collinearity is reported: CFBD credits a pass play's PPA to
    both passer and receiver, so QB and WR totals overlap and the regression
    can't split credit between them reliably.

Caveat: K is tuned with last season's rating as the prior. In production the
prior is Power, which should be more accurate, so the best K there is likely
a bit higher than what this reports.
"""

import json
import math
import os
import statistics
import sys
from collections import defaultdict

import config
import engine
import model_players as mp
import model_results as mr
import ranking

CALIBRATION_VERSION = 2
K_GRID = [0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0]
DAMP_GRID = [14.0, 20.0, 30.0, 45.0, 1e6]  # 1e6 ~ no damping
# Ridge strength (x mean diag(X'X)); 1e9 = the default weights, scaled.
RIDGE_GRID = [0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 1e9]
CV_FOLDS = 10              # folds grouped by team (a team's seasons stay together)
WEIGHT_BOUNDS = (0.5, 2.0)  # fitted weight stays within this multiple of its default
MIN_TRAIN_WEEK = 2


def progress(frac, stage):
    """Machine-readable progress for the dashboard (DAVE_PROGRESS=1)."""
    if os.environ.get("DAVE_PROGRESS"):
        print(f"@@PROGRESS {frac:.3f} {stage}", flush=True)


# ---------------------------------------------------------------------------
# Small linear algebra (keeps the project dependency-free)
# ---------------------------------------------------------------------------
def solve_linear(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            continue
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[r][c]:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if M[i][i] else 0.0 for i in range(n)]


def ridge(X, y, alpha, target, penalize):
    """min ||y - X b||^2 + alpha * sum_{j in penalize} (b_j - target_j)^2"""
    p = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) for j in range(p)] for i in range(p)]
    b = [sum(r[i] * yy for r, yy in zip(X, y)) for i in range(p)]
    for j in penalize:
        A[j][j] += alpha
        b[j] += alpha * target[j]
    return solve_linear(A, b)


def pearson(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb) if sa and sb else 0.0


# ---------------------------------------------------------------------------
# 1. Results solver walk-forward
# ---------------------------------------------------------------------------
def _season_games(raw):
    out = {int(y): rows for y, rows in (raw.get("history_games") or {}).items()}
    return out


def walk_forward(raw, classes):
    seasons = _season_games(raw)
    years = sorted(seasons)
    finals = {}
    for y in years:
        g = mr.played_games([{"games": seasons[y]}])
        cls = dict(classes)
        cls.update(mr.class_map([{"games": seasons[y]}]))
        finals[y] = (mr.solve_margin(g, cls), cls, g)

    # Year-over-year regression of FBS team ratings.
    slopes = []
    for y in years[1:]:
        prev, cur = finals[y - 1][0]["ratings"], finals[y][0]["ratings"]
        cls = finals[y][1]
        pairs = [(prev[t], cur[t]) for t in cur if t in prev and cls.get(t) == "fbs"]
        if len(pairs) > 30:
            xs, ys = zip(*pairs)
            mx = statistics.mean(xs)
            vx = sum((x - mx) ** 2 for x in xs)
            slopes.append(sum((x - mx) * (yy - statistics.mean(ys)) for x, yy in pairs) / vx)
    regress = statistics.mean(slopes) if slopes else engine.PARAMS["PROGRAM_REGRESS"]

    results = {}
    combos = len(K_GRID) * len(DAMP_GRID)
    done = 0
    for K in K_GRID:
        for C in DAMP_GRID:
            done += 1
            progress(0.05 + 0.65 * done / combos, f"Walk-forward backtest {done}/{combos}")
            resid, n = [], 0
            for y in years[1:]:
                _, cls, games = finals[y]
                prior = {t: regress * v for t, v in finals[y - 1][0]["ratings"].items()
                         if cls.get(t) == "fbs"}
                hfa = finals[y][0]["hfa"]
                fbs_y = {t for t, c in cls.items() if c == "fbs"}
                weeks = sorted({g["week"] for g in games if g["week"] is not None})
                for w in weeks:
                    if w < MIN_TRAIN_WEEK:
                        continue
                    train = [g for g in games if g["week"] is not None and g["week"] < w]
                    # Score FBS-vs-FBS only (train on everything).
                    test = [g for g in games if g["week"] == w
                            and g["home"] in fbs_y and g["away"] in fbs_y]
                    fit = mr.solve_margin(train, cls, prior=prior, lam=K, hfa=hfa, damp_c=C)
                    r = fit["ratings"]

                    def rt(t):
                        return r.get(t, prior.get(t, mr.CLASS_PRIOR.get(cls.get(t), -30.0)))
                    for g in test:
                        pred = rt(g["home"]) - rt(g["away"]) + (0 if g["neutral"] else hfa)
                        resid.append(((g["hp"] - g["ap"]) - pred, pred, g["hp"] > g["ap"]))
            if not resid:
                continue
            sd = math.sqrt(sum(e * e for e, _, _ in resid) / len(resid))
            L = sd * math.sqrt(3) / math.pi
            ll = 0.0
            for _, pred, hw in resid:
                p = min(max(1 / (1 + math.exp(-pred / L)), 1e-6), 1 - 1e-6)
                ll -= math.log(p if hw else 1 - p)
            results[(K, C)] = {"mae": sum(abs(e) for e, _, _ in resid) / len(resid),
                               "rmse": sd, "logloss": ll / len(resid), "n": len(resid)}
    return results, regress, finals


# ---------------------------------------------------------------------------
# 2. Power: point-in-time roster regression
# ---------------------------------------------------------------------------
def _players_as_of(players, target):
    """Player data as it existed the preseason before `target`."""
    keep = lambda d: {y: v for y, v in (d or {}).items() if int(y) < target}
    return {"rosters": {str(target): (players.get("rosters") or {}).get(str(target), []),
                        **keep(players.get("rosters"))},
            "ppa": keep(players.get("ppa")), "player_stats": keep(players.get("player_stats")),
            "usage": {}, "returning": [], "recruits": players.get("recruits") or {},
            "portal": [], "current_games": []}


def fit_power(raw, finals, classes):
    players = raw.get("players", {})
    years = sorted(finals)
    groups = list(mp.SLOT_SHARES)
    sched_z = {y: engine._sched_z(mr.schedule_strength(finals[y][2], finals[y][0]["ratings"]),
                                  finals[y][1]) for y in years}
    rows = []
    progress(0.72, "Rebuilding preseason rosters")
    for T in years[1:]:
        if not (players.get("rosters") or {}).get(str(T)):
            continue
        pv, _ = mp.compute_player_value(_players_as_of(players, T), (set(),) * 4,
                                        {y: z for y, z in sched_z.items() if y < T},
                                        T, 0.0, apply_availability=False)
        final, cls = finals[T][0]["ratings"], finals[T][1]
        prev = finals[T - 1][0]["ratings"]
        for team, d in pv.items():
            if cls.get(team) != "fbs" or team not in final:
                continue
            rows.append({"y": final[team], "prev": prev.get(team, 0.0), "team": team,
                         "x": [d["groups"].get(g, 0.0) for g in groups], "T": T})
    if len(rows) < 60:
        return None

    # Scale the default weights to the data, then ridge toward them. The ridge
    # strength is chosen by leave-one-season-out CV when 2+ seasons exist.
    w0 = [mp.GROUP_WEIGHT[g] for g in groups]
    ng = len(groups)

    def fit(train, alpha_frac):
        comp = [sum(a * b for a, b in zip(r["x"], w0)) for r in train]
        s_, _, _ = ridge([[c, r["prev"], 1.0] for c, r in zip(comp, train)],
                         [r["y"] for r in train], 0.0, [0, 0, 0], [])
        s_ = s_ if s_ > 0 else 1.0
        X = [r["x"] + [r["prev"], 1.0] for r in train]
        diag = sum(sum(r[j] * r[j] for r in X) for j in range(ng)) / ng
        target = [s_ * w for w in w0] + [0.0, 0.0]
        return ridge(X, [r["y"] for r in train], alpha_frac * diag, target, list(range(ng)))

    # Team-grouped K-fold CV on squared error.
    import zlib
    fold_of = {r["team"]: zlib.crc32(r["team"].encode()) % CV_FOLDS for r in rows}
    cv = {}
    for ai, af in enumerate(RIDGE_GRID):
        progress(0.80 + 0.15 * ai / len(RIDGE_GRID), "Cross-validating position weights")
        fold_mse = []
        for k in range(CV_FOLDS):
            tr = [r for r in rows if fold_of[r["team"]] != k]
            te = [r for r in rows if fold_of[r["team"]] == k]
            if not te or len(tr) < 30:
                continue
            bb = fit(tr, af)
            err = [(r["y"] - sum(b * xv for b, xv in zip(bb, r["x"] + [r["prev"], 1.0]))) ** 2
                   for r in te]
            fold_mse.append(sum(err) / len(err))
        mu = sum(fold_mse) / len(fold_mse)
        se = statistics.stdev(fold_mse) / math.sqrt(len(fold_mse)) if len(fold_mse) > 1 else 0.0
        cv[af] = (mu, se)
    best = min(cv, key=lambda a: cv[a][0])
    limit = cv[best][0] + cv[best][1]
    one_se = max(a for a in cv if cv[a][0] <= limit)      # most shrinkage within 1 SE
    defaults_ok = cv[RIDGE_GRID[-1]][0] <= limit
    alpha_frac = RIDGE_GRID[-1] if defaults_ok else one_se

    beta = fit(rows, alpha_frac)
    raw_w = {g: max(0.05, b) for g, b in zip(groups, beta[:ng])}
    # Only relative weights matter (the engine z-scores the roster total), so
    # normalize to the same total as the defaults, then bound each weight.
    norm = sum(w0) / sum(raw_w.values())
    lo, hi = WEIGHT_BOUNDS
    clamped = []
    fitted_w = {}
    for g in groups:
        v = raw_w[g] * norm
        d = mp.GROUP_WEIGHT[g]
        b_ = min(max(v, lo * d), hi * d)
        if abs(b_ - v) > 1e-9:
            clamped.append(g)
        fitted_w[g] = round(b_, 3)

    # Diagnostics: collinearity of passing-game groups, and each group's
    # correlation with the final rating after last season is accounted for.
    col = {g: [r["x"][i] for r in rows] for i, g in enumerate(groups)}
    a0, b0, c0 = ridge([[r["prev"], 1.0, 0.0] for r in rows], [r["y"] for r in rows], 0.0, [0, 0, 0], [])
    resid = [r["y"] - (a0 * r["prev"] + b0) for r in rows]
    diag = {"qb_wr_corr": pearson(col["QB"], col["WR"]),
            "qb_te_corr": pearson(col["QB"], col["TE"]),
            "partial_r": {g: pearson(col[g], resid) for g in groups}}

    # Power scaling: y ~ a * z(roster) + b * prev
    roster = [sum(fitted_w[g] * xv for g, xv in zip(groups, r["x"])) for r in rows]
    by_T = defaultdict(list)
    for v, r in zip(roster, rows):
        by_T[r["T"]].append(v)
    stats_T = {T: (statistics.mean(v), statistics.pstdev(v) or 1.0) for T, v in by_T.items()}
    zr = [(v - stats_T[r["T"]][0]) / stats_T[r["T"]][1] for v, r in zip(roster, rows)]
    a, b, _ = ridge([[z, r["prev"], 1.0] for z, r in zip(zr, rows)], [r["y"] for r in rows],
                    0.0, [0, 0, 0], [])
    pred = [a * z + b * r["prev"] for z, r in zip(zr, rows)]
    return {"group_weight": fitted_w, "a": a, "b": b, "n": len(rows),
            "ridge_alpha_frac": alpha_frac, "cv_mse": {str(k): v for k, v in cv.items()},
            "best_alpha": best, "one_se_alpha": one_se, "defaults_kept": defaults_ok,
            "clamped": clamped, "diag": diag,
            "r_roster_only": pearson(zr, [r["y"] for r in rows]),
            "r_prev_only": pearson([r["prev"] for r in rows], [r["y"] for r in rows]),
            "r_combined": pearson(pred, [r["y"] for r in rows]),
            "sd_y": statistics.pstdev([r["y"] for r in rows])}


# ---------------------------------------------------------------------------
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else config.RAW_FILE
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    classes = mr.class_map(raw.get("teams", []))
    params = {}

    print("1) Results solver walk-forward (scoring FBS-vs-FBS games) ...")
    res, regress, finals = walk_forward(raw, classes)
    if res:
        best = min(res, key=lambda k: res[k]["logloss"])
        print(f"   {'K':>5} {'damp':>6} {'MAE':>6} {'RMSE':>6} {'logloss':>8}")
        for (K, C), v in sorted(res.items()):
            mark = "  <- best" if (K, C) == best else ""
            print(f"   {K:>5g} {('none' if C > 1e5 else f'{C:.0f}'):>6} {v['mae']:>6.2f} "
                  f"{v['rmse']:>6.2f} {v['logloss']:>8.4f}{mark}")
        params.update(PRIOR_GAMES=best[0], MARGIN_DAMP=best[1],
                      MARGIN_SD=round(res[best]["rmse"], 2))
        print(f"   FBS-vs-FBS games scored: {res[best]['n']}")
        if best[0] in (K_GRID[0], K_GRID[-1]):
            print(f"   WARNING: best K ({best[0]:g}) is at the edge of the grid; "
                  "treat it as a bound, not an estimate.")
    params["PROGRAM_REGRESS"] = round(regress, 3)
    print(f"   year-over-year regression of team ratings: {regress:.3f}")

    print("2) Power: preseason roster -> final rating ...")
    pw = fit_power(raw, finals, classes)
    group_weight = {}
    if pw:
        sd_y = pw["sd_y"] or 1.0
        params.update(ROSTER_COEF=round(max(0.0, pw["a"] / sd_y), 3),
                      PRIOR_COEF=round(max(0.0, pw["b"]), 3))
        print(f"   team-seasons: {pw['n']}")
        print(f"   correlation with final rating: roster {pw['r_roster_only']:.3f}, "
              f"last season {pw['r_prev_only']:.3f}, combined {pw['r_combined']:.3f}")
        print("   ridge CV (team-grouped, mean squared error +/- 1 SE):")
        for k, (mu, se) in sorted(((float(k), v) for k, v in pw["cv_mse"].items())):
            tag = "defaults" if k >= 1e8 else f"{k:g}"
            marks = []
            if k == pw["best_alpha"]:
                marks.append("lowest error")
            if k == pw["ridge_alpha_frac"]:
                marks.append("CHOSEN")
            print(f"     {tag:>8}: {mu:7.2f} +/- {se:5.2f}" + (f"   <- {', '.join(marks)}" if marks else ""))
        d = pw["diag"]
        print(f"   passing-game overlap: corr(QB, WR) = {d['qb_wr_corr']:.2f}, "
              f"corr(QB, TE) = {d['qb_te_corr']:.2f}"
              + ("  (high: QB/WR weights can't be separated reliably)" if d["qb_wr_corr"] > 0.5 else ""))
        print("   each group vs. final rating, after last season is accounted for (partial r):")
        print("     " + ", ".join(f"{g} {v:+.2f}" for g, v in d["partial_r"].items()))
        if pw["defaults_kept"]:
            print("   Fitted weights don't beat the defaults by more than 1 SE -> keeping defaults.")
        else:
            group_weight = pw["group_weight"]
            print("   position weights (default -> fitted):")
            for g, v in group_weight.items():
                flag = "  (at bound)" if g in pw["clamped"] else ""
                print(f"     {g:>3}: {mp.GROUP_WEIGHT[g]:>5.2f} -> {v:>5.2f}{flag}")
        print(f"   ROSTER_COEF={params['ROSTER_COEF']}  PRIOR_COEF={params['PRIOR_COEF']}")
    else:
        print("   not enough point-in-time roster data; keeping defaults.")

    os.makedirs(config.DATA_DIR, exist_ok=True)
    out = {"version": CALIBRATION_VERSION, "params": params, "group_weight": group_weight,
           "source": path, "diagnostics": {"power": pw and {k: v for k, v in pw.items()
                                                             if k != "group_weight"}}}
    with open(engine.CALIBRATION_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    progress(1.0, "Done")
    print(f"Wrote {engine.CALIBRATION_FILE}")


if __name__ == "__main__":
    main()
