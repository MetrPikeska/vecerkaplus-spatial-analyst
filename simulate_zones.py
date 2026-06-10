"""
VečerkaPlus – P&L scénáře dle rozvozové zóny (náhodné adresy)
==============================================================
Pro každou rozvozovou zónu (5/10/15/20 km) vzorkuje náhodné adresy
uvnitř polygonu, počítá reálné jízdní vzdálenosti přes OSMnx graf
a simuluje Monte Carlo P&L s empirickou distribucí vzdáleností.

Výstupy:
  output/zone_scenarios.json    — P&L statistiky per zóna × scénář
  output/zone_distances.csv     — empirické vzdálenosti vzorků
  output/zone_scenarios.html    — interaktivní mapa s náhodnými body
"""

import warnings
warnings.filterwarnings("ignore")

import os, json, time
import numpy as np
import pandas as pd
import geopandas as gpd
import networkx as nx
import osmnx as ox
import folium
from shapely.geometry import Point

# ── konstanty ─────────────────────────────────────────────────────────────────
FM_LAT, FM_LON   = 49.6754886, 18.3389397
CRS_METRIC       = "EPSG:5514"
CRS_WGS          = "EPSG:4326"
N_SAMPLES        = 400    # náhodných bodů per zóna
N_TRIALS         = 5_000
N_MONTHS         = 12

ORDER_VALUE_MEAN  = 452.0
ORDER_VALUE_STD   = 140.0
AVG_GROSS_MARGIN  = 0.365
FREE_DELIVERY_THR = 1_000.0   # ≥ 1 000 Kč → dopravné zdarma
DELIVERY_FEE_Z12  = 39.0      # zákazník ≤ 20 km jízdní vzdálenosti
DELIVERY_FEE_Z3   = 164.0     # zákazník > 20 km
COURIER_FEE_Z1    = 120.0     # kurýr ≤ 10 km
COURIER_FEE_Z2    = 180.0     # kurýr 10–20 km
COURIER_FEE_Z3    = 250.0     # kurýr > 20 km

SCENARIOS = {
    "konzervativni": 1.0,
    "cilovy":        3.0,
    "optimisticky":  7.0,
}

ZONES = {
    "5 km":  "google_zone_5km.geojson",
    "10 km": "google_zone_10km.geojson",
    "15 km": "google_zone_15km.geojson",
    "20 km": "google_zone_20km.geojson",
}

ZONE_COLORS = {
    "5 km":  "#00e676",
    "10 km": "#ffd740",
    "15 km": "#ff9800",
    "20 km": "#e74c3c",
}

# Prstencová analýza — marginální pásma
RINGS = {
    "0–5 km":   ("google_zone_5km.geojson",  None),
    "5–10 km":  ("google_zone_10km.geojson", "google_zone_5km.geojson"),
    "10–15 km": ("google_zone_15km.geojson", "google_zone_10km.geojson"),
    "15–20 km": ("google_zone_20km.geojson", "google_zone_15km.geojson"),
}
RING_COLORS = {
    "0–5 km":   "#00e676",
    "5–10 km":  "#ffd740",
    "10–15 km": "#ff9800",
    "15–20 km": "#e74c3c",
}

# Scénáře dopravného: flat (aktuální) vs. 4-pásmové
PRICING_SCENARIOS = {
    "flat_39kc": {
        "label": "Aktuální (flat 39 Kč)",
        "fee_fn": lambda v, d: (
            0.0 if v >= FREE_DELIVERY_THR else (39.0 if d <= 20 else 164.0)
        ),
    },
    "tiered": {
        "label": "Pásmové dopravné",
        "fee_fn": lambda v, d: (
            0.0 if v >= 1_000.0 else
            (39.0 if d <= 8 else 69.0 if d <= 15 else 99.0 if d <= 20 else 149.0)
        ),
    },
}

DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR     = os.path.join(os.path.dirname(__file__), "output")
GRAPH_CACHE = os.path.join(DATA_DIR, "osm_fm_drive.graphml")

os.makedirs(OUT_DIR, exist_ok=True)
rng = np.random.default_rng(42)

# ── 1. OSM graf + single-source Dijkstra ──────────────────────────────────────
print("=== 1. OSM silniční graf ===")
G = ox.load_graphml(GRAPH_CACHE)

edges_gdf = ox.graph_to_gdfs(G, nodes=False)
if "travel_time" not in edges_gdf.columns:
    print("   Přepočítávám časy jízdy…")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

orig_node = ox.nearest_nodes(G, FM_LON, FM_LAT)
print(f"   Výchozí uzel: {orig_node}")

