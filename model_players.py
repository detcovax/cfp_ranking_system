"""
model_players.py -- player ratings and the bottom-up roster roll-up.

Step 1. season_observations()
    For every player-season, a production rate, its sample size n, and a z-score
    against qualified players in the same position group that season:
      QB/RB/WR/TE  average PPA per play          n = countable plays
      DL/LB/DB     weighted box-score events     n = tackles + passes defended
      K            FG%                            n = FG attempts
      P            yards per punt                 n = punts
      OL           no individual data -> recruiting prior + experience
    Each season z is opponent-adjusted:  z += SOS_BETA * schedule_z(team, year),
    which also acts as the competition-level translation for transfers
    (production against G5 schedules is discounted automatically).

Step 2. project_player()   -- Bayesian shrinkage across seasons

        sum_k lam^k * t_k * n_k * (z_k + dev_k)  +  m * z_prior
    R = -----------------------------------------------------------
                sum_k lam^k * t_k * n_k  +  m

    k       seasons back (0 = the current season, if under way)
    lam     season decay (LAMBDA)
    t_k     transfer trust (<1 for seasons at another school)
    dev_k   class-year development between that season and now
    z_prior recruiting composite -> expected z, plus class-year shift
    m       prior pseudo-sample size (per position group)

    R is in "z units": 0 = an average qualified contributor at the position.

Step 3. assign_roles()     -- who actually plays
    A player's role = his usage relative to the position leader on his team
    (CFBD usage share, else plays; tackles+PD for defense; attempts for K/P).
        role = c * this_season + (1 - c) * PREV_ROLE_TRUST * last_season
    c = min(1, team games / ROLE_CONF_GAMES), so actual playing time takes
    over within a few games. Transfers carry last season's role at a
    discount. Depth order = ROLE_WEIGHT * role + R: usage decides who starts,
    rating only breaks near-ties (and orders newcomers with no usage).

Step 4. roll_up()          -- depth chart x snap share x position weight
    Players fill position slots with expected snap shares. Out players are
    removed (the backup slides up); limited players fill half their slot and
    the remainder passes down the depth chart. Unfilled snaps are played at
    replacement level (REPL_Z). Each player's IMPACT is measured by re-running
    his group without him (or, if he's hurt, with him healthy): large for a
    starter, near zero for a backup.

        unit_raw = sum_groups W_g * sum_slots share * availability * R

Pure functions; no I/O.
"""

import math
import statistics
from collections import defaultdict

# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------
POSITION_GROUP = {
    "QB": ("QB", "offense"),
    "RB": ("RB", "offense"), "FB": ("RB", "offense"), "TB": ("RB", "offense"),
    "WR": ("WR", "offense"), "ATH": ("WR", "offense"), "TE": ("TE", "offense"),
    "OL": ("OL", "offense"), "OT": ("OL", "offense"), "OG": ("OL", "offense"),
    "C": ("OL", "offense"), "G": ("OL", "offense"), "T": ("OL", "offense"),
    "IOL": ("OL", "offense"),
    "DL": ("DL", "defense"), "DE": ("DL", "defense"), "DT": ("DL", "defense"),
    "NT": ("DL", "defense"), "EDGE": ("DL", "defense"),
    "LB": ("LB", "defense"), "ILB": ("LB", "defense"), "OLB": ("LB", "defense"),
    "MLB": ("LB", "defense"),
    "DB": ("DB", "defense"), "CB": ("DB", "defense"), "S": ("DB", "defense"),
    "SAF": ("DB", "defense"), "FS": ("DB", "defense"), "SS": ("DB", "defense"),
    "NB": ("DB", "defense"),
    "K": ("K", "special"), "PK": ("K", "special"), "P": ("P", "special"),
    "LS": ("LS", "special"),
}
SKILL = ("QB", "RB", "WR", "TE")
DEFENSE = ("DL", "LB", "DB")

# ---------------------------------------------------------------------------
# Tunable parameters (defaults are reasoned starting points; see calibrate.py)
# ---------------------------------------------------------------------------
LAMBDA = 0.60                 # per-season decay
TRANSFER_TRUST = 0.80         # sample weight on seasons played at another school
SOS_BETA = 0.30               # z shift per 1 SD of schedule strength
Z_CLAMP = 3.0

