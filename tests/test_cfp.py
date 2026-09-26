"""Rule tests for cfp.py against the 2026-27 CFP protocol."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import cfp

def teams(n=30):
    return [f"T{i:02d}" for i in range(1, n + 1)]     # T01 = committee #1

def conf_map(assign, n=30):
    c = {s: "Big Ten" for s in teams(n)}             # default: P4 non-champions
    c.update(assign)
    return c

def seeds(field):
    return [(sd["seed"], sd["school"], sd["bid"]) for sd in field["seeds"]]

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print("PASS", name)

order = teams()
# Case 1: straight seeding. #2 (non-champion) gets a bye; SEC champ at #9 gets seed 9.
conf = conf_map({"T01": "Big Ten", "T09": "SEC", "T05": "Big 12", "T07": "ACC", "T11": "Mountain West"})
champs = {"Big Ten": "T01", "SEC": "T09", "Big 12": "T05", "ACC": "T07", "Mountain West": "T11"}
f = cfp.select_field(order, conf, champs)
sd = {s: n for n, s, _ in seeds(f)}
check("non-champion ranked #2 gets seed 2 and a bye", sd["T02"] == 2 and f["seeds"][1]["bye"])
check("P4 champion ranked #9 is seeded 9, no bye", sd["T09"] == 9 and not f["seeds"][8]["bye"])
check("field is exactly the top 12 when all autos are inside it", set(sd) == set(order[:12]))

# Case 2: P4 champion ranked #18 -> in the field, seeded 12, displaces #12.
conf = conf_map({"T18": "ACC", "T11": "Sun Belt"})
champs = {"Big Ten": "T01", "SEC": "T03", "Big 12": "T04", "ACC": "T18", "Sun Belt": "T11"}
f = cfp.select_field(order, conf, champs)
sd = {s: n for n, s, _ in seeds(f)}
check("P4 champion ranked #18 gets in at seed 12", sd.get("T18") == 12)
check("#12 at-large is displaced", "T12" not in sd and f["displaced"] == ["T12"])

# Case 3: Group of 6 bid goes to the highest-ranked G6 team even if it lost its title game.
conf = conf_map({"T15": "American Athletic", "T20": "American Athletic", "T25": "Mountain West"})
champs = {"Big Ten": "T01", "SEC": "T02", "Big 12": "T03", "ACC": "T04",
          "American Athletic": "T20", "Mountain West": "T25"}
f = cfp.select_field(order, conf, champs)
bid = {s: b for _, s, b in seeds(f)}
check("highest-ranked G6 team (not the champion) gets the G6 bid", "T15" in bid and "Group of 6" in bid["T15"])
check("lower-ranked G6 champion does not", "T20" not in bid)

# Case 4: two autos outside the top 12 go to the bottom in rank order; Notre Dame at #11 is protected.
conf = conf_map({"T11": cfp.INDEPENDENTS, "T16": "SEC", "T22": "Pac-12"})
order4 = list(order); order4[10] = cfp.NOTRE_DAME
conf[cfp.NOTRE_DAME] = cfp.INDEPENDENTS
champs = {"Big Ten": "T01", "SEC": "T16", "Big 12": "T03", "ACC": "T04", "Pac-12": "T22"}
f = cfp.select_field(order4, conf, champs)
s4 = seeds(f)
check("autos outside the top 12 are seeds 11 and 12 in rank order", s4[10][1] == "T16" and s4[11][1] == "T22")
check("Notre Dame ranked #11 gets in on its automatic bid", any(s == cfp.NOTRE_DAME for _, s, _ in s4))
check("the two lowest at-large teams are displaced", f["displaced"] == ["T10", "T12"])

# Case 5: Notre Dame ranked #13 has no automatic bid.
order5 = list(order); order5[12] = cfp.NOTRE_DAME
f = cfp.select_field(order5, conf, {"Big Ten": "T01", "SEC": "T02", "Big 12": "T03", "ACC": "T04", "Pac-12": "T05"})
check("Notre Dame at #13 is out", all(s != cfp.NOTRE_DAME for _, s, _ in seeds(f)))

# Case 6: committee tiebreaks.
score = {"A": 10.0, "B": 9.2, "C": 5.0}
beat, rec = {}, {}
cfp.add_result(beat, rec, "B", "A")
check("head-to-head flips comparable teams", cfp.committee_order(score, beat, rec)[:2] == ["B", "A"])
score2 = {"A": 10.0, "B": 7.0}
check("head-to-head does not flip teams that aren't comparable", cfp.committee_order(score2, beat, rec) == ["A", "B"])
beat, rec = {}, {}
for o in ("X", "Y"):
    cfp.add_result(beat, rec, "B", o)
cfp.add_result(beat, rec, "A", "X"); cfp.add_result(beat, rec, "Y", "A")
check("common-opponent record breaks a tie without head-to-head", cfp.committee_order(score, beat, rec)[:2] == ["B", "A"])
print(f"\n{ok} checks passed")
