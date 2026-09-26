"""Score a model's Power/Current ratings against fixture truth.
usage: python evaluate.py <code_dir> <fixture.json>"""
import json, math, sys, time, os
code, fx = sys.argv[1], sys.argv[2]
sys.path.insert(0, code)
os.environ.setdefault("CFBD_API_KEY", "x")
import config
config.INJURIES_FILE = "/nonexistent.json"
import engine

raw = json.load(open(fx))
truth = json.load(open(fx.replace(".json", "_truth.json")))
Y = raw["meta"]["year"]

def pearson(a, b):
    n = len(a); ma, mb = sum(a)/n, sum(b)/n
    sa = math.sqrt(sum((x-ma)**2 for x in a)); sb = math.sqrt(sum((y-mb)**2 for y in b))
    return sum((x-ma)*(y-mb) for x, y in zip(a, b)) / (sa*sb)

def spearman(a, b):
    ra = {i: r for r, i in enumerate(sorted(range(len(a)), key=lambda i: a[i]))}
    rb = {i: r for r, i in enumerate(sorted(range(len(b)), key=lambda i: b[i]))}
    return pearson([ra[i] for i in range(len(a))], [rb[i] for i in range(len(b))])

t0 = time.time()
prep = engine.prepare(raw, injuries=[])
t1 = time.time()
w = engine.build_world(raw, prep, "avail")
t2 = time.time()
rows = w["rankings"]
tv = [truth[f"{r['school']}|{Y}"] for r in rows]
out = {"prep_s": round(t1-t0, 1), "world_s": round(t2-t1, 1)}
for view in ("power", "current", "predictive"):
    key = "strength"
    sv = [r[key][view] for r in rows]
    out[view] = {"pearson": round(pearson(sv, tv), 3), "spearman": round(spearman(sv, tv), 3)}
# Top-25 overlap with true top 25 (current view)
true_top = set(sorted(rows, key=lambda r: truth[f"{r['school']}|{Y}"], reverse=True)[:25][i]["school"] for i in range(25))
cur_top = set(r["school"] for r in sorted(rows, key=lambda r: r["strength"]["current"], reverse=True)[:25])
out["top25_overlap_current"] = len(true_top & cur_top)
print(json.dumps(out))