print("   Dijkstra (jízdní vzdálenost ke všem uzlům)…")
t0 = time.time()
dist_m_dict = nx.single_source_dijkstra_path_length(G, orig_node, weight="length")
print(f"   {len(dist_m_dict):,} uzlů za {time.time()-t0:.1f}s")

# ── 2. Vzorkování náhodných adres ─────────────────────────────────────────────
print("\n=== 2. Vzorkování náhodných adres ===")

def sample_points_in_polygon(polygon_m, n):
    """Rejection sampling náhodných bodů uvnitř polygonu (metrické CRS)."""
    minx, miny, maxx, maxy = polygon_m.bounds
    pts = []
    while len(pts) < n:
        xs = rng.uniform(minx, maxx, n * 8)
        ys = rng.uniform(miny, maxy, n * 8)
        for x, y in zip(xs, ys):
            if polygon_m.contains(Point(x, y)):
                pts.append(Point(x, y))
            if len(pts) >= n:
                break
    return pts[:n]

zone_dists   = {}   # {zone: np.array of driving km}
zone_pts_wgs = {}   # {zone: GeoDataFrame WGS84}

for zone_name, zone_file in ZONES.items():
    path = os.path.join(DATA_DIR, zone_file)
    gdf  = gpd.read_file(path).to_crs(CRS_METRIC)
    poly = gdf.geometry.unary_union

    pts_m   = sample_points_in_polygon(poly, N_SAMPLES)
    pts_gdf = gpd.GeoDataFrame(geometry=pts_m, crs=CRS_METRIC).to_crs(CRS_WGS)

    nodes   = ox.nearest_nodes(G,
        pts_gdf.geometry.x.values,
        pts_gdf.geometry.y.values,
    )
    dists   = np.array([dist_m_dict.get(n, np.nan) / 1000.0 for n in nodes])
    valid   = ~np.isnan(dists)
    dists   = dists[valid]
    pts_gdf = pts_gdf[valid].reset_index(drop=True)

    zone_dists[zone_name]   = dists
    zone_pts_wgs[zone_name] = pts_gdf

    pct_z1 = (dists <= 10).mean() * 100
    pct_z2 = ((dists > 10) & (dists <= 20)).mean() * 100
    pct_z3 = (dists > 20).mean() * 100
    print(
        f"   {zone_name}: median={np.median(dists):.1f} km | "
        f"≤10km {pct_z1:.0f}%  10–20km {pct_z2:.0f}%  >20km {pct_z3:.0f}%"
    )

# ── 3. Monte Carlo P&L (vectorized) ──────────────────────────────────────────
print("\n=== 3. Monte Carlo P&L ===")

def courier_cost(dists):
    return np.where(dists <= 10, COURIER_FEE_Z1,
           np.where(dists <= 20, COURIER_FEE_Z2, COURIER_FEE_Z3))

def customer_fee(values, dists):
    return np.where(
        values >= FREE_DELIVERY_THR, 0.0,
        np.where(dists <= 20, DELIVERY_FEE_Z12, DELIVERY_FEE_Z3),
    )

def simulate_zone(dist_samples, lambda_per_week):
    results = np.zeros((N_TRIALS, N_MONTHS))
    for month in range(N_MONTHS):
        n_weeks    = 4 if (month % 3 != 2) else 5
        n_orders   = rng.poisson(lambda_per_week * n_weeks, size=N_TRIALS)
        max_orders = max(1, int(n_orders.max()))

        vals  = rng.normal(ORDER_VALUE_MEAN, ORDER_VALUE_STD, (N_TRIALS, max_orders)).clip(200, 2000)
        didx  = rng.integers(0, len(dist_samples), (N_TRIALS, max_orders))
        dists = dist_samples[didx]

        gross = vals * AVG_GROSS_MARGIN
        net   = gross + customer_fee(vals, dists) - courier_cost(dists)

        mask              = np.arange(max_orders)[np.newaxis, :] < n_orders[:, np.newaxis]
        results[:, month] = (net * mask).sum(axis=1)
    return results

all_results = {}

