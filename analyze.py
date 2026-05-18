"""
VečerkaPlus – prostorová analýza dosahu rozvozu
Výchozí bod: byt řidiče (49.6754886N, 18.3389397E)
"""

import warnings
warnings.filterwarnings("ignore")

import os
import json
import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, shape
import folium
from branca.colormap import LinearColormap

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------
# Skutečná adresa bytu odkud vyjíždíme
FM_LAT, FM_LON = 49.6754886, 18.3389397
BUFFER_DIST_M  = 20_000
CRS_METRIC     = "EPSG:5514"
CRS_WGS        = "EPSG:4326"
# Průměrná velikost domácnosti ČR SLDB 2021
AVG_HH_SIZE    = 2.37

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

ORS_API_KEY = os.environ.get("ORS_API_KEY", "")

# ČSÚ SLDB 2021 – mapování kódů
SLDB_COLS = {
    "gis131620000": "obyvatelstvo_celkem",
    "gis131620001": "muzi",
    "gis131620002": "zeny",
    "gis131620011": "vek_0_14",
    "gis131620012": "vek_15_64",
    "gis131620013": "vek_65plus",
    "gis124070001": "prumerny_vek",
}

# 1km grid – domácnosti (klíčové sloupce)
GRID_COLS = {
    "g179999001": "hh_celkem",        # hospodařící domácnosti celkem
    "g179999002": "hh_bytove",        # bytové domácnosti
    "g179999004": "hh_uplne_rodiny",  # úplné rodiny
    "g179999005": "hh_neuplne_rodiny",# neúplné rodiny
    "g179999006": "hh_jednotlivci",   # domácnosti jednotlivců
}

# ---------------------------------------------------------------------------
# 1. Načtení obcí SLDB 2021
# ---------------------------------------------------------------------------
print("=== 1. Načítám obce SLDB 2021 ===")
sldb_path = os.path.join(DATA_DIR, "obce_sldb",
                         "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
obce = gpd.read_file(sldb_path).rename(columns=SLDB_COLS)
keep = ["kod", "nazev", "geometry"] + list(SLDB_COLS.values())
obce = obce[[c for c in keep if c in obce.columns]]
print(f"   {len(obce)} obcí, CRS: {obce.crs}")

# ---------------------------------------------------------------------------
# 2. Načtení 1km gridů domácností
# ---------------------------------------------------------------------------
print("\n=== 2. Načítám 1km grid domácností ===")
grid_path = os.path.join(DATA_DIR, "gridy_domacnosti",
                         "grid_domacnosti_sldb2021_20210326.gpkg")
gridy = gpd.read_file(grid_path).rename(columns=GRID_COLS)
keep_g = ["grd_inspir", "geometry"] + list(GRID_COLS.values())
gridy = gridy[[c for c in keep_g if c in gridy.columns]]
# Odhadnout počet osob z domácností
gridy["pop_odhad"] = (gridy["hh_celkem"] * AVG_HH_SIZE).round().astype(int)
print(f"   {len(gridy)} gridů, CRS: {gridy.crs}")

# ---------------------------------------------------------------------------
# 3. Buffer 20 km od výchozí adresy
# ---------------------------------------------------------------------------
print("\n=== 3. Buffer 20 km ===")
fm_pt_wgs = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS)
fm_pt_m   = fm_pt_wgs.to_crs(CRS_METRIC)
buffer_m  = fm_pt_m.buffer(BUFFER_DIST_M)
buffer_geom_m = buffer_m.iloc[0]
buffer_wgs = gpd.GeoDataFrame(geometry=buffer_m, crs=CRS_METRIC).to_crs(CRS_WGS)
print(f"   Plocha: {buffer_m.area.values[0]/1e6:.1f} km²")

# ---------------------------------------------------------------------------
# 4. Izochróna 20 min autem
# ---------------------------------------------------------------------------
print("\n=== 4. Izochróna (ORS) ===")
iso_file = os.path.join(DATA_DIR, "isochrone_20min.geojson")
if os.path.exists(iso_file):
    with open(iso_file) as f:
        iso_data = json.load(f)
    iso_geom_wgs = shape(iso_data["features"][0]["geometry"])
    isochrone_gdf = gpd.GeoDataFrame(
        [{"geometry": iso_geom_wgs}], crs=CRS_WGS
    )
    iso_geom_m = isochrone_gdf.to_crs(CRS_METRIC).geometry.iloc[0]
    print(f"   Načtena z cache, plocha: {iso_geom_m.area/1e6:.1f} km²")
