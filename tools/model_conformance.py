#!/usr/bin/env python3
"""E5: zhoda UML modelov s kódom (model-code conformance) a formálna správnosť sekvenčných diagramov.

Z kódu (AST) sa vytiahne referenčný zoznam operácií a závislostí; z diagramov (PlantUML v1 aj Mermaid/Graphviz v2)
sa pravidlami vyberú správy a hrany. Porovnáva sa:
  * sekvenčné diagramy zadania objednávky (AS-IS monolit, TO-BE saga): úplnosť, presnosť, poradie, async vs. sync,
    návratové správy, aktivácie, fragmenty break;
  * komponentový a nasadzovací diagram TO-BE: hrany medzi komponentmi voči skutočným volaniam (s dosiahnuteľnosťou
    z aktívnych ciest monolitu v etape S4);
  * komponentový diagram AS-IS: cykly a prístupy k cudzím tabuľkám voči E1 (static_analysis.json).
Výsledok: results/model_conformance.json"""
import ast, os, re, sys, json, itertools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
UML = os.path.join(ROOT, "uml")
V1 = os.path.join(UML, "v1_original")
SRC = os.path.join(UML, "src")
MODS = ["customers", "catalog", "inventory", "orders", "payments", "notifications", "reporting"]

def read(*p):
    return open(os.path.join(*p), encoding="utf8").read()

# ---------------------------------------------------------------- kód -> referenčné operácie
def sql_token(sql):
    s = " ".join(sql.split())
    if s.upper().startswith("BEGIN"): return "db.BEGIN"
    if s.upper().startswith("COMMIT"): return "db.COMMIT"
    if s.upper().startswith("ROLLBACK"): return "db.ROLLBACK"
    m = re.match(r"INSERT INTO (\w+)", s, re.I)
    if m: return f"db.INSERT {m.group(1)}"
    m = re.match(r"UPDATE (\w+) SET status='(\w+)'", s, re.I)
    if m: return f"db.UPDATE {m.group(1)} {m.group(2)}"
    m = re.match(r"UPDATE (\w+)", s, re.I)
    if m: return f"db.UPDATE {m.group(1)}"
    return None

def find_func(tree, name):
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n

def ordered_calls(fn):
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    return sorted(calls, key=lambda n: (n.lineno, n.col_offset))

def handler_ranges(fn):
    return [(h.lineno, max(getattr(x, "end_lineno", h.lineno) for x in ast.walk(h))) for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]

def truth_as_is():
    tree = ast.parse(read(ROOT, "monolith", "orders.py"))
    fn = find_func(tree, "place")
    hr = handler_ranges(fn)
    main, handler = [], []
    for c in ordered_calls(fn):
        tok = None
        f = c.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id in MODS:
                tok = f"{f.value.id}.{f.attr}"
            elif f.attr == "execute" and c.args and isinstance(c.args[0], ast.Constant):
                tok = sql_token(c.args[0].value)
        if not tok: continue
        (handler if any(a <= c.lineno <= b for a, b in hr) else main).append(tok)
    nested = set()
    for mod, func in [("inventory", "reserve"), ("inventory", "commit"), ("inventory", "release"), ("payments", "charge"), ("notifications", "send")]:
        t = ast.parse(read(ROOT, "monolith", f"{mod}.py"))
        g = find_func(t, func)
        for c in ast.walk(g):
            if not isinstance(c, ast.Call): continue
            f = c.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in MODS and f.value.id != mod:
                nested.add(f"{mod}>{f.value.id}.{f.attr}")
            elif isinstance(f, ast.Attribute) and f.attr == "execute" and c.args and isinstance(c.args[0], ast.Constant):
                tk = sql_token(c.args[0].value)
                if tk: nested.add(tk)
    # vetva elif _compensate() sa vykoná len v hybridných etapách S2/S3 (nie v S0), preto sa do referencie S0 nepočíta
    excluded = [t for t in dedupe(handler) if t != "db.ROLLBACK"]
    return dict(main=dedupe(main), handler=["db.ROLLBACK"], nested=sorted(nested), excluded_hybrid_only=excluded)

REMOTE_MAP = {"customer_get": "monolith.customer_get", "catalog_get": "catalog.get_product", "payment_charge": "billing.charge", "notify": "monolith.notify"}

