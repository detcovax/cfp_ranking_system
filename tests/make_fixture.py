"""
Synthetic CFBD-shaped dataset with known ground truth, for testing the model.

Players have a hidden true quality; team strength is a weighted sum of its
starters' true quality plus a program effect. Production stats (PPA per play,
tackles, FG%) are noisy readings of true quality. Games are generated from team
strength + home field + noise. The model never sees the truth; the test checks
how well it recovers it.
"""

import json
import math
import random
import sys

YEAR = 2026
HIST = [YEAR - 3, YEAR - 2, YEAR - 1]
PLAYED_WEEKS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
rng = random.Random(7)

CONFS = ["SEC", "Big Ten", "Big 12", "ACC", "American Athletic", "Mountain West",
         "Sun Belt", "Conference USA", "Mid-American"]
POWER = {"SEC", "Big Ten", "Big 12", "ACC"}
ROSTER = {"QB": 3, "RB": 4, "WR": 7, "TE": 3, "OL": 9, "DL": 8, "LB": 5, "DB": 8, "K": 1, "P": 1}
import os
TRUE_W = json.loads(os.environ["TRUE_W"]) if os.environ.get("TRUE_W") else {"QB": 3.5, "RB": 0.7, "WR": 0.9, "TE": 0.6, "OL": 0.8, "DL": 0.9, "LB": 0.8, "DB": 0.8, "K": 1.0, "P": 0.6}
STARTERS = {"QB": 1, "RB": 1, "WR": 3, "TE": 1, "OL": 5, "DL": 4, "LB": 3, "DB": 4, "K": 1, "P": 1}

teams = []
for i in range(128):
    conf = CONFS[i % len(CONFS)]
    teams.append({"school": f"FBS{i:03d}", "conference": conf, "classification": "fbs",
                  "abbreviation": f"F{i:03d}", "color": "#335577", "logos": [],
                  "_program": rng.gauss(4.0 if conf in POWER else -4.0, 3.0)})
for i in range(24):
    teams.append({"school": f"FCS{i:03d}", "conference": "FCS Conf", "classification": "fcs",
                  "abbreviation": f"C{i:03d}", "color": "#777777", "logos": [], "_program": -18.0})
N_LOWER = int(os.environ.get("N_LOWER", "0"))
for i in range(N_LOWER):  # noqa
    teams.append({"school": f"D2_{i:03d}", "conference": "D2 Conf", "classification": "ii",
                  "abbreviation": f"D{i:03d}", "color": "#999999", "logos": [], "_program": -30.0})
fbs = [t for t in teams if t["classification"] == "fbs"]

# --- players with careers --------------------------------------------------
pid_seq = [100000]
players = {}   # pid -> {pos, quality_by_year, team_by_year, class_by_year, recruit}


def new_player(team, pos, start_year, recruit_boost):
    pid_seq[0] += 1
    pid = str(pid_seq[0])
    rating = min(0.9999, max(0.75, rng.gauss(0.86 + recruit_boost, 0.04)))
    talent = (rating - 0.87) / 0.035 * 0.45 + rng.gauss(0, 0.8)
    players[pid] = {"pos": pos, "talent": talent, "start": start_year,
                    "team": {}, "rating": rating}
    return pid


for t in fbs:
    boost = 0.02 if t["conference"] in POWER else -0.02
    for pos, n in ROSTER.items():
        for k in range(n + 2):
            start = rng.choice([YEAR - 4, YEAR - 3, YEAR - 2, YEAR - 1, YEAR])
            pid = new_player(t["school"], pos, start, boost)
            for y in range(start, YEAR + 1):
                if y - start < 5:
                    players[pid]["team"][y] = t["school"]

# A few transfers: move some players' current team.
pids = list(players)
for pid in rng.sample(pids, 300):
    p = players[pid]
    if YEAR in p["team"] and YEAR - 1 in p["team"]:
        p["team"][YEAR] = rng.choice(fbs)["school"]


def quality(pid, y):
    p = players[pid]
    cls = y - p["start"] + 1
    dev = [0, -0.6, -0.25, -0.05, 0.05, 0.1][min(max(cls, 0), 5)]
    return p["talent"] + dev


def team_strength(school, y):
    roster = [pid for pid, p in players.items() if p["team"].get(y) == school]
    total = 0.0
    for pos, k in STARTERS.items():
        qs = sorted((quality(pid, y) for pid in roster if players[pid]["pos"] == pos), reverse=True)
        qs = (qs + [-1.0] * k)[:k]
        total += TRUE_W[pos] * sum(qs)
    return total


