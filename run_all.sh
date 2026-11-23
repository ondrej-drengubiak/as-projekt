#!/usr/bin/env bash
# Reprodukcia všetkých experimentov (Linux/macOS). Potrebuje Python 3.10+, voliteľne mmdc (Mermaid CLI) + graphviz pre diagramy.
set -e
pip install -r requirements.txt
python tools/seed.py
python tools/contract_tests.py      # E2: kontraktové testy cez všetky etapy
python tools/analyze_static.py      # E1: statická analýza + generovanie AS-IS UML
python tools/bench.py               # E3: výkon (trvá ~5 min, nespúšťať popri inej záťaži)
python tools/faults.py              # E4: vstrekovanie porúch
python tools/make_figures.py
python tools/model_conformance.py   # E5: zhoda UML modelov s kódom
command -v mmdc >/dev/null && command -v dot >/dev/null && python uml/render.py   # prekreslí diagramy z uml/src