def truth_saga():
    tree = ast.parse(read(ROOT, "services", "ordering", "app.py"))
    fn = find_func(tree, "place_order")
    hr = handler_ranges(fn)
    main, handler = [], []
    for c in ordered_calls(fn):
        f, tok = c.func, None
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == "remote":
                if f.attr == "inventory_op" and c.args and isinstance(c.args[0], ast.Constant):
                    tok = f"inventory.{c.args[0].value}"
                else:
                    tok = REMOTE_MAP.get(f.attr)
            elif f.attr == "execute" and c.args and isinstance(c.args[0], ast.Constant):
                tok = sql_token(c.args[0].value)
        if not tok: continue
        (handler if any(a <= c.lineno <= b for a, b in hr) else main).append(tok)
    # asynchrónnosť: kód nepoužíva async/await ani vlákna na ceste objednávky
    src = read(ROOT, "services", "ordering", "app.py") + read(ROOT, "common", "remote.py")
    async_calls = len(re.findall(r"\basync def\b|\bawait\b|threading|asyncio|Queue", src))
    return dict(main=dedupe(main), handler=dedupe(handler), nested=[], async_calls=async_calls)

def dedupe(xs):
    out = []
    for x in xs:
        if x not in out: out.append(x)
    return out

# ---------------------------------------------------------------- diagram -> správy
RULES_AS_IS = [
    (r"get\(customerId\)", "customers.get"), (r"get_product", "catalog.get_product"), (r"BEGIN", "db.BEGIN"),
    (r"INSERT orders", "db.INSERT orders"), (r"reserve\(", "inventory.reserve"), (r"UPDATE stock", "db.UPDATE stock"),
    (r"INSERT order_items", "db.INSERT order_items"), (r"charge\(", "payments.charge"),
    (r"credit_left", "payments>customers.credit_left"), (r"UPDATE customers", "db.UPDATE customers"),
    (r"INSERT payments", "db.INSERT payments"), (r"commit\(", "inventory.commit"), (r"SET (status = )?PAID", "db.UPDATE orders PAID"),
    (r"^COMMIT", "db.COMMIT"), (r"ROLLBACK", "db.ROLLBACK"), (r"send\(", "notifications.send"),
    (r"INSERT notifications", "db.INSERT notifications"),
]
RULES_SAGA = [
    (r"/customers/", "monolith.customer_get"), (r"/products/", "catalog.get_product"), (r"INSERT order \(|INSERT orders", "db.INSERT orders"),
    (r"INSERT order_items", "db.INSERT order_items"), (r"/reserve", "inventory.reserve"), (r"/payments", "billing.charge"),
    (r"/commit", "inventory.commit"), (r"/release|release\(", "inventory.release"), (r"= PAID", "db.UPDATE orders PAID"),
    (r"= CANCELLED", "db.UPDATE orders CANCELLED"), (r"/notifications", "monolith.notify"),
]

def parse_puml_seq(text):
    msgs, aliases, fr = [], {}, []
    for raw in text.splitlines():
        ln = raw.strip()
        m = re.match(r'(?:participant|actor|database)\s+"?([^"]+?)"?\s+as\s+(\w+)', ln)
        if m: aliases[m.group(2)] = m.group(1).replace("\\n", " "); continue
        m = re.match(r"(?:participant|actor|database)\s+(\w+)\s*$", ln)
        if m: aliases[m.group(1)] = m.group(1); continue
        m = re.match(r"(loop|alt|opt|group|break)\b", ln)
        if m: fr.append(m.group(1)); continue
        if ln.startswith("else"): continue
        if ln == "end": fr and fr.pop(); continue
        m = re.match(r"(\w+)\s*(-->>|--\>|->>|->)\s*(\w+)\s*:\s*(.*)", ln)
        if m:
            a, arrow, b, txt = m.groups()
            msgs.append(dict(src=a, dst=b, text=txt, reply=arrow.startswith("--"), asyn=arrow.endswith(">>") and not arrow.startswith("--"),
                             frames=list(fr), activ=False))
    return msgs, aliases

def parse_mmd_seq(text):
    msgs, aliases, fr = [], {}, []
    for raw in text.splitlines():
        ln = raw.strip()
        m = re.match(r"(?:participant|actor)\s+(\w+)\s+as\s+(.+)", ln)
        if m: aliases[m.group(1)] = m.group(2); continue
        m = re.match(r"(loop|alt|opt|break)\b", ln)
        if m: fr.append(m.group(1)); continue
        if ln.startswith("else") or ln.startswith("Note"): continue
        if ln == "end": fr and fr.pop(); continue
        m = re.match(r"(\w+)\s*(-->>|->>|-\))([+-]?)\s*(\w+)\s*:\s*(.*)", ln)
        if m:
            a, arrow, act, b, txt = m.groups()
            msgs.append(dict(src=a, dst=b, text=txt, reply=arrow == "-->>", asyn=arrow == "-)", frames=list(fr), activ=act == "+"))
    return msgs, aliases

