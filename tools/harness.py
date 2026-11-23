"""Spúšťanie etáp migrácie: S0 monolit, S1 +catalog, S2 +inventory, S3 +billing, S4 +ordering."""
import os, sys, json, shutil, subprocess, time, glob
import httpx
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common import db as cdb, schema
from tools import seed

P = dict(gateway=8000, monolith=8001, catalog=8101, inventory=8102, billing=8103, ordering=8104)
URL = {k: f"http://127.0.0.1:{v}" for k, v in P.items()}
STAGE_NAMES = {0: "S0 monolit", 1: "S1 +Catalog", 2: "S2 +Inventory", 3: "S3 +Billing", 4: "S4 +Ordering"}

def stage_services(stage):
    s = ["monolith"]
    for i, name in enumerate(["catalog", "inventory", "billing", "ordering"], 1):
        if stage >= i:
            s.append(name)
    return s

def routes(stage):
    r = {}
    if stage >= 1: r["/products"] = URL["catalog"]
    if stage >= 2: r["/inventory"] = URL["inventory"]
    if stage >= 4: r["/orders"] = URL["ordering"]; r["/reports"] = URL["ordering"]
    return r

def service_env(stage, name):
    e = {"MONOLITH_URL": URL["monolith"], "CATALOG_URL": URL["catalog"], "BILLING_URL": URL["billing"]}
    if name == "monolith":
        if stage >= 1: e["CATALOG_MODE"] = "remote"
        if stage >= 2: e["INVENTORY_MODE"] = "remote"; e["INVENTORY_URL"] = URL["inventory"]
        if stage >= 3: e["PAYMENT_MODE"] = "remote"
    if name == "catalog":
        e["INVENTORY_URL"] = URL["inventory"] if stage >= 2 else URL["monolith"]
    if name == "ordering":
        e["INVENTORY_URL"] = URL["inventory"]
    return e

def migrate_data(stage, d):
    """Jednorazový prenos dát do databáz vyčlenených služieb (cutover)."""
    src = cdb.connect(os.path.join(d, "monolith.db"))
    def copy(dbname, ddl, table, cols):
        t = cdb.connect(os.path.join(d, dbname)); t.executescript(ddl)
        rows = src.execute(f"SELECT {cols} FROM {table}").fetchall()
        t.executemany(f"INSERT INTO {table.split(' ')[0]} ({cols}) VALUES ({','.join('?'*len(cols.split(',')))})", [tuple(r) for r in rows])
        t.close()
    if stage >= 1: copy("catalog.db", schema.CATALOG, "products", "id,sku,name,price,category")
    if stage >= 2: copy("inventory.db", schema.INVENTORY, "stock", "product_id,quantity,reserved")
    if stage >= 3:
        t = cdb.connect(os.path.join(d, "billing.db")); t.executescript(schema.BILLING)
        for r in src.execute("SELECT id,credit_limit,credit_used FROM customers"):
            t.execute("INSERT INTO accounts VALUES(?,?,?)", tuple(r))
        for r in src.execute("SELECT id,order_id,customer_id,amount,status FROM payments"):
            t.execute("INSERT INTO payments VALUES(?,?,?,?,?)", tuple(r))
        t.close()
    if stage >= 4:
        copy("ordering.db", schema.ORDERING, "orders", "id,customer_id,status,total,created_at")
        t = cdb.connect(os.path.join(d, "ordering.db"))
        for r in src.execute("SELECT id,order_id,product_id,qty,unit_price FROM order_items"):
            t.execute("INSERT INTO order_items VALUES(?,?,?,?,?)", tuple(r))
        t.close()
    src.close()

class Stage:
    def __init__(self, stage, extra_env=None, workdir="data/run", products=100, customers=200, stock=5000):
        self.stage, self.extra, self.d = stage, extra_env or {}, os.path.join(ROOT, workdir)
        self.params = dict(products=products, customers=customers, stock=stock)
        self.procs = []
    def __enter__(self):
        shutil.rmtree(self.d, ignore_errors=True); os.makedirs(self.d)
        seed.make(os.path.join(self.d, "monolith.db"), **self.params)
        migrate_data(self.stage, self.d)
        base = dict(os.environ, PYTHONPATH=ROOT, DATA_DIR=self.d, **self.extra)
        mods = {"monolith": "monolith.app:app", "catalog": "services.catalog.app:app", "inventory": "services.inventory.app:app",
                "billing": "services.billing.app:app", "ordering": "services.ordering.app:app"}
        for name in stage_services(self.stage):
            env = dict(base, **service_env(self.stage, name))
            self._spawn(mods[name], P[name], env)
        env = dict(base, MONOLITH_URL=URL["monolith"], ROUTES=json.dumps(routes(self.stage)))
        self._spawn("gateway.app:app", P["gateway"], env)
        for name in stage_services(self.stage) + ["gateway"]:
            self._wait(URL[name])
        return self
    def _spawn(self, app, port, env):
        self.procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "error"],
                                           cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    def _wait(self, url, tries=100):
        for _ in range(tries):
            try:
                if httpx.get(url + ("/__routes" if url.endswith("8000") else "/health"), timeout=1).status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("service did not start: " + url)
    def __exit__(self, *a):
        for p in self.procs: p.terminate()
        for p in self.procs:
            try: p.wait(5)
            except Exception: p.kill()
        time.sleep(0.5)
    def db(self, name):
        return cdb.connect(os.path.join(self.d, name))
GW = URL["gateway"]
