import os, random
from common import remote
from common.errors import PaymentDeclined, Unavailable
from . import db, customers

def is_remote():
    return os.environ.get("PAYMENT_MODE", "local") == "remote"

def open_account(customer_id, credit_limit):
    if is_remote():
        remote.payment_open_account(customer_id, credit_limit)

def charge(order_id, customer_id, amount, simulate_failure=False):
    if is_remote():
        return remote.payment_charge(order_id, customer_id, amount, simulate_failure)
    if random.random() < float(os.environ.get("FAULT_RATE_PAYMENT", "0")):
        raise Unavailable("payment gateway unavailable")
    if simulate_failure:
        raise PaymentDeclined("simulated decline")
    if amount > customers.credit_left(customer_id):
        raise PaymentDeclined("credit limit exceeded")
    c = db.conn()
    c.execute("UPDATE customers SET credit_used=credit_used+? WHERE id=?", (amount, customer_id))
    cur = c.execute("INSERT INTO payments(order_id,customer_id,amount,status) VALUES(?,?,?,'AUTHORIZED')",
                    (order_id, customer_id, amount))
    return {"id": cur.lastrowid, "status": "AUTHORIZED"}