for zone_name, dists_km in zone_dists.items():
    all_results[zone_name] = {}
    avg_courier = float(np.mean(courier_cost(dists_km)))

    for sc_name, lam in SCENARIOS.items():
        arr    = simulate_zone(dists_km, lam)
        annual = arr.sum(axis=1)

        all_results[zone_name][sc_name] = {
            "lambda_per_week":  lam,
            "n_samples":        int(len(dists_km)),
            "dist_median_km":   round(float(np.median(dists_km)), 2),
            "dist_p95_km":      round(float(np.percentile(dists_km, 95)), 2),
            "avg_courier_kc":   round(avg_courier, 1),
            "pct_zone1":        round(float((dists_km <= 10).mean() * 100), 1),
            "pct_zone2":        round(float(((dists_km > 10) & (dists_km <= 20)).mean() * 100), 1),
            "pct_zone3":        round(float((dists_km > 20).mean() * 100), 1),
            "annual_p5":        round(float(np.percentile(annual,  5)), 0),
            "annual_p25":       round(float(np.percentile(annual, 25)), 0),
            "annual_p50":       round(float(np.percentile(annual, 50)), 0),
            "annual_p75":       round(float(np.percentile(annual, 75)), 0),
            "annual_p95":       round(float(np.percentile(annual, 95)), 0),
            "monthly_p50":      {
                str(m + 1): round(float(np.percentile(arr[:, m], 50)), 1)
                for m in range(N_MONTHS)
            },
        }

        r = all_results[zone_name][sc_name]
        print(
            f"   {zone_name} × {sc_name:15s} (λ={lam:.0f}/týd) → "
            f"roční p50={r['annual_p50']:>7,.0f} Kč  "
            f"[p25={r['annual_p25']:>7,.0f}  p95={r['annual_p95']:>7,.0f}]"
        )

out_json = os.path.join(OUT_DIR, "zone_scenarios.json")
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(all_results, f, ensure_ascii=False, indent=2)
print(f"\nJSON: {out_json}")

# ── 4. Prstencová analýza ─────────────────────────────────────────────────────
print("\n=== 4. Prstencová analýza (marginální pásma) ===")

ring_dists   = {}
ring_pts_wgs = {}

for ring_name, (outer_file, inner_file) in RINGS.items():
    outer_gdf = gpd.read_file(os.path.join(DATA_DIR, outer_file)).to_crs(CRS_METRIC)
    outer_poly = outer_gdf.geometry.unary_union
    if inner_file:
        inner_gdf  = gpd.read_file(os.path.join(DATA_DIR, inner_file)).to_crs(CRS_METRIC)
        ring_poly  = outer_poly.difference(inner_gdf.geometry.unary_union)
    else:
        ring_poly = outer_poly

    pts_m   = sample_points_in_polygon(ring_poly, N_SAMPLES)
    pts_gdf = gpd.GeoDataFrame(geometry=pts_m, crs=CRS_METRIC).to_crs(CRS_WGS)
    nodes   = ox.nearest_nodes(G, pts_gdf.geometry.x.values, pts_gdf.geometry.y.values)
    dists   = np.array([dist_m_dict.get(n, np.nan) / 1000.0 for n in nodes])
    valid   = ~np.isnan(dists)
    dists   = dists[valid]
    pts_gdf = pts_gdf[valid].reset_index(drop=True)

    ring_dists[ring_name]   = dists
    ring_pts_wgs[ring_name] = pts_gdf
    print(f"   {ring_name}: {len(dists)} bodů | median={np.median(dists):.1f} km | avg kurýr={np.mean(courier_cost(dists)):.0f} Kč")

ring_results = {}
for ring_name, dists_km in ring_dists.items():
    ring_results[ring_name] = {}
    for sc_name, lam in SCENARIOS.items():
        arr    = simulate_zone(dists_km, lam)
        annual = arr.sum(axis=1)
        ring_results[ring_name][sc_name] = {
            "annual_p50": round(float(np.percentile(annual, 50)), 0),
            "annual_p25": round(float(np.percentile(annual, 25)), 0),
            "annual_p95": round(float(np.percentile(annual, 95)), 0),
            "avg_dist_km":    round(float(np.mean(dists_km)), 2),
            "avg_courier_kc": round(float(np.mean(courier_cost(dists_km))), 1),
        }
        p50 = ring_results[ring_name][sc_name]["annual_p50"]
        print(f"   {ring_name} × {sc_name:15s} → roční p50={p50:>7,.0f} Kč")

ring_json = os.path.join(OUT_DIR, "ring_scenarios.json")
with open(ring_json, "w", encoding="utf-8") as f:
    json.dump(ring_results, f, ensure_ascii=False, indent=2)
print(f"\nJSON: {ring_json}")

# ── 5. Scénáře dopravného ─────────────────────────────────────────────────────
print("\n=== 5. Scénáře dopravného (flat vs. pásmové) ===")

