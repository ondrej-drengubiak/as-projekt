from . import db, payments

def create(name, email, credit_limit):
    cur = db.conn().execute(
        "INSERT INTO customers(name,email,credit_limit,credit_used) VALUES(?,?,?,0)",
        (name, email, credit_limit))
    cid = cur.lastrowid
    payments.open_account(cid, credit_limit)
    return get(cid)

def get(cid):
    r = db.conn().execute("SELECT id,name,email FROM customers WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None

def credit_left(cid):
    r = db.conn().execute("SELECT credit_limit-credit_used AS remaining FROM customers WHERE id=?", (cid,)).fetchone()
    return r["remaining"] if r else 0.0
