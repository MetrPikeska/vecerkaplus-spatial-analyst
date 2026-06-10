"""
VečerkaPlus – Monte Carlo P&L projekce
=======================================
5 000 trialů × 12 měsíců pro 3 scénáře poptávky.
Analýza citlivosti (tornado chart) pro klíčové parametry.

Výstupy:
  output/monte_carlo_results.csv   — 5000 × 12 řádků per scénář
  output/monte_carlo_summary.json  — p5/p25/p50/p75/p95 per měsíc per scénář
  output/sensitivity_analysis.csv  — tornado data
"""

import os, json
import numpy as np
import pandas as pd

# ── konstanty ─────────────────────────────────────────────────────────────────
N_TRIALS   = 5_000
N_MONTHS   = 12
N_WEEKS_MO = 4.33

# Distribuce z dat (zakaznici.csv, 7 objednávek)
ORDER_VALUE_MEAN = 452.0
ORDER_VALUE_STD  = 140.0
DIST_KM_MEAN     = 6.7
DIST_KM_STD      = 6.5

# Lognormální parametry pro vzdálenosti (pravostranně sešikmené — většina blízko, výjimky daleko)
import math as _math
_DIST_SIGMA = _math.sqrt(_math.log(1 + DIST_KM_STD**2 / DIST_KM_MEAN**2))  # ≈ 0.815
_DIST_MU    = _math.log(DIST_KM_MEAN) - _DIST_SIGMA**2 / 2                 # ≈ 1.570

# Fixní měsíční náklady (telefon, data, pojištění vozidla, platforma)
FIXED_COSTS_MONTHLY = 800.0   # Kč/měsíc

# Ramp-up: lambda roste od 0 exponenciálně na cílovou hodnotu s tau=4 měsíce
RAMP_TAU_MONTHS = 4.0

AVG_GROSS_MARGIN = 0.365
DELIVERY_FEE_Z12 = 39.0    # ≤ 20 km dopravné zákazníka
DELIVERY_FEE_Z3  = 164.0   # > 20 km
COURIER_FEE_Z1   = 120.0   # ≤ 10 km paušál kurýrovi
COURIER_FEE_Z2   = 180.0   # 10–20 km
COURIER_FEE_Z3   = 250.0   # > 20 km