# Prior pseudo-sample size m (same units as n for the group)
PRIOR_M = {"QB": 120, "RB": 60, "WR": 35, "TE": 25,
           "DL": 20, "LB": 20, "DB": 20, "K": 10, "P": 15}

# Minimum n to qualify for a season's reference distribution (full season)
QUALIFY_N = {"QB": 100, "RB": 50, "WR": 25, "TE": 15,
             "DL": 10, "LB": 10, "DB": 10, "K": 6, "P": 12}

# Development: expected z gain moving from class c to c+1
DEV_STEP = {1: 0.30, 2: 0.18, 3: 0.08, 4: 0.03, 5: 0.0}

# Recruiting prior: z = slope * clamp((composite - center) / width)
RECRUIT_CENTER, RECRUIT_WIDTH = 0.87, 0.035
RECRUIT_CLAMP = (-2.0, 2.5)
RECRUIT_SLOPE = 0.35
STARS_TO_COMPOSITE = {5: 0.985, 4: 0.925, 3: 0.86, 2: 0.80, 1: 0.78}
NO_RECRUIT_Z = -0.50          # walk-ons / unrated
CLASS_PRIOR_SHIFT = {1: -0.50, 2: -0.25, 3: -0.10, 4: 0.0, 5: 0.0, 0: -0.10}
NEVER_PLAYED_Z = -0.40        # upperclassman with no production on record
OL_EXPERIENCE_Z = 0.15        # per prior season on an FBS roster (max 3)

# Box-score event weights for defenders (CFBD statTypes)
DEF_EVENT_WEIGHTS = {"TOT": 1.0, "TFL": 2.5, "SACKS": 2.0, "QB HUR": 1.0,
                     "PD": 2.0, "INT": 5.0, "TD": 4.0}

# Roster roll-up: expected snap share by depth slot
SLOT_SHARES = {
    "QB": [1.0, 0.05],
    "RB": [0.60, 0.35, 0.05],
    "WR": [0.90, 0.85, 0.75, 0.30, 0.15],
    "TE": [0.70, 0.35],
    "OL": [1.0, 1.0, 1.0, 1.0, 1.0, 0.20, 0.10],
    "DL": [0.80, 0.80, 0.70, 0.70, 0.40, 0.30, 0.20],
    "LB": [0.85, 0.75, 0.40, 0.20],
    "DB": [0.95, 0.95, 0.90, 0.90, 0.60, 0.30, 0.15],
    "K": [1.0],
    "P": [1.0],
}
# Position weight: team value of +1 z at a full-snap slot (relative units;
# engine rescales units to points). Fit these with calibrate.py once you have
# a few seasons cached.
GROUP_WEIGHT = {"QB": 3.5, "RB": 0.7, "WR": 0.9, "TE": 0.6, "OL": 0.8,
                "DL": 0.9, "LB": 0.8, "DB": 0.8, "K": 1.0, "P": 0.6}
REPL_Z = -1.0                 # replacement-level player

# Roles (who actually gets snaps)
ROLE_WEIGHT = 2.5             # depth key = ROLE_WEIGHT * role + R
ROLE_CONF_GAMES = 3           # team games before this season's usage is fully trusted
PREV_ROLE_TRUST = 0.85        # last season's role carries over at this weight
TRANSFER_ROLE_TRUST = 0.70    # ...at a new school
STARTER_ROLE = 0.60           # role >= this = established starter
ROLE_LABELS = ((0.60, "Starter"), (0.25, "Rotation"), (0.001, "Backup"))
# Coach's revealed preference: when a player clearly starts over another
# (role gap >= this), the starter's effective rating is at least the backup's.
# The staff sees practice every day; our rating of two teammates is noisier
# than their depth chart. Also guarantees losing a starter never helps a team.
REVEALED_PREF_GAP = 0.30

# Availability
AUTO_OUT_MISSED_GAMES = 2     # this-season starter absent from this many of his
                              # team's games (counted in team games, so byes
                              # don't count) -> auto "out"
AUTO_MIN_APPEARANCES = 2      # must have started this season before vanishing
LIMITED_FACTOR = 0.5
OUT_FACTOR = 0.0


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
    return f"{rec.get('firstName', '') or ''} {rec.get('lastName', '') or ''}".strip()


