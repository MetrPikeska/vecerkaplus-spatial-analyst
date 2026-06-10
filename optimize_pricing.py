"""
VečerkaPlus – optimalizace dopravného per obec
===============================================
Pro každou obec v scoring tabulce vypočítá:
  - aktuální net/objednávku
  - minimální dopravné pro dosažení target net (TARGET_NET_KC)
  - doporučené pásmové dopravné
  - P&L srovnání: flat 39 Kč vs. doporučené pásmové vs. cost-based

Výstupy:
  output/pricing_optimization.csv   — per-obec doporučené dopravné
  output/pricing_optimization.html  — interaktivní přehled
"""

import os, json
import pandas as pd
import numpy as np

# ── konstanty ─────────────────────────────────────────────────────────────────
AVG_ORDER_KC     = 452.0
AVG_GROSS_MARGIN = 0.365
COURIER_FEE_Z1   = 120.0   # ≤ 10 km
COURIER_FEE_Z2   = 180.0   # 10–20 km
COURIER_FEE_Z3   = 250.0   # > 20 km
FREE_THR         = 1_000.0  # dopravné zdarma od X Kč

TARGET_NET_KC    = 60.0    # cílový čistý příspěvek per objednávku

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

GROSS_KC = AVG_ORDER_KC * AVG_GROSS_MARGIN  # ≈ 165 Kč


def courier_fee(dist_km: float) -> float:
    if dist_km <= 10:  return COURIER_FEE_Z1
    if dist_km <= 20:  return COURIER_FEE_Z2
    return COURIER_FEE_Z3


def net_order(dist_km: float, delivery_fee: float) -> float:
    return GROSS_KC + delivery_fee - courier_fee(dist_km)


def min_delivery_fee(dist_km: float, target: float = TARGET_NET_KC) -> float:
    """Minimální dopravné od zákazníka pro dosažení target net/objednávku."""
    needed = target - GROSS_KC + courier_fee(dist_km)
    return max(0.0, round(needed, 0))


def tiered_fee(dist_km: float) -> float:
    """Navrhované 4-pásmové dopravné."""
    if dist_km <= 8:   return 39.0
    if dist_km <= 15:  return 69.0
    if dist_km <= 20:  return 99.0
    return 149.0


# ── načtení scoring dat ───────────────────────────────────────────────────────
scoring_path = os.path.join(OUT_DIR, "obce_scoring.csv")
if not os.path.exists(scoring_path):
    raise FileNotFoundError(f"Nejprve spusť analyze_obce.py: {scoring_path}")

df = pd.read_csv(scoring_path, encoding="utf-8-sig")

# ── výpočet per obec ─────────────────────────────────────────────────────────
df["net_flat_39"]    = df["driving_dist_km"].apply(lambda d: net_order(d, 39.0)).round(1)
df["net_tiered"]     = df["driving_dist_km"].apply(lambda d: net_order(d, tiered_fee(d))).round(1)
df["tiered_fee_kc"]  = df["driving_dist_km"].apply(tiered_fee)
df["min_fee_kc"]     = df["driving_dist_km"].apply(min_delivery_fee)
df["courier_kc"]     = df["driving_dist_km"].apply(courier_fee)
df["net_gain_tiered"] = (df["net_tiered"] - df["net_flat_39"]).round(1)

# Doporučení dopravného
def fee_doporuceni(row):
    if row["min_fee_kc"] <= 39:
        return f"39 Kč (OK, margin ≥ {TARGET_NET_KC:.0f} Kč)"
    if row["min_fee_kc"] <= 99:
        return f"{int(row['tiered_fee_kc'])} Kč (pásmové)"
    return f"{int(row['min_fee_kc'])} Kč (cost-based)"

df["fee_doporuceni"] = df.apply(fee_doporuceni, axis=1)

# ── tisk ─────────────────────────────────────────────────────────────────────
print(f"{'Obec':<30} {'km':>5} {'kurýr':>6} {'flat39':>7} {'pásmové':>8} {'min_fee':>8} {'zisk+':>7}")
print("─" * 80)
for _, r in df.sort_values("driving_dist_km").iterrows():
    gain_str = f"+{r['net_gain_tiered']:.0f}" if r['net_gain_tiered'] > 0 else f"{r['net_gain_tiered']:.0f}"
    print(
        f"{r['nazev']:<30} {r['driving_dist_km']:>5.1f} {r['courier_kc']:>6.0f} "
        f"{r['net_flat_39']:>7.0f} {r['net_tiered']:>8.0f} {r['min_fee_kc']:>8.0f} "
        f"{gain_str:>7}"
    )

