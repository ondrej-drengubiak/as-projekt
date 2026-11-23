"""Vytvorí seed databázu monolitu (100 produktov, 200 zákazníkov)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import db as cdb, schema

CATS = ["books", "games", "garden", "kitchen", "sport"]

def make(path, products=100, customers=200, stock=5000):
    if os.path.exists(path):
        os.remove(path)
    c = cdb.connect(path)
    c.executescript(schema.MONOLITH)
    for i in range(1, products + 1):
        c.execute("INSERT INTO products VALUES(?,?,?,?,?)",
                  (i, f"SKU-{i:04d}", f"Product {i}", round(5 + (i * 7) % 95 + 0.99, 2), CATS[i % 5]))
        c.execute("INSERT INTO stock VALUES(?,?,0)", (i, stock))
    for i in range(1, customers + 1):
        c.execute("INSERT INTO customers(name,email,credit_limit,credit_used) VALUES(?,?,?,0)",
                  (f"Customer {i}", f"c{i}@example.com", 1e9))
    c.close()

if __name__ == "__main__":
    os.makedirs("data/seed", exist_ok=True)
    make("data/seed/monolith.db")
    print("seed ok")
