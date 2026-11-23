# Re-architektúra legacy monolitu na mikroslužby (AS, tím 6)

Referenčná implementácia a experimenty k eseji *„Re-architektúra legacy monolitu na mikroslužby: modelovanie domény
a transformačných vzorov v UML a ArchiMate"*. Autori: Ondrej Drengubiak, Vladyslav Chesnykov.

## Čo projekt obsahuje
| Priečinok | Obsah |
|---|---|
| `monolith/` | Legacy e-shop (7 modulov, jedna SQLite DB, ACID transakcia pri zadaní objednávky). Moduly `catalog`, `inventory`, `payments` majú feature toggle (Branch by Abstraction). |
| `services/` | Vyčlenené služby: `catalog`, `inventory`, `billing`, `ordering` (saga orchestrátor). Každá má vlastnú DB. |
| `gateway/` | Strangler Fig fasáda – smeruje cesty podľa tabuľky `ROUTES`. |
| `tools/` | `harness.py` (etapy S0–S4), `contract_tests.py`, `analyze_static.py`, `bench.py`, `faults.py`, `make_figures.py`, `model_conformance.py` (E5). |
| `uml/` | Diagramy: zdroje v `uml/src` (Mermaid `.mmd`, Graphviz `.dot`), vyrenderované `.png` (UML: use case, triedny, komponentový, nasadzovací, sekvenčný, stavový, aktivít; ArchiMate: Layered, Implementation and Migration), `render.py`. Pôvodné (v1) PlantUML verzie sú v `uml/v1_original` ako základ pre E5. |
| `results/` | JSON/CSV výsledky a grafy z experimentov. |

## Etapy migrácie
S0 monolit → S1 +Catalog → S2 +Inventory → S3 +Billing → S4 +Ordering. Pri každej etape sa dáta jednorazovo prenesú do DB služby
(cutover), gateway prepne trasu a monolit prepne príslušný modul na vzdialenú implementáciu.

## Spustenie
```bash
./run_all.sh                         # všetko
python tools/contract_tests.py       # len kontraktové testy
python tools/bench.py                # len výkonnostné meranie
```
Služby sa štartujú automaticky (uvicorn, porty 8000–8104) a po experimente sa ukončia.

## Experimenty
* **E1** statická analýza (AST): závislosti modulov, cykly, prístup k cudzím tabuľkám, DDD vs. Louvain vs. náhodné rozdelenie.
* **E2** kontraktové (golden-master) testy: 25 scenárov × 5 etáp, porovnanie celého prepisu komunikácie.
* **E3** výkon: POST /orders a GET /products/{id}, 8 súbežných klientov, 3 opakovania.
* **E4** vstrekovanie porúch: 25 % nedostupnosť platby + 15 % zamietnutie, so/bez kompenzácie v sage.
* **E5** zhoda modelov s kódom: z AST sa vytiahne referenčný zoznam operácií a závislostí a porovná sa s pôvodnými (v1) a opravenými (v2) diagramami; výsledok v `results/model_conformance.json`. Diagramy sa prekresľujú príkazom `python uml/render.py` (vyžaduje `mmdc` a Graphviz; cestu k Chrome možno zadať cez `CHROME_PATH`).

## Limity (hrozby validity)
Referenčný systém je syntetický, nie priemyselný. Merania bežali na 1 CPU, kde klient aj všetky procesy súperia o ten istý procesor,
bez reálnej sieťovej latencie – absolútne čísla sú preto orientačné, relatívne poradie etáp je spoľahlivejšie.
SQLite namiesto produkčnej DB; dáta sa migrujú offline (cutover), nie priebežnou replikáciou.