def _ppa_all(rec):
    for key in ("averagePPA", "avgPPA", "ppa"):
        v = rec.get(key)
        if isinstance(v, dict):
            return as_float(v.get("all"))
        if isinstance(v, (int, float)):
            return as_float(v)
    return 0.0


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _wstats(pairs):
    """Weighted mean / sd from [(value, weight)]."""
    tw = sum(w for _, w in pairs)
    if tw <= 0:
        return None, None
    mu = sum(v * w for v, w in pairs) / tw
    var = sum(w * (v - mu) ** 2 for v, w in pairs) / tw
    return mu, math.sqrt(var) or None


# ---------------------------------------------------------------------------
# Step 1: season observations
# ---------------------------------------------------------------------------
def season_observations(players, year, year_frac, sched_z):
    """Return (obs, info).

    obs[pid][yr] = {"group", "team", "rate", "n", "z", plus raw fields}
    info[pid]    = {"name", "position"}
    """
    raw = defaultdict(dict)
    info = {}

    def slot(pid, yr):
        return raw[pid].setdefault(yr, {})

    for yr_s, rows in (players.get("ppa") or {}).items():
        yr = int(yr_s)
        for r in rows:
            pid = str(r.get("id"))
            if pid == "None":
                continue
            o = slot(pid, yr)
            o["ppa_avg"] = as_float((r.get("averagePPA") or {}).get("all"))
            o["ppa_total"] = as_float((r.get("totalPPA") or {}).get("all"))
            o["plays"] = as_float(r.get("countablePlays"))
            o["pos"] = r.get("position")
            o["team"] = r.get("team") or o.get("team")
            info.setdefault(pid, {"name": r.get("name"), "position": r.get("position")})

    for yr_s, rows in (players.get("usage") or {}).items():
        yr = int(yr_s)
        for r in rows:
            pid = str(r.get("id") or r.get("playerId"))
            u = as_float((r.get("usage") or {}).get("overall"), None)
            if pid == "None" or u is None:
                continue
            o = slot(pid, yr)
            o["usage"] = u
            o.setdefault("team", r.get("team"))
            o.setdefault("pos", r.get("position"))

    for yr_s, rows in (players.get("player_stats") or {}).items():
        yr = int(yr_s)
        agg = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        meta = {}
        for r in rows:
            pid = str(r.get("playerId") or r.get("id"))
            if pid == "None":
                continue
            cat = (r.get("category") or "").lower()
            st = (r.get("statType") or "").upper()
            agg[pid][cat][st] += as_float(r.get("stat"))
            meta.setdefault(pid, (r.get("team"), r.get("position"), r.get("player")))
        for pid, cats in agg.items():
            o = slot(pid, yr)
            team, pos, name = meta[pid]
            o.setdefault("team", team)
            o.setdefault("pos", pos)
            info.setdefault(pid, {"name": name, "position": pos})
            d = cats.get("defensive", {})
            ints = cats.get("interceptions", {})
            if d or ints:
                ev = dict(d)
                ev["INT"] = ints.get("INT", 0.0)
                o["def_score"] = sum(DEF_EVENT_WEIGHTS.get(k, 0.0) * v for k, v in ev.items())
                o["def_n"] = d.get("TOT", 0.0) + d.get("PD", 0.0)
            k = cats.get("kicking", {})
            if k.get("FGA"):
                o["fga"] = k["FGA"]
                o["fg_pct"] = k.get("FGM", 0.0) / k["FGA"]
            p = cats.get("punting", {})
            if p.get("NO"):
                o["punts"] = p["NO"]
                o["ypp"] = (p.get("YDS", 0.0) / p["NO"]) if p.get("YDS") else p.get("YPP", 0.0)

    # Rate / n per group for each observation.
    def rate_n(o, group):
        if group in SKILL and o.get("plays"):
            return o["ppa_avg"], o["plays"]
        if group in DEFENSE and o.get("def_n"):
            return o["def_score"], o["def_n"]
        if group == "K":
            if o.get("fga"):
                return o["fg_pct"], o["fga"]
            if o.get("punts"):
                return o["ypp"], o["punts"]
        if group == "P":
            if o.get("punts"):
                return o["ypp"], o["punts"]
            if o.get("fga"):
                return o["fg_pct"], o["fga"]
        return None, None

    # Build reference distributions per (year, group).
    dist = defaultdict(list)
    for pid, yrs in raw.items():
        for yr, o in yrs.items():
            group = norm_pos(o.get("pos") or (info.get(pid) or {}).get("position"))[0]
            o["group"] = group
            rate, n = rate_n(o, group)
            o["rate"], o["n"] = rate, n
            if rate is None:
                continue
            frac = year_frac if yr == year else 1.0
            if n >= QUALIFY_N.get(group, 10) * max(frac, 0.1):
                # Defense is volume-based -> unweighted; efficiency stats weighted by n.
                dist[(yr, group)].append((rate, 1.0 if group in DEFENSE else n))
    ref = {}
    for key, pairs in dist.items():
        if len(pairs) >= 5:
            mu, sd = _wstats(pairs)
            if sd:
                ref[key] = (mu, sd)

    for pid, yrs in raw.items():
        for yr, o in yrs.items():
            o["z"] = None
            if o.get("rate") is None:
                continue
            ms = ref.get((yr, o["group"]))
            if not ms:
                continue
            z = (o["rate"] - ms[0]) / ms[1]
            o["z_raw"] = _clamp(z, -Z_CLAMP, Z_CLAMP)
            o["sos_z"] = (sched_z.get(yr) or {}).get(o.get("team"), 0.0)
            o["z"] = _clamp(o["z_raw"] + SOS_BETA * o["sos_z"], -Z_CLAMP, Z_CLAMP)
    return raw, info


