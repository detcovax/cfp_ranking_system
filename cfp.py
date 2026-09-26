"""
cfp.py -- College Football Playoff selection and seeding (2026-27 rules).

Source: collegefootballplayoff.com, "CFP Selection Committee Protocol and
Voting Process" and the 2026-27 bracket page.

How the field is built
  * Automatic bids (5): the ACC, Big Ten, Big 12 and SEC champions, plus the
    HIGHEST-RANKED TEAM (champion or not) from the American, Conference USA,
    MAC, Mountain West, Pac-12 or Sun Belt.
  * Notre Dame is automatic if ranked in the top 12 (then 6 at-large bids).
  * At-large (7): the best remaining teams in the committee's ranking.

How it is seeded (straight seeding)
  * Seeds follow the committee ranking. The four highest-ranked teams get
    seeds 1-4 and byes, whether or not they won a conference.
  * Automatic qualifiers ranked outside the top 12 go to the bottom of the
    seeding in rank order (they displace the lowest at-large teams).
  * Pairings: 5v12, 8v9, 6v11, 7v10 at the higher seed; 1 vs 8/9, 4 vs 5/12,
    2 vs 7/10, 3 vs 6/11; semis 1/4 path vs 2/3 path. No reseeding, no
    adjustments to avoid rematches.

How the committee separates comparable teams (protocol "principles")
  strength of schedule, head-to-head, comparative outcomes against common
  opponents (without rewarding margin), and key-player availability.
  committee_order() applies the first three; strength of schedule and
  availability are already in the score the engine passes in.
"""

P4_CONFS = ("SEC", "Big Ten", "Big 12", "ACC")
G6_CONFS = ("American Athletic", "Conference USA", "Mid-American",
            "Mountain West", "Pac-12", "Sun Belt")
INDEPENDENTS = "FBS Independents"
NOTRE_DAME = "Notre Dame"
FIELD_SIZE = 12
BYES = 4
ND_AUTO_TOP = 12
G6_BID_REQUIRES_TITLE = False   # 2026 rule: highest-ranked team, champion or not

# Committee tiebreaks only apply to "otherwise comparable" teams: adjacent in
# the ranking and within this many points of committee score.
COMPARABLE_GAP = 1.5
MIN_COMMON_OPPONENTS = 2
TIEBREAK_PASSES = 3
MC_TIEBREAK_DEPTH = 30          # tiebreaks in simulations: top 30 only


# ---------------------------------------------------------------------------
# Game classification
# ---------------------------------------------------------------------------
def is_ccg(g, conf_of):
    """A conference championship game (CFBD marks these in `notes`)."""
    notes = (g.get("notes") or "").lower()
    h, a = g.get("homeTeam"), g.get("awayTeam")
    c = conf_of.get(h)
    return "championship" in notes and c is not None and c == conf_of.get(a)


def is_conf_game(g, conf_of):
    """Regular-season conference game (counts toward the CCG race)."""
    if is_ccg(g, conf_of):
        return False
    flag = g.get("conferenceGame")
    if flag is not None:
        return bool(flag)
    c = conf_of.get(g.get("homeTeam"))
    return c is not None and c != INDEPENDENTS and c == conf_of.get(g.get("awayTeam"))


# ---------------------------------------------------------------------------
# Conference title race
# ---------------------------------------------------------------------------
def conference_race(known_by_school, conf_of, fbs, strength, win_prob, hfa):
    """Project each conference's championship game.

    Participants = top two by conference win % (expected wins for unplayed
    games), ties broken by rating. A championship game that has already been
    played decides the title; an unplayed one in the data is ignored so the
    as-of-week timeline can't peek at who actually qualified.

    Returns {conf: {"teams": [a, b], "p_a": P(a wins), "champion", "decided"}}.
    """
    out = {}
    members = {}
    for s in fbs:
        c = conf_of.get(s)
        if c in P4_CONFS or c in G6_CONFS:
            members.setdefault(c, []).append(s)
    for conf, teams in members.items():
        exp_w = {s: 0.0 for s in teams}
        games_n = {s: 0 for s in teams}
        decided = None
        for s in teams:
            for g in known_by_school.get(s, {}).get("games", []):
                hp, ap = g.get("homePoints"), g.get("awayPoints")
                if is_ccg(g, conf_of):
                    if hp is not None and ap is not None and hp != ap:
                        decided = (g.get("homeTeam"), g.get("awayTeam"), hp > ap)
                    continue
                if not is_conf_game(g, conf_of):
                    continue
                home = g.get("homeTeam") == s
                opp = g.get("awayTeam") if home else g.get("homeTeam")
                games_n[s] += 1
                if hp is not None and ap is not None:
                    tp, op = (hp, ap) if home else (ap, hp)
                    exp_w[s] += 1.0 if tp > op else 0.0
                else:
                    site = 0.0 if g.get("neutralSite") else (hfa if home else -hfa)
                    exp_w[s] += win_prob(strength(s) - strength(opp) + site)
        if decided:
            h, a, home_won = decided
            out[conf] = {"teams": [h, a], "p_a": 1.0 if home_won else 0.0,
                         "champion": h if home_won else a, "decided": True}
            continue
        ranked = sorted(teams, key=lambda s: (exp_w[s] / games_n[s] if games_n[s] else 0.0,
                                              strength(s)), reverse=True)
        if len(ranked) < 2:
            if ranked:
                out[conf] = {"teams": ranked, "p_a": 1.0, "champion": ranked[0],
                             "decided": False}
            continue
        a, b = ranked[0], ranked[1]
        p = win_prob(strength(a) - strength(b))   # neutral site
        out[conf] = {"teams": [a, b], "p_a": p, "champion": a if p >= 0.5 else b,
                     "decided": False}
    return out


