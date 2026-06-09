"""
VečerkaPlus – P&L scoring obcí v rozvozové zóně
================================================
Pro každou obec v Google ≤20 km zóně počítáme:
  1. Tržní potenciál (počet domácností) — váha 35 %
  2. P&L per objednávka (čistý příspěvek po odečtení kurýra) — váha 30 %
  3. Bytová zástavba (podíl bytových domů ≥4 byty) — váha 20 %
  4. Nightlife hustota (POI/1000 obyvatel) — váha 15 %

Výstup: output/obce_scoring.csv + output/obce_analyza.html
"""

import warnings
warnings.filterwarnings("ignore")

import os, json, re, math
import pandas as pd
import geopandas as gpd
import numpy as np
import folium
from shapely.geometry import Point

# ── konstanty ─────────────────────────────────────────────────────────────────
FM_LAT, FM_LON = 49.6754886, 18.3389397
CRS_METRIC = "EPSG:5514"
CRS_WGS    = "EPSG:4326"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")

# P&L parametry (shodné s kontextem projektu)
AVG_ORDER_KC      = 452    # průměr ze zakaznici.csv (7 objednávek)
AVG_GROSS_MARGIN  = 0.365  # hrubá marže z marže analýzy
COURIER_FEE_Z1    = 120    # kurýr paušál ≤10 km
COURIER_FEE_Z2    = 180    # kurýr paušál 10–20 km
COURIER_FEE_Z3    = 250    # kurýr paušál >20 km
DELIVERY_FEE_Z12  = 39     # zákazník platí dopravné ≤20 km (průměr z dat)
DELIVERY_FEE_Z3   = 164    # zákazník platí dopravné >20 km (průměr 149+179/2)
CONVERSION_RATE   = 0.002  # 0.2 % domácností/měsíc (base rate odhad)

# Vyřazené obce dle delivery-zones.ts
VYRAZENE = {"Ostravice", "Morávka"}

SLDB_COLS = {
    "gis131620000": "obyvatelstvo_celkem",
    "gis131620001": "muzi",
    "gis131620002": "zeny",
    "gis131620011": "vek_0_14",
    "gis131620012": "vek_15_64",
    "gis131620013": "vek_65plus",
    "gis124070001": "prumerny_vek",
}

TIER_COLORS = {"A": "#2ecc71", "B": "#f1c40f", "C": "#e74c3c"}

os.makedirs(OUT_DIR, exist_ok=True)


