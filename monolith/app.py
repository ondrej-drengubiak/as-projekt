"""Legacy monolit (HTTP vrstva)."""
from typing import List
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from common.errors import DomainError
from . import customers, catalog, inventory, orders, notifications, reporting

app = FastAPI(title="Legacy monolith")

@app.exception_handler(DomainError)
def _err(_: Request, e: DomainError):
    return JSONResponse(status_code=e.status, content={"detail": str(e)})

class CustomerIn(BaseModel):
    name: str
    email: str
    credit_limit: float = Field(ge=0)

class Item(BaseModel):
    product_id: int
    qty: int = Field(gt=0)

class OrderIn(BaseModel):
    customer_id: int
    items: List[Item] = Field(min_length=1)
    simulate_payment_failure: bool = False

class AdjustIn(BaseModel):
    delta: int

class NotificationIn(BaseModel):
    order_id: int
    customer_id: int
    message: str

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/customers", status_code=201)
def create_customer(b: CustomerIn):
    return customers.create(b.name, b.email, b.credit_limit)

@app.get("/customers/{cid}")
def get_customer(cid: int):
    c = customers.get(cid)
    if not c:
        raise HTTPException(404, "customer")
    return c

@app.get("/products")
def list_products(limit: int = 20):
    return catalog.list_products(limit)

@app.get("/products/{pid}")
def get_product(pid: int, with_stock: bool = True):
    p = catalog.get_product(pid, with_stock)
    if not p:
        raise HTTPException(404, "product")
    return p

@app.get("/inventory/{pid}")
def get_inventory(pid: int):
    g = inventory.get(pid)
    if not g:
        raise HTTPException(404, "product")
    return g

@app.post("/inventory/{pid}/adjust")
def adjust_inventory(pid: int, b: AdjustIn):
    return inventory.adjust(pid, b.delta)

@app.post("/orders", status_code=201)
def place_order(b: OrderIn):
    return orders.place(b.customer_id, [i.model_dump() for i in b.items], b.simulate_payment_failure)

@app.get("/orders/{oid}")
def get_order(oid: int):
    o = orders.get(oid)
    if not o:
        raise HTTPException(404, "order")
    return o

@app.get("/reports/sales")
def sales():
    return reporting.sales_report()

@app.post("/notifications", status_code=201)
def post_notification(b: NotificationIn):
    notifications.send(b.order_id, b.customer_id, b.message)
    return {"ok": True}

@app.get("/notifications")
def get_notifications(order_id: int):
    return notifications.for_order(order_id)