elif ORS_API_KEY:
    url = "https://api.openrouteservice.org/v2/isochrones/driving-car"
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {"locations": [[FM_LON, FM_LAT]], "range": [1200],
            "range_type": "time", "smoothing": 25}
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code == 200:
        iso_data = resp.json()
        with open(iso_file, "w") as f:
            json.dump(iso_data, f)
        iso_geom_wgs = shape(iso_data["features"][0]["geometry"])
        isochrone_gdf = gpd.GeoDataFrame([{"geometry": iso_geom_wgs}], crs=CRS_WGS)
        iso_geom_m = isochrone_gdf.to_crs(CRS_METRIC).geometry.iloc[0]
        print(f"   Stažena z ORS, plocha: {iso_geom_m.area/1e6:.1f} km²")
    else:
        print(f"   ORS chyba {resp.status_code}")
        iso_geom_m = None; isochrone_gdf = None
else:
    print("   ORS_API_KEY není nastaven a cache neexistuje — přeskakuji")
    iso_geom_m = None; isochrone_gdf = None

# ---------------------------------------------------------------------------
# 5. Spatial join: buffer × obce (počet obyvatel)
# ---------------------------------------------------------------------------
print("\n=== 5. Obce v bufferu ===")
obce_m = obce.to_crs(CRS_METRIC).copy()
obce_m["centroid"] = obce_m.geometry.centroid
in_buf = obce_m[obce_m["centroid"].within(buffer_geom_m)].copy().drop(columns=["centroid"])
pop_buf = in_buf["obyvatelstvo_celkem"].sum()

print(f"   Obcí v dosahu: {len(in_buf)}")
print(f"   Obyvatel (buffer): {pop_buf:,.0f}")

# Obce v izochroně
if iso_geom_m:
    obce_m["centroid"] = obce_m.geometry.centroid
    in_iso_obce = obce_m[obce_m["centroid"].within(iso_geom_m)].copy()
    pop_iso_obce = in_iso_obce["obyvatelstvo_celkem"].sum()
    print(f"   Obyvatel (izochróna, centroidy obcí): {pop_iso_obce:,.0f}")

# ---------------------------------------------------------------------------
# 6. Spatial join: gridy × zóny (přesnější odhad populace)
# ---------------------------------------------------------------------------
print("\n=== 6. Gridy domácností v zónách ===")
gridy_m = gridy.to_crs(CRS_METRIC)
gridy_m["centroid"] = gridy_m.geometry.centroid

# Buffer
gridy_buf = gridy_m[gridy_m["centroid"].within(buffer_geom_m)]
pop_grid_buf = gridy_buf["pop_odhad"].sum()
hh_buf = gridy_buf["hh_celkem"].sum()
print(f"   Buffer  – gridů: {len(gridy_buf):,}, domácností: {hh_buf:,}, pop odhad: {pop_grid_buf:,}")

# Izochróna
if iso_geom_m:
    gridy_iso = gridy_m[gridy_m["centroid"].within(iso_geom_m)]
    pop_grid_iso = gridy_iso["pop_odhad"].sum()
    hh_iso = gridy_iso["hh_celkem"].sum()
    print(f"   Izochróna – gridů: {len(gridy_iso):,}, domácností: {hh_iso:,}, pop odhad: {pop_grid_iso:,}")
    print(f"   Izochróna pokrývá {100*pop_grid_iso/pop_grid_buf:.0f} % populace bufferu")

# ---------------------------------------------------------------------------
# 7. Marketing spots v zónách
# ---------------------------------------------------------------------------
print("\n=== 7. Marketing spots ===")
spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg"))

def kategorie(row):
    if pd.notna(row.get("amenity")) and row["amenity"]:
        return str(row["amenity"])
    if pd.notna(row.get("shop")) and row["shop"]:
        return f"shop:{row['shop']}"
    if pd.notna(row.get("public_transport")) and row["public_transport"]:
        return f"pt:{row['public_transport']}"
    return "other"

spots["kategorie"] = spots.apply(kategorie, axis=1)
spots_m = spots.to_crs(CRS_METRIC)
spots_m["centroid"] = spots_m.geometry