# ---------------------------------------------------------------------------
# Committee ranking
# ---------------------------------------------------------------------------
def add_result(beat, record_vs, winner, loser):
    beat[(winner, loser)] = beat.get((winner, loser), 0) + 1
    record_vs.setdefault(winner, {}).setdefault(loser, [0, 0])[0] += 1
    record_vs.setdefault(loser, {}).setdefault(winner, [0, 0])[1] += 1


def _prefers(b, a, beat, record_vs):
    """Should b be ranked ahead of a (who is currently just above b)?"""
    bw, aw = beat.get((b, a), 0), beat.get((a, b), 0)
    if bw != aw:
        return bw > aw
    ra, rb = record_vs.get(a, {}), record_vs.get(b, {})
    common = (set(ra) & set(rb)) - {a, b}
    if len(common) < MIN_COMMON_OPPONENTS:
        return False

    def pct(rec):
        w = sum(rec[o][0] for o in common)
        l = sum(rec[o][1] for o in common)
        return w / (w + l) if w + l else 0.0
    return pct(rb) > pct(ra) + 1e-9


def committee_order(score, beat, record_vs, depth=None):
    """Order teams by committee score, then apply head-to-head and
    common-opponent tiebreaks between adjacent, comparable teams.
    depth limits tiebreaks to the top N (the Monte Carlo only needs the teams
    that can reach the field)."""
    order = sorted(score, key=lambda s: score[s], reverse=True)
    n = len(order) if depth is None else min(len(order), depth)
    for _ in range(TIEBREAK_PASSES):
        swapped = False
        for i in range(n - 1):
            a, b = order[i], order[i + 1]
            if score[a] - score[b] <= COMPARABLE_GAP and _prefers(b, a, beat, record_vs):
                order[i], order[i + 1] = b, a
                swapped = True
        if not swapped:
            break
    return order


# ---------------------------------------------------------------------------
# Selection + seeding
# ---------------------------------------------------------------------------
def select_field(order, conf_of, champions):
    """order: schools in committee-ranking order (best first).
    champions: {conference: champion school}.

    Returns {"seeds": [{"school", "seed", "committee_rank", "bid"}...],
             "first_four_out": [...], "displaced": [...]}.
    """
    rank = {s: i + 1 for i, s in enumerate(order)}
    bids = {}
    for conf in P4_CONFS:
        s = champions.get(conf)
        if s in rank:
            bids[s] = f"{conf} champion"
    for s in order:
        c = conf_of.get(s)
        if c in G6_CONFS and (not G6_BID_REQUIRES_TITLE or champions.get(c) == s):
            bids.setdefault(s, "Group of 6 bid"
                            + (f" ({c} champion)" if champions.get(c) == s else f" ({c})"))
            break
    if NOTRE_DAME in rank and rank[NOTRE_DAME] <= ND_AUTO_TOP:
        bids.setdefault(NOTRE_DAME, "Notre Dame (top 12)")
    field = dict(bids)
    for s in order:
        if len(field) >= FIELD_SIZE:
            break
        field.setdefault(s, "At-large")
    # Straight seeding by committee rank. Every non-automatic team in the field
    # ranks inside the top 12, so sorting by rank also puts automatic
    # qualifiers from outside the top 12 at the bottom, in rank order.
    seeded = sorted(field, key=rank.get)
    seeds = [{"school": s, "seed": i, "committee_rank": rank[s], "bid": field[s],
              "bye": i <= BYES} for i, s in enumerate(seeded, 1)]
    outside = [s for s in order if s not in field]
    displaced = [s for s in order[:FIELD_SIZE] if s not in field]
    return {"seeds": seeds, "first_four_out": outside[:4], "displaced": displaced}
