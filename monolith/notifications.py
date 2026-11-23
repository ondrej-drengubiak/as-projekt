from . import db, customers

def send(order_id, customer_id, message):
    cust = customers.get(customer_id)
    to = cust["email"] if cust else "unknown"
    db.conn().execute("INSERT INTO notifications(order_id,customer_id,message) VALUES(?,?,?)",
                      (order_id, customer_id, f"to={to}: {message}"))

def for_order(order_id):
    rows = db.conn().execute("SELECT id,order_id,customer_id,message FROM notifications WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
    return [dict(r) for r in rows]
