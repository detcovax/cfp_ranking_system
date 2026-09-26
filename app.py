"""
app.py -- single entry point for the DAVE ranking dashboard.

    pip install -r requirements.txt
    python app.py

Starts a local web server and opens the dashboard. Use "Update data" in the UI
to pull fresh data from the CollegeFootballData API and recompute.

The model exposes three rankings -- Power, Current, Predictive -- each with
offense / defense / special-teams / overall variants, in two availability modes
(full-strength or availability-adjusted). Predictive supports an as-of week and
custom "what-if" results, which can be saved as named scenarios.
"""

import os
import sys
import json
import subprocess
import datetime
import uuid
import hashlib
import threading
import webbrowser
from collections import OrderedDict

from flask import Flask, jsonify, send_file, request, abort

import config
import cfbd_client
import ranking
import engine

app = Flask(__name__)

# --- In-memory state --------------------------------------------------------
_lock = threading.Lock()
RAW = None              # last fetched raw data
PREP = None             # engine.prepare() output (sos, injuries, player value)
PROFILES = {}           # shared player profiles (availability-adjusted)
PLAYER_RANKINGS = []    # shared player ranking list
META = {}               # meta about the current dataset
WORLDS = OrderedDict()   # signature -> world dict (LRU-ish cache)
MC_CACHE = OrderedDict()  # signature+n -> monte-carlo result
WORLD_CACHE_MAX = 32

STATUS = {"state": "idle", "job": None, "message": "", "progress": {"stage": "", "frac": 0.0},
          "last_updated": None}
EXECUTED = {"raw_mtime": None, "cal_mtime": None, "at": None}   # inputs of the last Execute
CAL_REPORT_FILE = os.path.join(config.DATA_DIR, "calibration_report.txt")


# --- helpers ----------------------------------------------------------------
def _save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _norm_overrides(overrides):
    """Keep only well-formed {game_id: {homePoints, awayPoints}} entries."""
    out = {}
    for k, v in (overrides or {}).items():
        if not isinstance(v, dict):
            continue
        hp, ap = v.get("homePoints"), v.get("awayPoints")
        try:
            out[str(k)] = {"homePoints": int(hp), "awayPoints": int(ap)}
        except (TypeError, ValueError):
            continue
    return out


