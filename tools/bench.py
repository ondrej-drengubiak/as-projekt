"""Záťažový test: čítanie produktu (GET /products/{id}) a zadanie objednávky (POST /orders) v každej etape."""
import os, sys, json, random, time, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from concurrent.futures import ThreadPoolExecutor
import httpx
from tools.harness import Stage, GW, STAGE_NAMES

CONC, N_READ, N_WRITE, REPEATS = 8, 1500, 500, 3

def pct(xs, q):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(q * len(xs)))]

def run(client, reqs):
    lat, errs = [], 0
    def one(rq):
        m, path, body = rq
        t = time.perf_counter()
        r = client.request(m, path, json=body)
        return (time.perf_counter() - t) * 1000, r.status_code
    t0 = time.perf_counter()
    with ThreadPoolExecutor(CONC) as ex:
        for ms, sc in ex.map(one, reqs):
            lat.append(ms); errs += sc >= 400
    dur = time.perf_counter() - t0
    return {"n": len(reqs), "rps": len(reqs) / dur, "p50": pct(lat, .5), "p95": pct(lat, .95), "mean": statistics.mean(lat), "errors": errs}

def workloads(seed):
    rnd = random.Random(seed)
    reads = [("GET", f"/products/{rnd.randint(1, 100)}", None) for _ in range(N_READ)]
    writes = []
    for _ in range(N_WRITE):
        items = [{"product_id": rnd.randint(1, 100), "qty": rnd.randint(1, 3)} for _ in range(rnd.randint(1, 3))]
        writes.append(("POST", "/orders", {"customer_id": rnd.randint(1, 200), "items": items}))
    return reads, writes

if __name__ == "__main__":
    out = {}
    for st in [0, 1, 2, 3, 4]:
        with Stage(st) as s, httpx.Client(base_url=GW, timeout=20, limits=httpx.Limits(max_connections=50)) as c:
            run(c, workloads(0)[0][:200]); run(c, workloads(0)[1][:40])      # warm-up
            res = {"read": [], "write": []}
            for rep in range(REPEATS):
                rd, wr = workloads(100 + rep)
                res["read"].append(run(c, rd)); res["write"].append(run(c, wr))
        out[STAGE_NAMES[st]] = res
        print(STAGE_NAMES[st], {k: round(statistics.median(x["p50"] for x in v), 1) for k, v in res.items()}, flush=True)
    json.dump(out, open("results/bench.json", "w"), indent=1)
    print("done")
