"""
VečerkaPlus – prostorová analýza dosahu rozvozu
FM střed: 49.6833, 18.3667
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
from folium.plugins import MarkerCluster
from branca.colormap import LinearColormap

# ---------------------------------------------------------------------------
# Konfigurace
# ---------------------------------------------------------------------------
FM_LAT, FM_LON = 49.6833, 18.3667
BUFFER_DIST_M = 20_000          # 20 km
CRS_METRIC = "EPSG:5514"        # S-JTSK (záporné souřadnice)
CRS_WGS = "EPSG:4326"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT_DIR, exist_ok=True)

ORS_API_KEY = os.environ.get("ORS_API_KEY", "")

# ČSÚ SLDB 2021 – mapování kódů na čitelné názvy
SLDB_COLS = {
    "gis131620000": "obyvatelstvo_celkem",
    "gis131620001": "muzi",
    "gis131620002": "zeny",
    "gis131620011": "vek_0_14",
    "gis131620012": "vek_15_64",
    "gis131620013": "vek_65plus",
    "gis124070001": "prumerny_vek",
}

# ---------------------------------------------------------------------------
# 1. Načtení obcí SLDB 2021
# ---------------------------------------------------------------------------
print("=== 1. Načítám obce SLDB 2021 ===")
sldb_path = os.path.join(DATA_DIR, "obce_sldb",
                         "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")
obce = gpd.read_file(sldb_path)
print(f"   Načteno {len(obce)} obcí, CRS: {obce.crs}")

# Přejmenovat demografické sloupce
obce = obce.rename(columns=SLDB_COLS)
# Zachovat jen potřebné sloupce
keep = ["kod", "nazev", "geometry"] + list(SLDB_COLS.values())
keep = [c for c in keep if c in obce.columns]
obce = obce[keep]

# ---------------------------------------------------------------------------
# 2. Buffer 20 km od středu FM
# ---------------------------------------------------------------------------
print("\n=== 2. Buffer 20 km ===")
fm_point_wgs = gpd.GeoDataFrame(
    [{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS
)
fm_point_m = fm_point_wgs.to_crs(CRS_METRIC)
buffer_m = fm_point_m.buffer(BUFFER_DIST_M)
buffer_gdf = gpd.GeoDataFrame(geometry=buffer_m, crs=CRS_METRIC)
buffer_wgs = buffer_gdf.to_crs(CRS_WGS)
print(f"   Buffer hotov, plocha ≈ {buffer_m.area.values[0]/1e6:.1f} km²")

# ---------------------------------------------------------------------------
# 3. Spatial join buffer × obce → demografika
# ---------------------------------------------------------------------------
print("\n=== 3. Spatial join: buffer × obce ===")
# Obce musí být ve stejném CRS jako buffer
obce_m = obce.to_crs(CRS_METRIC)
buffer_geom = buffer_m.iloc[0]

# Průnik: obec musí mít centroid uvnitř bufferu (pro přesnější počítání)
obce_m["centroid"] = obce_m.geometry.centroid
obce_m["v_bufferu"] = obce_m["centroid"].within(buffer_geom)
obce_v_bufferu = obce_m[obce_m["v_bufferu"]].copy()
obce_v_bufferu = obce_v_bufferu.drop(columns=["centroid", "v_bufferu"])

print(f"   Obcí v dosahu: {len(obce_v_bufferu)}")

pop_total     = obce_v_bufferu["obyvatelstvo_celkem"].sum()
pop_0_14      = obce_v_bufferu["vek_0_14"].sum()
pop_15_64     = obce_v_bufferu["vek_15_64"].sum()
pop_65plus    = obce_v_bufferu["vek_65plus"].sum()
avg_age_mean  = obce_v_bufferu["prumerny_vek"].mean()

print(f"   Celkem obyvatel: {pop_total:,.0f}")
print(f"   0–14 let:        {pop_0_14:,.0f} ({100*pop_0_14/pop_total:.1f} %)")
print(f"   15–64 let:       {pop_15_64:,.0f} ({100*pop_15_64/pop_total:.1f} %)")
print(f"   65+ let:         {pop_65plus:,.0f} ({100*pop_65plus/pop_total:.1f} %)")
print(f"   Průměrný věk:    {avg_age_mean:.1f} let")

# ---------------------------------------------------------------------------
# 4. Spatial join buffer × marketing spots
# ---------------------------------------------------------------------------
print("\n=== 4. Spatial join: buffer × marketing spots ===")
spots_path = os.path.join(DATA_DIR, "marketing-spots-fm.gpkg")
spots = gpd.read_file(spots_path)
spots_m = spots.to_crs(CRS_METRIC)

spots_m["v_bufferu"] = spots_m.geometry.within(buffer_geom)
spots_v_bufferu = spots_m[spots_m["v_bufferu"]].copy()
print(f"   Celkem spotů v dosahu: {len(spots_v_bufferu)}")

# Kategorizace: primárně amenity, sekundárně shop/public_transport
def kategorie(row):
    if pd.notna(row.get("amenity")) and row["amenity"] not in ("", None):
        return str(row["amenity"])
    if pd.notna(row.get("shop")) and row["shop"] not in ("", None):
        return f"shop:{row['shop']}"
    if pd.notna(row.get("public_transport")) and row["public_transport"] not in ("", None):
        return f"pt:{row['public_transport']}"
    return "other"

spots_v_bufferu["kategorie"] = spots_v_bufferu.apply(kategorie, axis=1)

spots_counts = (
    spots_v_bufferu.groupby("kategorie")
    .size()
    .reset_index(name="pocet")
    .sort_values("pocet", ascending=False)
)
print(spots_counts.to_string(index=False))

# ---------------------------------------------------------------------------
# 5. Izochróna 20 min autem z FM přes ORS
# ---------------------------------------------------------------------------
print("\n=== 5. Izochróna (OpenRouteService) ===")
isochrone_gdf = None
isochrone_geom = None

if ORS_API_KEY:
    url = "https://api.openrouteservice.org/v2/isochrones/driving-car"
    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }
    body = {
        "locations": [[FM_LON, FM_LAT]],
        "range": [1200],   # 20 min = 1200 s
        "range_type": "time",
        "smoothing": 25,
    }
    resp = requests.post(url, headers=headers, json=body, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        feat = data["features"][0]
        isochrone_geom = shape(feat["geometry"])
        isochrone_gdf = gpd.GeoDataFrame(
            [{"geometry": isochrone_geom, "range_s": 1200}], crs=CRS_WGS
        )
        print("   Izochróna úspěšně stažena z ORS.")
    else:
        print(f"   ORS chyba {resp.status_code}: {resp.text[:200]}")
else:
    print("   ORS_API_KEY není nastaven — přeskakuji API volání.")
    print("   Nastav: export ORS_API_KEY='tvůj_klíč'  (https://openrouteservice.org/dev)")

# ---------------------------------------------------------------------------
# 6. Porovnání buffer vs. izochróna
# ---------------------------------------------------------------------------
print("\n=== 6. Porovnání zón ===")

# Obyvatelstvo v bufferu (centroidy uvnitř) – spočítáno výše
pop_buffer = int(pop_total)

pop_isochrone = None
if isochrone_gdf is not None:
    iso_m = isochrone_gdf.to_crs(CRS_METRIC)
    iso_geom = iso_m.geometry.iloc[0]
    obce_m2 = obce.to_crs(CRS_METRIC).copy()
    obce_m2["centroid"] = obce_m2.geometry.centroid
    obce_m2["v_iso"] = obce_m2["centroid"].within(iso_geom)
    pop_isochrone = int(obce_m2[obce_m2["v_iso"]]["obyvatelstvo_celkem"].sum())
    print(f"   Buffer 20 km:   {pop_buffer:>10,} obyvatel")
    print(f"   Izochróna 20':  {pop_isochrone:>10,} obyvatel")
    diff = pop_buffer - pop_isochrone
    print(f"   Rozdíl:         {diff:>10,} ({100*diff/pop_buffer:.1f} % méně v izochroně)")
else:
    print(f"   Buffer 20 km:   {pop_buffer:>10,} obyvatel")
    print("   Izochróna: nedostupná (bez ORS klíče)")

# ---------------------------------------------------------------------------
# 7. Export tabulek
# ---------------------------------------------------------------------------
print("\n=== 7. Export CSV ===")

# Tabulka obcí v dosahu
obce_export = obce_v_bufferu[[c for c in [
    "kod", "nazev", "obyvatelstvo_celkem", "muzi", "zeny",
    "vek_0_14", "vek_15_64", "vek_65plus", "prumerny_vek"
] if c in obce_v_bufferu.columns]].copy()
obce_export = obce_export.sort_values("obyvatelstvo_celkem", ascending=False)
obce_export.to_csv(os.path.join(OUT_DIR, "obce_v_dosahu.csv"), index=False, encoding="utf-8-sig")
print(f"   Uloženo: output/obce_v_dosahu.csv ({len(obce_export)} řádků)")

# Tabulka marketing spots podle kategorie
spots_counts.to_csv(os.path.join(OUT_DIR, "marketing_spots_kategorie.csv"), index=False, encoding="utf-8-sig")
print(f"   Uloženo: output/marketing_spots_kategorie.csv")

# Souhrnná tabulka
summary = {
    "metriky": [
        "Počet obcí v dosahu (20 km)",
        "Celkem obyvatel (buffer 20 km)",
        "  z toho 0–14 let",
        "  z toho 15–64 let",
        "  z toho 65+ let",
        "Průměrný věk (střed obcí)",
        "Celkem marketing spots",
        "  restaurace",
        "  puby",
        "  fast food",
        "  kavárny",
        "  bary",
        "  zastávky MHD (pt:platform)",
        "Obyvatel v izochroně 20 min",
    ],
    "hodnota": [
        len(obce_v_bufferu),
        f"{pop_buffer:,}",
        f"{int(pop_0_14):,} ({100*pop_0_14/pop_total:.1f} %)",
        f"{int(pop_15_64):,} ({100*pop_15_64/pop_total:.1f} %)",
        f"{int(pop_65plus):,} ({100*pop_65plus/pop_total:.1f} %)",
        f"{avg_age_mean:.1f}",
        len(spots_v_bufferu),
    ] + [
        int(spots_counts[spots_counts.kategorie == k]["pocet"].sum())
        if k in spots_counts.kategorie.values else 0
        for k in ["restaurant", "pub", "fast_food", "cafe", "bar", "pt:platform"]
    ] + [
        f"{pop_isochrone:,}" if pop_isochrone is not None else "N/A (ORS_API_KEY chybí)"
    ]
}
pd.DataFrame(summary).to_csv(
    os.path.join(OUT_DIR, "souhrn.csv"), index=False, encoding="utf-8-sig"
)
print(f"   Uloženo: output/souhrn.csv")

# ---------------------------------------------------------------------------
# 8. Interaktivní mapa (folium)
# ---------------------------------------------------------------------------
print("\n=== 8. Tvorba mapy ===")

m = folium.Map(
    location=[FM_LAT, FM_LON],
    zoom_start=10,
    tiles="CartoDB dark_matter",
)

# --- Choropleth – obyvatelstvo obcí ---
obce_wgs = obce_v_bufferu.to_crs(CRS_WGS).copy()
obce_wgs["obyvatelstvo_celkem"] = obce_wgs["obyvatelstvo_celkem"].fillna(0)

# Pouze obce s geometrií
obce_wgs_valid = obce_wgs[obce_wgs.geometry.notna()].copy()

pop_min = obce_wgs_valid["obyvatelstvo_celkem"].quantile(0.05)
pop_max = obce_wgs_valid["obyvatelstvo_celkem"].quantile(0.95)
colormap = LinearColormap(
    ["#1a1a2e", "#16213e", "#0f3460", "#533483", "#e94560"],
    vmin=pop_min, vmax=pop_max,
    caption="Počet obyvatel obce"
)

choropleth_layer = folium.FeatureGroup(name="Obce (choropleth dle obyvatel)", show=True)
for _, row in obce_wgs_valid.iterrows():
    pop = row["obyvatelstvo_celkem"]
    color = colormap(min(pop, pop_max))
    tooltip_text = (
        f"<b>{row['nazev']}</b><br>"
        f"Obyvatel: {int(pop):,}<br>"
        f"0–14: {int(row.get('vek_0_14', 0) or 0):,} | "
        f"15–64: {int(row.get('vek_15_64', 0) or 0):,} | "
        f"65+: {int(row.get('vek_65plus', 0) or 0):,}<br>"
        f"Průměrný věk: {row.get('prumerny_vek', 0):.1f}"
    )
    folium.GeoJson(
        row.geometry.__geo_interface__,
        style_function=lambda x, c=color: {
            "fillColor": c,
            "color": "#444",
            "weight": 0.5,
            "fillOpacity": 0.65,
        },
        tooltip=folium.Tooltip(tooltip_text),
    ).add_to(choropleth_layer)
choropleth_layer.add_to(m)
colormap.add_to(m)

# --- Buffer 20 km ---
folium.GeoJson(
    buffer_wgs.geometry.iloc[0].__geo_interface__,
    name="Buffer 20 km",
    style_function=lambda x: {
        "color": "#00e5ff",
        "weight": 2.5,
        "fillColor": "#00e5ff",
        "fillOpacity": 0.07,
        "dashArray": "6 4",
    },
    tooltip="Buffer 20 km od středu FM",
).add_to(m)

# --- Izochróna ---
if isochrone_gdf is not None:
    folium.GeoJson(
        isochrone_gdf.geometry.iloc[0].__geo_interface__,
        name="Izochróna 20 min (auto)",
        style_function=lambda x: {
            "color": "#ff6b35",
            "weight": 2.5,
            "fillColor": "#ff6b35",
            "fillOpacity": 0.12,
        },
        tooltip="Izochróna 20 min autem",
    ).add_to(m)

# --- Marketing spots (barevně dle kategorie) ---
SPOT_COLORS = {
    "restaurant":    "#ff4081",
    "pub":           "#ffd740",
    "fast_food":     "#ff6d00",
    "cafe":          "#69f0ae",
    "bar":           "#e040fb",
    "nightclub":     "#f06292",
    "fuel":          "#90a4ae",
    "shop:convenience": "#80cbc4",
    "shop:supermarket": "#4dd0e1",
    "pt:platform":   "#b0bec5",
    "pt:stop_position": "#78909c",
}
DEFAULT_COLOR = "#aaaaaa"

spots_layer_groups = {}
spots_wgs = spots_v_bufferu.to_crs(CRS_WGS)
for kat in spots_wgs["kategorie"].unique():
    grp = folium.FeatureGroup(name=f"Spots: {kat}", show=(kat not in ["pt:platform", "pt:stop_position"]))
    spots_layer_groups[kat] = grp
    grp.add_to(m)

for _, row in spots_wgs.iterrows():
    kat = row["kategorie"]
    color = SPOT_COLORS.get(kat, DEFAULT_COLOR)
    name = row.get("name") or row.get("name:cs") or kat
    popup_html = (
        f"<b>{name}</b><br>"
        f"Kategorie: {kat}<br>"
        f"{row.get('addr:street', '')} {row.get('addr:housenumber', '')}<br>"
        f"{row.get('addr:city', '')}"
    )
    folium.CircleMarker(
        location=[row.geometry.y, row.geometry.x],
        radius=5,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.85,
        weight=1,
        popup=folium.Popup(popup_html, max_width=250),
        tooltip=f"{name} ({kat})",
    ).add_to(spots_layer_groups[kat])

# --- FM střed ---
folium.Marker(
    location=[FM_LAT, FM_LON],
    tooltip="VečerkaPlus – sklad FM",
    icon=folium.Icon(color="blue", icon="home", prefix="fa"),
).add_to(m)

# --- Legenda ---
legend_html = """
<div style="position:fixed;bottom:30px;left:30px;z-index:9999;
     background:rgba(10,10,20,0.92);padding:14px 18px;border-radius:6px;
     border:1px solid #00e5ff;color:#eee;font-family:monospace;font-size:12px;
     max-width:220px;">
  <b style="color:#00e5ff">VečerkaPlus – dosah</b><br><br>
  <span style="color:#00e5ff">──────</span> Buffer 20 km<br>
  <span style="color:#ff6b35">──────</span> Izochróna 20 min<br><br>
  <b>Marketing spots</b><br>
  <span style="color:#ff4081">●</span> Restaurace &nbsp;
  <span style="color:#ffd740">●</span> Pub<br>
  <span style="color:#ff6d00">●</span> Fast food &nbsp;
  <span style="color:#69f0ae">●</span> Kavárna<br>
  <span style="color:#e040fb">●</span> Bar &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <span style="color:#b0bec5">●</span> Zastávka
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