# Testujeme na provozní 20 km zóně, cílový scénář λ=3/týden
dists_op   = zone_dists["20 km"]
pricing_results = {}
for pricing_key, pricing in PRICING_SCENARIOS.items():
    fee_fn = pricing["fee_fn"]

    results = np.zeros((N_TRIALS, N_MONTHS))
    for month in range(N_MONTHS):
        n_weeks  = 4 if (month % 3 != 2) else 5
        n_orders = rng.poisson(SCENARIOS["cilovy"] * n_weeks, size=N_TRIALS)
        max_ord  = max(1, int(n_orders.max()))

        vals  = rng.normal(ORDER_VALUE_MEAN, ORDER_VALUE_STD, (N_TRIALS, max_ord)).clip(200, 2000)
        didx  = rng.integers(0, len(dists_op), (N_TRIALS, max_ord))
        dists = dists_op[didx]

        fees  = np.vectorize(fee_fn)(vals, dists)
        gross = vals * AVG_GROSS_MARGIN
        net   = gross + fees - courier_cost(dists)
        mask  = np.arange(max_ord)[np.newaxis, :] < n_orders[:, np.newaxis]
        results[:, month] = (net * mask).sum(axis=1)

    annual = results.sum(axis=1)
    avg_fee = float(np.mean([fee_fn(ORDER_VALUE_MEAN, d) for d in dists_op]))
    pricing_results[pricing_key] = {
        "label":      pricing["label"],
        "avg_fee_kc": round(avg_fee, 1),
        "annual_p25": round(float(np.percentile(annual, 25)), 0),
        "annual_p50": round(float(np.percentile(annual, 50)), 0),
        "annual_p95": round(float(np.percentile(annual, 95)), 0),
    }
    r = pricing_results[pricing_key]
    print(f"   {pricing['label']:30s}: avg dopravné={r['avg_fee_kc']:.0f} Kč | roční p50={r['annual_p50']:>7,.0f} Kč")

pricing_json = os.path.join(OUT_DIR, "pricing_scenarios.json")
with open(pricing_json, "w", encoding="utf-8") as f:
    json.dump(pricing_results, f, ensure_ascii=False, indent=2)
print(f"JSON: {pricing_json}")

# ── 6. CSV vzdáleností ────────────────────────────────────────────────────────
dist_rows = []
for zone_name, dists in zone_dists.items():
    for d in dists:
        dist_rows.append({
            "zone":        zone_name,
            "dist_km":     round(float(d), 2),
            "courier_fee": int(courier_cost(np.array([d]))[0]),
        })
dist_csv = os.path.join(OUT_DIR, "zone_distances.csv")
pd.DataFrame(dist_rows).to_csv(dist_csv, index=False)
print(f"CSV: {dist_csv}")

# ── 8. Folium mapa ────────────────────────────────────────────────────────────
print("\n=== 8. Folium mapa ===")
m = folium.Map([FM_LAT, FM_LON], zoom_start=11,
               tiles="CartoDB Positron", prefer_canvas=True)

# Zóny (od největší → správné pořadí vrstev)
for zone_name in reversed(list(ZONES.keys())):
    gdf   = gpd.read_file(os.path.join(DATA_DIR, ZONES[zone_name]))
    color = ZONE_COLORS[zone_name]
    folium.GeoJson(
        gdf.to_crs(CRS_WGS).geometry.iloc[0].__geo_interface__,
        name=f"Zóna {zone_name}",
        style_function=lambda _, c=color: {
            "fillColor": c, "color": c, "weight": 2,
            "fillOpacity": 0.06, "dashArray": "5,4",
        },
    ).add_to(m)

# Náhodné body (max 120 per zone, vizualizace)
for zone_name, pts_gdf in zone_pts_wgs.items():
    color    = ZONE_COLORS[zone_name]
    dists    = zone_dists[zone_name]
    show     = zone_name == "20 km"
    grp      = folium.FeatureGroup(name=f"Vzorky – {zone_name}", show=show)
    n_vis    = min(120, len(pts_gdf))
    vis_idx  = rng.choice(len(pts_gdf), n_vis, replace=False)
    for i in vis_idx:
        pt      = pts_gdf.geometry.iloc[i]
        d       = float(dists[i])
        courier = int(courier_cost(np.array([d]))[0])
        est_fee = 0 if ORDER_VALUE_MEAN >= FREE_DELIVERY_THR else (
            DELIVERY_FEE_Z12 if d <= 20 else DELIVERY_FEE_Z3
        )
        folium.CircleMarker(
            [pt.y, pt.x], radius=4,
            color=color, weight=1,
            fill_color=color, fill_opacity=0.75,
            tooltip=(
                f"<b>Zóna {zone_name}</b><br>"
                f"Jízdní vzdálenost: <b>{d:.1f} km</b><br>"
                f"Kurýr paušál: <b>{courier} Kč</b><br>"
                f"Dopravné zákazník (průměr. obj.): <b>{int(est_fee)} Kč</b>"
            ),
        ).add_to(grp)
    grp.add_to(m)

