"""
build_zone_policy.py
Generates output/zone_policy.html — delivery coverage polygons + policy recommendations.
"""

import json
import math
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
from shapely.geometry import mapping

FM_LAT, FM_LON = 49.6754886, 18.3389397
CRS_METRIC = "EPSG:5514"
OUTPUT_DIR = Path("output")

AVG_BASKET_KC = 452
GROSS_MARGIN = 0.365

ZONE_CONFIG = [
    {"km": 5,  "ring": "0–5 km",   "fee": 39,  "free_from": 1000, "min_order": 500,  "courier": 120, "color": "#00e676", "bg": "rgba(0,230,118,0.12)"},
    {"km": 10, "ring": "5–10 km",  "fee": 69,  "free_from": 1000, "min_order": 500,  "courier": 120, "color": "#ffd740", "bg": "rgba(255,215,64,0.12)"},
    {"km": 15, "ring": "10–15 km", "fee": 99,  "free_from": 1200, "min_order": 700,  "courier": 180, "color": "#ff9800", "bg": "rgba(255,152,0,0.12)"},
    {"km": 20, "ring": "15–20 km", "fee": 149, "free_from": 1500, "min_order": 700,  "courier": 180, "color": "#e74c3c", "bg": "rgba(231,76,60,0.12)"},
]

NIGHTLIFE_AMENITIES = {"pub", "bar", "nightclub", "cafe", "restaurant", "fast_food"}


