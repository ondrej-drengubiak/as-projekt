"""Charakterizačné (kontraktové) testy: rovnaký scenár proti každej etape migrácie cez gateway.
Overujú (a) očakávané stavové kódy/telá a (b) zhodu celého prepisu komunikácie s etapou S0 (golden master)."""
import os, sys, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx
from tools.harness import Stage, GW, STAGE_NAMES

def scenario(c):
    out = []
    def step(name, method, path, expect, check=None, **kw):
        r = c.request(method, path, **kw)
        try: body = r.json()
        except Exception: body = r.text
        ok = r.status_code == expect and (check(body) if check else True)
        out.append({"name": name, "status": r.status_code, "expect": expect, "ok": bool(ok), "body": body})
        return body
    cu = step("create customer", "POST", "/customers", 201, lambda b: b["name"] == "Test" and "id" in b,
              json={"name": "Test", "email": "t@x.sk", "credit_limit": 500})
    poor = step("create low-credit customer", "POST", "/customers", 201, json={"name": "Poor", "email": "p@x.sk", "credit_limit": 10})
    step("get customer", "GET", f"/customers/{cu['id']}", 200, lambda b: b["email"] == "t@x.sk")
    step("unknown customer 404", "GET", "/customers/999999", 404)
    step("list products", "GET", "/products?limit=5", 200, lambda b: len(b) == 5 and b[0]["id"] == 1)
    step("get product with stock flag", "GET", "/products/3", 200, lambda b: b["in_stock"] is True and b["price"] > 0)
    step("unknown product 404", "GET", "/products/999999", 404)
    step("get inventory", "GET", "/inventory/3", 200, lambda b: b["available"] == b["quantity"] - b["reserved"])
    step("adjust inventory", "POST", "/inventory/3/adjust", 200, lambda b: b["quantity"] == 5010, json={"delta": 10})
    step("adjust unknown product", "POST", "/inventory/999999/adjust", 404, json={"delta": 1})
    o = step("place order OK", "POST", "/orders", 201, lambda b: b["status"] == "PAID" and len(b["items"]) == 2 and b["total"] > 0,
             json={"customer_id": cu["id"], "items": [{"product_id": 3, "qty": 2}, {"product_id": 4, "qty": 1}]})
    step("get order", "GET", f"/orders/{o['id']}", 200, lambda b: b["id"] == o["id"] and b["status"] == "PAID")
    step("stock committed", "GET", "/inventory/3", 200, lambda b: b["quantity"] == 5008 and b["reserved"] == 0)
    step("notification sent", "GET", f"/notifications?order_id={o['id']}", 200, lambda b: len(b) == 1)
    step("order unknown customer 404", "POST", "/orders", 404, json={"customer_id": 999999, "items": [{"product_id": 3, "qty": 1}]})
    step("order unknown product 404", "POST", "/orders", 404, json={"customer_id": cu["id"], "items": [{"product_id": 999999, "qty": 1}]})
    step("order out of stock 409", "POST", "/orders", 409, json={"customer_id": cu["id"], "items": [{"product_id": 5, "qty": 10**7}]})
    step("order credit exceeded 402", "POST", "/orders", 402, json={"customer_id": poor["id"], "items": [{"product_id": 6, "qty": 5}]})
    step("order simulated decline 402", "POST", "/orders", 402,
         json={"customer_id": cu["id"], "items": [{"product_id": 7, "qty": 1}], "simulate_payment_failure": True})
    step("stock released after decline", "GET", "/inventory/7", 200, lambda b: b["reserved"] == 0 and b["quantity"] == 5000)
    step("partial reservation released", "POST", "/orders", 409,
         json={"customer_id": cu["id"], "items": [{"product_id": 8, "qty": 1}, {"product_id": 9, "qty": 10**7}]})
    step("no leak after partial", "GET", "/inventory/8", 200, lambda b: b["reserved"] == 0)
    step("invalid payload 422", "POST", "/orders", 422, json={"customer_id": cu["id"], "items": []})
    step("invalid qty 422", "POST", "/orders", 422, json={"customer_id": cu["id"], "items": [{"product_id": 3, "qty": 0}]})
    step("sales report", "GET", "/reports/sales", 200, lambda b: b["orders_paid"] == 1 and abs(b["revenue"] - o["total"]) < 0.01
         and abs(sum(b["revenue_by_category"].values()) - b["revenue"]) < 0.01)
    return out

def run_stage(stage):
    with Stage(stage) as s:
        with httpx.Client(base_url=GW, timeout=10) as c:
            res = scenario(c)
    return res

if __name__ == "__main__":
    stages = [int(x) for x in sys.argv[1:]] or [0, 1, 2, 3, 4]
    summary, transcripts = [], {}
    for st in stages:
        res = run_stage(st)
        passed = sum(r["ok"] for r in res)
        t = json.dumps([[r["name"], r["status"], r["body"]] for r in res], sort_keys=True)
        transcripts[st] = hashlib.sha256(t.encode()).hexdigest()[:12]
        summary.append({"stage": STAGE_NAMES[st], "tests": len(res), "passed": passed, "transcript_sha": transcripts[st],
                        "failed": [r["name"] for r in res if not r["ok"]]})
        print(summary[-1])
    same = len(set(transcripts.values())) == 1
    os.makedirs("results", exist_ok=True)
    json.dump({"stages": summary, "all_transcripts_identical": same}, open("results/contract_tests.json", "w"), indent=1, ensure_ascii=False)
    print("identical transcripts:", same)
