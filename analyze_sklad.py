"""
Analýza optimálního umístění skladu VečerkaPlus
================================================
Hodnotíme kandidátní lokality dle 4 kritérií:
  1. Hustota domácností v dosahu (SLDB 2021 grid, 3 km od skladu)
  2. Koncentrace nightlife (bary, hospody, restaurace do 3 km)
  3. Vzdálenost ke stávajícím zákazníkům (vážená tržbou)
  4. Poloha vůči centru rozvozové zóny (≤ 20 km Google)

Výstup: output/sklad_analyza.html (interaktivní mapa + scoring tabulka)
"""

import os
import math
import pandas as pd
import geopandas as gpd
import folium
from folium import plugins
from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union
import numpy as np

# ── konstanty ─────────────────────────────────────────────────────────────────
FM_LAT, FM_LON = 49.6754886, 18.3389397
CRS_METRIC = "EPSG:5514"
CRS_WGS    = "EPSG:4326"
AVG_HH_SIZE = 2.37
DATA_DIR   = "data"
OUT_DIR    = "output"
RADIUS_SKLAD_M = 3_000   # poloměr pro hodnocení okolí skladu [m]

os.makedirs(OUT_DIR, exist_ok=True)

# ── načtení dat ───────────────────────────────────────────────────────────────
print("=== Načítám data ===")

# 20 km rozvozová zóna
zone20 = gpd.read_file(os.path.join(DATA_DIR, "google_zone_20km.geojson")).to_crs(CRS_METRIC)
zone20_geom = zone20.geometry.unary_union

# 1km grid domácností
GRID_COLS = {
    "g179999001": "hh_celkem",
    "g179999002": "hh_bytove",
}
grid_raw = gpd.read_file(
    os.path.join(DATA_DIR, "gridy_domacnosti", "grid_domacnosti_sldb2021_20210326.gpkg")
).rename(columns=GRID_COLS).to_crs(CRS_METRIC)
grid_raw["centroid"] = grid_raw.geometry.centroid
grid_zone = grid_raw[grid_raw["centroid"].within(zone20_geom)].copy()
grid_zone["pop_odhad"] = (grid_zone["hh_celkem"] * AVG_HH_SIZE).round().astype(int)
print(f"   Grid v zóně: {len(grid_zone)} buněk, {grid_zone['hh_celkem'].sum():,} domácností")

# Zákazníci
zak = pd.read_csv(os.path.join(DATA_DIR, "zakaznici.csv"))
zak_gdf = gpd.GeoDataFrame(
    zak, geometry=gpd.points_from_xy(zak.lng, zak.lat), crs=CRS_WGS
).to_crs(CRS_METRIC)

# Nightlife spoty
spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg")).to_crs(CRS_METRIC)
nightlife_cats = ["bar", "pub", "nightclub", "restaurant", "fast_food", "cafe"]
nightlife = spots[spots["amenity"].isin(nightlife_cats)].copy()
print(f"   Nightlife spotů: {len(nightlife)} (bary, hospody, restaurace, kavárny)")

# ── těžiště zákazníků (vážené tržbou) ────────────────────────────────────────
total_trzba = zak["trzba_kc"].sum()
cx = (zak_gdf.geometry.x * zak["trzba_kc"]).sum() / total_trzba
cy = (zak_gdf.geometry.y * zak["trzba_kc"]).sum() / total_trzba
customer_centroid = Point(cx, cy)
print(f"   Centroid zákazníků (vážený tržbou): EPSG:5514 ({cx:.0f}, {cy:.0f})")

# ── těžiště nightlife ─────────────────────────────────────────────────────────
nx = nightlife.geometry.x.mean()
ny = nightlife.geometry.y.mean()
nightlife_centroid = Point(nx, ny)

# ── těžiště domácností v zóně ─────────────────────────────────────────────────
total_hh = grid_zone["hh_celkem"].sum()
hx = (grid_zone["centroid"].x * grid_zone["hh_celkem"]).sum() / total_hh
hy = (grid_zone["centroid"].y * grid_zone["hh_celkem"]).sum() / total_hh
hh_centroid = Point(hx, hy)