spots_buf = spots_m[spots_m.geometry.within(buffer_geom_m)]
spots_iso = spots_m[spots_m.geometry.within(iso_geom_m)] if iso_geom_m else None

counts_buf = spots_buf.groupby("kategorie").size().reset_index(name="pocet_buffer")
if spots_iso is not None:
    counts_iso = spots_iso.groupby("kategorie").size().reset_index(name="pocet_izochro")
    spots_counts = counts_buf.merge(counts_iso, on="kategorie", how="outer").fillna(0)
    spots_counts["pocet_izochro"] = spots_counts["pocet_izochro"].astype(int)
else:
    spots_counts = counts_buf
spots_counts = spots_counts.sort_values("pocet_buffer", ascending=False)
print(spots_counts.to_string(index=False))

# ---------------------------------------------------------------------------
# 8. Export tabulek
# ---------------------------------------------------------------------------
print("\n=== 8. Export CSV ===")

# Obce v dosahu (buffer)
in_buf_wgs = in_buf.to_crs(CRS_WGS)
obce_export = in_buf_wgs[[c for c in [
    "kod", "nazev", "obyvatelstvo_celkem", "muzi", "zeny",
    "vek_0_14", "vek_15_64", "vek_65plus", "prumerny_vek"
] if c in in_buf_wgs.columns]].copy()
obce_export = obce_export.sort_values("obyvatelstvo_celkem", ascending=False)
obce_export.to_csv(os.path.join(OUT_DIR, "obce_v_dosahu.csv"), index=False, encoding="utf-8-sig")
print(f"   obce_v_dosahu.csv ({len(obce_export)} řádků)")

# Marketing spots
spots_counts.to_csv(os.path.join(OUT_DIR, "marketing_spots_kategorie.csv"), index=False, encoding="utf-8-sig")
print(f"   marketing_spots_kategorie.csv")

# Souhrnná tabulka
def fmt(v):
    if isinstance(v, float):
        return f"{v:,.0f}" if v > 100 else f"{v:.1f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)

summary_rows = [
    ("Výchozí bod (byt)", f"{FM_LAT}°N, {FM_LON}°E"),
    ("--- BUFFER 20 km ---", ""),
    ("Obcí v dosahu", len(in_buf)),
    ("Obyvatel (SLDB, centroidy obcí)", f"{int(pop_buf):,}"),
    ("Domácností (1km grid)", f"{int(hh_buf):,}"),
    ("Odh. obyvatel (grid × 2.37)", f"{int(pop_grid_buf):,}"),
    ("--- IZOCHRÓNA 20 min autem ---", ""),
    ("Plocha izochrony", f"{iso_geom_m.area/1e6:.0f} km²" if iso_geom_m else "N/A"),
    ("Domácností (1km grid)", f"{int(hh_iso):,}" if iso_geom_m else "N/A"),
    ("Odh. obyvatel (grid × 2.37)", f"{int(pop_grid_iso):,}" if iso_geom_m else "N/A"),
    ("Pokrytí vs buffer", f"{100*pop_grid_iso/pop_grid_buf:.0f} %" if iso_geom_m else "N/A"),
    ("--- MARKETING SPOTS (buffer) ---", ""),
    ("Restaurace", int(spots_counts[spots_counts.kategorie=="restaurant"]["pocet_buffer"].sum())),
    ("Puby", int(spots_counts[spots_counts.kategorie=="pub"]["pocet_buffer"].sum())),
    ("Fast food", int(spots_counts[spots_counts.kategorie=="fast_food"]["pocet_buffer"].sum())),
    ("Kavárny", int(spots_counts[spots_counts.kategorie=="cafe"]["pocet_buffer"].sum())),
    ("Bary", int(spots_counts[spots_counts.kategorie=="bar"]["pocet_buffer"].sum())),
]
pd.DataFrame(summary_rows, columns=["metrika", "hodnota"]).to_csv(
    os.path.join(OUT_DIR, "souhrn.csv"), index=False, encoding="utf-8-sig"
)
print(f"   souhrn.csv")

# ---------------------------------------------------------------------------
# 9. Interaktivní mapa (folium)
# ---------------------------------------------------------------------------
print("\n=== 9. Tvorba mapy ===")
m = folium.Map(location=[FM_LAT, FM_LON], zoom_start=10, tiles="CartoDB dark_matter")

