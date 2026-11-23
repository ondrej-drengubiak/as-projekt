import os
from common import remote
from common.errors import NotFound, OutOfStock
from . import db, catalog

def is_remote():
    return os.environ.get("INVENTORY_MODE", "local") == "remote"

def get(pid):
    if is_remote():
        return remote.inventory_get(pid)
    r = db.conn().execute("SELECT product_id,quantity,reserved FROM stock WHERE product_id=?", (pid,)).fetchone()
    if not r:
        return None
    return {"product_id": r["product_id"], "quantity": r["quantity"], "reserved": r["reserved"],
            "available": r["quantity"] - r["reserved"]}

def available(pid):
    g = get(pid)
    return g["available"] if g else 0

def adjust(pid, delta):
    if not catalog.get_product(pid, with_stock=False):
        raise NotFound("product")
    c = db.conn()
    cur = c.execute("UPDATE stock SET quantity=quantity+? WHERE product_id=? AND quantity+?>=reserved", (delta, pid, delta))
    if cur.rowcount == 0:
        raise OutOfStock("adjustment would drop below reserved")
    return get(pid)

def reserve(pid, qty):
    if is_remote():
        return remote.inventory_op("reserve", pid, qty)
    cur = db.conn().execute("UPDATE stock SET reserved=reserved+? WHERE product_id=? AND quantity-reserved>=?", (qty, pid, qty))
    if cur.rowcount == 0:
        raise OutOfStock(f"product {pid}")

def commit(pid, qty):
    if is_remote():
        return remote.inventory_op("commit", pid, qty)
    db.conn().execute("UPDATE stock SET quantity=quantity-?, reserved=reserved-? WHERE product_id=?", (qty, qty, pid))

def release(pid, qty):
    if is_remote():
        return remote.inventory_op("release", pid, qty)
    db.conn().execute("UPDATE stock SET reserved=reserved-? WHERE product_id=?", (qty, pid))
