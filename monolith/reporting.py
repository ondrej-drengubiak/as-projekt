from . import db

def sales_report():
    c = db.conn()
    n, rev = c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE status='PAID'").fetchone()
    rows = c.execute(
        "SELECT p.category AS cat, SUM(oi.qty*oi.unit_price) AS rev "
        "FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN products p ON p.id=oi.product_id "
        "WHERE o.status='PAID' GROUP BY p.category ORDER BY p.category").fetchall()
    return {"orders_paid": n, "revenue": round(rev, 2),
            "revenue_by_category": {r["cat"]: round(r["rev"], 2) for r in rows}}