def seq_metrics(msgs, aliases, rules, truth, client_alias):
    isdb = lambda x: ".db" in aliases.get(x, x)
    calls = [m for m in msgs if not m["reply"]]
    toks, per_msg = [], []
    for m in calls:
        for rx, tok in rules:
            if re.search(rx, m["text"]):
                if tok == "customers.get" and aliases.get(m["src"], m["src"]) == "notifications":
                    tok = "notifications>customers.get"
                toks.append(tok); per_msg.append(tok)
    toks = dedupe(toks)
    T = set(truth["main"]) | set(truth["handler"]) | set(truth["nested"])
    M = set(toks)
    recall = len(M & T) / len(T)
    precision = len(M & T) / len(M) if M else 0.0
    lcs = lcs_len([t for t in toks if t in truth["main"]], truth["main"]) / len(truth["main"])
    pairs = {(m["src"], m["dst"]) for m in calls if m["src"] != m["dst"] and not isdb(m["dst"]) and not isdb(m["src"])}
    replied = {p for p in pairs if any(r["reply"] and (r["src"], r["dst"]) == (p[1], p[0]) for r in msgs)}
    err = re.compile(r"\b[45]\d\d\b")
    errs = [m for m in msgs if m["reply"] or m["dst"] == client_alias] 
    errs = [m for m in msgs if m["dst"] == client_alias and err.search(m["text"])]
    loop_no_break = [m for m in errs if "loop" in m["frames"] and "break" not in m["frames"]]
    return dict(
        messages=len(msgs), calls=len(calls), replies=len(msgs) - len(calls),
        ops_in_model=sorted(M), ops_missing=sorted(T - M), ops_phantom=sorted(M - T),
        recall=round(recall, 3), precision=round(precision, 3), order_lcs=round(lcs, 3),
        pairs=len(pairs), pairs_with_reply=len(replied), reply_pair_coverage=round(len(replied) / len(pairs), 3) if pairs else None,
        activations=sum(1 for m in msgs if m["activ"]), break_fragments=sum(1 for m in msgs if "break" in m["frames"] and False),
        async_messages=sum(1 for m in calls if m["asyn"]), error_exits_in_loop_without_break=len(loop_no_break),
    )

def lcs_len(a, b):
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, x in enumerate(a, 1):
        for j, y in enumerate(b, 1):
            dp[i][j] = dp[i - 1][j - 1] + 1 if x == y else max(dp[i - 1][j], dp[i][j - 1])
    return dp[-1][-1]

def count_breaks(text):
    return len(re.findall(r"^\s*break\b", text, re.M))

# ---------------------------------------------------------------- kód -> závislosti medzi službami (S4)
def remote_env():
    t = ast.parse(read(ROOT, "common", "remote.py"))
    out = {}
    for f in [n for n in t.body if isinstance(n, ast.FunctionDef)]:
        for c in ast.walk(f):
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith("_URL"):
                out[f.name] = c.value
        for c in ast.walk(f):
            if isinstance(c, ast.Subscript) and isinstance(c.slice, ast.Constant) and str(c.slice.value).endswith("_URL"):
                out[f.name] = c.slice.value
    return out

ENV2SVC = {"CATALOG_URL": "catalog", "INVENTORY_URL": "inventory", "BILLING_URL": "billing", "MONOLITH_URL": "monolith"}

