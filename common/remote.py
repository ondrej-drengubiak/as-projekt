"""HTTP klienti pre volania medzi službami (a z monolitu na vyčlenené služby)."""
import os, httpx
from .errors import NotFound, OutOfStock, PaymentDeclined, Unavailable

_c = httpx.Client(timeout=5.0, limits=httpx.Limits(max_connections=200, max_keepalive_connections=100))

def _req(method, url, **kw):
    try:
        return _c.request(method, url, **kw)
    except httpx.HTTPError as e:
        raise Unavailable(f"upstream unavailable: {url}") from e

def _detail(r, what):
    try:
        return r.json().get("detail", what)
    except Exception:
        return what

def _json(r, what):
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 404: raise NotFound(_detail(r, what))
    if r.status_code == 409: raise OutOfStock(_detail(r, what))
    if r.status_code == 402: raise PaymentDeclined(_detail(r, what))
    raise Unavailable(f"{what}: HTTP {r.status_code}")

def _opt(r, what):
    return None if r.status_code == 404 else _json(r, what)

def catalog_get(pid, with_stock=True):
    r = _req("GET", f"{os.environ['CATALOG_URL']}/products/{pid}", params={"with_stock": str(with_stock).lower()})
    return _opt(r, "product")

def catalog_list(limit=1000):
    return _json(_req("GET", f"{os.environ['CATALOG_URL']}/products", params={"limit": limit}), "products")

def inventory_get(pid):
    return _opt(_req("GET", f"{os.environ['INVENTORY_URL']}/inventory/{pid}"), "stock")

def inventory_op(op, pid, qty):
    return _json(_req("POST", f"{os.environ['INVENTORY_URL']}/inventory/{pid}/{op}", json={"qty": qty}), f"inventory {op}")

def payment_charge(order_id, customer_id, amount, simulate_failure=False):
    return _json(_req("POST", f"{os.environ['BILLING_URL']}/payments",
                      json={"order_id": order_id, "customer_id": customer_id, "amount": amount,
                            "simulate_failure": simulate_failure}), "payment")

def payment_open_account(customer_id, credit_limit):
    return _json(_req("POST", f"{os.environ['BILLING_URL']}/accounts",
                      json={"customer_id": customer_id, "credit_limit": credit_limit}), "account")

def customer_get(cid):
    return _opt(_req("GET", f"{os.environ['MONOLITH_URL']}/customers/{cid}"), "customer")

def notify(order_id, customer_id, message):
    try:
        _req("POST", f"{os.environ['MONOLITH_URL']}/notifications",
             json={"order_id": order_id, "customer_id": customer_id, "message": message})
    except Unavailable:
        pass  # best effort
