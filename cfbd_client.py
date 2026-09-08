"""
cfbd_client.py -- CollegeFootballData API client.

Exposes fetch_all(progress) which pulls everything the ranking model needs
(teams, games, team stats, and full player history) and returns one normalized
dict. Network calls happen here and nowhere else.

Run on a machine that can reach api.collegefootballdata.com.
"""

import time
import datetime
import requests

import config


class CFBDError(Exception):
    pass


def _call(endpoint, params=None, _tries=5):
    url = f"{config.CFBD_BASE_URL}/{endpoint}"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {config.CFBD_API_KEY}",
    }
    last_err = None
    for attempt in range(1, _tries + 1):
        resp = None
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                raise CFBDError("Unauthorized (401): check your CFBD_API_KEY.")
            if resp.status_code == 429:
                time.sleep(min(15, 3 * attempt))
                last_err = CFBDError("Rate limited (429)")
                continue
            raise CFBDError(f"HTTP {resp.status_code} for /{endpoint}")
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * attempt)
    raise CFBDError(f"Failed /{endpoint} after {_tries} tries: {last_err}")


def _noop(*_a, **_k):
    pass


# ---------------------------------------------------------------------------
# Teams / games / team stats
# ---------------------------------------------------------------------------
def _fetch_teams_and_games(year, progress):
    progress("Fetching teams...", 0.05)
    teams = _call("teams")

    progress("Fetching games...", 0.12)
    games = _call("games", {"year": year})

    progress("Fetching FPI ratings...", 0.16)
    try:
        fpi = _call("ratings/fpi", {"year": year})
    except CFBDError:
        fpi = []

    by_school = {}
    for t in teams:
        t["games"] = []
        t["ratings"] = {"fpi": []}
        by_school[t.get("school")] = t
    for g in games:
        for side in ("homeTeam", "awayTeam"):
            t = by_school.get(g.get(side))
            if t is not None:
                t["games"].append(g)
    for r in fpi:
        t = by_school.get(r.get("team"))
        if t is not None:
            t["ratings"]["fpi"].append(r)

    progress("Fetching team season stats...", 0.22)
    basic = _call("stats/season", {"year": year})
    progress("Fetching advanced team stats...", 0.28)
    advanced = _call("stats/season/advanced", {"year": year})

    # Merge basic statName/statValue rows into the advanced offense/defense dicts.
    adv_index = {}
    for a in advanced:
        a.setdefault("offense", {})
        a.setdefault("defense", {})
        adv_index[(a.get("season"), a.get("team"), a.get("conference"))] = a
    for s in basic:
        key = (s.get("season"), s.get("team"), s.get("conference"))
        name = s.get("statName", "")
        cat = "defense" if "Opponent" in name else "offense"
        a = adv_index.get(key)
        if a is None:
            a = {"season": s.get("season"), "team": s.get("team"),
                 "conference": s.get("conference"), "offense": {}, "defense": {}}
            adv_index[key] = a
        a[cat][name] = s.get("statValue")
    for a in adv_index.values():
        t = by_school.get(a.get("team"))
        if t is not None:
            t["stats"] = a

    return teams


# ---------------------------------------------------------------------------
# Player history
# ---------------------------------------------------------------------------
def _fetch_players(year, progress):
    hist_years = config.HISTORY_YEARS
    prod_years = sorted(set(hist_years + [year]))
    roster_years = sorted(set(hist_years + [year]))

    players = {"rosters": {}, "ppa": {}, "usage": {}, "player_stats": {},
               "returning": [], "recruits": {}, "portal": [], "current_games": []}

    for i, y in enumerate(roster_years):
        progress(f"Fetching roster {y}...", 0.32 + 0.03 * i)
        players["rosters"][str(y)] = _call("roster", {"year": y})

    for i, y in enumerate(prod_years):
        progress(f"Fetching player PPA {y}...", 0.42 + 0.03 * i)
        players["ppa"][str(y)] = _safe_list("ppa/players/season", {"year": y})

    for i, y in enumerate(prod_years):
        progress(f"Fetching player usage {y}...", 0.52 + 0.02 * i)
        players["usage"][str(y)] = _safe_list("player/usage", {"year": y})

    stat_categories = ["passing", "rushing", "receiving", "defensive",
                       "interceptions", "fumbles"]
    for i, y in enumerate(prod_years):
        progress(f"Fetching player season stats {y}...", 0.60 + 0.03 * i)
        merged = []
        for cat in stat_categories:
            merged.extend(_safe_list("stats/player/season",
                                     {"year": y, "category": cat}))
        players["player_stats"][str(y)] = merged

    progress("Fetching returning production...", 0.72)
    players["returning"] = _safe_list("player/returning", {"year": year})

    for i, y in enumerate(config.RECRUIT_YEARS):
        progress(f"Fetching recruiting {y}...", 0.76 + 0.02 * i)
        players["recruits"][str(y)] = _safe_list("recruiting/players", {"year": y})

    progress("Fetching transfer portal...", 0.84)
    players["portal"] = _safe_list("player/portal", {"year": year})

    progress("Fetching current-season per-game data...", 0.88)
    current = []
    for wk in config.CURRENT_WEEKS:
        rows = _safe_list("ppa/players/games",
                          {"year": year, "week": wk, "seasonType": "regular"})
        for r in rows:
            r.setdefault("week", wk)
        current.extend(rows)
    players["current_games"] = current

    return players


def _safe_list(endpoint, params):
    try:
        data = _call(endpoint, params)
        return data if isinstance(data, list) else []
    except CFBDError:
        return []


def _fetch_history_games(progress):
    """Games for each history year, used to compute per-season strength of
    schedule for the player-value model. Keyed by year string."""
    out = {}
    years = config.HISTORY_YEARS
    for i, y in enumerate(years):
        progress(f"Fetching {y} schedule (strength of schedule)...",
                 0.90 + 0.02 * i)
        out[str(y)] = _safe_list("games", {"year": y})
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def fetch_all(progress=None, year=None):
    progress = progress or _noop
    year = year or config.YEAR

    teams = _fetch_teams_and_games(year, progress)
    players = _fetch_players(year, progress)
    history_games = _fetch_history_games(progress)

    progress("Finalizing...", 0.95)
    counts = {
        "teams": len(teams),
        "roster_current": len(players["rosters"].get(str(year), [])),
        "returning": len(players["returning"]),
        "current_game_rows": len(players["current_games"]),
        "history_game_rows": sum(len(v) for v in history_games.values()),
    }
    return {
        "meta": {
            "year": year,
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "history_years": config.HISTORY_YEARS,
            "counts": counts,
        },
        "teams": teams,
        "players": players,
        "history_games": history_games,
    }