def truth_edges():
    renv = remote_env()
    svc = lambda fn: ENV2SVC[renv[fn]]
    # routy etapy S4 sa čítajú zo zdrojáku harnessu (bez importu httpx)
    hsrc = read(ROOT, "tools", "harness.py")
    body = hsrc[hsrc.index("def routes(stage):"):hsrc.index("def service_env")]
    routes = {}
    for stg, rest in re.findall(r"if stage >= (\d): (.*)", body):
        if int(stg) <= 4:
            for path, svc_name in re.findall(r'r\["([^"]+)"\] = URL\["(\w+)"\]', rest):
                routes[path] = svc_name
    active, dormant = set(), set()
    for _, svc_name in routes.items():
        active.add(("gateway", svc_name))
    active.add(("gateway", "monolith"))
    for sname, path in [("catalog", "services/catalog/app.py"), ("ordering", "services/ordering/app.py"), ("billing", "services/billing/app.py")]:
        t = ast.parse(read(ROOT, path))
        for c in ast.walk(t):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name) and c.func.value.id == "remote" and c.func.attr in renv:
                active.add((sname, svc(c.func.attr)))
    # monolit: dosiahnuteľnosť z handlerov, ktoré v S4 ostali na default trase
    funcs, calls, remotes, handlers = {}, {}, {}, {}
    for m in MODS + ["app"]:
        t = ast.parse(read(ROOT, "monolith", f"{m}.py"))
        for f in [n for n in t.body if isinstance(n, ast.FunctionDef)]:
            me = f"{m}.{f.name}"; calls[me] = set(); remotes[me] = set()
            for c in ast.walk(f):
                if isinstance(c, ast.Call):
                    fn = c.func
                    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                        if fn.value.id == "remote" and fn.attr in renv: remotes[me].add(svc(fn.attr))
                        elif fn.value.id in MODS: calls[me].add(f"{fn.value.id}.{fn.attr}")
                    elif isinstance(fn, ast.Name): calls[me].add(f"{m}.{fn.id}")
            if m == "app":
                for d in f.decorator_list:
                    if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant):
                        handlers[me] = d.args[0].value
    def routed_away(path):
        return any(path == p or path.startswith(p + "/") for p in routes)
    live = [h for h, p in handlers.items() if not routed_away(p)]
    seen, stack = set(), list(live)
    while stack:
        x = stack.pop()
        if x in seen: continue
        seen.add(x); stack += [y for y in calls.get(x, ()) if y in calls]
    reach = set().union(*(remotes[x] for x in seen if x in remotes)) if seen else set()
    allrem = set().union(*remotes.values())
    for d in reach: active.add(("monolith", d))
    for d in allrem - reach: dormant.add(("monolith", d))
    return active, dormant, sorted(live)

def edges_puml_component(text):
    out = set()
    m2s = dict(GW="gateway", ORD="ordering", CAT="catalog", INV="inventory", BIL="billing", MONO="monolith")
    for ln in text.splitlines():
        m = re.match(r"\s*(\w+)\s+-\w*->\s+(\w+)", ln)
        if m and m.group(1) in m2s and m.group(2) in m2s: out.add((m2s[m.group(1)], m2s[m.group(2)]))
    return out

def edges_dot_component(text):
    prov, req, sec = {}, set(), None
    n2s = dict(GW="gateway", ORD="ordering", CAT="catalog", INV="inventory", BIL="billing", MONO="monolith")
    for ln in text.splitlines():
        if "// poskytuje" in ln: sec = "p"; continue
        if "// dáta" in ln: sec = None; continue
        if "// vyžaduje" in ln: sec = "r"; continue
        for a, b in re.findall(r"(\w+)\s*->\s*(\w+)", ln):
            if sec == "p": prov[b] = a
            elif sec == "r": req.add((a, b))
    return {(n2s[a], n2s[prov[b]]) for a, b in req if a in n2s and b in prov and prov[b] in n2s}

def edges_puml_deploy(text):
    m2s = dict(gw="gateway", mono="monolith", cat="catalog", inv="inventory", bil="billing", ord="ordering")
    out = set()
    for ln in text.splitlines():
        m = re.match(r"\s*(\w+)\s+-->\s+(\w+)", ln)
        if m and m.group(1) in m2s and m.group(2) in m2s: out.add((m2s[m.group(1)], m2s[m.group(2)]))
    return out

def edges_dot_deploy(text):
    m2s = dict(a_gw="gateway", a_mono="monolith", a_cat="catalog", a_inv="inventory", a_bil="billing", a_ord="ordering")
    return {(m2s[a], m2s[b]) for a, b in re.findall(r"(a_\w+)\s*->\s*(a_\w+)", text) if a in m2s and b in m2s}

def edge_metrics(model, active, dormant):
    return dict(model_edges=len(model), truth_edges=len(active), matched=len(model & active),
                recall=round(len(model & active) / len(active), 3), precision=round(len(model & active) / len(model), 3) if model else 0,
                missing=sorted("%s->%s" % e for e in active - model), phantom=sorted("%s->%s" % e for e in model - active),
                dormant_in_code=sorted("%s->%s" % e for e in dormant), dormant_in_model=sorted("%s->%s" % e for e in model & dormant))

