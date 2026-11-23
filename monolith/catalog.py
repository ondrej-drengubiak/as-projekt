import os
from common import remote
from . import db, inventory

def is_remote():
    return os.environ.get("CATALOG_MODE", "local") == "remote"

def get_product(pid, with_stock=True):
    if is_remote():
        return remote.catalog_get(pid, with_stock)
    r = db.conn().execute("SELECT id,sku,name,price,category FROM products WHERE id=?", (pid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    if with_stock:
        d["in_stock"] = inventory.available(pid) > 0
    return d

def list_products(limit=20):
    if is_remote():
        return remote.catalog_list(limit)
    rows = db.conn().execute("SELECT id,sku,name,price,category FROM products ORDER BY id LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