# ---------------------------------------------------------------------------
# Recruiting
# ---------------------------------------------------------------------------
def build_recruits(players):
    """Index recruits by athlete id, (name, school), and unique name."""
    by_id, by_ns, by_name = {}, {}, defaultdict(list)
    for yr, rows in (players.get("recruits") or {}).items():
        for r in rows:
            rec = {"stars": int(as_float(r.get("stars"))),
                   "rating": as_float(r.get("rating")), "year": int(as_float(yr)),
                   "school": r.get("committedTo") or r.get("school")}
            aid = r.get("athleteId")
            if aid not in (None, ""):
                by_id[str(aid)] = rec
            nm = full_name(r).lower()
            by_ns[(nm, (rec["school"] or "").lower())] = rec
            by_name[nm].append(rec)
    return {"by_id": by_id, "by_ns": by_ns,
            "by_name": {k: v[0] for k, v in by_name.items() if len(v) == 1}}


def find_recruit(recruits, pid, name, team):
    nm = (name or "").lower()
    return (recruits["by_id"].get(str(pid))
            or recruits["by_ns"].get((nm, (team or "").lower()))
            or recruits["by_name"].get(nm))


def recruit_prior_z(rec):
    if not rec:
        return NO_RECRUIT_Z
    comp = rec.get("rating") or STARS_TO_COMPOSITE.get(rec.get("stars", 0))
    if not comp:
        return NO_RECRUIT_Z
    lo, hi = RECRUIT_CLAMP
    return RECRUIT_SLOPE * _clamp((comp - RECRUIT_CENTER) / RECRUIT_WIDTH, lo, hi)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def parse_injuries(entries):
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


def _appearances(players):
    """(weeks each player appeared, weeks each team played, name/team keys)."""
    apps, team_weeks, name_team = defaultdict(set), defaultdict(set), {}
    for r in players.get("current_games", []) or []:
        pid = str(r.get("id") or r.get("playerId"))
        if pid == "None":
            continue
        wk = int(as_float(r.get("week")))
        apps[pid].add(wk)
        if r.get("team"):
            team_weeks[r["team"]].add(wk)
        name_team[pid] = (str(r.get("name", "")).lower(), str(r.get("team", "")).lower())
    return apps, team_weeks, name_team