folium.LayerControl(collapsed=False).add_to(m)

map_path = os.path.join(OUT_DIR, "vecerkaplus_mapa.html")
m.save(map_path)
print(f"   Mapa uložena: output/vecerkaplus_mapa.html")

# ---------------------------------------------------------------------------
# 9. Výsledkový souhrn
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("VÝSLEDKY VečerkaPlus – prostorová analýza")
print("="*60)
print(f"  Střed FM:           {FM_LAT}, {FM_LON}")
print(f"  Počet obcí (20 km): {len(obce_v_bufferu)}")
print(f"  Obyvatelé (buffer): {pop_buffer:,}")
print(f"  Věk 0–14:           {100*pop_0_14/pop_total:.1f} %")
print(f"  Věk 15–64:          {100*pop_15_64/pop_total:.1f} %")
print(f"  Věk 65+:            {100*pop_65plus/pop_total:.1f} %")
print(f"  Prům. věk:          {avg_age_mean:.1f} let")
print(f"  Spots celkem:       {len(spots_v_bufferu)}")
for _, r in spots_counts.head(8).iterrows():
    print(f"    {r['kategorie']:<25} {r['pocet']:>5}")
if pop_isochrone is not None:
    print(f"  Obyvatelé (20 min): {pop_isochrone:,}")
print("="*60)
print("Výstupy v /output:")
print("  vecerkaplus_mapa.html")
print("  obce_v_dosahu.csv")
print("  marketing_spots_kategorie.csv")
print("  souhrn.csv")
