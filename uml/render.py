#!/usr/bin/env python3
"""Vyrenderuje všetky diagramy z uml/src/ do uml/*.png.
Sekvenčné, stavové a triedne diagramy: Mermaid (mmdc). Komponentové, nasadzovacie, aktivitné, use case a ArchiMate: Graphviz (dot).
Premenná CHROME_PATH môže ukazovať na Chrome/Chromium pre mmdc."""
import os, sys, glob, json, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
chrome = os.environ.get("CHROME_PATH")
pp = {"args": ["--no-sandbox", "--disable-gpu"]}
if chrome: pp["executablePath"] = chrome
ppf = os.path.join(tempfile.gettempdir(), "pp_render.json"); json.dump(pp, open(ppf, "w"))
only = sys.argv[1:]
for f in sorted(glob.glob(os.path.join(SRC, "*"))):
    base, ext = os.path.splitext(os.path.basename(f))
    if only and not any(o in base for o in only): continue
    out = os.path.join(HERE, base + ".png")
    if ext == ".mmd":
        cmd = ["mmdc", "-i", f, "-o", out, "-p", ppf, "-c", os.path.join(HERE, "mermaid.config.json"), "-s", "2", "-b", "white"]
    elif ext == ".dot":
        cmd = (["neato", "-n2", "-Tpng", "-Gdpi=170", f, "-o", out] if open(f, encoding="utf8").read().startswith("// Pevn") else ["dot", "-Tpng", "-Gdpi=170", f, "-o", out])
    else:
        continue
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=SRC)
    print(("OK  " if r.returncode == 0 else "FAIL"), base, r.stderr.strip()[:300])