def build_availability(players, manual, apply_availability=True, plist=None):
    """Return (status_by_id, source_by_id).

    Manual entries (injuries.json / player popup) always apply. Automatic
    detection only considers players who STARTED THIS SEASON at positions
    covered by per-game data (QB/RB/WR/TE): appeared in at least
    AUTO_MIN_APPEARANCES games as the position's leader in usage, then missed
    AUTO_OUT_MISSED_GAMES straight team games. Backups come and go, and a
    last-season starter who simply isn't playing this year is a depth-chart
    change, not an injury (his role falls on its own), so neither is flagged.
    A starter who returns clears automatically.
    """
    status, source = {}, {}
    if not apply_availability:
        return status, source
    out_ids, lim_ids, out_names, lim_names = manual
    apps, team_weeks, name_team = _appearances(players)
    for pid in out_ids:
        status[pid], source[pid] = "out", "manual"
    for pid in lim_ids:
        if pid not in status:
            status[pid], source[pid] = "limited", "manual"
    for p in plist or []:
        pid = p["id"]
        nt = (p["name"].lower(), (p["team"] or "").lower())
        if pid not in status and nt in out_names:
            status[pid], source[pid] = "out", "manual"
        elif pid not in status and nt in lim_names:
            status[pid], source[pid] = "limited", "manual"
        if pid in status or p["group"] not in SKILL:
            continue
        weeks = team_weeks.get(p["team"])
        if not weeks:
            continue
        if p["cur_role"] < STARTER_ROLE or len(apps.get(pid, ())) < AUTO_MIN_APPEARANCES:
            continue
        last = max(apps[pid])
        missed = sum(1 for w in weeks if w > last)
        if missed >= AUTO_OUT_MISSED_GAMES:
            status[pid], source[pid] = "out", "auto"
            p["missed_games"] = missed
    return status, source


# ---------------------------------------------------------------------------
# Step 2: project a player
# ---------------------------------------------------------------------------
def _dev_between(class_now, k):
    """Cumulative development from k seasons ago to now."""
    if not class_now or k <= 0:
        return 0.0
    start = max(1, class_now - k)
    return sum(DEV_STEP.get(c, 0.0) for c in range(start, class_now))


def project_player(entry, obs, info, recruits, roster_seasons, year, status_by_id):
    pid = str(entry.get("id"))
    group, side = norm_pos(entry.get("position"))
    class_now = int(as_float(entry.get("year"), 0))
    name = full_name(entry) or (info.get(pid) or {}).get("name") or pid
    team = entry.get("team")

    rec = find_recruit(recruits, pid, name, team)
    prior = recruit_prior_z(rec) + CLASS_PRIOR_SHIFT.get(class_now, CLASS_PRIOR_SHIFT[0])
    seasons = obs.get(pid, {})
    has_prod = any(o.get("z") is not None for o in seasons.values())
    if group == "OL":
        prior += OL_EXPERIENCE_Z * min(roster_seasons, 3)
    elif not has_prod and class_now >= 3:
        prior += NEVER_PLAYED_Z

    m = PRIOR_M.get(group, 20)
    num, den = m * prior, float(m)
    used = []
    cur_n = 0.0
    for yr, o in sorted(seasons.items(), reverse=True):
        k = year - yr
        z, n = o.get("z"), o.get("n") or 0.0
        if k < 0 or z is None or n <= 0 or group in ("OL", "LS", "UNK"):
            continue
        trust = TRANSFER_TRUST if (k > 0 and o.get("team") and team and o["team"] != team) else 1.0
        w = (LAMBDA ** k) * trust * n
        dev = _dev_between(class_now, k)
        num += w * (z + dev)
        den += w
        if k == 0:
            cur_n = n
        used.append({"year": yr, "z": round(z, 2), "n": round(n, 1),
                     "weight": round(w, 1), "dev": round(dev, 2)})
    R = num / den if den else prior

    st = status_by_id.get(pid)
    avail = OUT_FACTOR if st == "out" else (LIMITED_FACTOR if st == "limited" else 1.0)
    latest = max(seasons) if seasons else None
    ppa_recent = (round(seasons[latest]["ppa_avg"], 3)
                  if latest is not None and seasons[latest].get("plays") else None)
    basis = "history" if used else ("recruit" if rec else "unknown")
    return {"id": pid, "name": name, "team": team, "position": entry.get("position"),
            "group": group, "side": side, "class": class_now,
            "R": R, "prior_z": round(prior, 2), "prior_share": round(m / den, 2),
            "grade": round(50 + 15 * R, 1), "avail": avail, "status": st or "active",
            "basis": basis, "seasons_used": used, "cur_n": cur_n,
            "ppa_recent": ppa_recent,
            "recruit": ({"stars": rec["stars"], "rating": rec["rating"]} if rec else None)}