# ---------------------------------------------------------------- AS-IS komponentový diagram voči E1
def as_is_component():
    e1 = json.load(open(os.path.join(ROOT, "results", "static_analysis.json")))
    cyc = {frozenset(c) for c in e1["cycles"]}
    foreign = {(x["module"], x["table"]) for x in e1["cross_owner_table_access"]}
    v1 = read(V1, "02_component_as_is.puml")
    red = re.findall(r"(\w+)\s+-\[#CC0000\]->\s+(\w+)", v1)
    v1_cyc = {frozenset(p) for p in red}
    v1_for = {(a, b[2:]) for a, b in re.findall(r"(\w+)\s+\.\[#CC0000\]\.>\s+(\w+)", v1)}
    v2 = read(SRC, "02_component_as_is.dot")
    sec = v2.split("// cyklické závislosti")[1].split("// prístup k tabuľkám")[0]
    v2_cyc = {frozenset(p) for p in re.findall(r"(\w+)\s*->\s*(\w+)", sec)}
    sec2 = v2.split("// cudzie tabuľky")[1].split("legend")[0]
    tmap = {"t_items": "order_items", "t_customers": "customers", "t_orders": "orders", "t_products": "products"}
    v2_for = {(a, tmap.get(b, b)) for a, b in re.findall(r"(\w+)\s*->\s*(\w+)", sec2)}
    f = lambda m, t: dict(found=len(m & t), truth=len(t), phantom=len(m - t))
    return dict(cycles_v1=f(v1_cyc, cyc), cycles_v2=f(v2_cyc, cyc), foreign_v1=f(v1_for, foreign), foreign_v2=f(v2_for, foreign))

# ---------------------------------------------------------------- hlavný beh
def main():
    res = {}
    ta, ts = truth_as_is(), truth_saga()
    res["truth"] = dict(as_is=ta, saga=dict(main=ts["main"], handler=ts["handler"], nested=ts["nested"]), async_calls_in_saga_code=ts["async_calls"])
    out = {}
    v1 = read(V1, "04_sequence_place_order_as_is.puml"); m, a = parse_puml_seq(v1)
    out["as_is_v1"] = seq_metrics(m, a, RULES_AS_IS, ta, "Klient"); out["as_is_v1"]["break_fragments"] = count_breaks(v1)
    v2 = read(SRC, "04_sequence_place_order_as_is.mmd"); m, a = parse_mmd_seq(v2)
    out["as_is_v2"] = seq_metrics(m, a, RULES_AS_IS, ta, "K"); out["as_is_v2"]["break_fragments"] = count_breaks(v2)
    v1 = read(V1, "05_sequence_place_order_saga.puml"); m, a = parse_puml_seq(v1)
    out["saga_v1"] = seq_metrics(m, a, RULES_SAGA, ts, "Klient"); out["saga_v1"]["break_fragments"] = count_breaks(v1)
    v2 = read(SRC, "05_sequence_place_order_saga.mmd"); m, a = parse_mmd_seq(v2)
    out["saga_v2"] = seq_metrics(m, a, RULES_SAGA, ts, "K"); out["saga_v2"]["break_fragments"] = count_breaks(v2)
    res["sequence"] = out
    active, dormant, live = truth_edges()
    res["structure_truth"] = dict(active=sorted("%s->%s" % e for e in active), dormant=sorted("%s->%s" % e for e in dormant), monolith_live_handlers=live)
    res["component_to_be_v1"] = edge_metrics(edges_puml_component(read(V1, "03_component_to_be.puml")), active, dormant)
    res["component_to_be_v2"] = edge_metrics(edges_dot_component(read(SRC, "03_component_to_be.dot")), active, dormant)
    res["deployment_v1"] = edge_metrics(edges_puml_deploy(read(V1, "07_deployment_s4.puml")), active, dormant)
    res["deployment_v2"] = edge_metrics(edges_dot_deploy(read(SRC, "07_deployment_s4.dot")), active, dormant)
    res["component_as_is"] = as_is_component()
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "results", "model_conformance.json"), "w", encoding="utf8"), ensure_ascii=False, indent=1)
    show(res)

def show(r):
    print("TRUTH as-is main:", r["truth"]["as_is"]["main"]); print("   handler:", r["truth"]["as_is"]["handler"], "nested:", r["truth"]["as_is"]["nested"])
    print("TRUTH saga main:", r["truth"]["saga"]["main"], "handler:", r["truth"]["saga"]["handler"], "async calls in code:", r["truth"]["async_calls_in_saga_code"])
    for k, v in r["sequence"].items():
        print(f"\n{k}: msgs={v['messages']} calls={v['calls']} recall={v['recall']} precision={v['precision']} order={v['order_lcs']} "
              f"reply_pairs={v['pairs_with_reply']}/{v['pairs']} activ={v['activations']} break={v['break_fragments']} async={v['async_messages']} err_in_loop={v['error_exits_in_loop_without_break']}")
        print("   missing:", v["ops_missing"], "phantom:", v["ops_phantom"])
    print("\nstructure truth:", r["structure_truth"])
    for k in ["component_to_be_v1", "component_to_be_v2", "deployment_v1", "deployment_v2"]:
        print(k, r[k])
    print("as-is component:", r["component_as_is"])

if __name__ == "__main__":
    main()