# Souhrn
print(f"\n── Souhrn ──────────────────────────────────────────")
print(f"Aktuální flat 39 Kč — průměr net/obj: {df['net_flat_39'].mean():.1f} Kč")
print(f"Pásmové dopravné    — průměr net/obj: {df['net_tiered'].mean():.1f} Kč")
print(f"Průměrné zlepšení při zavedení pásem: +{df['net_gain_tiered'].mean():.1f} Kč/objednávku")
obci_pod_cil = (df["net_flat_39"] < TARGET_NET_KC).sum()
print(f"Obcí kde flat 39 Kč nesplňuje cíl {TARGET_NET_KC:.0f} Kč net: {obci_pod_cil}/{len(df)}")

# ── CSV export ────────────────────────────────────────────────────────────────
cols_out = ["nazev","tier","doporuceni","driving_dist_km","courier_kc",
            "net_flat_39","tiered_fee_kc","net_tiered","net_gain_tiered",
            "min_fee_kc","fee_doporuceni","monthly_contribution_kc"]
csv_path = os.path.join(OUT_DIR, "pricing_optimization.csv")
df[[c for c in cols_out if c in df.columns]].to_csv(csv_path, index=False, encoding="utf-8-sig")
print(f"\nCSV: {csv_path}")

# ── HTML přehled ──────────────────────────────────────────────────────────────
TIER_COLORS = {"A": "#2ecc71", "B": "#f1c40f", "C": "#e74c3c"}

rows_html = ""
for _, r in df.sort_values("driving_dist_km").iterrows():
    gain    = r["net_gain_tiered"]
    gain_cl = "color:#27ae60;font-weight:700" if gain > 10 else ("color:#e67e22" if gain > 0 else "color:#888")
    tc      = TIER_COLORS.get(r.get("tier","C"), "#888")
    rows_html += (
        f"<tr>"
        f"<td><span style='color:{tc};font-weight:700'>{r['nazev']}</span></td>"
        f"<td style='text-align:right'>{r['driving_dist_km']:.1f}</td>"
        f"<td style='text-align:right'>{r['courier_kc']:.0f}</td>"
        f"<td style='text-align:right'>{r['net_flat_39']:.0f}</td>"
        f"<td style='text-align:right'>{r['tiered_fee_kc']:.0f}</td>"
        f"<td style='text-align:right'>{r['net_tiered']:.0f}</td>"
        f"<td style='text-align:right;{gain_cl}'>+{gain:.0f}</td>"
        f"<td style='text-align:right'>{r['min_fee_kc']:.0f}</td>"
        f"<td style='color:#555;font-size:11px'>{r['fee_doporuceni']}</td>"
        f"</tr>\n"
    )

html = f"""<!DOCTYPE html>
<html lang="cs">
<head><meta charset="utf-8">
<title>VečerkaPlus – Optimalizace dopravného</title>
<style>
  body {{ font-family: sans-serif; margin: 24px; color: #222; }}
  h1 {{ font-size: 20px; }}
  .summary {{ background: #f8f9fa; padding: 12px 16px; border-radius: 8px;
              margin-bottom: 20px; font-size: 13px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th {{ background: #f0f0f0; padding: 6px 8px; text-align: left;
        border-bottom: 2px solid #ddd; white-space: nowrap; }}
  td {{ padding: 5px 8px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #fafafa; }}
</style>
</head>
<body>
<h1>VečerkaPlus – Optimalizace dopravného per obec</h1>
<div class="summary">
  <b>Cílový net/objednávku:</b> {TARGET_NET_KC:.0f} Kč &nbsp;·&nbsp;
  <b>Gross (průměr. obj. {AVG_ORDER_KC:.0f} Kč × {AVG_GROSS_MARGIN*100:.0f} %):</b> {GROSS_KC:.0f} Kč &nbsp;·&nbsp;
  <b>Zlepšení zavedením pásem (průměr):</b> +{df['net_gain_tiered'].mean():.1f} Kč/obj
  <br><br>
  <b>Návrh pásem:</b>
  ≤8 km → 39 Kč &nbsp;|&nbsp; 8–15 km → 69 Kč &nbsp;|&nbsp; 15–20 km → 99 Kč &nbsp;|&nbsp; >20 km → 149 Kč
  &nbsp;(dopravné zdarma ≥ 1 000 Kč)
</div>
<table>
  <tr>
    <th>Obec</th>
    <th style="text-align:right">km</th>
    <th style="text-align:right">Kurýr</th>
    <th style="text-align:right">Net flat 39</th>
    <th style="text-align:right">Pásmové Kč</th>
    <th style="text-align:right">Net pásmové</th>
    <th style="text-align:right">Δ net</th>
    <th style="text-align:right">Min. fee</th>
    <th>Doporučení</th>
  </tr>
  {rows_html}
</table>
<p style="color:#888;font-size:11px;margin-top:16px">
  Generováno: 2026-06-10 · Avg objednávka {AVG_ORDER_KC:.0f} Kč · Marže {AVG_GROSS_MARGIN*100:.0f} %
</p>
</body></html>"""

html_path = os.path.join(OUT_DIR, "pricing_optimization.html")
with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"HTML: {html_path}")
print("\nHotovo ✓")