# ---------------------------------------------------------------------------
# Step 3: roles -- who actually gets snaps
# ---------------------------------------------------------------------------
def _role_metric(o, group):
    if group in SKILL:
        return o.get("usage") if o.get("usage") is not None else o.get("plays")
    if group in DEFENSE:
        return o.get("def_n")
    if group == "K":
        return o.get("fga")
    if group == "P":
        return o.get("punts")
    return None


def assign_roles(plist_by_team, obs, year, team_games):
    """Set p["role"], p["cur_role"], p["prev_role"], p["prev_role_here"]."""
    # Leader (max metric) per (team, year, group) across everyone observed.
    leader = defaultdict(float)
    for pid, yrs in obs.items():
        for yr, o in yrs.items():
            m = _role_metric(o, o.get("group"))
            if m and o.get("team"):
                key = (o["team"], yr, o["group"])
                leader[key] = max(leader[key], m)

    def share(o, group, team):
        if not o or not o.get("team"):
            return 0.0
        g = o.get("group") or group
        m = _role_metric(o, g)
        lead = leader.get((o["team"], o.get("_yr"), g))
        return min(1.0, m / lead) if m and lead else 0.0

    for pid, yrs in obs.items():
        for yr, o in yrs.items():
            o["_yr"] = yr

    for team, plist in plist_by_team.items():
        g_played = team_games.get(team, 0)
        for p in plist:
            seasons = obs.get(p["id"], {})
            cur = seasons.get(year)
            prev = seasons.get(year - 1)
            cur_role = share(cur, p["group"], team) if cur and cur.get("team") == team else 0.0
            prev_role = share(prev, p["group"], team)
            here = bool(prev and prev.get("team") == team)
            prev_eff = prev_role * (PREV_ROLE_TRUST if here else TRANSFER_ROLE_TRUST)
            has_cur_data = leader.get((team, year, p["group"]), 0.0) > 0
            c = min(1.0, g_played / ROLE_CONF_GAMES) if has_cur_data else 0.0
            p["cur_role"] = round(cur_role, 3)
            p["prev_role"] = round(prev_role, 3)
            p["prev_role_here"] = round(prev_role if here else 0.0, 3)
            p["role_confidence"] = round(c, 2)
            p["role"] = round(c * cur_role + (1 - c) * prev_eff, 3)


def role_label(p):
    if p["avail"] <= 0:
        return "Out"
    for cut, lab in ROLE_LABELS:
        if p["snap_share"] >= cut:
            return lab
    return "Reserve"


# ---------------------------------------------------------------------------
# Step 4: roll up a roster
# ---------------------------------------------------------------------------
def _fill(active, shares):
    """Pour snap shares down an ordered list of active players.
    Returns (group total of share * R, [(player, share)])."""
    total, carry, i, taken = 0.0, 0.0, 0, []
    for share in shares:
        need = share + carry
        carry = 0.0
        if i < len(active):
            p = active[i]
            i += 1
            take = min(need, 1.0) * p["avail"]
            carry = need - take
            taken.append((p, take))
            total += take * p.get("R_eff", p["R"])
        else:
            total += need * REPL_Z
    total += carry * REPL_Z
    return total, taken
