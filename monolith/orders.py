import os, datetime
from common.errors import NotFound
from . import db, customers, catalog, inventory, payments, notifications

def _atomic():
    """Kým sú všetci účastníci lokálni, celé zadanie objednávky beží v jednej ACID transakcii."""
    return not (inventory.is_remote() or payments.is_remote())

def _compensate():
    return os.environ.get("COMPENSATE", "1") != "0"

def get(oid):
    c = db.conn()
    o = c.execute("SELECT id,customer_id,status,total FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        return None
    items = c.execute("SELECT product_id,qty,unit_price FROM order_items WHERE order_id=? ORDER BY id", (oid,)).fetchall()
    d = dict(o)
    d["items"] = [dict(i) for i in items]
    return d

def place(customer_id, items, simulate_failure=False):
    if not customers.get(customer_id):
        raise NotFound("customer")
    lines = []
    for it in items:
        p = catalog.get_product(it["product_id"], with_stock=False)
        if not p:
            raise NotFound(f"product {it['product_id']}")
        lines.append((p["id"], it["qty"], p["price"]))
    total = round(sum(q * pr for _, q, pr in lines), 2)
    c = db.conn()
    atomic = _atomic()
    if atomic:
        c.execute("BEGIN IMMEDIATE")
    reserved, oid = [], None
    try:
        now = datetime.datetime.utcnow().isoformat()
        oid = c.execute("INSERT INTO orders(customer_id,status,total,created_at) VALUES(?,?,?,?)",
                        (customer_id, "PENDING", total, now)).lastrowid
        for pid, q, pr in lines:
            inventory.reserve(pid, q)
            reserved.append((pid, q))
            c.execute("INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(?,?,?,?)", (oid, pid, q, pr))
        payments.charge(oid, customer_id, total, simulate_failure)
        for pid, q in reserved:
            inventory.commit(pid, q)
        c.execute("UPDATE orders SET status='PAID' WHERE id=?", (oid,))
        if atomic:
            c.execute("COMMIT")
    except Exception:
        if atomic:
            c.execute("ROLLBACK")
        elif _compensate():
            for pid, q in reserved:
                try:
                    inventory.release(pid, q)
                except Exception:
                    pass
            if oid:
                c.execute("UPDATE orders SET status='CANCELLED' WHERE id=?", (oid,))
        raise
    notifications.send(oid, customer_id, f"order {oid} paid, total {total}")
    return get(oid)