# ── P&L výpočet ───────────────────────────────────────────────────────────────
def net_per_order(dist_km):
    gross = AVG_ORDER_KC * AVG_GROSS_MARGIN
    if dist_km <= 10:
        return gross + DELIVERY_FEE_Z12 - COURIER_FEE_Z1
    elif dist_km <= 20:
        return gross + DELIVERY_FEE_Z12 - COURIER_FEE_Z2
    else:
        return gross + DELIVERY_FEE_Z3 - COURIER_FEE_Z3


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((phi2-phi1)/2)**2
         + math.cos(phi1)*math.cos(phi2)*math.sin(math.radians(lon2-lon1)/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def score_0_10(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([5.0] * len(series), index=series.index)
    return 10 * (series - mn) / (mx - mn)


# ── načtení dat ───────────────────────────────────────────────────────────────
print("=== Načítám data ===")

zone20 = gpd.read_file(os.path.join(DATA_DIR, "google_zone_20km.geojson")).to_crs(CRS_METRIC)
zone20_geom = zone20.geometry.unary_union
print(f"   Zóna: {zone20_geom.area/1e6:.0f} km²")

sldb_path = os.path.join(DATA_DIR, "obce_sldb",
                         "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
obce_all = gpd.read_file(sldb_path).rename(columns=SLDB_COLS)
keep = ["kod", "nazev", "geometry"] + list(SLDB_COLS.values())
obce_all = obce_all[[c for c in keep if c in obce_all.columns]]
obce_m = obce_all.to_crs(CRS_METRIC)
obce_m["_c"] = obce_m.geometry.centroid
obce_zone = obce_m[obce_m["_c"].within(zone20_geom)].drop(columns=["_c"]).copy()
print(f"   Obcí v zóně: {len(obce_zone)}")

# 1km grid domácností → agregat per obec
grid = gpd.read_file(os.path.join(DATA_DIR, "gridy_domacnosti",
    "grid_domacnosti_sldb2021_20210326.gpkg")).rename(columns={"g179999001": "hh_celkem"}).to_crs(CRS_METRIC)
grid_pts = gpd.GeoDataFrame(grid[["hh_celkem"]], geometry=grid.geometry.centroid, crs=CRS_METRIC)
hh_per_obec = (
    gpd.sjoin(grid_pts, obce_zone[["kod", "geometry"]], how="left", predicate="within")
    .groupby("kod")["hh_celkem"].sum()
    .rename("hh_celkem")
)
print(f"   Grid: {len(grid)} buněk")

# Nightlife spoty → agregat per obec
spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg")).to_crs(CRS_METRIC)
nightlife = spots[spots["amenity"].isin({"bar","pub","nightclub","restaurant","fast_food","cafe"})].copy()
nl_per_obec = (
    gpd.sjoin(nightlife[["amenity","geometry"]], obce_zone[["kod","geometry"]], how="left", predicate="within")
    .groupby("kod").size()
    .rename("nightlife_count")
)
print(f"   Nightlife: {len(nightlife)} spotů")

# RÚIAN bytové domy (≥4 byty) → agregat per obec
budovy = gpd.read_file(os.path.join(DATA_DIR, "ruian_budovy_fm.gpkg"))
bytove = budovy[budovy["pocetbytu"] >= 4].copy()
bytove_pts = gpd.GeoDataFrame(
    bytove[["pocetbytu"]], geometry=bytove.to_crs(CRS_METRIC).geometry.centroid, crs=CRS_METRIC
)
byt_per_obec = (
    gpd.sjoin(bytove_pts, obce_zone[["kod","geometry"]], how="left", predicate="within")
    .groupby("kod")["pocetbytu"].sum()
    .rename("byt_domy_byty")
)
print(f"   RÚIAN bytové domy: {len(bytove)} budov")

# Google distance cache → medián driving distance per obec
print("\n=== Driving distance z cache ===")
with open(os.path.join(DATA_DIR, "google_distance_cache.json")) as f:
    cache_raw = json.load(f)

cache_pts = []
for key_str, dist_km in cache_raw.items():
    nums = re.findall(r"-?\d+\.\d+", key_str)
    if len(nums) >= 2:
        cache_pts.append({"lat": float(nums[0]), "lng": float(nums[1]), "dist_km": float(dist_km)})

cache_gdf = gpd.GeoDataFrame(
    cache_pts,
    geometry=gpd.points_from_xy([p["lng"] for p in cache_pts], [p["lat"] for p in cache_pts]),
    crs=CRS_WGS,
).to_crs(CRS_METRIC)

joined_cache = gpd.sjoin(cache_gdf[["dist_km","geometry"]], obce_zone[["kod","geometry"]],
                          how="left", predicate="within")
dist_per_obec  = joined_cache.groupby("kod")["dist_km"].median().rename("driving_dist_km")
cache_per_obec = joined_cache.groupby("kod")["dist_km"].count().rename("cache_points")
print(f"   Cache: {len(cache_gdf)} bodů, {(cache_per_obec > 0).sum()}/{len(obce_zone)} obcí pokryto")

# ── sestavení výsledné tabulky ────────────────────────────────────────────────
print("\n=== Sestavuji tabulku obcí ===")

df = obce_zone.copy()
df = df.merge(hh_per_obec.to_frame(), on="kod", how="left")
df = df.merge(nl_per_obec.to_frame(), on="kod", how="left")
df = df.merge(byt_per_obec.to_frame(), on="kod", how="left")
df = df.merge(dist_per_obec.to_frame(), on="kod", how="left")
df = df.merge(cache_per_obec.to_frame(), on="kod", how="left")
df[["hh_celkem","nightlife_count","byt_domy_byty","cache_points"]] = (
    df[["hh_celkem","nightlife_count","byt_domy_byty","cache_points"]].fillna(0).astype(int)
)

# Haversine fallback pro obce bez cache bodů
fm_wgs = (FM_LAT, FM_LON)
for idx, row in df[df["cache_points"] == 0].iterrows():
    c = gpd.GeoSeries([row.geometry.centroid], crs=CRS_METRIC).to_crs(CRS_WGS).iloc[0]
    df.at[idx, "driving_dist_km"] = round(haversine_km(*fm_wgs, c.y, c.x) * 1.25, 1)

df["driving_dist_km"] = df["driving_dist_km"].round(1)

# P&L metriky
df["net_per_order_kc"]       = df["driving_dist_km"].apply(net_per_order).round(1)
df["expected_orders_month"]  = (df["hh_celkem"] * CONVERSION_RATE).round(1)
df["monthly_contribution_kc"] = (df["expected_orders_month"] * df["net_per_order_kc"]).round(0).astype(int)
df["byt_podil"]              = (df["byt_domy_byty"] / df["hh_celkem"].replace(0, np.nan)).fillna(0).round(3)
df["nightlife_per_1k"]       = (
    df["nightlife_count"] / (df["obyvatelstvo_celkem"].replace(0, np.nan) / 1000)
).fillna(0).round(2)
df["vyrazeno"] = df["nazev"].isin(VYRAZENE)

# ── scoring ───────────────────────────────────────────────────────────────────
df["s_trh"]       = score_0_10(df["hh_celkem"])
# Absolutní P&L škála: 0–120 Kč → 0–10 (nepenalizuje 10-20km zónu na nulu)
MAX_PL_KC = 120.0
df["s_pl"]        = (df["net_per_order_kc"].clip(0, MAX_PL_KC) / MAX_PL_KC * 10).round(2)
df["s_byty"]      = score_0_10(df["byt_podil"])
df["s_nightlife"] = score_0_10(df["nightlife_per_1k"])

df["skore_total"] = (
    0.45 * df["s_trh"] +
    0.20 * df["s_pl"]  +
    0.20 * df["s_byty"] +
    0.15 * df["s_nightlife"]
).round(2).clip(0, 10)

# Tiering podle absolutního měsíčního příspěvku (reálná P&L interpretace)
#   A: ≥ 100 Kč/měsíc → aktivně marketovat, priorota doručení
#   B: ≥ 30 Kč/měsíc  → rozvážet na objednávku, bez aktivního marketingu
#   C: < 30 Kč/měsíc  → marginální, neinvestovat čas
TIER_A_KC = 100
TIER_B_KC = 30
df["tier"] = df["monthly_contribution_kc"].apply(
    lambda v: "A" if v >= TIER_A_KC else ("B" if v >= TIER_B_KC else "C")
)
df = df.sort_values("skore_total", ascending=False).reset_index(drop=True)
df["rank"] = df.index + 1

# ── print výsledků ────────────────────────────────────────────────────────────
EMOJI = {"A": "🟢", "B": "🟡", "C": "🔴"}
print(f"\n{'#':<4} {'T':<4} {'Obec':<30} {'HH':>7} {'km':>6} {'Kč/obj':>7} {'Kč/měsíc':>10} {'Skóre':>7}")
print("─" * 80)
for _, r in df.iterrows():
    print(f"{int(r['rank']):<4} {EMOJI[r.tier]}{r.tier}  {r.nazev:<28} "
          f"{int(r.hh_celkem):>7,} {r.driving_dist_km:>6.1f} "
          f"{r.net_per_order_kc:>7.0f} {r.monthly_contribution_kc:>10,} {r.skore_total:>7.2f}")

a = (df.tier == "A").sum(); b = (df.tier == "B").sum(); c = (df.tier == "C").sum()
print(f"\nTier A: {a} obcí | Tier B: {b} | Tier C: {c}")
print(f"Celkový měsíční potenciál Tier A: {df[df.tier=='A']['monthly_contribution_kc'].sum():,} Kč")
print(f"Celkový měsíční potenciál Tier B: {df[df.tier=='B']['monthly_contribution_kc'].sum():,} Kč")

# ── export CSV ────────────────────────────────────────────────────────────────
cols_out = ["kod","nazev","rank","tier","hh_celkem","obyvatelstvo_celkem","vek_15_64",
            "driving_dist_km","net_per_order_kc","expected_orders_month",
            "monthly_contribution_kc","nightlife_count","nightlife_per_1k",
            "byt_domy_byty","byt_podil","cache_points",
            "s_trh","s_pl","s_byty","s_nightlife","skore_total","vyrazeno"]
csv_out = os.path.join(OUT_DIR, "obce_scoring.csv")
df[[c for c in cols_out if c in df.columns]].to_csv(csv_out, index=False, encoding="utf-8-sig")
print(f"\nCSV: {csv_out}")

# ── Folium mapa ───────────────────────────────────────────────────────────────
print("\n=== Generuji mapu ===")

m = folium.Map(location=[49.72, 18.35], zoom_start=10, tiles="CartoDB Positron", prefer_canvas=True)
result_wgs = df.to_crs(CRS_WGS)

# Choropleth obcí
obce_layer = folium.FeatureGroup(name="Obce – P&L scoring tier", show=True)
gross_kc = round(AVG_ORDER_KC * AVG_GROSS_MARGIN)

for _, row in result_wgs.iterrows():
    color = TIER_COLORS[row["tier"]]
    vyraz_note = "<br><span style='color:#e74c3c'>⚠️ Vyřazeno z doručování</span>" if row["vyrazeno"] else ""
    dist = row["driving_dist_km"]
    if dist <= 10:
        cf, df_fee = COURIER_FEE_Z1, DELIVERY_FEE_Z12
    elif dist <= 20:
        cf, df_fee = COURIER_FEE_Z2, DELIVERY_FEE_Z12
    else:
        cf, df_fee = COURIER_FEE_Z3, DELIVERY_FEE_Z3

    popup_html = (
        f'<div style="font-family:sans-serif;min-width:280px;max-width:340px">'
        f'<b style="font-size:15px">#{int(row["rank"])} {row.nazev}</b>'
        f'<span style="background:{color};color:#000;padding:2px 8px;border-radius:4px;margin-left:8px">Tier {row.tier}</span>'
        f'{vyraz_note}<br><br>'
        f'<table style="border-collapse:collapse;width:100%;font-size:.87rem">'
        f'<tr><td>Celkové skóre</td><td><b style="font-size:15px;color:{color}">{row.skore_total:.2f}/10</b></td></tr>'
        f'<tr><td>Driving distance</td><td><b>{dist:.1f} km</b></td></tr>'
        f'<tr><td>Domácností</td><td><b>{int(row.hh_celkem):,}</b></td></tr>'
        f'<tr><td>Obyvatel</td><td><b>{int(row.obyvatelstvo_celkem):,}</b></td></tr>'
        f'<tr><td colspan=2 style="padding-top:8px;font-weight:bold;color:#555">P&amp;L per objednávka (průměr {AVG_ORDER_KC} Kč)</td></tr>'
        f'<tr><td style="padding-left:8px">Hrubá marže ({int(AVG_GROSS_MARGIN*100)} %)</td><td>+{gross_kc} Kč</td></tr>'
        f'<tr><td style="padding-left:8px">Dopravné od zákazníka</td><td>+{df_fee} Kč</td></tr>'
        f'<tr><td style="padding-left:8px">Kurýr paušál</td><td>−{cf} Kč</td></tr>'
        f'<tr><td style="padding-left:8px"><b>Čistý příspěvek</b></td><td><b style="color:{color}">{row.net_per_order_kc:.0f} Kč</b></td></tr>'
        f'<tr><td colspan=2 style="padding-top:8px;font-weight:bold;color:#555">Potenciál (conversion {CONVERSION_RATE*100:.1f} % HH/měs.)</td></tr>'
        f'<tr><td style="padding-left:8px">Odh. obj./měsíc</td><td>{row.expected_orders_month:.1f}</td></tr>'
        f'<tr><td style="padding-left:8px"><b>Odh. příspěvek/měs.</b></td><td><b>{int(row.monthly_contribution_kc):,} Kč</b></td></tr>'
        f'<tr><td style="padding-left:8px">Nightlife POI</td><td>{int(row.nightlife_count)} ({row.nightlife_per_1k:.1f}/1k ob.)</td></tr>'
        f'<tr><td style="padding-left:8px">Byty v byt. domech</td><td>{int(row.byt_domy_byty):,}</td></tr>'
        f'</table>'
        f'<div style="margin-top:8px;font-size:.78rem;color:#888">'
        f'Skóre: trh {row.s_trh:.1f} | P&amp;L {row.s_pl:.1f} | byty {row.s_byty:.1f} | nightlife {row.s_nightlife:.1f}'
        f'</div></div>'
    )
    folium.GeoJson(
        row.geometry.__geo_interface__,
        style_function=lambda x, c=color, t=row["tier"]: {
            "fillColor": c, "color": "#444", "weight": 0.8,
            "fillOpacity": 0.65 if t == "A" else (0.50 if t == "B" else 0.35),
        },
        tooltip=folium.Tooltip(
            f"<b>{row.nazev}</b> — Tier {row['tier']} | "
            f"{row.skore_total:.2f}/10 | {int(row.net_per_order_kc)} Kč/obj"
        ),
        popup=folium.Popup(popup_html, max_width=360),
    ).add_to(obce_layer)
obce_layer.add_to(m)

# Rozvozová zóna
folium.GeoJson(
    zone20.to_crs(CRS_WGS).geometry.iloc[0].__geo_interface__,
    name="Rozvozová zóna ≤20 km",
    style_function=lambda _: {"color": "#3388ff", "weight": 2.5, "fillOpacity": 0.03},
).add_to(m)

# Nightlife spoty
nl_group = folium.FeatureGroup(name="Nightlife spoty", show=False)
cat_colors = {"bar":"#e74c3c","pub":"#e67e22","nightclub":"#8e44ad",
              "restaurant":"#27ae60","fast_food":"#f39c12","cafe":"#2980b9"}
for _, r in nightlife.to_crs(CRS_WGS).iterrows():
    folium.CircleMarker(
        location=[r.geometry.y, r.geometry.x],
        radius=3, color=cat_colors.get(r["amenity"],"#888"),
        fill=True, fill_opacity=0.7,
        tooltip=f"{r.get('name','?')} ({r['amenity']})",
    ).add_to(nl_group)
nl_group.add_to(m)

# Zákazníci
zak_df = pd.read_csv(os.path.join(DATA_DIR, "zakaznici.csv")).dropna(subset=["lat","lng"])
zak_group = folium.FeatureGroup(name="Zákazníci (objednávky)", show=True)
for _, r in zak_df.iterrows():
    folium.CircleMarker(
        location=[r.lat, r.lng], radius=9,
        color="#fff", weight=2, fill_color="#e74c3c", fill_opacity=0.95,
        tooltip=f"#{int(r.id)}: {r.adresa} — {int(r.trzba_kc)} Kč, {r.vzdalenost_km} km",
    ).add_to(zak_group)
zak_group.add_to(m)

# Výchozí bod
folium.Marker(
    location=[FM_LAT, FM_LON],
    tooltip="Výchozí bod (byt řidiče)",
    icon=folium.DivIcon(
        html='<div style="font-size:22px;filter:drop-shadow(1px 1px 2px #fff)">🏠</div>',
        icon_size=(28, 28), icon_anchor=(14, 14),
    ),
).add_to(m)

# Top 10 tabulka jako HTML overlay
top10 = df.head(10)
rows_html = ""
for _, r in top10.iterrows():
    c = TIER_COLORS[r["tier"]]
    rows_html += (
        f'<tr>'
        f'<td style="color:{c};font-weight:700">{int(r["rank"])}</td>'
        f'<td style="font-weight:600">{r.nazev}</td>'
        f'<td style="color:{c}">{r.tier}</td>'
        f'<td style="text-align:right">{r.driving_dist_km:.0f}</td>'
        f'<td style="text-align:right;color:{c}">{r.net_per_order_kc:.0f}</td>'
        f'<td style="text-align:right">{int(r.hh_celkem):,}</td>'
        f'<td style="text-align:right;font-weight:700;color:{c}">{r.skore_total:.1f}</td>'
        f'</tr>\n'
    )

legend_html = f"""
<div style="
  position:fixed;bottom:24px;right:24px;z-index:9999;
  background:white;border:1px solid #ddd;border-radius:10px;
  padding:14px 18px;font-family:sans-serif;font-size:12px;
  box-shadow:2px 2px 10px rgba(0,0,0,.15);max-width:400px">
  <b style="font-size:14px">VečerkaPlus – Výběr obcí pro rozvoz</b>
  <hr style="margin:6px 0">
  <div><span style="color:#2ecc71;font-size:16px">■</span> <b>Tier A</b> (≥100 Kč/měs) — Prioritní — aktivně marketovat</div>
  <div><span style="color:#f1c40f;font-size:16px">■</span> <b>Tier B</b> (30–100 Kč/měs) — Výhodné — rozvážet na objednávku</div>
  <div><span style="color:#e74c3c;font-size:16px">■</span> <b>Tier C</b> (&lt;30 Kč/měs) — Marginální — bez aktivního marketingu</div>
  <hr style="margin:6px 0">
  <b>Top 10 obcí</b>
  <table style="width:100%;border-collapse:collapse;margin-top:4px">
    <tr style="color:#888;font-size:11px">
      <th>#</th><th style="text-align:left">Obec</th><th>T</th>
      <th style="text-align:right">km</th>
      <th style="text-align:right">Kč/obj</th>
      <th style="text-align:right">HH</th>
      <th style="text-align:right">Skóre</th>
    </tr>
    {rows_html}
  </table>
  <hr style="margin:6px 0">
  <small style="color:#888">
    Váhy: trh 35 %, P&amp;L 30 %, byty 20 %, nightlife 15 %<br>
    P&amp;L = hrubá marže ({gross_kc} Kč) + dopravné od zákazníka − kurýr paušál
  </small>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

out_map = os.path.join(OUT_DIR, "obce_analyza.html")
m.save(out_map)
print(f"   Mapa: {out_map}")
print("\nHotovo ✓")