# ── střed rozvozové zóny ──────────────────────────────────────────────────────
zone_centroid_m = zone20_geom.centroid

print("\n=== Těžiště ===")
for name, pt in [("Zákazníci (váž. tržbou)", customer_centroid),
                 ("Nightlife spoty", nightlife_centroid),
                 ("Domácnosti (grid)", hh_centroid),
                 ("Střed rozvozové zóny", zone_centroid_m)]:
    wgs = gpd.GeoSeries([pt], crs=CRS_METRIC).to_crs(CRS_WGS).iloc[0]
    print(f"   {name}: {wgs.y:.5f}°N, {wgs.x:.5f}°E")

# ── definice kandidátních lokalit ────────────────────────────────────────────
# Realistické lokality: průmyslové zóny, obchodní areály FM a okolí
# Zdroj: místní znalost + OSM průmyslové/obchodní zóny v FM
candidates_raw = [
    {
        "id": "A",
        "nazev": "Frýdek-Místek centrum (Pivovar / Nám. Svobody)",
        "poznamka": "Srdce FM, max. dosah do okolí; dražší nájmy",
        "lat": 49.6830, "lon": 18.3548,
    },
    {
        "id": "B",
        "nazev": "FM – průmyslová zóna Chlebovice (Na Zahumení)",
        "poznamka": "Levné sklady, snadný sjezd na R48/I-56; 3 km od centra FM",
        "lat": 49.6600, "lon": 18.3150,
    },
    {
        "id": "C",
        "nazev": "FM – Lískovecká (u Kauflandu, sever FM)",
        "poznamka": "Hustá zástavba severu FM, blízko Ostravy; komerční zóna",
        "lat": 49.7020, "lon": 18.3480,
    },
    {
        "id": "D",
        "nazev": "Frýdlant nad Ostravicí – centrum",
        "poznamka": "Jižní brána zóny; nízké nájmy, horší dosah na FM a Ostravu",
        "lat": 49.5920, "lon": 18.3580,
    },
    {
        "id": "E",
        "nazev": "Třinec – západ (Oldřichovice)",
        "poznamka": "Velké město, ale na okraji zóny; risknantní dosah na FM",
        "lat": 49.6760, "lon": 18.6200,
    },
    {
        "id": "F",
        "nazev": "Ostrava – Hrabová / Rudná (průmyslová zóna)",
        "poznamka": "Nejlepší dosah na Ostravu; drahé nájmy, daleko od FM zákazníků",
        "lat": 49.7700, "lon": 18.2200,
    },
    {
        "id": "G",
        "nazev": "FM – Sad B. Nikodema (byt řidiče – current)",
        "poznamka": "Stávající základna řidiče; referenční bod",
        "lat": FM_LAT, "lon": FM_LON,
    },
    {
        "id": "H",
        "nazev": "Místek – Nádražní / Vlakové nádraží",
        "poznamka": "Komerční lokace v jižní části FM, blízko osy zákazníků",
        "lat": 49.6920, "lon": 18.3600,
    },
]

cand_gdf = gpd.GeoDataFrame(
    candidates_raw,
    geometry=gpd.points_from_xy(
        [c["lon"] for c in candidates_raw],
        [c["lat"] for c in candidates_raw]
    ),
    crs=CRS_WGS
).to_crs(CRS_METRIC)

# ── scoring ───────────────────────────────────────────────────────────────────
print("\n=== Výpočet skóre ===")