def _sig(avail, week, overrides):
    payload = json.dumps({"a": avail, "w": week, "o": overrides or {}}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def _cache_put(cache, key, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > WORLD_CACHE_MAX:
        cache.popitem(last=False)


def get_world(avail="avail", week=None, overrides=None):
    """Return (signature, world) for a (mode, as-of week, overrides) request,
    building and caching it on demand."""
    avail = "full" if avail == "full" else "avail"
    week = None if week in (None, "", "null") else int(week)
    overrides = _norm_overrides(overrides)
    key = _sig(avail, week, overrides)
    if key in WORLDS:
        WORLDS.move_to_end(key)
        return key, WORLDS[key]
    if RAW is None or PREP is None:
        return key, None
    world = engine.build_world(RAW, PREP, avail=avail, cutoff_week=week, overrides=overrides)
    _cache_put(WORLDS, key, world)
    return key, world


def _world_from_request():
    """Resolve a world from request args/body: avail, week, overrides, or a
    saved scenario id (which supplies week + overrides unless overridden)."""
    body = request.get_json(silent=True) or {}
    args = request.args
    avail = body.get("avail") or args.get("avail") or "avail"
    week = body.get("week", args.get("week"))
    overrides = body.get("overrides")
    scen_id = body.get("scenario") or args.get("scenario")
    if scen_id:
        scen = _get_scenario(scen_id)
        if scen:
            if week in (None, "", "null"):
                week = scen.get("as_of_week")
            if overrides is None:
                overrides = scen.get("overrides")
    return get_world(avail, week, overrides)


# --- scenario storage -------------------------------------------------------
def _load_scenarios():
    data = _read_json(config.SCENARIOS_FILE, {"scenarios": []})
    if isinstance(data, list):
        data = {"scenarios": data}
    return data.get("scenarios", [])


def _get_scenario(sid):
    for s in _load_scenarios():
        if str(s.get("id")) == str(sid):
            return s
    return None


def _save_scenarios(items):
    _save_json(config.SCENARIOS_FILE, {"scenarios": items})


# --- compute pipeline -------------------------------------------------------
def _build_profiles(fbs_set):
    players = RAW.get("players", {})
    pv, pv_extras = PREP["pv_modes"]["avail"]
    profiles = ranking.build_player_profiles(pv_extras, players, fbs_set, PREP["sched_pts"])
    conf_by_team = {t["school"]: t.get("conference") for t in RAW.get("teams", [])}
    for prof in profiles.values():
        prof["conference"] = conf_by_team.get(prof["team"])
    player_rankings = []
    for i, p in enumerate(sorted(profiles.values(), key=lambda x: x["value"], reverse=True), 1):
        player_rankings.append({
            "overall_rank": i, "id": p["id"], "name": p["name"], "team": p["team"],
            "conference": p["conference"], "position": p["position"],
            "group": p["group"], "side": p["side"], "class": p["class"],
            "value": p["value"], "grade": p["grade"], "status": p["status"],
            "role": p.get("role"), "impact": p.get("impact"), "value_full": p.get("value_full"),
            "ppa_recent": p["ppa_recent"], "pos_rank": p["pos_rank"],
        })
    return profiles, player_rankings


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def pending():
    """What has changed on disk since the last Execute."""
    raw_m, cal_m = _mtime(config.RAW_FILE), _mtime(engine.CALIBRATION_FILE)
    return {"data": raw_m is not None and raw_m != EXECUTED["raw_mtime"],
            "calibration": cal_m != EXECUTED["cal_mtime"],
            "has_fetched_data": raw_m is not None,
            "has_calibration": cal_m is not None,
            "executed_at": EXECUTED["at"]}


def recompute(save=True):
    """Rebuild everything from RAW: prep, base worlds, profiles, meta."""
    global PREP, PROFILES, PLAYER_RANKINGS, META, WORLDS, MC_CACHE
    EXECUTED.update(raw_mtime=_mtime(config.RAW_FILE), cal_mtime=_mtime(engine.CALIBRATION_FILE),
                    at=datetime.datetime.now().isoformat(timespec="seconds"))
    PREP = engine.prepare(RAW)
    WORLDS = OrderedDict()
    MC_CACHE = OrderedDict()
    base_avail = engine.build_world(RAW, PREP, avail="avail")
    base_full = engine.build_world(RAW, PREP, avail="full")
    _cache_put(WORLDS, _sig("avail", None, {}), base_avail)
    _cache_put(WORLDS, _sig("full", None, {}), base_full)
    fbs_set = set(base_avail["teams"].keys())
    PROFILES, PLAYER_RANKINGS = _build_profiles(fbs_set)
    weeks, latest = engine.season_weeks(RAW.get("teams", []))
    manual = PREP["manual"]
    has_inj = any(len(s) for s in manual)
    META = {
        "year": int(RAW.get("meta", {}).get("year", config.YEAR)),
        "generated": RAW.get("meta", {}).get("generated"),
        "mode": "in-season" if base_avail["has_games"] else "preseason",
        "team_count": len(base_avail["rankings"]),
        "weeks": weeks,
        "latest_played_week": latest,
        "has_injuries": has_inj,
        "hfa": round(PREP["hfa"], 2),
        "params": PREP["params"],
        "calibration": PREP.get("calibration"),
        "scale": "points vs. average FBS team, neutral field",
    }
    if save:
        payload = {"meta": META, "players": PROFILES, "player_rankings": PLAYER_RANKINGS,
                   "base": {"avail": base_avail, "full": base_full}}
        _save_json(config.COMPUTED_FILE, payload)


def _load_cached():
    global RAW
    RAW = _read_json(config.RAW_FILE, None)
    if RAW is not None:
        try:
            recompute(save=False)
            STATUS["last_updated"] = META.get("generated")
        except Exception as e:  # pragma: no cover - defensive
            print("Recompute from cache failed:", e)


def _progress(stage, frac):
    STATUS["progress"] = {"stage": stage, "frac": round(frac, 3)}


def _job_fetch():
    """Fetch: pull from CFBD and save raw.json. Rankings on screen don't change."""
    raw = cfbd_client.fetch_all(progress=_progress)
    _save_json(config.RAW_FILE, raw)
    year = str(raw.get("meta", {}).get("year", config.YEAR))
    n_fbs = len(raw.get("fbs_teams") or []) or sum(1 for t in raw.get("teams", [])
                                                   if t.get("classification") == "fbs")
    n_roster = len((raw.get("players", {}).get("rosters") or {}).get(year, []))
    n_games = sum(1 for t in raw.get("teams", []) for g in t.get("games", [])
                  if g.get("homePoints") is not None) // 2
    return (f"Fetched {n_fbs} FBS teams, {n_roster:,} roster players, {n_games:,} completed games. "
            "Click Execute to compute ratings from it.")


def _job_execute():
    """Execute: compute ratings from the saved data + calibration."""
    global RAW
    _progress("Loading saved data...", 0.05)
    raw = _read_json(config.RAW_FILE, None)
    if raw is None:
        raise RuntimeError("No saved data yet. Click Fetch first.")
    _progress("Computing player ratings, results, and rankings...", 0.3)
    with _lock:
        RAW = raw
        recompute(save=True)
    cal = PREP.get("calibration", {}).get("message", "")
    return f"Ratings computed for {META['team_count']} teams ({META['mode']}; {cal})."


def _job_calibrate():
    """Calibrate: fit parameters from the saved data (separate process, so it
    always starts from the built-in defaults). Rankings don't change until Execute."""
    if _mtime(config.RAW_FILE) is None:
        raise RuntimeError("No saved data yet. Click Fetch first.")
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibrate.py")
    env = dict(os.environ, DAVE_PROGRESS="1", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen([sys.executable, script, config.RAW_FILE], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=env,
                            cwd=os.path.dirname(script))
    lines = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("@@PROGRESS "):
            _, frac, stage = line.split(" ", 2)
            _progress(stage, float(frac))
        else:
            lines.append(line)
    proc.wait()
    report = "\n".join(lines)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(CAL_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    if proc.returncode != 0:
        tail = "\n".join(lines[-6:])
        raise RuntimeError(f"calibrate.py failed:\n{tail}")
    return "Calibration saved. Review the report, then click Execute to apply it."


JOBS = {"fetch": _job_fetch, "execute": _job_execute, "calibrate": _job_calibrate}
JOB_LABEL = {"fetch": "Fetching from CFBD", "execute": "Executing ratings", "calibrate": "Calibrating"}


def _run_job(name):
    try:
        STATUS.update(state="running", job=name, message=JOB_LABEL[name] + "...",
                      progress={"stage": "Starting...", "frac": 0.0})
        msg = JOBS[name]()
        STATUS.update(state="done", message=msg, progress={"stage": "Done", "frac": 1.0},
                      last_updated=META.get("generated"))
    except Exception as e:
        STATUS.update(state="error", message=f"{type(e).__name__}: {e}",
                      progress={"stage": "Error", "frac": 0.0})


def _start_job(name):
    if STATUS["state"] == "running":
        return jsonify({"started": False, "status": STATUS,
                        "message": f"{JOB_LABEL.get(STATUS.get('job'), 'A job')} is already running."}), 409
    threading.Thread(target=_run_job, args=(name,), daemon=True).start()
    return jsonify({"started": True, "status": STATUS})


# --- routes -----------------------------------------------------------------
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "dashboard.html"))


@app.route("/api/meta")
def api_meta():
    return jsonify({
        "has_data": RAW is not None and bool(META),
        "year": META.get("year", config.YEAR),
        "mode": META.get("mode"),
        "generated": META.get("generated"),
        "team_count": META.get("team_count", 0),
        "weeks": META.get("weeks", []),
        "latest_played_week": META.get("latest_played_week", 0),
        "has_injuries": META.get("has_injuries", False),
        "mc_sims": config.MC_SIMS,
        "status": STATUS,
        "pending": pending(),
        "calibration": (PREP or {}).get("calibration"),
    })


def _rankings_payload(world, key):
    return {"meta": {"avail": world["avail"], "cutoff_week": world["cutoff_week"],
                     "has_games": world["has_games"], "mode": META.get("mode"),
                     "key": key},
            "rankings": world["rankings"],
            "bracket": world["bracket"]}


@app.route("/api/rankings")
def api_rankings():
    """Base (live) rankings for quick first paint."""
    key, world = get_world(request.args.get("avail", "avail"), None, None)
    if world is None:
        return jsonify({"meta": {"has_data": False}, "rankings": []})
    return jsonify(_rankings_payload(world, key))


@app.route("/api/world", methods=["GET", "POST"])
def api_world():
    key, world = _world_from_request()
    if world is None:
        return jsonify({"meta": {"has_data": False}, "rankings": []})
    return jsonify(_rankings_payload(world, key))


def _lookup_world_by_key():
    key = request.args.get("key")
    if key and key in WORLDS:
        WORLDS.move_to_end(key)
        return WORLDS[key]
    # Fall back to (re)building from explicit params or the base world.
    _, world = _world_from_request()
    return world


@app.route("/api/team/<path:school>")
def api_team(school):
    world = _lookup_world_by_key()
    if world is None:
        abort(404)
    team = world["teams"].get(school)
    if team is None:
        abort(404)
    return jsonify(team)


@app.route("/api/game/<gid>")
def api_game(gid):
    world = _lookup_world_by_key()
    if world is None:
        abort(404)
    game = world["games"].get(str(gid))
    if game is None:
        abort(404)
    return jsonify(game)


@app.route("/api/upcoming")
def api_upcoming():
    world = _lookup_world_by_key()
    if world is None:
        return jsonify({"weeks": {}, "mode": None})
    return jsonify({"weeks": world["upcoming"], "mode": META.get("mode"),
                    "cutoff_week": world["cutoff_week"]})


@app.route("/api/conferences")
def api_conferences():
    world = _lookup_world_by_key()
    if world is None:
        return jsonify({"conferences": [], "matrix": {"order": [], "records": {}}})
    return jsonify(world.get("conferences") or {"conferences": []})


@app.route("/api/bracket")
def api_bracket():
    world = _lookup_world_by_key()
    if world is None:
        return jsonify({"bracket": None})
    return jsonify({"bracket": world["bracket"]})


@app.route("/api/predict")
def api_predict():
    world = _lookup_world_by_key()
    if world is None:
        return jsonify({"error": "no data"}), 400
    home = request.args.get("home", "")
    away = request.args.get("away", "")
    basis = request.args.get("basis", "current")
    neutral = request.args.get("neutral", "0") in ("1", "true", "True")
    result = engine.predict_pair(world["rankings"], home, away, neutral, basis=basis)
    return jsonify(result)


@app.route("/api/teams_list")
def api_teams_list():
    key, world = get_world(request.args.get("avail", "avail"), None, None)
    if world is None:
        return jsonify([])
    return jsonify([{"school": r["school"], "abbreviation": r["abbreviation"],
                     "conference": r["conference"], "rank": r["ranks"]["current"]["overall"]}
                    for r in world["rankings"]])


@app.route("/api/simulate", methods=["GET", "POST"])
def api_simulate():
    key, world = _world_from_request()
    if world is None:
        return jsonify({"error": "no data"}), 400
    body = request.get_json(silent=True) or {}
    n = int(body.get("n") or request.args.get("n") or config.MC_SIMS)
    n = max(200, min(n, 20000))
    avail = world["avail"]
    week = world["cutoff_week"]
    # Reconstruct overrides used for this world for the MC (from the same request).
    overrides = _norm_overrides(body.get("overrides"))
    scen_id = body.get("scenario") or request.args.get("scenario")
    if scen_id and not overrides:
        scen = _get_scenario(scen_id)
        if scen:
            overrides = _norm_overrides(scen.get("overrides"))
    mkey = key + f":{n}"
    if mkey in MC_CACHE:
        MC_CACHE.move_to_end(mkey)
        return jsonify(MC_CACHE[mkey])
    mc = engine.montecarlo(RAW, PREP, world, avail=avail, cutoff_week=week,
                           overrides=overrides, n_sims=n, seed=17)
    _cache_put(MC_CACHE, mkey, mc)
    return jsonify(mc)


# --- players ----------------------------------------------------------------
@app.route("/api/players")
def api_players():
    return jsonify(PLAYER_RANKINGS)


@app.route("/api/player/<pid>")
def api_player(pid):
    prof = PROFILES.get(str(pid))
    if prof is None:
        abort(404)
    return jsonify(prof)


def _write_injuries(pid, status, name=None, team=None):
    data = _read_json(config.INJURIES_FILE, {"players": []})
    if isinstance(data, list):
        data = {"players": data}
    pid_s = str(pid)
    entries = [e for e in data.get("players", []) if str(e.get("id")) != pid_s]
    if status in ("out", "limited", "questionable", "doubtful"):
        entry = {"id": int(pid) if pid_s.isdigit() else pid_s, "status": status}
        if name:
            entry["name"] = name
        if team:
            entry["team"] = team
        entries.append(entry)
    data["players"] = entries
    _save_json(config.INJURIES_FILE, data)


@app.route("/api/player/<pid>/injury", methods=["POST"])
def api_player_injury(pid):
    if RAW is None:
        return jsonify({"ok": False, "message": "No data loaded. Click 'Update data' first."}), 400
    body = request.get_json(silent=True) or {}
    status = (body.get("status") or "active").lower()
    if status not in ("out", "limited", "active", "questionable", "doubtful"):
        return jsonify({"ok": False, "message": "invalid status"}), 400
    prof = PROFILES.get(str(pid), {})
    _write_injuries(pid, status, prof.get("name"), prof.get("team"))
    with _lock:
        recompute(save=True)  # injuries change player value -> rebuild worlds
    new_prof = PROFILES.get(str(pid))
    team = new_prof.get("team") if new_prof else None
    _, base = get_world("avail", None, None)
    team_row = next((r for r in base["rankings"] if r["school"] == team), None) if base else None
    return jsonify({"ok": True, "status": status, "player": new_prof,
                    "team_rating": team_row["ratings"]["current"]["overall"] if team_row else None,
                    "team_rank": team_row["ranks"]["current"]["overall"] if team_row else None})


# --- scenarios --------------------------------------------------------------
@app.route("/api/scenarios", methods=["GET", "POST"])
def api_scenarios():
    if request.method == "GET":
        return jsonify({"scenarios": _load_scenarios()})
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip() or "Untitled scenario"
    week = body.get("as_of_week")
    week = None if week in (None, "", "null") else int(week)
    overrides = _norm_overrides(body.get("overrides"))
    items = _load_scenarios()
    sid = body.get("id")
    now_entry = {"name": name, "as_of_week": week, "overrides": overrides}
    if sid:
        found = False
        for s in items:
            if str(s.get("id")) == str(sid):
                s.update(now_entry)
                found = True
                break
        if not found:
            now_entry["id"] = str(sid)
            items.append(now_entry)
    else:
        now_entry["id"] = uuid.uuid4().hex[:12]
        items.append(now_entry)
        sid = now_entry["id"]
    _save_scenarios(items)
    return jsonify({"ok": True, "id": str(sid), "scenarios": items})


@app.route("/api/scenarios/<sid>", methods=["DELETE"])
def api_scenario_delete(sid):
    items = [s for s in _load_scenarios() if str(s.get("id")) != str(sid)]
    _save_scenarios(items)
    return jsonify({"ok": True, "scenarios": items})


# --- refresh flow -----------------------------------------------------------
@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    return _start_job("fetch")


@app.route("/api/execute", methods=["POST"])
def api_execute():
    return _start_job("execute")


@app.route("/api/calibrate", methods=["POST"])
def api_calibrate():
    return _start_job("calibrate")


@app.route("/api/calibration")
def api_calibration():
    cal = _read_json(engine.CALIBRATION_FILE, None)
    try:
        with open(CAL_REPORT_FILE, "r", encoding="utf-8") as f:
            report = f.read()
    except OSError:
        report = None
    return jsonify({"calibration": cal, "report": report,
                    "in_use": (PREP or {}).get("calibration"), "pending": pending()})


@app.route("/api/status")
def api_status():
    return jsonify(dict(STATUS, pending=pending()))


def _open_browser():
    try:
        webbrowser.open(f"http://{config.HOST}:{config.PORT}")
    except Exception:
        pass


def main():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    _load_cached()
    print(f"DAVE Ranking dashboard -> http://{config.HOST}:{config.PORT}")
    if RAW is None:
        print("No data yet. Open the dashboard and click 'Update data'.")
    if os.environ.get("CFP_NO_BROWSER") != "1":
        threading.Timer(1.0, _open_browser).start()
    app.run(host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
