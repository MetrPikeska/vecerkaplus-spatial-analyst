"""
VečerkaPlus – síťová analýza dostupnosti (OSMnx)
================================================
Izochróny 5/10/15/20 minut jízdy od výchozího bodu řidiče.
Pokrytí domácností per časové pásmo, porovnání s Google Distance Matrix zónou.

Výstupy:
  data/osm_fm_drive.graphml    — cache OSM grafu (stáhne se jen jednou)
  data/osm_isochrones.geojson  — 4 polygony izochrón
  output/network_summary.json  — tabulka dostupnosti
  output/network_analyza.html  — interaktivní mapa
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
from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union
from shapely import concave_hull

# ── konstanty ─────────────────────────────────────────────────────────────────
FM_LAT, FM_LON   = 49.6754886, 18.3389397
CRS_METRIC       = "EPSG:5514"
CRS_WGS          = "EPSG:4326"
AVG_HH_SIZE      = 2.37
GRAPH_DIST_M     = 25_000       # okruh stahování grafu

TIME_LIMITS_MIN  = [5, 10, 15, 20]
ISOCHRONY_COLORS = {5:"#00e676", 10:"#ffd740", 15:"#ff9800", 20:"#e74c3c"}

DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR   = os.path.join(os.path.dirname(__file__), "output")
GRAPH_CACHE   = os.path.join(DATA_DIR, "osm_fm_drive.graphml")
ISO_GEOJSON   = os.path.join(DATA_DIR, "osm_isochrones.geojson")
SUMMARY_JSON  = os.path.join(OUT_DIR,  "network_summary.json")

os.makedirs(OUT_DIR, exist_ok=True)

# ── 1. OSM graph ──────────────────────────────────────────────────────────────
print("=== 1. OSM silniční graf ===")
if os.path.exists(GRAPH_CACHE):
    print(f"   Načítám z cache: {GRAPH_CACHE}")
    G = ox.load_graphml(GRAPH_CACHE)
else:
    print(f"   Stahuji OSM graf ({GRAPH_DIST_M/1000:.0f} km okruh)…")
    t0 = time.time()
    G = ox.graph_from_point(
        (FM_LAT, FM_LON),
        dist=GRAPH_DIST_M,
        network_type="drive",
        simplify=True,
    )
    print(f"   Staženo za {time.time()-t0:.1f}s — {len(G.nodes)} uzlů, {len(G.edges)} hran")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    ox.save_graphml(G, filepath=GRAPH_CACHE)
    print(f"   Uloženo: {GRAPH_CACHE}")

# Ověř přítomnost travel_time (po načtení z cache nemusí být)
edges_gdf = ox.graph_to_gdfs(G, nodes=False)
if "travel_time" not in edges_gdf.columns:
    print("   Přepočítávám rychlosti a jízdní časy…")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)

orig_node = ox.nearest_nodes(G, FM_LON, FM_LAT)
print(f"   Výchozí uzel: {orig_node}")

# ── 2. Izochróny ──────────────────────────────────────────────────────────────
print("\n=== 2. Výpočet izochrón ===")

def make_isochrone(G, center_node, travel_time_s):
    """Vrátí Shapely polygon pokrývající oblasti dosažitelné do travel_time_s."""
    subG = nx.ego_graph(G, center_node, radius=travel_time_s, distance="travel_time")
    nodes_gdf, _ = ox.graph_to_gdfs(subG)
    pts = nodes_gdf.geometry.to_crs(CRS_WGS)
    # concave_hull (ratio 0.05) je přesnější než konvexní obal
    mp = MultiPoint(list(pts))
    try:
        poly = concave_hull(mp, ratio=0.05)
    except Exception:
        poly = mp.convex_hull
    # Pokud je výsledek příliš malý nebo prázdný, fallback na konvexní obal
    if poly.is_empty or poly.area < 1e-6:
        poly = mp.convex_hull
    return poly

isochrony = []
for minutes in TIME_LIMITS_MIN:
    t_s = minutes * 60
    poly = make_isochrone(G, orig_node, t_s)
    isochrony.append({"minutes": minutes, "geometry": poly})
    nodes_count = len(nx.ego_graph(G, orig_node, radius=t_s, distance="travel_time").nodes)
    print(f"   {minutes} min — {nodes_count} uzlů, plocha {poly.area * 1e4:.0f} km² (WGS)")

iso_gdf = gpd.GeoDataFrame(isochrony, crs=CRS_WGS)
iso_gdf.to_file(ISO_GEOJSON, driver="GeoJSON")
print(f"\n   Izochróny uloženy: {ISO_GEOJSON}")

# ── 3. Pokrytí domácností ─────────────────────────────────────────────────────
print("\n=== 3. Pokrytí domácností per izochróna ===")

grid = gpd.read_file(os.path.join(DATA_DIR, "gridy_domacnosti",
    "grid_domacnosti_sldb2021_20210326.gpkg")).rename(columns={"g179999001": "hh_celkem"})
grid_m   = grid.to_crs(CRS_METRIC)
grid_pts = gpd.GeoDataFrame(grid_m[["hh_celkem"]], geometry=grid_m.geometry.centroid, crs=CRS_METRIC)

# Google 20km zóna jako referenční hodnota
zone20 = gpd.read_file(os.path.join(DATA_DIR, "google_zone_20km.geojson")).to_crs(CRS_METRIC)
zone20_geom = zone20.geometry.unary_union
hh_google20 = int(grid_pts[grid_pts.geometry.within(zone20_geom)]["hh_celkem"].sum())

summary = {}
prev_hh = 0
for _, row in iso_gdf.iterrows():
    minutes = int(row["minutes"])
    iso_m = gpd.GeoDataFrame([{"geometry": row.geometry}], crs=CRS_WGS).to_crs(CRS_METRIC).geometry.iloc[0]
    hh = int(grid_pts[grid_pts.geometry.within(iso_m)]["hh_celkem"].sum())
    area_km2 = iso_m.area / 1e6
    pct_google = hh / hh_google20 * 100 if hh_google20 > 0 else 0
    incremental = hh - prev_hh
    summary[str(minutes)] = {
        "minutes": minutes,
        "area_km2": round(area_km2, 1),
        "hh_count": hh,
        "pop_est": int(hh * AVG_HH_SIZE),
        "pct_google20": round(pct_google, 1),
        "incremental_hh": incremental,
    }
    print(f"   {minutes:2d} min — {area_km2:.0f} km² — {hh:,} HH ({pct_google:.0f} % Google 20km) +{incremental:,} přírůstek")
    prev_hh = hh

summary["google20"] = {"hh_count": hh_google20, "area_km2": round(zone20_geom.area / 1e6, 1)}

with open(SUMMARY_JSON, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
print(f"\n   Souhrn uložen: {SUMMARY_JSON}")

# ── 4. Folium mapa ────────────────────────────────────────────────────────────
print("\n=== 4. Generuji mapu ===")

m = folium.Map(location=[FM_LAT, FM_LON], zoom_start=11,
               tiles="CartoDB Positron", prefer_canvas=True)

# Izochróny (od největší po nejmenší → správné překrytí)
for minutes in sorted(TIME_LIMITS_MIN, reverse=True):
    row = iso_gdf[iso_gdf["minutes"] == minutes].iloc[0]
    color = ISOCHRONY_COLORS[minutes]
    s = summary[str(minutes)]
    folium.GeoJson(
        row.geometry.__geo_interface__,
        name=f"Izochróna {minutes} min",
        style_function=lambda x, c=color, m=minutes: {
            "fillColor": c, "color": c, "weight": 2,
            "fillOpacity": 0.25, "dashArray": "" if m == 20 else "4,4",
        },
        tooltip=folium.Tooltip(
            f"<b>{minutes} min jízdy</b><br>"
            f"Plocha: {s['area_km2']:.0f} km²<br>"
            f"Domácností: {s['hh_count']:,}<br>"
            f"Odh. obyvatel: {s['pop_est']:,}<br>"
            f"% z Google 20km zóny: {s['pct_google20']:.0f} %"
        ),
    ).add_to(m)

# Google 20km zóna (srovnávací)
folium.GeoJson(
    zone20.to_crs(CRS_WGS).geometry.iloc[0].__geo_interface__,
    name="Google zóna ≤20 km jízdy (referenční)",
    style_function=lambda _: {"color": "#3388ff", "weight": 2.5,
                               "fillOpacity": 0.04, "dashArray": "6,4"},
).add_to(m)

# 1km grid heatmap (domácnosti)
grid_vis = grid_pts[grid_pts.geometry.within(zone20_geom)].to_crs(CRS_WGS)
heat_data = [[r.geometry.y, r.geometry.x, r.hh_celkem]
             for _, r in grid_vis[grid_vis.hh_celkem > 0].iterrows()]
from folium.plugins import HeatMap
HeatMap(heat_data, name="Hustota domácností", min_opacity=0.2,
        radius=16, blur=20, max_zoom=13, show=False).add_to(m)

# Zákazníci
zak = pd.read_csv(os.path.join(DATA_DIR, "zakaznici.csv")).dropna(subset=["lat","lng"])
zak_grp = folium.FeatureGroup(name="Zákazníci (objednávky)", show=True)
for _, r in zak.iterrows():
    folium.CircleMarker([r.lat, r.lng], radius=9, color="#fff", weight=2,
                        fill_color="#e74c3c", fill_opacity=0.95,
                        tooltip=f"#{int(r.id)} — {int(r.trzba_kc)} Kč, {r.vzdalenost_km} km").add_to(zak_grp)
zak_grp.add_to(m)

# FM výchozí bod
folium.Marker([FM_LAT, FM_LON], tooltip="Výchozí bod (byt řidiče)",
              icon=folium.DivIcon(
                  html='<div style="font-size:22px;filter:drop-shadow(1px 1px 2px #fff)">🏠</div>',
                  icon_size=(28,28), icon_anchor=(14,14))).add_to(m)

# Legenda
legend_rows = ""
for minutes in TIME_LIMITS_MIN:
    s = summary[str(minutes)]
    c = ISOCHRONY_COLORS[minutes]
    legend_rows += (
        f'<tr>'
        f'<td><span style="color:{c};font-size:16px">■</span> {minutes} min</td>'
        f'<td style="text-align:right">{s["area_km2"]:.0f} km²</td>'
        f'<td style="text-align:right">{s["hh_count"]:,}</td>'
        f'<td style="text-align:right">{s["pct_google20"]:.0f} %</td>'
        f'</tr>\n'
    )
legend_html = f"""
<div style="position:fixed;bottom:24px;right:24px;z-index:9999;
  background:white;border:1px solid #ddd;border-radius:10px;
  padding:14px 18px;font-family:sans-serif;font-size:12px;
  box-shadow:2px 2px 10px rgba(0,0,0,.15);min-width:300px">
  <b style="font-size:14px">VečerkaPlus – síťová dostupnost (OSM)</b>
  <hr style="margin:6px 0">
  <table style="width:100%;border-collapse:collapse">
    <tr style="color:#888;font-size:11px">
      <th style="text-align:left">Izochróna</th>
      <th style="text-align:right">Plocha</th>
      <th style="text-align:right">Domácností</th>
      <th style="text-align:right">% Google 20km</th>
    </tr>
    {legend_rows}
    <tr style="border-top:1px solid #ddd;color:#3388ff">
      <td>--- Google ≤20 km ---</td>
      <td style="text-align:right">{summary['google20']['area_km2']:.0f} km²</td>
      <td style="text-align:right">{summary['google20']['hh_count']:,}</td>
      <td style="text-align:right">100 %</td>
    </tr>
  </table>
  <hr style="margin:6px 0">
  <small style="color:#888">Silniční síť: OpenStreetMap · Výpočet: OSMnx {ox.__version__}</small>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

out_map = os.path.join(OUT_DIR, "network_analyza.html")
m.save(out_map)
print(f"   Mapa: {out_map}")
print("\nHotovo ✓")