def fmt_n(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def load_ring_geometries():
    rings = []
    prev_metric = None
    for cfg in ZONE_CONFIG:
        gdf = gpd.read_file(f"data/google_zone_{cfg['km']}km.geojson")
        curr_metric = gdf.to_crs(CRS_METRIC).geometry.union_all()
        if prev_metric is None:
            ring_metric = curr_metric
        else:
            ring_metric = curr_metric.difference(prev_metric)
        ring_wgs = (
            gpd.GeoDataFrame(geometry=[ring_metric], crs=CRS_METRIC)
            .to_crs("EPSG:4326")
            .geometry.iloc[0]
        )
        rings.append({"geom": ring_wgs, **cfg})
        prev_metric = curr_metric
    return rings


def load_customers():
    df = pd.read_csv("data/zakaznici.csv")
    df = df.dropna(subset=["lat", "lng"])
    return df


def count_nightlife_per_ring(rings):
    spots = gpd.read_file("data/marketing-spots-fm.gpkg")
    spots = spots[spots["amenity"].isin(NIGHTLIFE_AMENITIES)].copy()
    spots = spots.to_crs(CRS_METRIC)

    counts = {}
    prev_metric = None
    for ring in rings:
        curr_metric_geom = (
            gpd.GeoDataFrame(geometry=[ring["geom"]], crs="EPSG:4326")
            .to_crs(CRS_METRIC)
            .geometry.iloc[0]
        )
        if prev_metric is not None:
            ring_metric_geom = curr_metric_geom.union(prev_metric)
        else:
            ring_metric_geom = curr_metric_geom

        in_ring = spots[spots.geometry.within(ring_metric_geom)]
        if prev_metric is not None:
            in_prev = spots[spots.geometry.within(prev_metric)]
            ring_only = len(in_ring) - len(in_prev)
        else:
            ring_only = len(in_ring)
        counts[ring["km"]] = max(ring_only, 0)
        prev_metric = curr_metric_geom
    return counts


def compute_economics(rings):
    gross = round(AVG_BASKET_KC * GROSS_MARGIN)
    for ring in rings:
        ring["gross_kc"] = gross
        ring["net_kc"] = gross + ring["fee"] - ring["courier"]
        ring["breakeven"] = math.ceil(500 / ring["net_kc"])
    return rings


def load_demographics():
    with open("output/network_summary.json") as f:
        data = json.load(f)
    return {
        5:  {"hh": data["5"]["incremental_hh"],  "pop": data["5"]["pop_est"]},
        10: {"hh": data["10"]["incremental_hh"], "pop": data["10"]["pop_est"] - data["5"]["pop_est"]},
        15: {"hh": data["15"]["incremental_hh"], "pop": data["15"]["pop_est"] - data["10"]["pop_est"]},
        20: {"hh": data["20"]["incremental_hh"], "pop": data["20"]["pop_est"] - data["15"]["pop_est"]},
    }


def load_municipalities():
    with open("output/recommended_zone.json") as f:
        return json.load(f)


def build_folium_map(rings, customers, poi_counts):
    m = folium.Map(
        location=[FM_LAT, FM_LON],
        zoom_start=11,
        tiles="CartoDB positron",
        prefer_canvas=True,
    )

    # Ring polygons (outer → inner so inner renders on top)
    for ring in reversed(rings):
        folium.GeoJson(
            data=mapping(ring["geom"]),
            style_function=lambda _, r=ring: {
                "fillColor": r["color"],
                "fillOpacity": 0.20,
                "color": r["color"],
                "weight": 2.5,
                "dashArray": "4 4" if r["km"] > 10 else None,
            },
            tooltip=folium.Tooltip(
                f"<b>{ring['ring']}</b><br>"
                f"Dopravné: {ring['fee']} Kč<br>"
                f"Min objednávka: {ring['min_order']} Kč<br>"
                f"Příspěvek: <b>{ring['net_kc']} Kč/obj</b>"
            ),
        ).add_to(m)

    # Customer markers
    for _, row in customers.iterrows():
        folium.CircleMarker(
            location=[row["lat"], row["lng"]],
            radius=max(5, min(14, row["trzba_kc"] / 60)),
            color="#1565c0",
            fill=True,
            fill_color="#42a5f5",
            fill_opacity=0.85,
            tooltip=f"Objednávka: {row['trzba_kc']} Kč | {row.get('vzdalenost_km', '?')} km",
        ).add_to(m)

    # Origin marker
    folium.Marker(
        location=[FM_LAT, FM_LON],
        tooltip="VečerkaPlus – výchozí bod",
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
    ).add_to(m)

    return m


def render_html(rings, demographics, poi_counts, municipalities, folium_map):
    map_html = folium_map._repr_html_()

    # Traffic-light policy config
    policy = [
        {
            "km": 5,
            "indicator": "#2ecc71",
            "indicator_label": "Aktivně obsloužit",
            "headline": "0–5 km — Jádro FM",
            "body": (
                "Základní provozní zóna. Nejnižší dopravné (39 Kč) přitahuje impulzivní objednávky, "
                "husté osídlení a nejvyšší koncentrace nightlife. Frýdek-Místek centrum, Staré Město, Sviadnov, Lyžbice. "
                "Doporučena agresivní propagace (social media, letáky v barech)."
            ),
        },
        {
            "km": 10,
            "indicator": "#27ae60",
            "indicator_label": "Aktivně obsloužit",
            "headline": "5–10 km — Rozšířený dosah",
            "body": (
                "Nejvyšší příspěvková marže (114 Kč/obj) ze všech zón — kurýrní náklady jsou stejné jako v pásu 0–5 km, "
                "ale dopravné je vyšší (69 Kč). Zahrnuje Havířov (Tier A, ~1 600 Kč/měs), Bašku, Paskov, Dobrá, Šenov. "
                "Doporučena aktivní marketingová kampaň, testování skupinových objednávek."
            ),
        },
        {
            "km": 15,
            "indicator": "#f39c12",
            "indicator_label": "Podmínečně",
            "headline": "10–15 km — Selektivní obsluha",
            "body": (
                "Marže 84 Kč/obj je solidní, ale jen kde poptávka skutečně přijde. "
                "Prioritizovat Frýdlant n.O. (centrum), Petřvald, Brušperk, Příbor. "
                "Pro venkovské obce (Krásná, Hukvaldy, Pstruží) "
                "přijímat objednávky jen pokud kurýr není vytížen v pásu 0–10 km. "
                "Min objednávka 700 Kč."
            ),
        },
        {
            "km": 20,
            "indicator": "#e67e22",
            "indicator_label": "Pouze prémiové objednávky",
            "headline": "15–20 km — Prémiové doručení",
            "body": (
                "Marže 134 Kč/obj při dosažení prahu, ale doručení trvá 45–70 min. "
                "Kurýr stráví na jedné jízdě čas, ve kterém by zvládl 2–3 doručení v centru FM. "
                "Přijímat pouze objednávky ≥ 1 500 Kč (= dopravné zdarma) a pouze pokud je kurýr bez zakázky. "
                "Aktivně nemarketovat. Výjimky dle domluvy."
            ),
        },
    ]

    # Economics table rows
    econ_rows = ""
    for ring in rings:
        km = ring["km"]
        demo = demographics[km]
        poi = poi_counts.get(km, 0)
        net = ring["net_kc"]
        net_color = "#2ecc71" if net >= 100 else "#f39c12" if net >= 80 else "#e74c3c"
        econ_rows += f"""
        <tr>
          <td><span class="ring-dot" style="background:{ring['color']}"></span> {ring['ring']}</td>
          <td>{ring['fee']} Kč</td>
          <td>{ring['min_order']} Kč</td>
          <td>{ring['free_from']} Kč</td>
          <td>{ring['courier']} Kč</td>
          <td style="color:{net_color};font-weight:700">{net} Kč</td>
          <td>{fmt_n(demo['hh'])}</td>
          <td>{fmt_n(demo['pop'])}</td>
          <td>{poi}</td>
        </tr>"""

    # Policy cards
    policy_cards = ""
    for p in policy:
        ring = next(r for r in rings if r["km"] == p["km"])
        policy_cards += f"""
        <div class="policy-card" style="border-left:4px solid {p['indicator']}">
          <div class="policy-header">
            <span class="policy-badge" style="background:{p['indicator']}">{p['indicator_label']}</span>
            <strong>{p['headline']}</strong>
          </div>
          <p>{p['body']}</p>
          <div class="policy-metrics">
            <span>Dopravné: <b>{ring['fee']} Kč</b></span>
            <span>Min objednávka: <b>{ring['min_order']} Kč</b></span>
            <span>Zdarma od: <b>{ring['free_from']} Kč</b></span>
            <span>Marže/obj: <b style="color:{p['indicator']}">{ring['net_kc']} Kč</b></span>
          </div>
        </div>"""

    # Municipality lists
    def muni_list(items, label, color):
        rows = "".join(f"<li>{m}</li>" for m in items)
        return f"""
        <div class="muni-col">
          <h4 style="color:{color}">{label} ({len(items)})</h4>
          <ul>{rows}</ul>
        </div>"""

    muni_html = (
        muni_list(municipalities["ponechat"], "✅ Vždy obsloužit", "#27ae60")
        + muni_list(municipalities["podmínečně"], "⚠️ Podmínečně", "#f39c12")
        + muni_list(municipalities["vyřadit"], "🚫 Neobsloužit", "#e74c3c")
    )

    total_keep_revenue = municipalities["souhrn"]["tier_A_mesicni_kc"] + municipalities["souhrn"]["tier_B_mesicni_kc"]

    html = f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="utf-8"/>
<title>Rozvozová politika — VečerkaPlus</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #0f1117; color: #e0e0e0; line-height: 1.6; }}
  a {{ color: #42a5f5; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px; }}

  h1 {{ font-size: 1.9rem; font-weight: 700; color: #fff; margin-bottom: 4px; }}
  h2 {{ font-size: 1.25rem; font-weight: 600; color: #90caf9; margin: 40px 0 16px; border-bottom: 1px solid #1e3a5f; padding-bottom: 6px; }}
  h3 {{ font-size: 1.05rem; color: #ccc; margin-bottom: 10px; }}
  p {{ color: #bdbdbd; margin-bottom: 10px; }}

  .subtitle {{ color: #78909c; font-size: 0.9rem; margin-bottom: 32px; }}

  /* Map */
  .map-wrap {{ border-radius: 10px; overflow: hidden; border: 1px solid #1e3a5f; margin-bottom: 8px; }}
  .map-wrap iframe {{ width: 100%; height: 540px; border: none; display: block; }}

  /* Table */
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
  th {{ background: #1a2a3a; color: #90caf9; padding: 10px 12px; text-align: left; font-weight: 600; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid #1c2d3f; }}
  tr:hover td {{ background: #151e2a; }}
  .ring-dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}

  /* Policy cards */
  .policy-card {{ background: #131b26; border-radius: 8px; padding: 18px 20px; margin-bottom: 16px; }}
  .policy-header {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
  .policy-badge {{ font-size: 0.75rem; font-weight: 700; padding: 3px 10px; border-radius: 99px; color: #000; white-space: nowrap; }}
  .policy-metrics {{ display: flex; gap: 20px; flex-wrap: wrap; margin-top: 12px; font-size: 0.82rem; color: #90a4ae; }}
  .policy-metrics span b {{ color: #e0e0e0; }}

  /* Municipality grid */
  .muni-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }}
  .muni-col h4 {{ font-size: 0.92rem; margin-bottom: 8px; }}
  .muni-col ul {{ list-style: none; padding: 0; }}
  .muni-col ul li {{ font-size: 0.83rem; color: #ccc; padding: 3px 0; border-bottom: 1px solid #1a2530; }}
  .muni-col ul li:last-child {{ border-bottom: none; }}

  /* Insight box */
  .insight {{ background: #1a2744; border: 1px solid #2979ff; border-radius: 8px; padding: 16px 20px; margin: 24px 0; }}
  .insight strong {{ color: #82b1ff; }}

  /* Revenue summary */
  .summary-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }}
  .summary-card {{ background: #131b26; border-radius: 8px; padding: 14px 18px; flex: 1; min-width: 160px; }}
  .summary-card .val {{ font-size: 1.6rem; font-weight: 700; color: #fff; }}
  .summary-card .lbl {{ font-size: 0.78rem; color: #78909c; margin-top: 2px; }}

  @media (max-width: 700px) {{
    .muni-grid {{ grid-template-columns: 1fr; }}
    .summary-row {{ flex-direction: column; }}
  }}
</style>
</head>
<body>
<div class="container">

  <h1>Rozvozová politika VečerkaPlus</h1>
  <p class="subtitle">Pátek–neděle 22:00–6:00 · Frýdek-Místek · Vygenerováno 2026-06-10</p>

  <div class="summary-row">
    <div class="summary-card">
      <div class="val">20 km</div>
      <div class="lbl">Maximální rozvozová vzdálenost</div>
    </div>
    <div class="summary-card">
      <div class="val">4 zóny</div>
      <div class="lbl">Cenové pásma (5 / 10 / 15 / 20 km)</div>
    </div>
    <div class="summary-card">
      <div class="val">{fmt_n(municipalities['souhrn']['ponechat_count'])} obcí</div>
      <div class="lbl">Doporučeno aktivně obsloužit</div>
    </div>
    <div class="summary-card">
      <div class="val">{fmt_n(total_keep_revenue)} Kč</div>
      <div class="lbl">Odhadovaný měsíční příspěvek (Tier A+B)</div>
    </div>
  </div>

  <!-- MAP -->
  <h2>Mapa pokrytí</h2>
  <div class="map-wrap">{map_html}</div>
  <p style="font-size:0.8rem;color:#546e7a;margin-top:6px">
    Polygony: Google Distance Matrix (řidičská vzdálenost z FM). Modré body = reálné objednávky.
  </p>

  <!-- ECONOMICS TABLE -->
  <h2>Ekonomika podle zóny</h2>
  <p style="font-size:0.85rem;color:#78909c;margin-bottom:12px">
    Příspěvek/objednávku = hrubá marže ({round(GROSS_MARGIN*100)}% z průměrné objednávky {AVG_BASKET_KC} Kč = {round(AVG_BASKET_KC*GROSS_MARGIN)} Kč) + dopravné − náklady kurýra.
    Domácnosti a obyvatelé z OSMnx isodistančního modelu (orientační).
  </p>
  <table>
    <thead>
      <tr>
        <th>Zóna</th>
        <th>Dopravné</th>
        <th>Min obj.</th>
        <th>Zdarma od</th>
        <th>Kurýr/obj</th>
        <th>Příspěvek/obj</th>
        <th>Domácností</th>
        <th>Obyvatelé</th>
        <th>Nightlife POI</th>
      </tr>
    </thead>
    <tbody>{econ_rows}</tbody>
  </table>

  <div class="insight" style="margin-top:20px">
    <strong>Klíčový závěr:</strong> Marže jsou kladné ve všech 4 zónách.
    Limitujícím faktorem není ziskovost, ale <strong>čas kurýra</strong> —
    doručení do 15–20 km trvá 45–70 min = kurýr nestihne druhou objednávku v centru FM,
    kde by vydělal 3–4× více za hodinu.
  </div>

  <!-- POLICY RECOMMENDATIONS -->
  <h2>Doporučení pro rozvozovou politiku</h2>
  {policy_cards}

  <!-- MUNICIPALITY LIST -->
  <h2>Doporučení po obcích</h2>
  <p style="font-size:0.85rem;color:#78909c;margin-bottom:16px">
    Hodnocení vychází z tržního potenciálu (počet domácností × noční konverze),
    P&amp;L příspěvku, hustoty bytové zástavby a nightlife POI indexu.
  </p>
  <div class="muni-grid">{muni_html}</div>

</div>
</body>
</html>"""

    return html


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Načítám geometrie zón …")
    rings = load_ring_geometries()
    rings = compute_economics(rings)

    print("Načítám zákazníky …")
    customers = load_customers()

    print("Počítám nightlife POI na zónu …")
    poi_counts = count_nightlife_per_ring(rings)

    print("Načítám demografiku …")
    demographics = load_demographics()

    print("Načítám doporučení obcí …")
    municipalities = load_municipalities()

    print("Stavím mapu …")
    folium_map = build_folium_map(rings, customers, poi_counts)

    print("Generuji HTML …")
    html = render_html(rings, demographics, poi_counts, municipalities, folium_map)

    out_path = OUTPUT_DIR / "zone_policy.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"✓ {out_path}")

    # Print economics summary to console
    print("\n── Ekonomika zón ──")
    gross = round(AVG_BASKET_KC * GROSS_MARGIN)
    for ring in rings:
        print(f"  {ring['ring']:12s}  fee={ring['fee']:3d} Kč  kurýr={ring['courier']} Kč  příspěvek={ring['net_kc']:4d} Kč  nightlife POI={poi_counts.get(ring['km'], 0)}")


if __name__ == "__main__":
    main()
