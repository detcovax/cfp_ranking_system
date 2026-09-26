import json, os, sys, time, shutil, tempfile
os.environ["CFBD_API_KEY"] = "x"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
tmp = tempfile.mkdtemp()
config.INJURIES_FILE = os.path.join(tmp, "injuries.json")
config.SCENARIOS_FILE = os.path.join(tmp, "scenarios.json")
config.COMPUTED_FILE = os.path.join(tmp, "computed.json")
import app as A
A.RAW = json.load(open(sys.argv[1]))
t = time.time(); A.recompute(save=True); print("recompute", round(time.time() - t, 1), "s")
c = A.app.test_client()

def get(u, **kw):
    r = c.get(u, **kw); assert r.status_code == 200, (u, r.status_code, r.data[:300]); return r.get_json()
def post(u, body):
    r = c.post(u, json=body); assert r.status_code == 200, (u, r.status_code, r.data[:300]); return r.get_json()

meta = get("/api/meta"); print("meta mode", meta.get("mode") or meta)
rk = get("/api/rankings")["rankings"]
print("teams", len(rk))
for r in rk[:5]:
    print(f"  #{r['ranks']['current']['overall']:>3} {r['school']}  power {r['ratings']['power']['overall']:+.1f}  "
          f"current {r['ratings']['current']['overall']:+.1f}  pred {r['ratings']['predictive']['overall']:+.1f}  "
          f"off {r['ratings']['current']['offense']:+.1f} def {r['ratings']['current']['defense']:+.1f} "
          f"st {r['ratings']['current']['special']:+.1f}  {r['record']} proj {r['proj_record']} prior {r['prior_share']}")
top = rk[0]["school"]
team = get(f"/api/team/{top}")
print("team players", len(team["players"]), "top:", [(p["position"], p["value"], p["depth_rank"], p["snap_share"]) for p in team["players"][:4]])
print("power breakdown", team["power_breakdown"])
done = [g for g in team["schedule"] if g["completed"]]
todo = [g for g in team["schedule"] if not g["completed"]]
if done:
    gd = get(f"/api/game/{done[0]['id']}"); print("played game credit:", json.dumps(gd["credit"])[:260])
todo_fbs = [g for g in todo if g["opponent"].startswith("FBS")] if todo else []
if todo_fbs:
    gu = get(f"/api/game/{todo_fbs[0]['id']}"); print("upcoming game:", gu["prediction"]["spread"], gu["prediction"]["proj_home"], "-", gu["prediction"]["proj_away"], gu["impact"]["label"])
print("upcoming weeks", list(get("/api/upcoming")["weeks"])[:5])
cf = get("/api/conferences"); print("conferences", len(cf["conferences"]), [(c["conference"], c["avg"], c["cfp_bids"]) for c in cf["conferences"][:3]])
b = get("/api/bracket")["bracket"]; print("bracket champ", b["champion"], "seeds", [s["school"] for s in b["seeds"][:4]])
p = get(f"/api/predict?home={rk[0]['school']}&away={rk[30]['school']}&basis=power"); print("predict", p["prediction"]["spread"], p["prediction"]["win_prob_home"])
players = get("/api/players"); print("players", len(players), "top5", [(x["position"], x["team"], x["value"], x["grade"]) for x in players[:5]])
prof = get(f"/api/player/{players[0]['id']}"); print("profile:", prof["summary"]); print("  seasons:", [(s['year'], s['z'], s['weight'], s['sos']) for s in prof['seasons']])
t = time.time(); mc = post("/api/simulate", {"n": 2000}); print("MC 2000 sims", round(time.time() - t, 1), "s; top playoff%:",
      sorted(((v["playoff_pct"], s) for s, v in mc["teams"].items()), reverse=True)[:4])
# What-if: flip the top team's next (or last) game into a 40-point loss.
g = (todo or done)[0]; home_is_top = g["home_away"] == "vs"
ov = {str(g["id"]): {"homePoints": 0 if home_is_top else 40, "awayPoints": 40 if home_is_top else 0}}
w = post("/api/world", {"avail": "avail", "overrides": ov})
row = next(r for r in w["rankings"] if r["school"] == top)
print("what-if: top team current", rk[0]["ratings"]["current"]["overall"], "->", row["ratings"]["current"]["overall"], "rank", row["ranks"]["current"]["overall"])
# Injury: knock out the top team's QB.
qb = next(x for x in team["players"] if x["group"] == "QB")
inj = post(f"/api/player/{qb['id']}/injury", {"status": "out"})
print("QB out: team current", rk[0]["ratings"]["current"]["overall"], "->", inj["team_rating"], "rank", inj["team_rank"])
team2 = get(f"/api/team/{top}")
print("  new QB depth:", [(x["name"], x["status"], x["depth_rank"], x["snap_share"]) for x in team2["players"] if x["group"] == "QB"])
post(f"/api/player/{qb['id']}/injury", {"status": "active"})
full = get("/api/rankings?avail=full")
print("full-strength ok", len(full["rankings"]))
json.load(open(config.COMPUTED_FILE)); print("computed.json serializes OK")