def roll_up(plist, year_frac=None, group_totals=None):
    """Depth chart -> unit raw values. Also sets per-player snap_share,
    depth_rank, team_contrib, role label, and impact_raw (team value lost if
    this player is out; for a player who IS out, what his absence costs)."""
    by_group = defaultdict(list)
    for p in plist:
        by_group[p["group"]].append(p)
        p.update(snap_share=0.0, team_contrib=0.0, depth_rank=None,
                 impact_raw=0.0, healthy_share=0.0)

    units = {"offense": 0.0, "defense": 0.0, "special": 0.0}
    for group, shares in SLOT_SHARES.items():
        gl = by_group.get(group, [])
        gl.sort(key=lambda p: ROLE_WEIGHT * p.get("role", 0.0) + p["R"], reverse=True)
        # Effective rating: R, raised to the best R among players this one
        # clearly starts over (computed on the healthy depth chart).
        for i, p in enumerate(gl):
            below = [q["R"] for q in gl[i + 1:]
                     if p.get("role", 0.0) - q.get("role", 0.0) >= REVEALED_PREF_GAP]
            p["R_eff"] = max([p["R"]] + below)
        active = [p for p in gl if p["avail"] > 0]
        side = norm_pos(group)[1]
        w = GROUP_WEIGHT[group]
        total, taken = _fill(active, shares)
        for p, take in taken:
            p["snap_share"] = round(take, 2)
            p["team_contrib"] = w * take * p["R_eff"]
        # Impact: re-run the group without each contributor, or with each
        # injured player restored to health.
        for p in gl:
            if p["avail"] >= 1.0 and p["snap_share"] > 0:
                without, _ = _fill([q for q in active if q is not p], shares)
                # Floor at 0: if the next man up were better, he'd be playing.
                p["impact_raw"] = max(0.0, w * (total - without))
                p["healthy_share"] = p["snap_share"]
            elif p["avail"] < 1.0:
                saved = p["avail"]
                p["avail"] = 1.0
                healthy, h_taken = _fill([q for q in gl if q["avail"] > 0], shares)
                p["avail"] = saved
                p["impact_raw"] = max(0.0, w * (healthy - total))
                p["healthy_share"] = round(next((t for q, t in h_taken if q is p), 0.0), 2)
        units[side] += w * total
        if group_totals is not None:
            group_totals[group] = total
        for rank, p in enumerate(active + [p for p in gl if p["avail"] <= 0], 1):
            p["depth_rank"] = rank
    for p in plist:
        p["role_label"] = role_label(p) if p["group"] in SLOT_SHARES else "—"
    return units


# ---------------------------------------------------------------------------
# Public: rate every current-roster player and roll up each team
# ---------------------------------------------------------------------------
def compute_player_value(players, manual, sched_z, year, year_frac,
                         apply_availability=True, team_games=None):
    """Return (by_team, extras).

    by_team[team] = {"raw": {offense, defense, special}, "impaired",
                     "returning_pct", "players": [...]}
    Values are in relative units; engine.prepare() maps them to points.
    """
    obs, info = season_observations(players, year, year_frac, sched_z)
    recruits = build_recruits(players)
    if team_games is None:          # fall back to weeks seen in per-game data
        _, tw, _ = _appearances(players)
        team_games = {t: len(w) for t, w in tw.items()}

    roster_hist = defaultdict(int)
    for yr_s, rows in (players.get("rosters") or {}).items():
        if int(yr_s) < year:
            for r in rows:
                roster_hist[str(r.get("id"))] += 1

    by_team, by_id = defaultdict(list), {}
    for entry in (players.get("rosters") or {}).get(str(year), []):
        if not entry.get("team"):
            continue
        p = project_player(entry, obs, info, recruits,
                           roster_hist.get(str(entry.get("id")), 0), year, {})
        by_team[p["team"]].append(p)
        by_id[p["id"]] = p

    # Roles first (who plays), then availability (which needs roles to know
    # who is an established starter), then the depth chart.
    assign_roles(by_team, obs, year, team_games)
    status_by_id, status_source = build_availability(players, manual, apply_availability,
                                                     list(by_id.values()))
    for p in by_id.values():
        st = status_by_id.get(p["id"])
        p["status"] = st or "active"
        p["status_source"] = status_source.get(p["id"])
        p["avail"] = OUT_FACTOR if st == "out" else (LIMITED_FACTOR if st == "limited" else 1.0)

    returning = {r.get("team"): as_float(r.get("percentPPA"))
                 for r in players.get("returning", [])}
    out = {}
    for team, plist in by_team.items():
        groups = {}
        units = roll_up(plist, year_frac, groups)
        plist.sort(key=lambda p: (p["impact_raw"], p["R"]), reverse=True)
        out[team] = {"raw": units, "groups": groups,
                     "impaired": sum(1 for p in plist if p["status"] in ("out", "limited")),
                     "returning_pct": round(returning.get(team, 0.0), 3),
                     "players": plist}
    return out, {"by_id": by_id, "obs": obs, "info": info, "recruits": recruits,
                 "status_by_id": status_by_id, "status_source": status_source}
