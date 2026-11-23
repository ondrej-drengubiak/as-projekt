"""Statická analýza legacy monolitu (AST): modulová a funkčná závislostná sieť, väzby cez zdieľané tabuľky,
kandidáti na Bounded Contexts (DDD vs. Louvain) a porovnanie s náhodnými rozdeleniami. Generuje aj as-is UML (PlantUML)."""
import ast, re, os, sys, json, random, glob
import networkx as nx
from networkx.algorithms import community as nxc
from sklearn.metrics import adjusted_rand_score
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODS = ["customers", "catalog", "inventory", "orders", "payments", "notifications", "reporting"]
TABLE_OWNER = {"customers": "customers", "products": "catalog", "stock": "inventory", "orders": "orders",
               "order_items": "orders", "payments": "payments", "notifications": "notifications"}
CONTEXT = {"customers": "Customer", "catalog": "Catalog", "inventory": "Inventory", "orders": "Ordering",
           "reporting": "Ordering", "payments": "Billing", "notifications": "Notification"}
SQL = re.compile(r"\b(INSERT INTO|UPDATE|DELETE FROM|FROM|JOIN)\s+(\w+)", re.I)

def parse():
    imports, funcs, calls, tables = {}, {}, set(), {}
    for m in MODS:
        tree = ast.parse(open(f"{ROOT}/monolith/{m}.py").read())
        imports[m] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.level == 1 and n.module is None:
                imports[m] |= {a.name for a in n.names if a.name in MODS}
        funcs[m] = [f.name for f in tree.body if isinstance(f, ast.FunctionDef)]
    for m in MODS:
        tree = ast.parse(open(f"{ROOT}/monolith/{m}.py").read())
        for f in [f for f in tree.body if isinstance(f, ast.FunctionDef)]:
            me = f"{m}.{f.name}"
            for n in ast.walk(f):
                if isinstance(n, ast.Call):
                    fn = n.func
                    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in MODS and fn.attr in funcs[fn.value.id]:
                        calls.add((me, f"{fn.value.id}.{fn.attr}"))
                    elif isinstance(fn, ast.Name) and fn.id in funcs[m]:
                        calls.add((me, f"{m}.{fn.id}"))
                if isinstance(n, ast.Constant) and isinstance(n.value, str):
                    for kw, t in SQL.findall(n.value):
                        if t.lower() in TABLE_OWNER:
                            mode = "W" if kw.upper() in ("INSERT INTO", "UPDATE", "DELETE FROM") else "R"
                            tables.setdefault(me, {}).setdefault(t.lower(), set()).add(mode)
    return imports, funcs, calls, tables