true_strength = {}
for y in HIST + [YEAR]:
    raw = {t["school"]: team_strength(t["school"], y) for t in fbs}
    mu = sum(raw.values()) / len(raw)
    sd = math.sqrt(sum((v - mu) ** 2 for v in raw.values()) / len(raw))
    for t in fbs:
        true_strength[(t["school"], y)] = 10.0 * (raw[t["school"]] - mu) / sd + 0.4 * t["_program"]
    for t in teams:
        if t["classification"] in ("fcs", "ii"):
            true_strength[(t["school"], y)] = t["_program"] + rng.gauss(0, float(os.environ.get("LOWER_SD", "7")))

# --- schedules --------------------------------------------------------------
gid = [500000]


def schedule(y, played_weeks):
    games = []
    order = [t["school"] for t in fbs]
    for wk in range(1, 13):
        rng.shuffle(order)
        for a, b in zip(order[0::2], order[1::2]):
            if wk <= 2 and rng.random() < 0.25:
                b = rng.choice([t["school"] for t in teams if t["classification"] == "fcs"])
            gid[0] += 1
            neutral = rng.random() < 0.05
            g = {"id": gid[0], "season": y, "week": wk, "seasonType": "regular",
                 "neutralSite": neutral, "homeTeam": a, "awayTeam": b,
                 "homeClassification": "fbs",
                 "awayClassification": "fcs" if b.startswith("FCS") else "fbs",
                 "homeConference": None, "awayConference": None,
                 "homePoints": None, "awayPoints": None, "completed": False}
            if wk <= played_weeks:
                m = true_strength[(a, y)] - true_strength[(b, y)] + (0 if neutral else 2.5) + rng.gauss(0, 14)
                total = max(20, rng.gauss(55, 10))
                hp = max(0, round((total + m) / 2))
                ap = max(0, round((total - m) / 2))
                if hp == ap:
                    hp += 3
                g.update(homePoints=hp, awayPoints=ap, completed=True)
            games.append(g)
        low = [t["school"] for t in teams if t["classification"] in ("fcs", "ii")]
        rng.shuffle(low)
        for a, b in zip(low[0::2], low[1::2]):
            gid[0] += 1
            g = {"id": gid[0], "season": y, "week": wk, "seasonType": "regular", "neutralSite": False,
                 "homeTeam": a, "awayTeam": b,
                 "homeClassification": "ii" if a.startswith("D2") else "fcs",
                 "awayClassification": "ii" if b.startswith("D2") else "fcs",
                 "homePoints": None, "awayPoints": None, "completed": False}
            if wk <= played_weeks:
                m = true_strength[(a, y)] - true_strength[(b, y)] + 2.5 + rng.gauss(0, 16)
                total = max(20, rng.gauss(52, 12))
                hp, ap = max(0, round((total + m) / 2)), max(0, round((total - m) / 2))
                if hp == ap:
                    hp += 3
                g.update(homePoints=hp, awayPoints=ap, completed=True)
            games.append(g)
    return games


hist_games = {str(y): schedule(y, 99) for y in HIST}
cur_games = schedule(YEAR, PLAYED_WEEKS)
for t in teams:
    t["games"] = [g for g in cur_games if t["school"] in (g["homeTeam"], g["awayTeam"])]
    t["ratings"] = {"fpi": []}

