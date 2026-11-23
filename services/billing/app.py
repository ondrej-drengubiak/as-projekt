"""Billing služba (Bounded Context: Fakturácia/Úver). Vlastná DB: billing.db."""
import os, random
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from common.db import thread_conn

app = FastAPI(title="billing-service")

def db():
    return thread_conn("billing.db")

class AccountIn(BaseModel):
    customer_id: int
    credit_limit: float = Field(ge=0)

class PaymentIn(BaseModel):
    order_id: int
    customer_id: int
    amount: float
    simulate_failure: bool = False

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/accounts", status_code=201)
def open_account(b: AccountIn):
    db().execute("INSERT OR REPLACE INTO accounts(customer_id,credit_limit,credit_used) VALUES(?,?,0)", (b.customer_id, b.credit_limit))
    return {"ok": True}

@app.post("/payments", status_code=201)
def charge(b: PaymentIn):
    if random.random() < float(os.environ.get("FAULT_RATE_PAYMENT", "0")):
        raise HTTPException(503, "payment gateway unavailable")
    if b.simulate_failure:
        raise HTTPException(402, "simulated decline")
    c = db()
    acc = c.execute("SELECT credit_limit-credit_used AS remaining FROM accounts WHERE customer_id=?", (b.customer_id,)).fetchone()
    if not acc or b.amount > acc["remaining"]:
        raise HTTPException(402, "credit limit exceeded")
    c.execute("UPDATE accounts SET credit_used=credit_used+? WHERE customer_id=?", (b.amount, b.customer_id))
    cur = c.execute("INSERT INTO payments(order_id,customer_id,amount,status) VALUES(?,?,?,'AUTHORIZED')",
                    (b.order_id, b.customer_id, b.amount))
    return {"id": cur.lastrowid, "status": "AUTHORIZED"}
