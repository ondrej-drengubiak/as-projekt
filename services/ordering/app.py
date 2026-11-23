"""Ordering služba (Bounded Context: Objednávky). Orchestruje sagu zadania objednávky.
Vlastná DB: ordering.db. Zákazníka overuje cez ACL na monolit, ostatné cez služby."""
import os, datetime
from typing import List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from common import remote
from common.db import thread_conn
from common.errors import DomainError, NotFound

app = FastAPI(title="ordering-service")

@app.exception_handler(DomainError)
def _err(_: Request, e: DomainError):
    return JSONResponse(status_code=e.status, content={"detail": str(e)})

def db():
    return thread_conn("ordering.db")

class Item(BaseModel):
    product_id: int
    qty: int = Field(gt=0)

class OrderIn(BaseModel):
    customer_id: int
    items: List[Item] = Field(min_length=1)
    simulate_payment_failure: bool = False

def _get(oid):
    c = db()
    o = c.execute("SELECT id,customer_id,status,total FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        return None
    items = c.execute("SELECT product_id,qty,unit_price FROM order_items WHERE order_id=? ORDER BY id", (oid,)).fetchall()
    d = dict(o)
    d["items"] = [dict(i) for i in items]
    return d

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/orders", status_code=201)
def place_order(b: OrderIn):
    compensate = os.environ.get("COMPENSATE", "1") != "0"
    if not remote.customer_get(b.customer_id):                      # ACL -> monolit
        raise NotFound("customer")
    lines = []
    for it in b.items:
        p = remote.catalog_get(it.product_id, with_stock=False)    # -> catalog-service
        if not p:
            raise NotFound(f"product {it.product_id}")
        lines.append((p["id"], it.qty, p["price"]))
    total = round(sum(q * pr for _, q, pr in lines), 2)
    c = db()
    oid = c.execute("INSERT INTO orders(customer_id,status,total,created_at) VALUES(?,?,?,?)",
                    (b.customer_id, "PENDING", total, datetime.datetime.utcnow().isoformat())).lastrowid
    reserved = []
    try:
        for pid, q, pr in lines:
            remote.inventory_op("reserve", pid, q)                  # krok 1 sagy
            reserved.append((pid, q))
            c.execute("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(?,?,?,?)", (oid, pid, q, pr))
        remote.payment_charge(oid, b.customer_id, total, b.simulate_payment_failure)   # krok 2
        for pid, q in reserved:
            remote.inventory_op("commit", pid, q)                   # krok 3
        c.execute("UPDATE orders SET status='PAID' WHERE id=?", (oid,))
    except Exception:
        if compensate:                                              # kompenzačné akcie
            for pid, q in reserved:
                try:
                    remote.inventory_op("release", pid, q)
                except Exception:
                    pass
            c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (oid,))
        raise
    remote.notify(oid, b.customer_id, f"order {oid} paid, total {total}")
    return _get(oid)

@app.get("/orders/{oid}")
def get_order(oid: int):
    o = _get(oid)
    if not o:
        raise HTTPException(404, "order")
    return o

@app.get("/reports/sales")
def sales():
    c = db()
    n, rev = c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE status='PAID'").fetchone()
    per_product = c.execute(
        "SELECT oi.product_id AS pid, SUM(oi.qty*oi.unit_price) AS rev FROM order_items oi "
        "JOIN orders o ON o.id=oi.order_id WHERE o.status='PAID' GROUP BY oi.product_id").fetchall()
    cat_of = {p["id"]: p["category"] for p in remote.catalog_list(100000)}   # API composition
    by_cat = {}
    for r in per_product:
        k = cat_of.get(r["pid"])
        by_cat[k] = by_cat.get(k, 0.0) + r["rev"]
    return {"orders_paid": n, "revenue": round(rev, 2),
            "revenue_by_category": {k: round(v, 2) for k, v in sorted(by_cat.items())}}