SCENARIOS = {
    "konzervativni": 1.0,
    "cilovy":        3.0,
    "optimisticky":  7.0,
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

rng = np.random.default_rng(42)

# ── pomocné funkce ─────────────────────────────────────────────────────────────

def net_per_order(order_value, dist_km,
                  gross_margin=AVG_GROSS_MARGIN,
                  delivery_fee_z12=DELIVERY_FEE_Z12,
                  courier_z1=COURIER_FEE_Z1,
                  courier_z2=COURIER_FEE_Z2,
                  courier_z3=COURIER_FEE_Z3):
    gross = order_value * gross_margin
    if dist_km <= 10:
        return gross + delivery_fee_z12 - courier_z1
    elif dist_km <= 20:
        return gross + delivery_fee_z12 - courier_z2
    else:
        return gross + DELIVERY_FEE_Z3 - courier_z3


def run_trials(lambda_per_week, n_trials=N_TRIALS, n_months=N_MONTHS, **kwargs):
    """Vrátí (n_trials × n_months) array měsíčního P&L.

    Vylepšení oproti v1:
    - Lognormální vzdálenosti (pravostranně sešikmené, reálnější než symetrická Normal)
    - Ramp-up: lambda roste exponenciálně na cílovou hodnotu (tau=RAMP_TAU_MONTHS)
    - Fixní náklady: odečteny každý měsíc
    """
    results = np.zeros((n_trials, n_months))
    for month in range(n_months):
        # Ramp-up: efektivní lambda pro tento měsíc
        ramp = 1.0 - np.exp(-(month + 1) / RAMP_TAU_MONTHS)
        effective_lam = lambda_per_week * ramp

        n_weeks = 4 if (month % 3 != 2) else 5
        n_orders_per_trial = rng.poisson(effective_lam * n_weeks, size=n_trials)
        for trial_idx in range(n_trials):
            n = int(n_orders_per_trial[trial_idx])
            if n == 0:
                results[trial_idx, month] = -FIXED_COSTS_MONTHLY
                continue
            values  = rng.normal(ORDER_VALUE_MEAN, ORDER_VALUE_STD, n).clip(200, 2000)
            dists   = rng.lognormal(_DIST_MU, _DIST_SIGMA, n).clip(0.5, 35)
            monthly = sum(net_per_order(v, d, **kwargs) for v, d in zip(values, dists))
            results[trial_idx, month] = monthly - FIXED_COSTS_MONTHLY
    return results


# ── 1. Simulace scénářů ───────────────────────────────────────────────────────
print("=== Monte Carlo P&L simulace ===")
print(f"N_TRIALS={N_TRIALS}, N_MONTHS={N_MONTHS}")

all_rows   = []
mc_summary = {}

for scenario_name, lam in SCENARIOS.items():
    print(f"\nScénář '{scenario_name}' — λ={lam} obj/týden…")
    arr = run_trials(lam)          # shape (N_TRIALS, N_MONTHS)

    # percentily per měsíc
    pcts = np.percentile(arr, [5, 25, 50, 75, 95], axis=0)
    mc_summary[scenario_name] = {
        "lambda_per_week": lam,
        "months": {
            str(m + 1): {
                "p5":   round(pcts[0, m], 1),
                "p25":  round(pcts[1, m], 1),
                "p50":  round(pcts[2, m], 1),
                "p75":  round(pcts[3, m], 1),
                "p95":  round(pcts[4, m], 1),
            }
            for m in range(N_MONTHS)
        },
        "annual_p50": round(float(arr.sum(axis=1).mean()), 0),
        "annual_p5":  round(float(np.percentile(arr.sum(axis=1), 5)), 0),
        "annual_p95": round(float(np.percentile(arr.sum(axis=1), 95)), 0),
    }
    print(f"   Roční P50 = {mc_summary[scenario_name]['annual_p50']:.0f} Kč  "
          f"[p5={mc_summary[scenario_name]['annual_p5']:.0f}, p95={mc_summary[scenario_name]['annual_p95']:.0f}]")

    # CSV řádky (vzorkování — 500 trialů × 12 měsíců kvůli velikosti)
    for trial_i in range(min(500, N_TRIALS)):
        for month_j in range(N_MONTHS):
            all_rows.append({
                "scenario": scenario_name,
                "trial": trial_i,
                "month": month_j + 1,
                "monthly_pl_kc": round(arr[trial_i, month_j], 2),
            })

results_df = pd.DataFrame(all_rows)
results_path = os.path.join(OUT_DIR, "monte_carlo_results.csv")
results_df.to_csv(results_path, index=False)
print(f"\nVýsledky uloženy: {results_path} ({len(results_df)} řádků)")

# ── 2. Analýza citlivosti (tornado) ──────────────────────────────────────────
print("\n=== Analýza citlivosti (tornado) ===")

BASE_LAM = SCENARIOS["cilovy"]
VARIATION = 0.30

params = {
    "Průměrná tržba/obj":    ("order_value_mean",  ORDER_VALUE_MEAN,  ORDER_VALUE_MEAN * (1 - VARIATION),  ORDER_VALUE_MEAN * (1 + VARIATION)),
    "Hrubá marže":           ("gross_margin",      AVG_GROSS_MARGIN,  AVG_GROSS_MARGIN * (1 - VARIATION),  AVG_GROSS_MARGIN * (1 + VARIATION)),
    "Dopravné zákazníka":    ("delivery_fee_z12",  DELIVERY_FEE_Z12,  DELIVERY_FEE_Z12 * (1 - VARIATION),  DELIVERY_FEE_Z12 * (1 + VARIATION)),
    "Kurýr 10–20 km paušál": ("courier_z2",        COURIER_FEE_Z2,    COURIER_FEE_Z2 * (1 - VARIATION),    COURIER_FEE_Z2 * (1 + VARIATION)),
    "Průměrná vzdálenost":   ("dist_mean",         DIST_KM_MEAN,      DIST_KM_MEAN * (1 - VARIATION),      DIST_KM_MEAN * (1 + VARIATION)),
}

# base P50 (cílový scénář)
base_arr = run_trials(BASE_LAM)
base_p50 = float(np.median(base_arr.sum(axis=1)))
print(f"   Základní roční P50 (cílový λ={BASE_LAM}): {base_p50:.0f} Kč")

tornado_rows = []
for label, (param_key, base_val, low_val, high_val) in params.items():
    kw_low  = {}
    kw_high = {}
    if param_key == "order_value_mean":
        def _run_with_mean(mean_val, lam):
            arr = np.zeros((N_TRIALS, N_MONTHS))
            for month in range(N_MONTHS):
                ramp     = 1.0 - np.exp(-(month + 1) / RAMP_TAU_MONTHS)
                n_weeks  = 4 if (month % 3 != 2) else 5
                n_orders = rng.poisson(lam * ramp * n_weeks, size=N_TRIALS)
                for i in range(N_TRIALS):
                    n = int(n_orders[i])
                    arr[i, month] = -FIXED_COSTS_MONTHLY
                    if n == 0:
                        continue
                    values = rng.normal(mean_val, ORDER_VALUE_STD, n).clip(200, 2000)
                    dists  = rng.lognormal(_DIST_MU, _DIST_SIGMA, n).clip(0.5, 35)
                    arr[i, month] += sum(net_per_order(v, d) for v, d in zip(values, dists))
            return arr
        low_p50  = float(np.median(_run_with_mean(low_val,  BASE_LAM).sum(axis=1)))
        high_p50 = float(np.median(_run_with_mean(high_val, BASE_LAM).sum(axis=1)))
    elif param_key == "gross_margin":
        low_p50  = float(np.median(run_trials(BASE_LAM, gross_margin=low_val).sum(axis=1)))
        high_p50 = float(np.median(run_trials(BASE_LAM, gross_margin=high_val).sum(axis=1)))
    elif param_key == "delivery_fee_z12":
        low_p50  = float(np.median(run_trials(BASE_LAM, delivery_fee_z12=low_val).sum(axis=1)))
        high_p50 = float(np.median(run_trials(BASE_LAM, delivery_fee_z12=high_val).sum(axis=1)))
    elif param_key == "courier_z2":
        low_p50  = float(np.median(run_trials(BASE_LAM, courier_z2=low_val).sum(axis=1)))
        high_p50 = float(np.median(run_trials(BASE_LAM, courier_z2=high_val).sum(axis=1)))
    elif param_key == "dist_mean":
        def _run_with_dist(dist_mean_val, lam):
            # Přepočítat lognormal parametry pro daný mean (std proporcionálně)
            import math as _m
            ratio   = dist_mean_val / DIST_KM_MEAN
            sigma_v = _DIST_SIGMA
            mu_v    = _m.log(dist_mean_val) - sigma_v**2 / 2
            arr = np.zeros((N_TRIALS, N_MONTHS))
            for month in range(N_MONTHS):
                ramp     = 1.0 - np.exp(-(month + 1) / RAMP_TAU_MONTHS)
                n_weeks  = 4 if (month % 3 != 2) else 5
                n_orders = rng.poisson(lam * ramp * n_weeks, size=N_TRIALS)
                for i in range(N_TRIALS):
                    n = int(n_orders[i])
                    arr[i, month] = -FIXED_COSTS_MONTHLY
                    if n == 0:
                        continue
                    values = rng.normal(ORDER_VALUE_MEAN, ORDER_VALUE_STD, n).clip(200, 2000)
                    dists  = rng.lognormal(mu_v, sigma_v, n).clip(0.5, 35)
                    arr[i, month] += sum(net_per_order(v, d) for v, d in zip(values, dists))
            return arr
        low_p50  = float(np.median(_run_with_dist(low_val,  BASE_LAM).sum(axis=1)))
        high_p50 = float(np.median(_run_with_dist(high_val, BASE_LAM).sum(axis=1)))
    else:
        low_p50 = high_p50 = base_p50

    delta_low  = low_p50  - base_p50
    delta_high = high_p50 - base_p50
    swing      = abs(high_p50 - low_p50)
    tornado_rows.append({
        "parameter": label,
        "base_value": round(base_val, 3),
        "low_value":  round(low_val, 3),
        "high_value": round(high_val, 3),
        "low_p50_kc":   round(low_p50, 0),
        "high_p50_kc":  round(high_p50, 0),
        "delta_low_kc": round(delta_low, 0),
        "delta_high_kc": round(delta_high, 0),
        "swing_kc":     round(swing, 0),
    })
    print(f"   {label}: base={base_val:.2f} → [{low_p50:.0f}, {high_p50:.0f}] (swing {swing:.0f} Kč)")

tornado_df = pd.DataFrame(tornado_rows).sort_values("swing_kc", ascending=False)
sens_path = os.path.join(OUT_DIR, "sensitivity_analysis.csv")
tornado_df.to_csv(sens_path, index=False)
print(f"\nCitlivost uložena: {sens_path}")

# ── 3. Breakeven analýza ──────────────────────────────────────────────────────
print("\n=== Breakeven analýza ===")
breakeven = {}
for scenario_name, lam in SCENARIOS.items():
    arr = run_trials(lam)
    annual = arr.sum(axis=1)
    p25 = float(np.percentile(annual, 25))
    breakeven[scenario_name] = {
        "lambda": lam,
        "annual_p25": round(p25, 0),
        "breakeven_positive": p25 > 0,
    }
    status = "✓ p25 > 0" if p25 > 0 else "✗ p25 < 0"
    print(f"   λ={lam} obj/týden — roční p25 = {p25:.0f} Kč  {status}")

mc_summary["breakeven"] = breakeven

# Uložit kompletní summary
with open(os.path.join(OUT_DIR, "monte_carlo_summary.json"), "w", encoding="utf-8") as f:
    json.dump(mc_summary, f, ensure_ascii=False, indent=2)
print(f"\nSouhrn uložen: {os.path.join(OUT_DIR, 'monte_carlo_summary.json')}")
print("\nHotovo ✓")
