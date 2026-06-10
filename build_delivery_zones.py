"""
VečerkaPlus – export rozvozových zón pro webovou aplikaci
==========================================================
Ze stávajících Google Distance Matrix polygonů (driving distance ≤ X km)
sestaví jeden GeoJSON s pásmovými metadaty vhodný pro point-in-polygon
ve frontend aplikaci (turf.js / @turf/boolean-point-in-polygon).

Logika:
  Zákazníkovy GPS souřadnice → zkontroluj od nejbližší zóny:
    ≤ 5 km  → delivery_fee 39 Kč, min_order 500 Kč
    ≤ 10 km → delivery_fee 69 Kč, min_order 500 Kč
    ≤ 15 km → delivery_fee 99 Kč, min_order 700 Kč
    ≤ 20 km → delivery_fee 149 Kč, min_order 700 Kč
    mimo    → not_served

Výstupy:
  data/delivery_zones.geojson        — produkční GeoJSON pro appku (4 features)
  data/delivery_zones_simplified.geojson — zjednodušená verze (~60 % menší)
  output/delivery_zones_preview.html — vizuální kontrola výsledku
"""

import json, os
import geopandas as gpd
import folium
from shapely.geometry import mapping

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
FM_LAT, FM_LON = 49.6754886, 18.3389397

# ── konfigurace zón a cen ─────────────────────────────────────────────────────
ZONES = [
    {
        "zone_km":       5,
        "file":          "google_zone_5km.geojson",
        "label":         "do 5 km",
        "delivery_fee":  39,
        "free_from":     1000,
        "min_order":     500,
        "color":         "#00e676",
        "description":   "Jádro FM — nejrychlejší doručení ~25 min",
    },
    {
        "zone_km":       10,
        "file":          "google_zone_10km.geojson",
        "label":         "5–10 km",
        "delivery_fee":  69,
        "free_from":     1000,
        "min_order":     500,
        "color":         "#ffd740",
        "description":   "Okolí FM — doručení ~35 min",
    },
    {
        "zone_km":       15,
        "file":          "google_zone_15km.geojson",
        "label":         "10–15 km",
        "delivery_fee":  99,
        "free_from":     1200,
        "min_order":     700,
        "color":         "#ff9800",
        "description":   "Frýdlant, Šenov, Havířov sever — doručení ~45 min",
    },
    {
        "zone_km":       20,
        "file":          "google_zone_20km.geojson",
        "label":         "15–20 km",
        "delivery_fee":  149,
        "free_from":     1500,
        "min_order":     700,
        "color":         "#e74c3c",
        "description":   "Havířov, Příbor, Petřvald — doručení ~55 min",
    },
]

# ── načtení a sestavení FeatureCollection ─────────────────────────────────────
print("=== Sestavuji delivery_zones.geojson ===")

features_full = []
features_simp = []

for zone in ZONES:
    path = os.path.join(DATA_DIR, zone["file"])
    gdf  = gpd.read_file(path)
    geom = gdf.geometry.union_all()

    props = {k: v for k, v in zone.items() if k != "file"}

    features_full.append({
        "type":       "Feature",
        "properties": props,
        "geometry":   mapping(geom),
    })

    # Zjednodušení: tolerance 0.0003° ≈ ~25 m — neznatelné pro uživatele
    geom_simp = geom.simplify(0.0003, preserve_topology=True)
    features_simp.append({
        "type":       "Feature",
        "properties": props,
        "geometry":   mapping(geom_simp),
    })

    n_full = sum(len(list(mapping(geom)["coordinates"][0])) if geom.geom_type == "Polygon"
                 else sum(len(r[0]) for r in mapping(geom)["coordinates"])
                 for _ in [None])
    n_simp = sum(len(list(mapping(geom_simp)["coordinates"][0])) if geom_simp.geom_type == "Polygon"
                 else sum(len(r[0]) for r in mapping(geom_simp)["coordinates"])
                 for _ in [None])
    print(f"   {zone['zone_km']:2d} km: {n_full} vrcholů → zjednodušeno na {n_simp} ({n_simp/n_full*100:.0f} %)")

fc_full = {"type": "FeatureCollection", "features": features_full}
fc_simp = {"type": "FeatureCollection", "features": features_simp}

out_full = os.path.join(DATA_DIR, "delivery_zones.geojson")
out_simp = os.path.join(DATA_DIR, "delivery_zones_simplified.geojson")

with open(out_full, "w", encoding="utf-8") as f:
    json.dump(fc_full, f, ensure_ascii=False, separators=(",", ":"))

with open(out_simp, "w", encoding="utf-8") as f:
    json.dump(fc_simp, f, ensure_ascii=False, separators=(",", ":"))

size_full = os.path.getsize(out_full) / 1024
size_simp = os.path.getsize(out_simp) / 1024
print(f"\n   Plný:        {out_full} ({size_full:.0f} kB)")
print(f"   Zjednodušený: {out_simp} ({size_simp:.0f} kB, -{100-size_simp/size_full*100:.0f} %)")

# ── vizuální preview ──────────────────────────────────────────────────────────
print("\n=== Folium preview ===")
m = folium.Map([FM_LAT, FM_LON], zoom_start=11, tiles="CartoDB Positron")

