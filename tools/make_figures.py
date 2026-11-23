import json, os, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
b = json.load(open(f"{ROOT}/results/bench_summary.json")); f = json.load(open(f"{ROOT}/results/faults.json"))
st = ["S0", "S1", "S2", "S3", "S4"]; keys = list(b)
NAVY, TEAL, RED, GREY = "#1E2761", "#028090", "#C0392B", "#9CA3AF"
fig, ax = plt.subplots(1, 3, figsize=(11, 3.4))
x = np.arange(5); w = 0.38
ax[0].bar(x - w/2, [b[k]["write"]["p50"] for k in keys], w, label="p50", color=NAVY)
ax[0].bar(x + w/2, [b[k]["write"]["p95"] for k in keys], w, label="p95", color=TEAL)
for i, k in enumerate(keys): ax[0].text(i - w/2, b[k]["write"]["p50"] + 3, f'{b[k]["write"]["p50"]:.0f}', ha="center", fontsize=8)
ax[0].set_xticks(x); ax[0].set_xticklabels(st); ax[0].set_ylabel("ms"); ax[0].set_title("(a) Latencia POST /orders", fontsize=10); ax[0].legend(fontsize=8, frameon=False)
ax[1].plot(st, [b[k]["write"]["rps"] for k in keys], "o-", color=NAVY, label="zadanie objednávky")
ax[1].plot(st, [b[k]["read"]["rps"] for k in keys], "s-", color=TEAL, label="čítanie produktu")
ax[1].set_ylabel("požiadavky / s"); ax[1].set_title("(b) Priepustnosť", fontsize=10); ax[1].legend(fontsize=8, frameon=False); ax[1].set_ylim(0, 330)
lab = ["S0\nACID", "S2\nbez komp.", "S2\ns komp.", "S4\nbez komp.", "S4\ns komp."]
vals = [r["reserved_leaked_units"] for r in f]
bars = ax[2].bar(lab, vals, color=[TEAL if v == 0 else RED for v in vals])
for bar, v in zip(bars, vals): ax[2].text(bar.get_x() + bar.get_width()/2, v + 10, str(v), ha="center", fontsize=9)
ax[2].set_title("(c) Uniknuté rezervácie (ks tovaru)", fontsize=10); ax[2].tick_params(axis="x", labelsize=8); ax[2].set_ylim(0, 640)
for a in ax:
    for s in ("top", "right"): a.spines[s].set_visible(False)
plt.tight_layout(); plt.savefig(f"{ROOT}/results/figures/results.png", dpi=170)