def main():
    imports, funcs, calls, tables = parse()
    # --- modulový graf
    G = nx.DiGraph(); G.add_nodes_from(MODS)
    for a, bs in imports.items():
        for b in bs: G.add_edge(a, b)
    metrics = {}
    for m in MODS:
        ce, ca = G.out_degree(m), G.in_degree(m)
        metrics[m] = {"Ce": ce, "Ca": ca, "I": round(ce / (ce + ca), 2) if ce + ca else 0}
    sccs = [sorted(s) for s in nx.strongly_connected_components(G) if len(s) > 1]
    # --- tabuľky: modul x tabuľka
    mt = {}
    for f, d in tables.items():
        m = f.split(".")[0]
        for t, modes in d.items():
            mt.setdefault((m, t), set()).update(modes)
    cross = {k: v for k, v in mt.items() if TABLE_OWNER[k[1]] != k[0]}
    shared = {t: sorted({m for (m, tt) in mt if tt == t}) for t in TABLE_OWNER if len({m for (m, tt) in mt if tt == t}) > 1}
    # --- funkčný graf
    F = nx.Graph()
    for m in MODS:
        for f in funcs[m]: F.add_node(f"{m}.{f}")
    for a, b in calls:
        if a != b: F.add_edge(a, b, weight=F.get_edge_data(a, b, {}).get("weight", 0) + 1.0)
    by_table = {}
    for f, d in tables.items():
        for t in d: by_table.setdefault(t, []).append(f)
    for t, fs in by_table.items():
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                w = F.get_edge_data(fs[i], fs[j], {}).get("weight", 0)
                F.add_edge(fs[i], fs[j], weight=w + 0.25)
    F.remove_nodes_from([n for n in list(F.nodes) if F.degree(n) == 0])
    nodes = sorted(F.nodes)
    ddd = {n: CONTEXT[n.split(".")[0]] for n in nodes}
    def groups(part): 
        g = {}
        for n, c in part.items(): g.setdefault(c, set()).add(n)
        return list(g.values())
    def Q(part): return nxc.modularity(F, groups(part), weight="weight")
    lv = nxc.louvain_communities(F, weight="weight", seed=42, resolution=1.0)
    louv = {n: i for i, c in enumerate(lv) for n in c}
    def cut(part):
        calls_cut = sum(1 for a, b in calls if a in part and b in part and part[a] != part[b])
        tbl_cut = 0
        for t, fs in by_table.items():
            fs = [f for f in fs if f in part]
            tbl_cut += sum(1 for i in range(len(fs)) for j in range(i + 1, len(fs)) if part[fs[i]] != part[fs[j]])
        return calls_cut, tbl_cut
    rnd = random.Random(1)
    labs = [ddd[n] for n in nodes]; qs = []
    for _ in range(2000):
        rnd.shuffle(labs); qs.append(Q(dict(zip(nodes, labs))))
    res = {
        "modules": metrics, "cycles": sccs,
        "n_functions": len(nodes), "n_call_edges": len(calls),
        "cross_owner_table_access": [{"module": m, "table": t, "owner": TABLE_OWNER[t], "mode": "".join(sorted(v))} for (m, t), v in sorted(cross.items())],
        "n_cross_owner_table_access": len(cross), "shared_tables": shared,
        "ddd": {"contexts": len(set(ddd.values())), "Q": round(Q(ddd), 3), "calls_cut": cut(ddd)[0], "table_pairs_cut": cut(ddd)[1]},
        "louvain": {"communities": len(lv), "Q": round(Q(louv), 3), "calls_cut": cut(louv)[0], "table_pairs_cut": cut(louv)[1],
                    "ARI_vs_DDD": round(adjusted_rand_score([ddd[n] for n in nodes], [louv[n] for n in nodes]), 3),
                    "members": [sorted(c) for c in lv]},
        "random_baseline": {"Q_mean": round(float(np.mean(qs)), 3), "Q_std": round(float(np.std(qs)), 3),
                            "Q_p95": round(float(np.percentile(qs, 95)), 3), "n": len(qs)},
    }
    # --- to-be: skenovanie zdrojov služieb
    svc = {}
    for s, dbtables in {"catalog": {"products"}, "inventory": {"stock"}, "billing": {"accounts", "payments"}, "ordering": {"orders", "order_items"}}.items():
        src = open(f"{ROOT}/services/{s}/app.py").read()
        used = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                used |= {t.lower() for _, t in SQL.findall(n.value)}
        deps = set()
        for fn, tgt in [("catalog_get", "catalog"), ("catalog_list", "catalog"), ("inventory_get", "inventory"), ("inventory_op", "inventory"),
                        ("payment_charge", "billing"), ("customer_get", "monolith"), ("notify", "monolith")]:
            if f"remote.{fn}(" in src: deps.add(tgt)
        svc[s] = {"tables_used": sorted(used), "foreign_tables": sorted(used - dbtables), "sync_deps": sorted(deps)}
    msrc = open(f"{ROOT}/monolith/payments.py").read()   # zvyšok monolitu: customers.create -> payments.open_account -> billing
    svc["monolith_remainder"] = {"tables_used": ["customers", "notifications"], "foreign_tables": [],
                                 "sync_deps": ["billing"] if "remote.payment_open_account(" in msrc else []}
    res["to_be_services"] = svc
    res["to_be_http_dependencies"] = sum(len(v["sync_deps"]) for v in svc.values())
    os.makedirs(f"{ROOT}/results/figures", exist_ok=True)
    json.dump(res, open(f"{ROOT}/results/static_analysis.json", "w"), indent=1, ensure_ascii=False)
    figures(mt, metrics, G)
    puml(G, sccs, mt)
    print(json.dumps({k: res[k] for k in ["cycles", "n_functions", "n_call_edges", "n_cross_owner_table_access", "shared_tables", "ddd", "random_baseline", "to_be_http_dependencies"]}, indent=1, ensure_ascii=False))
    print(json.dumps(res["louvain"], indent=1)[:1500])
    print(json.dumps(res["to_be_services"], indent=1))

def figures(mt, metrics, G):
    tabs = list(TABLE_OWNER)
    M = np.zeros((len(MODS), len(tabs)))
    for (m, t), v in mt.items():
        M[MODS.index(m), tabs.index(t)] = 1 if TABLE_OWNER[t] == m else 2
    fig, ax = plt.subplots(figsize=(7, 3.8))
    from matplotlib.colors import ListedColormap
    ax.imshow(M, cmap=ListedColormap(["#f3f4f6", "#9ca3af", "#dc2626"]), vmin=0, vmax=2)
    ax.set_xticks(range(len(tabs))); ax.set_xticklabels(tabs, rotation=30, ha="right"); ax.set_yticks(range(len(MODS))); ax.set_yticklabels(MODS)
    for (m, t), v in mt.items():
        ax.text(tabs.index(t), MODS.index(m), "".join(sorted(v)), ha="center", va="center", color="white", fontsize=9, fontweight="bold")
    ax.set_title("Prístup modulov k tabuľkám (šedá = vlastná, červená = cudzia tabuľka)", fontsize=10)
    plt.tight_layout(); plt.savefig(f"{ROOT}/results/figures/table_access.png", dpi=170); plt.close()

def puml(G, sccs, mt):
    cyc = {frozenset(e) for s in sccs for e in G.edges if e[0] in s and e[1] in s}
    L = ["@startuml", "title Komponentový diagram – AS-IS legacy monolit (generované statickou analýzou)", "skinparam componentStyle uml2",
         "skinparam shadowing false", "left to right direction", 'package "Legacy monolit" {']
    for m in MODS: L.append(f"  component [{m}] as {m}")
    L.append("}")
    L.append('package "Zdieľaná DB (monolith.db)" {')
    for t in TABLE_OWNER: L.append(f'  database "{t}" as t_{t}')
    L.append("}")
    for a, b in G.edges:
        col = "#CC0000" if frozenset((a, b)) in cyc else "#444444"
        L.append(f"{a} -[{col}]-> {b}")
    for (m, t), v in sorted(mt.items()):
        cross = TABLE_OWNER[t] != m
        L.append(f"{m} .[{'#CC0000' if cross else '#999999'}].> t_{t} : {''.join(sorted(v))}")
    L += ["legend right", "  červená plná = cyklická závislosť modulov", "  červená bodkovaná = prístup k cudzej tabuľke", "endlegend", "@enduml"]
    open(f"{ROOT}/uml/v1_original/02_component_as_is.puml", "w").write("\n".join(L))

if __name__ == "__main__":
    main()