for zone in reversed(ZONES):
    path = os.path.join(DATA_DIR, zone["file"])
    gdf  = gpd.read_file(path)
    color = zone["color"]
    fee   = zone["delivery_fee"]
    free  = zone["free_from"]
    folium.GeoJson(
        gdf.geometry.union_all().__geo_interface__,
        name=f"Zóna {zone['label']}",
        style_function=lambda _, c=color: {
            "fillColor": c, "color": c, "weight": 2.5,
            "fillOpacity": 0.12, "dashArray": "4,3",
        },
        tooltip=folium.Tooltip(
            f"<b>Driving distance {zone['label']}</b><br>"
            f"Dopravné: <b>{fee} Kč</b><br>"
            f"Zdarma od: <b>{free} Kč</b><br>"
            f"Min. objednávka: <b>{zone['min_order']} Kč</b><br>"
            f"<i>{zone['description']}</i>"
        ),
    ).add_to(m)

folium.Marker(
    [FM_LAT, FM_LON], tooltip="Výchozí bod řidiče",
    icon=folium.DivIcon(
        html='<div style="font-size:22px;filter:drop-shadow(1px 1px 2px #fff)">🏠</div>',
        icon_size=(28,28), icon_anchor=(14,14),
    ),
).add_to(m)

# Legenda
legend_rows = "".join(
    f"<tr>"
    f"<td><span style='color:{z['color']};font-size:16px'>■</span> {z['label']}</td>"
    f"<td style='text-align:right'><b>{z['delivery_fee']} Kč</b></td>"
    f"<td style='text-align:right'>zdarma ≥{z['free_from']} Kč</td>"
    f"<td style='text-align:right'>min {z['min_order']} Kč</td>"
    f"</tr>"
    for z in ZONES
)
usage_note = """
<hr style='margin:8px 0'>
<b style='font-size:11px'>Implementace (turf.js):</b>
<pre style='font-size:10px;background:#f5f5f5;padding:6px;border-radius:4px;margin:4px 0'>
import booleanPointInPolygon from '@turf/boolean-point-in-polygon'
import { point } from '@turf/helpers'
import zones from './delivery_zones.geojson'

function getDeliveryFee(lat, lon) {
  const pt = point([lon, lat])
  const zone = zones.features.find(f =>
    booleanPointInPolygon(pt, f)
  )
  return zone?.properties ?? null  // null = not served
}
</pre>
"""
legend_html = f"""
<div style="position:fixed;bottom:20px;right:20px;z-index:9999;
  background:white;border:1px solid #ddd;border-radius:10px;
  padding:14px 18px;font-family:sans-serif;font-size:12px;
  box-shadow:2px 2px 10px rgba(0,0,0,.15);min-width:460px">
  <b style="font-size:14px">VečerkaPlus – rozvozové zóny (driving distance)</b>
  <div style="color:#888;font-size:10px;margin:4px 0">
    Polygony = Google Distance Matrix izocontury · bod zákazníka → nejbližší zóna
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:11px">
    <tr style="color:#888"><th>Zóna</th><th>Dopravné</th><th>Podmínka</th><th>Min. obj.</th></tr>
    {legend_rows}
    <tr><td colspan=4 style="color:#888;font-size:10px;padding-top:4px">
      Zóny jsou vnořené — zákazník patří do nejbližší (nejmenší) zóny.
    </td></tr>
  </table>
  {usage_note}
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
folium.LayerControl(collapsed=False).add_to(m)

out_map = os.path.join(OUT_DIR, "delivery_zones_preview.html")
m.save(out_map)
print(f"   Preview: {out_map}")

# ── TypeScript snippet ────────────────────────────────────────────────────────
ts_snippet = """\
// delivery-zones.ts — point-in-polygon lookup pro rozvozové zóny VečerkaPlus
// Závislosti: @turf/boolean-point-in-polygon @turf/helpers
// GeoJSON: data/delivery_zones_simplified.geojson (zkopírovat do public/ nebo assets/)

import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { point } from "@turf/helpers";
import type { Feature, Polygon, MultiPolygon } from "geojson";
import zonesGeoJson from "./delivery_zones_simplified.geojson";

export interface DeliveryZone {
  zone_km: number;
  label: string;
  delivery_fee: number;   // Kč
  free_from: number;      // Kč — dopravné zdarma od této částky
  min_order: number;      // Kč — minimální objednávka
  description: string;
}

export function getDeliveryZone(lat: number, lon: number): DeliveryZone | null {
  const pt = point([lon, lat]);
  // Zóny jsou seřazeny od nejmenší (5 km) — vrátíme první shodu
  const feature = (zonesGeoJson.features as Feature<Polygon | MultiPolygon, DeliveryZone>[])
    .find((f) => booleanPointInPolygon(pt, f));
  return feature?.properties ?? null;
}

export function calcDeliveryFee(lat: number, lon: number, orderValue: number): {
  fee: number;
  zone: DeliveryZone | null;
  served: boolean;
} {
  const zone = getDeliveryZone(lat, lon);
  if (!zone) return { fee: 0, zone: null, served: false };
  const fee = orderValue >= zone.free_from ? 0 : zone.delivery_fee;
  return { fee, zone, served: true };
}
"""

ts_path = os.path.join(DATA_DIR, "delivery-zones.ts")
with open(ts_path, "w", encoding="utf-8") as f:
    f.write(ts_snippet)
print(f"   TypeScript snippet: {ts_path}")
print("\nHotovo ✓")