# --- player data ------------------------------------------------------------
rosters, ppa, pstats, recruits, current_games = {}, {}, {}, {}, []
usage = {}
PLAYS = {"QB": 380, "RB": 150, "WR": 70, "TE": 35}
for y in HIST + [YEAR]:
    rosters[str(y)] = []
    ppa[str(y)] = []
    pstats[str(y)] = []
    usage[str(y)] = []
    frac = 1.0 if y < YEAR else PLAYED_WEEKS / 12
    by_team_pos = {}
    for pid, p in players.items():
        team = p["team"].get(y)
        if not team:
            continue
        cls = y - p["start"] + 1
        rosters[str(y)].append({"id": int(pid), "firstName": "P", "lastName": pid,
                                "team": team, "position": p["pos"], "year": min(cls, 5)})
        by_team_pos.setdefault((team, p["pos"]), []).append(pid)
    qb_q = {}
    for (team, pos), plist in by_team_pos.items():
        if pos == "QB":
            qb_q[team] = max(quality(x, y) for x in plist)
    SHARED = float(os.environ.get("QB_SHARED", "0"))
    for (team, pos), plist in by_team_pos.items():
        plist.sort(key=lambda x: quality(x, y), reverse=True)
        for depth, pid in enumerate(plist):
            q = quality(pid, y)
            share = [1.0, 0.35, 0.15, 0.05][min(depth, 3)] if pos != "WR" else [1, 1, 0.9, 0.4, 0.2, 0.05][min(depth, 5)]
            if pos in PLAYS:
                plays = PLAYS[pos] * share * frac * rng.uniform(0.8, 1.2)
                if plays < 3:
                    continue
                own = (1 - SHARED) * q + SHARED * qb_q.get(team, 0.0) if pos in ("WR", "TE") else q
                avg = 0.12 + 0.10 * own + rng.gauss(0, 0.5 / math.sqrt(plays))
                ppa[str(y)].append({"season": y, "id": int(pid), "name": f"P {pid}",
                                    "position": pos, "team": team, "conference": None,
                                    "countablePlays": round(plays),
                                    "averagePPA": {"all": avg}, "totalPPA": {"all": avg * plays}})
                usage[str(y)].append({"season": y, "id": int(pid), "name": f"P {pid}", "position": pos,
                                      "team": team, "usage": {"overall": round(plays / (720 * frac), 4)}})
            elif pos in ("DL", "LB", "DB"):
                base = {"DL": 30, "LB": 60, "DB": 45}[pos] * share * frac
                if base < 2:
                    continue
                tot = max(0, rng.gauss(base * (1 + 0.15 * q), 4))
                rows = {"TOT": tot, "SOLO": tot * 0.6, "TFL": max(0, rng.gauss(base * 0.1 * (1 + 0.4 * q), 1)),
                        "SACKS": max(0, rng.gauss(base * 0.05 * (1 + 0.5 * q), 0.8)),
                        "PD": max(0, rng.gauss(base * 0.06 * (1 + 0.4 * q), 0.8))}
                for st, v in rows.items():
                    pstats[str(y)].append({"season": y, "playerId": pid, "player": f"P {pid}",
                                           "position": pos, "team": team, "category": "defensive",
                                           "statType": st, "stat": str(round(v, 1))})
            elif pos == "K" and depth == 0:
                fga = max(4, round(20 * frac))
                fgm = sum(rng.random() < min(0.95, 0.75 + 0.06 * q) for _ in range(fga))
                for st, v in (("FGA", fga), ("FGM", fgm)):
                    pstats[str(y)].append({"season": y, "playerId": pid, "player": f"P {pid}", "position": pos,
                                           "team": team, "category": "kicking", "statType": st, "stat": str(v)})
            elif pos == "P" and depth == 0:
                no = max(5, round(55 * frac))
                ypp = 42 + 2.0 * q + rng.gauss(0, 6 / math.sqrt(no))
                for st, v in (("NO", no), ("YDS", round(no * ypp))):
                    pstats[str(y)].append({"season": y, "playerId": pid, "player": f"P {pid}", "position": pos,
                                           "team": team, "category": "punting", "statType": st, "stat": str(v)})
            if y == YEAR and pos in PLAYS and share >= 0.35:
                for wk in range(1, PLAYED_WEEKS + 1):
                    current_games.append({"id": int(pid), "name": f"P {pid}", "team": team,
                                          "week": wk, "averagePPA": {"all": 0.1}})

for pid, p in players.items():
    y = p["start"]
    recruits.setdefault(str(y), []).append({"athleteId": pid, "name": f"P {pid}",
                                             "committedTo": p["team"][y], "position": p["pos"],
                                             "stars": 5 if p["rating"] > 0.98 else 4 if p["rating"] > 0.89 else 3,
                                             "rating": round(p["rating"], 4), "year": y})

raw = {"meta": {"year": YEAR, "generated": "fixture", "history_years": HIST, "counts": {}},
       "teams": [{k: v for k, v in t.items() if not k.startswith("_")} for t in teams],
       "players": {"rosters": rosters, "ppa": ppa, "usage": usage, "player_stats": pstats,
                   "returning": [], "recruits": recruits, "portal": [],
                   "current_games": current_games},
       "history_games": hist_games}
truth = {f"{s}|{y}": v for (s, y), v in true_strength.items()}
out = sys.argv[1] if len(sys.argv) > 1 else "fixture.json"
json.dump(raw, open(out, "w"))
json.dump(truth, open(out.replace(".json", "_truth.json"), "w"))
print("players", len(players), "cur games", len(cur_games), "->", out)
