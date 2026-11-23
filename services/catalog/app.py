"""Catalog služba (Bounded Context: Katalóg). Vlastná DB: catalog.db."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from common import remote
from common.db import thread_conn
from common.errors import DomainError

app = FastAPI(title="catalog-service")

@app.exception_handler(DomainError)
def _err(_: Request, e: DomainError):
    return JSONResponse(status_code=e.status, content={"detail": str(e)})

def db():
    return thread_conn("catalog.db")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/products")
def list_products(limit: int = 20):
    rows = db().execute("SELECT id,sku,name,price,category FROM products ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/products/{pid}")
def get_product(pid: int, with_stock: bool = True):
    r = db().execute("SELECT id,sku,name,price,category FROM products WHERE id=?", (pid,)).fetchone()
    if not r:
        raise HTTPException(404, "product")
    d = dict(r)
    if with_stock:
        g = remote.inventory_get(pid)          # INVENTORY_URL: monolit (S1) alebo inventory-service (S2+)
        d["in_stock"] = bool(g and g["available"] > 0)
    return d