# Reální zákazníci
zak_path = os.path.join(DATA_DIR, "zakaznici.csv")
if os.path.exists(zak_path):
    zak = pd.read_csv(zak_path).dropna(subset=["lat", "lng"])
    grp_zak = folium.FeatureGroup(name="Reální zákazníci", show=True)
    for _, r in zak.iterrows():
        d = float(r.vzdalenost_km)
        folium.CircleMarker(
            [r.lat, r.lng], radius=9,
            color="#fff", weight=2,
            fill_color="#c62828", fill_opacity=0.95,
            tooltip=(
                f"<b>#{int(r.id)} – {r.get('jmeno', '')}</b><br>"
                f"Tržba: {int(r.trzba_kc)} Kč | Vzdálenost: {d:.1f} km<br>"
                f"Dopravné zákazník: {int(r.dopravne_zakaznik_kc)} Kč"
            ),
        ).add_to(grp_zak)
    grp_zak.add_to(m)

# Výchozí bod
folium.Marker(
    [FM_LAT, FM_LON],
    tooltip="Výchozí bod (byt řidiče)",
    icon=folium.DivIcon(
        html='<div style="font-size:22px;filter:drop-shadow(1px 1px 2px #fff)">🏠</div>',
        icon_size=(28, 28), icon_anchor=(14, 14),
    ),
).add_to(m)

# ── Legenda: srovnávací tabulka P&L ──────────────────────────────────────────
header_row = (
    "<tr style='color:#888;font-size:10px'>"
    "<th>Zóna</th><th>Scénář</th>"
    "<th style='text-align:right'>Méd. dist.</th>"
    "<th style='text-align:right'>Avg kurýr</th>"
    "<th style='text-align:right'>p25 Kč/rok</th>"
    "<th style='text-align:right'>p50 Kč/rok</th>"
    "<th style='text-align:right'>p95 Kč/rok</th>"
    "</tr>"
)
table_rows = ""
for zone_name in ZONES:
    color = ZONE_COLORS[zone_name]
    for sc_name in SCENARIOS:
        r = all_results[zone_name][sc_name]
        table_rows += (
            f"<tr>"
            f"<td><span style='color:{color}'>■</span> {zone_name}</td>"
            f"<td>{sc_name}</td>"
            f"<td style='text-align:right'>{r['dist_median_km']:.1f} km</td>"
            f"<td style='text-align:right'>{r['avg_courier_kc']:.0f} Kč</td>"
            f"<td style='text-align:right'>{r['annual_p25']:,.0f}</td>"
            f"<td style='text-align:right'><b>{r['annual_p50']:,.0f}</b></td>"
            f"<td style='text-align:right'>{r['annual_p95']:,.0f}</td>"
            f"</tr>"
        )

legend_html = f"""
<div style="position:fixed;bottom:20px;right:20px;z-index:9999;
  background:white;border:1px solid #ddd;border-radius:10px;
  padding:14px 18px;font-family:sans-serif;font-size:11px;
  box-shadow:2px 2px 10px rgba(0,0,0,.18);min-width:560px;
  max-height:420px;overflow-y:auto">
  <b style="font-size:13px">VečerkaPlus – P&L dle rozvozové zóny</b>
  <div style="color:#888;font-size:10px;margin-bottom:6px">
    Monte Carlo {N_TRIALS:,} iterací × {N_MONTHS} měsíců | empirická distribuce vzdáleností
  </div>
  <table style="width:100%;border-collapse:collapse">
    {header_row}
    {table_rows}
  </table>
  <hr style="margin:8px 0">
  <small style="color:#888">
    Kurýr: ≤10km={COURIER_FEE_Z1:.0f}Kč | 10–20km={COURIER_FEE_Z2:.0f}Kč | >20km={COURIER_FEE_Z3:.0f}Kč &nbsp;·&nbsp;
    Dopravné zákazník zdarma ≥{FREE_DELIVERY_THR:.0f}Kč
  </small>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

out_map = os.path.join(OUT_DIR, "zone_scenarios.html")
m.save(out_map)
print(f"Mapa: {out_map}")
print("\nHotovo ✓")