# --- Choropleth obcí ---
obce_v = in_buf_wgs[in_buf_wgs.geometry.notna()].copy()
obce_v["obyvatelstvo_celkem"] = obce_v["obyvatelstvo_celkem"].fillna(0)
p05 = obce_v["obyvatelstvo_celkem"].quantile(0.05)
p95 = obce_v["obyvatelstvo_celkem"].quantile(0.95)
cmap = LinearColormap(
    ["#0d1b2a", "#1b4332", "#40916c", "#d9ed92", "#f4a261"],
    vmin=p05, vmax=p95, caption="Počet obyvatel obce"
)
obce_layer = folium.FeatureGroup(name="Obce – obyvatelé (SLDB 2021)", show=True)
for _, row in obce_v.iterrows():
    pop = row["obyvatelstvo_celkem"]
    folium.GeoJson(
        row.geometry.__geo_interface__,
        style_function=lambda x, c=cmap(min(pop, p95)): {
            "fillColor": c, "color": "#333", "weight": 0.4, "fillOpacity": 0.6,
        },
        tooltip=folium.Tooltip(
            f"<b>{row['nazev']}</b><br>"
            f"Obyvatel: {int(pop):,}<br>"
            f"0–14: {int(row.get('vek_0_14') or 0):,} | "
            f"15–64: {int(row.get('vek_15_64') or 0):,} | "
            f"65+: {int(row.get('vek_65plus') or 0):,}"
        ),
    ).add_to(obce_layer)
obce_layer.add_to(m)
cmap.add_to(m)

# --- 1km grid hustota domácností ---
grid_layer = folium.FeatureGroup(name="1km grid – domácnosti (SLDB 2021)", show=False)
gridy_vis = gridy_buf[gridy_buf["hh_celkem"] > 0].to_crs(CRS_WGS)
hh_max = gridy_vis["hh_celkem"].quantile(0.95)
cmap_grid = LinearColormap(
    ["#03071e", "#370617", "#9d0208", "#f48c06", "#ffba08"],
    vmin=0, vmax=hh_max, caption="Domácností / km²"
)
for _, row in gridy_vis.iterrows():
    hh = row["hh_celkem"]
    folium.GeoJson(
        row.geometry.__geo_interface__,
        style_function=lambda x, c=cmap_grid(min(hh, hh_max)): {
            "fillColor": c, "color": "none", "fillOpacity": 0.55,
        },
        tooltip=f"Domácnosti: {int(hh):,} | Odh. obyvatel: {int(row['pop_odhad']):,}",
    ).add_to(grid_layer)
grid_layer.add_to(m)

# --- Buffer 20 km ---
folium.GeoJson(
    buffer_wgs.geometry.iloc[0].__geo_interface__,
    name="Buffer 20 km",
    style_function=lambda x: {
        "color": "#00e5ff", "weight": 2.5,
        "fillColor": "#00e5ff", "fillOpacity": 0.05, "dashArray": "6 4",
    },
    tooltip="Buffer 20 km",
).add_to(m)

# --- Izochróna ---
if isochrone_gdf is not None:
    folium.GeoJson(
        isochrone_gdf.geometry.iloc[0].__geo_interface__,
        name="Izochróna 20 min autem",
        style_function=lambda x: {
            "color": "#ff6b35", "weight": 2.5,
            "fillColor": "#ff6b35", "fillOpacity": 0.1,
        },
        tooltip="Izochróna 20 min autem",
    ).add_to(m)

# --- Marketing spots ---
SPOT_COLORS = {
    "restaurant": "#ff4081", "pub": "#ffd740", "fast_food": "#ff6d00",
    "cafe": "#69f0ae", "bar": "#e040fb", "nightclub": "#f06292",
    "fuel": "#90a4ae", "shop:convenience": "#80cbc4",
    "shop:supermarket": "#4dd0e1", "pt:platform": "#607d8b",
    "pt:stop_position": "#546e7a",
}
# Seskupit spoty: zobrazit jen relevantní pro rozvoz
KEY_CATS = ["restaurant", "pub", "fast_food", "cafe", "bar", "nightclub"]
spot_layers = {}
for kat in KEY_CATS:
    grp = folium.FeatureGroup(name=f"Spots: {kat}", show=True)
    spot_layers[kat] = grp
    grp.add_to(m)
