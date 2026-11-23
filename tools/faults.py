"""Experiment zlyhaní: čo sa stane s invariantmi, keď zmizne ACID transakcia a zlyhá platba.
Vstrekujeme (a) biznis zamietnutie platby (402) v 15 % objednávok a (b) nedostupnosť platobnej služby (503) v 25 % volaní."""
import os, sys, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import httpx
from tools.harness import Stage, GW

N, CONC, STOCK, PRODUCTS = 400, 4, 5000, 100

def one_config(stage, compensate):
    env = {"COMPENSATE": "1" if compensate else "0", "FAULT_RATE_PAYMENT": "0.25"}
    rnd = random.Random(7)
    reqs = [{"customer_id": rnd.randint(1, 200),
             "items": [{"product_id": rnd.randint(1, PRODUCTS), "qty": rnd.randint(1, 3)} for _ in range(rnd.randint(1, 3))],
             "simulate_payment_failure": rnd.random() < 0.15} for _ in range(N)]
    with Stage(stage, extra_env=env, stock=STOCK, products=PRODUCTS) as s:
        with httpx.Client(base_url=GW, timeout=20) as c:
            with ThreadPoolExecutor(CONC) as ex:
                codes = Counter(ex.map(lambda b: c.post("/orders", json=b).status_code, reqs))
        inv = s.db("inventory.db") if stage >= 2 else s.db("monolith.db")
        orders_db = s.db("ordering.db") if stage >= 4 else s.db("monolith.db")
        leaked = inv.execute("SELECT COALESCE(SUM(reserved),0) FROM stock").fetchone()[0]
        qty_total = inv.execute("SELECT SUM(quantity) FROM stock").fetchone()[0]
        sold_paid = orders_db.execute("SELECT COALESCE(SUM(oi.qty),0) FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status='PAID'").fetchone()[0]
        status = dict(orders_db.execute("SELECT status, COUNT(*) FROM orders GROUP BY status").fetchall())
    return {"stage": stage, "compensation": compensate, "http": dict(codes), "reserved_leaked_units": leaked,
            "stock_vs_paid_mismatch_units": abs((STOCK * PRODUCTS - qty_total) - sold_paid),
            "orders_by_status": status, "orphan_pending_orders": status.get("PENDING", 0)}

if __name__ == "__main__":
    out = []
    for stage, comp in [(0, True), (2, False), (2, True), (4, False), (4, True)]:
        r = one_config(stage, comp); out.append(r); print(r, flush=True)
    json.dump(out, open("results/faults.json", "w"), indent=1)
