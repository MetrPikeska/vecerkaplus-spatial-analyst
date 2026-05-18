"""
Vybudování reálné rozvozové zóny VečerkaPlus pomocí Google Distance Matrix API.
Logika shodná s vecerkaplus.cz: driving distance ≤ 20 km z "Frýdek-Místek, ČR".
"""

import json
import time
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, MultiPoint
from shapely.ops import unary_union
import os

# ---------------------------------------------------------------------------
GOOGLE_KEY = "AIzaSyC8EhWAIi2-BBQDEdTcBMoCoynvZ19Gd3s"
ORIGIN     = "Frýdek-Místek, Česká republika"   # shodné s App.tsx
MAX_KM     = 20.0                                # limit z App.tsx
FM_LAT, FM_LON = 49.6833, 18.3667               # střed FM (geocode origin)
GRID_STEP_KM   = 1.5                             # rozlišení gridu
SEARCH_RADIUS_KM = 28                            # trochu větší než limit

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
CACHE_FILE = os.path.join(DATA_DIR, "google_distance_cache.json")

# ---------------------------------------------------------------------------
# 1. Generovat grid bodů
# ---------------------------------------------------------------------------
def latlon_grid(center_lat, center_lon, radius_km, step_km):
    """Pravidelný grid bodů v kruhu kolem centra."""
    # 1 stupeň lat ≈ 111 km; 1 stupeň lon ≈ 111*cos(lat) km
    dlat = step_km / 111.0
    dlon = step_km / (111.0 * np.cos(np.radians(center_lat)))
    steps_lat = int(radius_km / step_km) + 1
    steps_lon = int(radius_km / step_km) + 1
    points = []
    for i in range(-steps_lat, steps_lat + 1):
        for j in range(-steps_lon, steps_lon + 1):
            lat = center_lat + i * dlat
            lon = center_lon + j * dlon
            # Vzdušná vzdálenost pro filtraci
            d = np.sqrt(((lat - center_lat) * 111) ** 2 +
                        ((lon - center_lon) * 111 * np.cos(np.radians(center_lat))) ** 2)
            if d <= radius_km:
                points.append((lat, lon))
    return points

# ---------------------------------------------------------------------------
# 2. Google Distance Matrix — batch (max 25 destinací/request)
# ---------------------------------------------------------------------------
def query_distances(destinations, cache):
    """Dotáže Google API pro seznam (lat, lon) bodů, vrátí dict {(lat,lon): km}."""
    results = {}
    to_query = [d for d in destinations if d not in cache]

    print(f"   Cache: {len(destinations)-len(to_query)} bodů, API: {len(to_query)} bodů")

    BATCH = 25
    for i in range(0, len(to_query), BATCH):
        batch = to_query[i:i + BATCH]
        dests_str = "|".join(f"{lat},{lon}" for lat, lon in batch)
        url = (
            "https://maps.googleapis.com/maps/api/distancematrix/json"
            f"?origins={requests.utils.quote(ORIGIN)}"
            f"&destinations={requests.utils.quote(dests_str)}"
            f"&mode=driving"
            f"&key={GOOGLE_KEY}"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()
        if data.get("status") != "OK":
            print(f"   API chyba: {data.get('status')}")
            continue
        for idx, element in enumerate(data["rows"][0]["elements"]):
            pt = batch[idx]
            if element["status"] == "OK":
                km = element["distance"]["value"] / 1000.0
                cache[str(pt)] = km
                results[pt] = km
            else:
                cache[str(pt)] = None
                results[pt] = None
        # Rate limit: max 10 req/s
        time.sleep(0.12)
        if (i // BATCH + 1) % 10 == 0:
            print(f"   ... {i+BATCH}/{len(to_query)} bodů hotovo")

    # Přidej cached výsledky
    for pt in destinations:
        if pt not in results:
            v = cache.get(str(pt))
            results[pt] = v
    return results

# ---------------------------------------------------------------------------
# Hlavní tok
# ---------------------------------------------------------------------------
print("=== Budování Google rozvozové zóny ===")
print(f"    Origin: {ORIGIN}")
print(f"    Limit:  ≤ {MAX_KM} km driving")
print(f"    Grid:   {GRID_STEP_KM} km krok, {SEARCH_RADIUS_KM} km rádius")

# Načíst cache
cache = {}
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE) as f:
        cache = json.load(f)
    print(f"    Načteno {len(cache)} cached bodů")

# Generovat grid
grid = latlon_grid(FM_LAT, FM_LON, SEARCH_RADIUS_KM, GRID_STEP_KM)
print(f"    Celkem bodů v gridu: {len(grid)}")

# Dotázat vzdálenosti
distances = query_distances(grid, cache)

# Uložit cache
with open(CACHE_FILE, "w") as f:
    json.dump(cache, f)
print(f"    Cache uložena: {len(cache)} bodů")

# ---------------------------------------------------------------------------
# 3. Sestavit zónu jako polygon
# ---------------------------------------------------------------------------
in_zone  = [pt for pt, km in distances.items() if km is not None and km <= MAX_KM]
out_zone = [pt for pt, km in distances.items() if km is not None and km > MAX_KM]

print(f"\n    V zóně (≤ {MAX_KM} km):  {len(in_zone)} bodů")
print(f"    Mimo zónu:              {len(out_zone)} bodů")
print(f"    Nedostupné:             {sum(1 for km in distances.values() if km is None)} bodů")

# Vytvořit polygon z bodů v zóně — buffer o půl kroku gridu + unary_union
step_deg = GRID_STEP_KM / 111.0 * 0.75
zone_polys = [Point(lon, lat).buffer(step_deg) for lat, lon in in_zone]
zone_polygon = unary_union(zone_polys)

# Uložit jako GeoJSON
zone_gdf = gpd.GeoDataFrame([{"geometry": zone_polygon, "source": "Google Distance Matrix",
                               "origin": ORIGIN, "max_km": MAX_KM}],
                            crs="EPSG:4326")
zone_path = os.path.join(DATA_DIR, "google_zone_20km.geojson")
zone_gdf.to_file(zone_path, driver="GeoJSON")
print(f"\n    Zóna uložena: data/google_zone_20km.geojson")

# Statistiky
area_km2 = zone_gdf.to_crs("EPSG:5514").geometry.area.values[0] / 1e6
print(f"    Plocha zóny: {area_km2:.0f} km²")

# CSV se vzdálenostmi všech bodů
rows = []
for (lat, lon), km in distances.items():
    rows.append({"lat": lat, "lon": lon, "distance_km": km,
                 "v_zone": km <= MAX_KM if km is not None else None})
pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "google_grid_distances.csv"),
                          index=False, encoding="utf-8-sig")
print(f"    Grid CSV: output/google_grid_distances.csv")
print("\nHotovo.")