other_grp = folium.FeatureGroup(name="Spots: ostatní", show=False)
spot_layers["other"] = other_grp
other_grp.add_to(m)

spots_vis = spots_buf.to_crs(CRS_WGS)
for _, row in spots_vis.iterrows():
    kat = row["kategorie"]
    if kat not in KEY_CATS:
        kat_layer = "other"
    else:
        kat_layer = kat
    color = SPOT_COLORS.get(row["kategorie"], "#aaaaaa")
    name = row.get("name") or row.get("name:cs") or row["kategorie"]
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5, color=color, fill=True, fill_color=color,
        fill_opacity=0.85, weight=1,
        tooltip=f"{name} ({row['kategorie']})",
        popup=folium.Popup(
            f"<b>{name}</b><br>Kategorie: {row['kategorie']}<br>"
            f"{row.get('addr:street','') or ''} {row.get('addr:housenumber','') or ''}<br>"
            f"{row.get('addr:city','') or ''}",
            max_width=250,
        ),
    ).add_to(spot_layers[kat_layer])

# --- Výchozí bod ---
folium.Marker(
    location=[FM_LAT, FM_LON],
    tooltip="Výchozí bod (byt řidiče)",
    icon=folium.Icon(color="blue", icon="home", prefix="fa"),
).add_to(m)

# --- Legenda ---
iso_pop_str = f"{int(pop_grid_iso):,}" if iso_geom_m else "N/A"
legend_html = f"""
<div style="position:fixed;bottom:30px;left:30px;z-index:9999;
     background:rgba(10,10,20,0.93);padding:14px 18px;border-radius:6px;
     border:1px solid #00e5ff;color:#eee;font-family:monospace;font-size:12px;min-width:230px;">
  <b style="color:#00e5ff">VečerkaPlus – dosah rozvozu</b><br>
  <span style="color:#aaa;font-size:10px">výjezd: {FM_LAT}°N {FM_LON}°E</span><br><br>
  <span style="color:#00e5ff">──────</span> Buffer 20 km<br>
  &nbsp;&nbsp;domácností: <b>{int(hh_buf):,}</b> | pop: <b>{int(pop_grid_buf):,}</b><br><br>
  <span style="color:#ff6b35">──────</span> Izochróna 20 min<br>
  &nbsp;&nbsp;domácností: <b>{int(hh_iso) if iso_geom_m else 'N/A':}</b> | pop: <b>{iso_pop_str}</b><br><br>
  <b>Spoty (klíčové)</b><br>
  <span style="color:#ff4081">●</span> Restaurace &nbsp;
  <span style="color:#ffd740">●</span> Pub<br>
  <span style="color:#ff6d00">●</span> Fast food &nbsp;
  <span style="color:#69f0ae">●</span> Kavárna<br>
  <span style="color:#e040fb">●</span> Bar
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

map_path = os.path.join(OUT_DIR, "vecerkaplus_mapa.html")
m.save(map_path)
print(f"   Mapa: output/vecerkaplus_mapa.html")

# ---------------------------------------------------------------------------
# 10. Závěrečný souhrn
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("VÝSLEDKY VečerkaPlus – prostorová analýza")
print("="*60)
print(f"  Výchozí bod:        {FM_LAT}°N, {FM_LON}°E")
print()
print("  BUFFER 20 km")
print(f"    Obcí:             {len(in_buf)}")
print(f"    Domácností:       {int(hh_buf):,}")
print(f"    Odh. obyvatel:    {int(pop_grid_buf):,}")
if iso_geom_m:
    print()
    print("  IZOCHRÓNA 20 min autem")
    print(f"    Plocha:           {iso_geom_m.area/1e6:.0f} km²")
    print(f"    Domácností:       {int(hh_iso):,}")
    print(f"    Odh. obyvatel:    {int(pop_grid_iso):,}")
    print(f"    = {100*pop_grid_iso/pop_grid_buf:.0f} % populace v bufferu")
print()
print("  MARKETING SPOTS (buffer 20 km)")
for _, r in spots_counts[spots_counts["kategorie"].isin(KEY_CATS)].iterrows():
    print(f"    {r['kategorie']:<20} {int(r['pocet_buffer']):>5}",
          end="")
    if "pocet_izochro" in r.index:
        print(f"  (v izochroně: {int(r['pocet_izochro'])})", end="")
    print()
print("="*60)
