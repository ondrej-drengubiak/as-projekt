"""Inventory služba (Bounded Context: Sklad). Vlastná DB: inventory.db."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from common.db import thread_conn

app = FastAPI(title="inventory-service")

def db():
    return thread_conn("inventory.db")

class Qty(BaseModel):
    qty: int = Field(gt=0)

class AdjustIn(BaseModel):
    delta: int

def _get(pid):
    r = db().execute("SELECT product_id,quantity,reserved FROM stock WHERE product_id=?", (pid,)).fetchone()
    if not r:
        return None
    return {"product_id": r["product_id"], "quantity": r["quantity"], "reserved": r["reserved"],
            "available": r["quantity"] - r["reserved"]}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/inventory/{pid}")
def get_inventory(pid: int):
    g = _get(pid)
    if not g:
        raise HTTPException(404, "product")
    return g

@app.post("/inventory/{pid}/adjust")
def adjust(pid: int, b: AdjustIn):
    if not _get(pid):
        raise HTTPException(404, "product")
    cur = db().execute("UPDATE stock SET quantity=quantity+? WHERE product_id=? AND quantity+?>=reserved", (b.delta, pid, b.delta))
    if cur.rowcount == 0:
        raise HTTPException(409, "adjustment would drop below reserved")
    return _get(pid)

@app.post("/inventory/{pid}/reserve")
def reserve(pid: int, b: Qty):
    if not _get(pid):
        raise HTTPException(404, "product")
    cur = db().execute("UPDATE stock SET reserved=reserved+? WHERE product_id=? AND quantity-reserved>=?", (b.qty, pid, b.qty))
    if cur.rowcount == 0:
        raise HTTPException(409, f"product {pid}")
    return {"ok": True}

@app.post("/inventory/{pid}/commit")
def commit(pid: int, b: Qty):
    db().execute("UPDATE stock SET quantity=quantity-?, reserved=reserved-? WHERE product_id=?", (b.qty, b.qty, pid))
    return {"ok": True}

@app.post("/inventory/{pid}/release")
def release(pid: int, b: Qty):
    db().execute("UPDATE stock SET reserved=reserved-? WHERE product_id=?", (b.qty, pid))
    return {"ok": True}