def score_0_10(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([5.0] * len(series), index=series.index)
    return 10 * (series - mn) / (mx - mn)

results = []
for _, row in cand_gdf.iterrows():
    pt = row.geometry

    # -- kritérium 1: domácnosti v RADIUS_SKLAD_M od skladu --
    buf = pt.buffer(RADIUS_SKLAD_M)
    hh_nearby = grid_zone[grid_zone["centroid"].within(buf)]["hh_celkem"].sum()

    # -- kritérium 2: nightlife v RADIUS_SKLAD_M --
    nl_nearby = nightlife[nightlife.geometry.within(buf)].shape[0]

    # -- kritérium 3: střední vzdálenost od zákazníků (vážená tržbou) --
    dists = zak_gdf.geometry.distance(pt)
    avg_dist_weighted = (dists * zak["trzba_kc"]).sum() / zak["trzba_kc"].sum()

    # -- kritérium 4: vzdálenost od centroidu zóny --
    dist_zone_center = pt.distance(zone_centroid_m)

    # -- je bod uvnitř zóny? --
    in_zone = zone20_geom.contains(pt)

    results.append({
        "id": row["id"],
        "nazev": row["nazev"],
        "poznamka": row["poznamka"],
        "lat": row["lat"],
        "lon": row["lon"],
        "hh_3km": int(hh_nearby),
        "nightlife_3km": int(nl_nearby),
        "avg_dist_zak_m": int(avg_dist_weighted),
        "dist_zone_center_m": int(dist_zone_center),
        "in_zone": in_zone,
    })

df = pd.DataFrame(results)

# normalizace a vážení
# vyšší hh = lepší → max→10
df["s_hh"]     = score_0_10(df["hh_3km"])
# vyšší nightlife = lepší
df["s_nl"]     = score_0_10(df["nightlife_3km"])
# nižší vzdálenost od zákazníků = lepší → invertujeme
df["s_zak"]    = 10 - score_0_10(df["avg_dist_zak_m"])
# nižší vzdálenost od středu zóny = lepší
df["s_zone"]   = 10 - score_0_10(df["dist_zone_center_m"])

# váhy (součet = 1)
W_HH   = 0.30   # hustota potenciálních zákazníků
W_NL   = 0.30   # blízkost k nightlife (core cílová skupina)
W_ZAK  = 0.25   # blízkost ke stávajícím zákazníkům
W_ZONE = 0.15   # centrálnost v zóně

df["skore_total"] = (
    W_HH   * df["s_hh"]  +
    W_NL   * df["s_nl"]  +
    W_ZAK  * df["s_zak"] +
    W_ZONE * df["s_zone"]
).round(2)

# penalizace: bod mimo zónu
df.loc[~df["in_zone"], "skore_total"] -= 2.0
df["skore_total"] = df["skore_total"].clip(0, 10)

df = df.sort_values("skore_total", ascending=False).reset_index(drop=True)
df["rank"] = df.index + 1

print(df[["rank","id","nazev","hh_3km","nightlife_3km","avg_dist_zak_m","skore_total","in_zone"]].to_string(index=False))

# ── mapa ──────────────────────────────────────────────────────────────────────
print("\n=== Generuji mapu ===")

m = folium.Map(
    location=[49.69, 18.38],
    zoom_start=11,
    tiles="CartoDB Positron",
    prefer_canvas=True,
)

# rozvozová zóna
zone20_wgs = zone20.to_crs(CRS_WGS)
folium.GeoJson(
    zone20_wgs.__geo_interface__,
    name="Rozvozová zóna ≤ 20 km",
    style_function=lambda _: {"fillColor":"#3388ff","fillOpacity":0.08,"color":"#2255cc","weight":2},
).add_to(m)

# grid domácností (heatmap)
grid_vis = grid_zone[grid_zone["hh_celkem"] > 0].to_crs(CRS_WGS)
heat_data = []
for _, r in grid_vis.iterrows():
    c = r["centroid"]
    c_wgs = gpd.GeoSeries([c], crs=CRS_METRIC).to_crs(CRS_WGS).iloc[0]
    heat_data.append([c_wgs.y, c_wgs.x, r["hh_celkem"]])
plugins.HeatMap(
    heat_data,
    name="Hustota domácností (SLDB 2021)",
    min_opacity=0.25,
    radius=18,
    blur=22,
    max_zoom=13,
    show=True,
).add_to(m)

# nightlife spoty
nl_group = folium.FeatureGroup(name="Nightlife (bary, hospody, restaurace)", show=False)
cat_colors = {"bar":"#e74c3c","pub":"#e67e22","nightclub":"#8e44ad",
              "restaurant":"#27ae60","fast_food":"#f39c12","cafe":"#2980b9"}
for _, r in nightlife.to_crs(CRS_WGS).iterrows():
    col = cat_colors.get(r["amenity"], "#888888")
    folium.CircleMarker(
        location=[r.geometry.y, r.geometry.x],
        radius=4, color=col, fill=True, fill_opacity=0.6,
        tooltip=f"{r.get('name','?')} ({r['amenity']})",
    ).add_to(nl_group)
nl_group.add_to(m)

# zákazníci
zak_group = folium.FeatureGroup(name="Zákazníci", show=True)
for _, r in zak_gdf.to_crs(CRS_WGS).iterrows():
    folium.CircleMarker(
        location=[r.geometry.y, r.geometry.x],
        radius=8, color="#ffffff", weight=2,
        fill_color="#e74c3c", fill_opacity=0.9,
        tooltip=f"Zákazník #{r['id']}: {r['trzba_kc']} Kč, {r['vzdalenost_km']} km",
    ).add_to(zak_group)
zak_group.add_to(m)

# těžiště
centroids_group = folium.FeatureGroup(name="Těžiště analýzy", show=True)
centroids = [
    (customer_centroid, "Centroid zákazníků (váž. tržbou)", "#e74c3c", "★"),
    (nightlife_centroid, "Centroid nightlife", "#e67e22", "♪"),
    (hh_centroid, "Centroid domácností", "#2980b9", "⌂"),
    (zone_centroid_m, "Střed rozvozové zóny", "#27ae60", "◉"),
]
for pt_m, label, color, icon_char in centroids:
    pt_wgs = gpd.GeoSeries([pt_m], crs=CRS_METRIC).to_crs(CRS_WGS).iloc[0]
    folium.Marker(
        location=[pt_wgs.y, pt_wgs.x],
        tooltip=label,
        icon=folium.DivIcon(
            html=f'<div style="font-size:22px;color:{color};text-shadow:1px 1px 2px #fff">{icon_char}</div>',
            icon_size=(30, 30), icon_anchor=(15, 15),
        ),
    ).add_to(centroids_group)
centroids_group.add_to(m)

# 3 km buffer kolem top 3 kandidátů
buf_group = folium.FeatureGroup(name="3km buffer – top kandidáti", show=True)
top3_colors = ["#f1c40f","#95a5a6","#cd7f32"]
for i, (_, row) in enumerate(df.head(3).iterrows()):
    pt = gpd.GeoSeries([Point(row["lon"], row["lat"])], crs=CRS_WGS).to_crs(CRS_METRIC).iloc[0]
    buf_wgs = gpd.GeoSeries([pt.buffer(RADIUS_SKLAD_M)], crs=CRS_METRIC).to_crs(CRS_WGS).iloc[0]
    folium.GeoJson(
        buf_wgs.__geo_interface__,
        style_function=lambda _, c=top3_colors[i]: {
            "fillColor": c, "fillOpacity": 0.10, "color": c, "weight": 2, "dashArray": "5,5"
        },
        tooltip=f"#{i+1} {row['nazev']} – 3km dosah",
    ).add_to(buf_group)
buf_group.add_to(m)

# kandidátní lokality
cand_group = folium.FeatureGroup(name="Kandidátní lokality skladu", show=True)
rank_colors = {1:"#f1c40f", 2:"#95a5a6", 3:"#cd7f32"}
for _, row in df.iterrows():
    color = rank_colors.get(row["rank"], "#555555")
    in_z = "✓ v zóně" if row["in_zone"] else "✗ mimo zónu"
    popup_html = f"""
    <div style="font-family:sans-serif;min-width:260px">
      <b style="font-size:14px">#{row['rank']} {row['id']}: {row['nazev']}</b><br>
      <i style="color:#666">{row['poznamka']}</i><br><br>
      <table style="border-collapse:collapse;width:100%">
        <tr><td>Celkové skóre</td><td><b style="font-size:16px;color:{color}">{row['skore_total']:.1f}/10</b></td></tr>
        <tr><td>Domácnosti ≤ 3 km</td><td><b>{row['hh_3km']:,}</b></td></tr>
        <tr><td>Nightlife ≤ 3 km</td><td><b>{row['nightlife_3km']}</b></td></tr>
        <tr><td>Průměrná vzdálenost k zákazníkům</td><td><b>{row['avg_dist_zak_m']/1000:.1f} km</b></td></tr>
        <tr><td>Poloha</td><td>{in_z}</td></tr>
      </table>
    </div>
    """
    folium.Marker(
        location=[row["lat"], row["lon"]],
        popup=folium.Popup(popup_html, max_width=320),
        tooltip=f"#{row['rank']} {row['id']}: {row['nazev']} — skóre {row['skore_total']:.1f}",
        icon=folium.DivIcon(
            html=f"""
            <div style="
              background:{color};border:2px solid #333;border-radius:50%;
              width:32px;height:32px;line-height:32px;text-align:center;
              font-weight:bold;font-size:14px;color:#000;
              box-shadow:2px 2px 4px rgba(0,0,0,.4)">
              {row['id']}
            </div>""",
            icon_size=(32, 32), icon_anchor=(16, 16),
        ),
    ).add_to(cand_group)
cand_group.add_to(m)

# legenda
legend_html = """
<div style="
  position:fixed;bottom:30px;left:30px;z-index:9999;
  background:white;border:1px solid #ccc;border-radius:8px;
  padding:14px 18px;font-family:sans-serif;font-size:13px;
  box-shadow:2px 2px 8px rgba(0,0,0,.2);max-width:280px">
  <b style="font-size:15px">Analýza skladu VečerkaPlus</b>
  <hr style="margin:6px 0">
  <div style="margin:4px 0"><span style="color:#f1c40f;font-size:18px">●</span> #1 — nejlepší lokalita</div>
  <div style="margin:4px 0"><span style="color:#95a5a6;font-size:18px">●</span> #2 — dobrá alternativa</div>
  <div style="margin:4px 0"><span style="color:#cd7f32;font-size:18px">●</span> #3 — rezervní volba</div>
  <div style="margin:4px 0"><span style="color:#555;font-size:18px">●</span> ostatní kandidáti</div>
  <hr style="margin:6px 0">
  <div style="margin:4px 0"><span style="color:#e74c3c">★</span> Centroid zákazníků (váž. tržbou)</div>
  <div style="margin:4px 0"><span style="color:#e67e22">♪</span> Centroid nightlife</div>
  <div style="margin:4px 0"><span style="color:#2980b9">⌂</span> Centroid domácností</div>
  <div style="margin:4px 0"><span style="color:#27ae60">◉</span> Střed rozvozové zóny</div>
  <hr style="margin:6px 0">
  <small style="color:#888">Váhy skóre: domácnosti 30 %, nightlife 30 %,<br>zákazníci 25 %, centralita 15 %</small>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

out_map = os.path.join(OUT_DIR, "sklad_analyza.html")
m.save(out_map)
print(f"   Mapa uložena: {out_map}")

# ── textový výstup ────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("DOPORUČENÍ – TOP 3 LOKALITY PRO SKLAD")
print("="*60)
for _, row in df.head(3).iterrows():
    print(f"\n#{row['rank']} [{row['id']}] {row['nazev']}")
    print(f"   Skóre: {row['skore_total']:.1f}/10")
    print(f"   Domácnosti ≤ 3 km: {row['hh_3km']:,}")
    print(f"   Nightlife ≤ 3 km:  {row['nightlife_3km']}")
    print(f"   Průměr ke zákazníkům: {row['avg_dist_zak_m']/1000:.1f} km")
    print(f"   {row['poznamka']}")

# uložení tabulky
csv_out = os.path.join(OUT_DIR, "sklad_scoring.csv")
df.to_csv(csv_out, index=False)
print(f"\nScoringová tabulka: {csv_out}")
