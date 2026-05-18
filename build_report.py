"""
VečerkaPlus – generátor HTML reportu prostorové analýzy
"""
import warnings; warnings.filterwarnings("ignore")
import os, json
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, shape
import math

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR  = os.path.join(os.path.dirname(__file__), "output")
CRS_METRIC = "EPSG:5514"
CRS_WGS    = "EPSG:4326"
FM_LAT, FM_LON = 49.6754886, 18.3389397

# ── Načtení dat ────────────────────────────────────────────────────────────
print("Načítám data...")

# Google zóna
zone_gdf = gpd.read_file(os.path.join(DATA_DIR, "google_zone_20km.geojson"))
zone_m   = zone_gdf.to_crs(CRS_METRIC).geometry.iloc[0]
zone_area_km2 = zone_m.area / 1e6

# SLDB obce
obce = gpd.read_file(os.path.join(DATA_DIR, "obce_sldb",
    "csu_geodb_sde_CISOB_obyvatelstvo_etl_20210326.gpkg")).rename(columns={
    "gis131620000":"obyvatelstvo_celkem","gis131620001":"muzi","gis131620002":"zeny",
    "gis131620011":"vek_0_14","gis131620012":"vek_15_64","gis131620013":"vek_65plus",
    "gis124070001":"prumerny_vek"})
fm_pt = gpd.GeoDataFrame([{"geometry": Point(FM_LON, FM_LAT)}], crs=CRS_WGS).to_crs(CRS_METRIC)
buf_m = fm_pt.buffer(20000).iloc[0]
obce_m = obce.to_crs(CRS_METRIC); obce_m["c"] = obce_m.geometry.centroid
in_buf = obce_m[obce_m["c"].within(buf_m)]
in_iso = obce_m[obce_m["c"].within(zone_m)]
pop_buf   = int(in_buf["obyvatelstvo_celkem"].sum())
pop_iso   = int(in_iso["obyvatelstvo_celkem"].sum())
vek_0_14  = int(in_iso["vek_0_14"].sum())
vek_15_64 = int(in_iso["vek_15_64"].sum())
vek_65p   = int(in_iso["vek_65plus"].sum())
avg_vek   = round(in_iso["prumerny_vek"].mean(), 1)

# Gridy domácností
gridy = gpd.read_file(os.path.join(DATA_DIR, "gridy_domacnosti",
    "grid_domacnosti_sldb2021_20210326.gpkg")).rename(columns={"g179999001":"hh_celkem"})
gridy_m = gridy.to_crs(CRS_METRIC); gridy_m["c"] = gridy_m.geometry.centroid
hh_iso = int(gridy_m[gridy_m["c"].within(zone_m)]["hh_celkem"].sum())
pop_grid_iso = int(hh_iso * 2.37)

# RÚIAN budovy
budovy = gpd.read_file(os.path.join(DATA_DIR, "ruian_budovy_fm.gpkg"))
total_budov    = len(budovy)
bytove_domy    = int((budovy["zpusobvyuzitikod"] == 6).sum())
rodinne_domy   = int((budovy["zpusobvyuzitikod"] == 7).sum())
bytu_bytove    = int(budovy[budovy["zpusobvyuzitikod"] == 6]["pocetbytu"].sum())
bytu_rodinne   = int(budovy[budovy["zpusobvyuzitikod"] == 7]["pocetbytu"].sum())
bytu_celkem    = int(budovy["pocetbytu"].sum())
panelaky       = int((budovy["pocetpodlazi"] >= 5).sum())
bytu_panelaky  = int(budovy[budovy["pocetpodlazi"] >= 5]["pocetbytu"].sum())

# Marketing spots
spots = gpd.read_file(os.path.join(DATA_DIR, "marketing-spots-fm.gpkg"))
spots_m = spots.to_crs(CRS_METRIC)
in_zone_spots = spots_m[spots_m.geometry.within(zone_m)]
def kat(r):
    a = r.get("amenity")
    if pd.notna(a) and a: return str(a)
    s = r.get("shop")
    if pd.notna(s) and s: return f"shop:{s}"
    return "other"
in_zone_spots = in_zone_spots.copy()
in_zone_spots["kat"] = in_zone_spots.apply(kat, axis=1)
spot_counts = in_zone_spots.groupby("kat").size().to_dict()

# Palivové parametry (nastavitelné)
SPOTREBA_L_100KM = 7.0    # průměrná spotřeba l/100 km
CENA_PHM_KC_L    = 38.0   # cena pohonných hmot Kč/l
DOPRAVNE_ZDARMA_KC = 1000  # práh pro bezplatné dopravné

cost_per_km = (SPOTREBA_L_100KM / 100) * CENA_PHM_KC_L  # Kč/km

# Zákazníci
df_zak = pd.read_csv(os.path.join(DATA_DIR, "zakaznici.csv"))
n_objednavek   = len(df_zak)
trzba_avg      = round(df_zak["trzba_kc"].mean(), 0)
trzba_total    = int(df_zak["trzba_kc"].sum())
naklady_total  = round(df_zak["naklady_rozvoz_kc"].sum(), 1)
vzdalenost_avg = round(df_zak["vzdalenost_km"].mean(), 1)
vzdalenost_max = df_zak["vzdalenost_km"].max()
free_delivery  = int((df_zak["dopravne_zakaznik_kc"] == 0).sum())

# Prodejní kategorie
kat_counts = df_zak["produkt_kategorie"].value_counts().to_dict()

# Scénáře vzdáleností
scenare = pd.read_csv(os.path.join(OUT_DIR, "scenare_vzdalenosti.csv"))

# Produkty a položky objednávek
polozky = pd.read_csv(os.path.join(DATA_DIR, "polozky.csv"))
katalog = pd.read_csv(os.path.join(DATA_DIR, "products_rows.csv"))

pol_sys = polozky[polozky["v_systemu"] == True].copy()
pol_sys["rozdil_cena"] = pol_sys["cena_katalog_kc"] - pol_sys["cena_kc"]
trzba_zbozi_celkem = int(pol_sys["cena_kc"].sum())
kat_rev = pol_sys.groupby("kategorie")["cena_kc"].sum().sort_values(ascending=False)
sold_skus = pol_sys["produkt"].nunique()
total_skus = len(katalog)
kat_skus = katalog.groupby("category").size().to_dict()
out_of_stock = int((katalog["stock"] == 0).sum())
price_changed = pol_sys[pol_sys["rozdil_cena"] > 0][["produkt","kategorie","cena_kc","cena_katalog_kc","rozdil_cena"]].drop_duplicates("produkt")
price_same = pol_sys[pol_sys["rozdil_cena"] <= 0][["produkt","kategorie","cena_kc","cena_katalog_kc","rozdil_cena"]].drop_duplicates("produkt")

# Cenová historie
cena_hist = pd.read_csv(os.path.join(DATA_DIR, "cena_historie.csv"))
changed_hist = cena_hist[cena_hist["zmena_kc"] > 0].copy()
unchanged_hist = cena_hist[cena_hist["zmena_kc"] == 0].copy()
avg_price_change_pct = round(cena_hist[cena_hist["zmena_kc"] > 0]["zmena_pct"].mean(), 1)

# Predikce objednávek
import numpy as np
# Týdenní data: týden od spuštění (14.3.2026), počet objednávek
weeks_data = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 2),   # první objednávky v týdnu 5
    (6, 0), (7, 1), (8, 1), (9, 1),             # stabilní 1/týden posledních 3 týdny
]
# Aktuální trend: průměr posledních 3 týdnů = 1 obj/týden
trend_weekly = 1.0
avg_trzba_obj = float(trzba_avg)
avg_dopravne_zakaznik = round(df_zak[df_zak["dopravne_zakaznik_kc"] > 0]["dopravne_zakaznik_kc"].mean(), 0)
# Průměrný příjem na objednávku (tržba + dopravné od zákazníka)
avg_revenue_per_order = avg_trzba_obj + avg_dopravne_zakaznik * (1 - free_delivery/n_objednavek)
avg_fuel_per_order = cost_per_km * vzdalenost_avg * 2  # round trip

# Tři predikční scénáře (obj/týden v budoucích měsících)
scenarios_pred = {
    "Konzervativní (1/týden)":  {"weekly": 1.0,  "color": "#888"},
    "Cílový (3/víkend)":        {"weekly": 3.0,  "color": "#29B6F6"},
    "Optimistický (7/víkend)":  {"weekly": 7.0,  "color": "#00e676"},
}
pred_months = list(range(1, 13))

# Scénáře s palivovými náklady
scenare["avg_delivery_km"] = scenare["limit_km"] * 0.35
scenare["fuel_avg_kc"] = (scenare["avg_delivery_km"] * 2 * cost_per_km).round(1)
scenare["fuel_max_kc"] = (scenare["limit_km"] * 2 * cost_per_km).round(1)

print("Data načtena, generuji report...")

# ── HTML report ────────────────────────────────────────────────────────────
def fmt_n(n): return f"{n:,}".replace(",", " ")

def _hl(km): return ' style="background:var(--bg3);border:1px solid var(--cyan);"' if km == 20 else ""
HTML = f"""<!DOCTYPE html>
<html lang="cs">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VečerkaPlus — Prostorová analýza dosahu</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #080808;
    --bg2: #111118;
    --bg3: #1a1a28;
    --cyan: #29B6F6;
    --pink: #FF3D9A;
    --green: #00e676;
    --yellow: #ffd740;
    --muted: #666;
    --text: #e0e0e0;
    --border: #222;
    --radius: 2px;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: 'Segoe UI', system-ui, sans-serif; font-size: 15px; line-height: 1.6; }}
  a {{ color: var(--cyan); }}

  /* Layout */
  .container {{ max-width: 1100px; margin: 0 auto; padding: 0 24px 80px; }}
  .section {{ margin: 48px 0; }}
  h1 {{ font-size: 2rem; color: var(--cyan); letter-spacing: -.5px; margin-bottom: 4px; }}
  h2 {{ font-size: 1.3rem; color: var(--cyan); border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 20px; margin-top: 8px; }}
  h3 {{ font-size: 1rem; color: var(--yellow); margin-bottom: 10px; }}
  p {{ margin-bottom: 12px; color: #bbb; }}
  .lead {{ font-size: 1.05rem; color: var(--text); }}
  strong {{ color: var(--text); }}

  /* Header */
  .header {{ background: var(--bg2); border-bottom: 2px solid var(--cyan); padding: 28px 0; margin-bottom: 8px; }}
  .header .container {{ display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px; }}
  .header-meta {{ color: var(--muted); font-size: 0.85rem; text-align: right; }}
  .badge {{ display: inline-block; background: var(--bg3); border: 1px solid var(--cyan); color: var(--cyan); border-radius: var(--radius); padding: 2px 10px; font-size: 0.78rem; margin-right: 6px; }}

  /* KPI grid */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
  .kpi {{ background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }}
  .kpi .val {{ font-size: 1.9rem; font-weight: 700; color: var(--cyan); line-height: 1.1; }}
  .kpi .val.pink {{ color: var(--pink); }}
  .kpi .val.green {{ color: var(--green); }}
  .kpi .val.yellow {{ color: var(--yellow); }}
  .kpi .lbl {{ font-size: 0.78rem; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: .4px; }}

  /* Tables */
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th {{ background: var(--bg3); color: var(--cyan); padding: 8px 12px; text-align: left; font-weight: 600; border-bottom: 1px solid var(--border); }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); color: #ccc; }}
  tr:hover td {{ background: var(--bg3); }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .tag {{ display: inline-block; padding: 1px 7px; border-radius: 2px; font-size: 0.75rem; font-weight: 600; }}
  .tag-lihoviny {{ background: #1a0a0f; color: var(--pink); border: 1px solid var(--pink); }}
  .tag-vino {{ background: #1a0d15; color: #e879a0; border: 1px solid #e879a0; }}
  .tag-tabak {{ background: #0d1017; color: #90a4ae; border: 1px solid #90a4ae; }}
  .tag-snack {{ background: #0f1208; color: var(--yellow); border: 1px solid var(--yellow); }}

  /* Charts */
  .chart-wrap {{ background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }}
  .charts-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 640px) {{ .charts-2col {{ grid-template-columns: 1fr; }} }}

  /* Highlight box */
  .highlight {{ background: var(--bg3); border-left: 3px solid var(--cyan); padding: 14px 18px; border-radius: var(--radius); margin: 16px 0; }}
  .highlight.warn {{ border-color: var(--yellow); }}
  .highlight.positive {{ border-color: var(--green); }}

  /* Order cards */
  .orders-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }}
  .order-card {{ background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; }}
  .order-card .order-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }}
  .order-card .order-id {{ color: var(--cyan); font-weight: 700; font-size: 0.85rem; }}
  .order-card .order-val {{ color: var(--green); font-weight: 700; font-size: 1.1rem; }}
  .order-card .order-meta {{ font-size: 0.82rem; color: var(--muted); margin-bottom: 6px; }}
  .order-card .order-items {{ font-size: 0.88rem; color: #bbb; }}

  /* Two-col text + data */
  .two-col {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 24px; align-items: start; }}
  @media (max-width: 700px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  /* Progress bars */
  .bar-row {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 0.88rem; }}
  .bar-label {{ width: 120px; color: #aaa; flex-shrink: 0; }}
  .bar-track {{ flex: 1; background: var(--bg3); height: 8px; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 4px; background: var(--cyan); }}
  .bar-fill.pink {{ background: var(--pink); }}
  .bar-fill.green {{ background: var(--green); }}
  .bar-val {{ width: 60px; text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }}

  /* Map iframe */
  .map-container {{ border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }}
  .map-container iframe {{ width: 100%; height: 520px; border: none; display: block; }}

  /* Footer */
  .footer {{ margin-top: 60px; padding-top: 24px; border-top: 1px solid var(--border); color: var(--muted); font-size: 0.8rem; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }}

  /* TOC */
  .toc {{ background: var(--bg2); border: 1px solid var(--border); padding: 16px 20px; border-radius: var(--radius); margin-bottom: 40px; }}
  .toc h3 {{ margin-bottom: 10px; color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: .6px; }}
  .toc ol {{ padding-left: 20px; }}
  .toc li {{ margin: 4px 0; }}
  .toc a {{ color: #888; text-decoration: none; font-size: 0.9rem; }}
  .toc a:hover {{ color: var(--cyan); }}
</style>
</head>
<body>

<div class="header">
  <div class="container">
    <div>
      <div style="color:var(--muted);font-size:.8rem;margin-bottom:4px;">PROSTOROVÁ ANALÝZA</div>
      <h1>VečerkaPlus</h1>
      <div style="color:#888;margin-top:4px;">Noční rozvoz alkoholu &amp; doplňkového zboží · Frýdek-Místek</div>
      <div style="margin-top:10px;">
        <span class="badge">Pá–Ne 22:00–6:00</span>
        <span class="badge">≤ 20 km jízdy</span>
        <span class="badge">spuštění 14. 3. 2026</span>
      </div>
    </div>
    <div class="header-meta">
      Zpracováno: 19. 5. 2026<br>
      Datové zdroje: Google Maps · ČSÚ SLDB 2021<br>
      RÚIAN · OSM · ArcČR 4.3
    </div>
  </div>
</div>

<div class="container">

<div class="toc">
  <h3>Obsah</h3>
  <ol>
    <li><a href="#summary">Executive summary</a></li>
    <li><a href="#zona">Rozvozová zóna</a></li>
    <li><a href="#demografie">Demografický profil</a></li>
    <li><a href="#zastavba">Bytová zástavba (RÚIAN)</a></li>
    <li><a href="#zakaznici">Zákazníci a objednávky</a></li>
    <li><a href="#finance">Finanční přehled</a></li>
    <li><a href="#sortiment">Sortiment a produkty</a></li>
    <li><a href="#cena-historie">Cenová historie</a></li>
    <li><a href="#predikce">Predikce a scénáře růstu</a></li>
    <li><a href="#marketing">Marketingové příležitosti</a></li>
    <li><a href="#scenare">Scénáře vzdálenosti + palivo</a></li>
    <li><a href="#mapa">Interaktivní mapa</a></li>
    <li><a href="#zaver">Závěry a doporučení</a></li>
  </ol>
</div>

<!-- ── 1. EXECUTIVE SUMMARY ──────────────────────────────────────────────── -->
<div class="section" id="summary">
<h2>1. Executive summary</h2>
<p class="lead">VečerkaPlus je první noční rozvozová služba ve Frýdku-Místku specializovaná na alkohol a doplňkové zboží. Provoz byl zahájen 14. března 2026; první objednávka přišla 18. dubna 2026 po&nbsp;pěti týdnech od spuštění. Do 15. května 2026 bylo doručeno <strong>5 objednávek</strong> celkové tržby <strong>{fmt_n(trzba_total)} Kč</strong>.</p>

<div class="kpi-grid" style="margin:24px 0;">
  <div class="kpi"><div class="val">{fmt_n(pop_grid_iso)}</div><div class="lbl">Odh. obyvatel v dosahu</div></div>
  <div class="kpi"><div class="val">{fmt_n(hh_iso)}</div><div class="lbl">Domácností v dosahu</div></div>
  <div class="kpi"><div class="val">{fmt_n(bytu_celkem)}</div><div class="lbl">Bytů (RÚIAN)</div></div>
  <div class="kpi"><div class="val pink">{fmt_n(n_objednavek)}</div><div class="lbl">Objednávek (celkem)</div></div>
  <div class="kpi"><div class="val green">{int(trzba_avg)} Kč</div><div class="lbl">Průměrná tržba</div></div>
  <div class="kpi"><div class="val yellow">{round(zone_area_km2)} km²</div><div class="lbl">Plocha rozvozové zóny</div></div>
</div>

<div class="highlight positive">
  <strong>Potenciál:</strong> V reálné rozvozové zóně žije odhadem <strong>{fmt_n(pop_grid_iso)} obyvatel</strong> v <strong>{fmt_n(hh_iso)} domácnostech</strong>. Bytové domy (panelová zástavba ≥5 podlaží) koncentrují <strong>{fmt_n(bytu_panelaky)} bytů</strong> — to je hlavní cílový segment pro noční rozvoz. Všechny dosavadní objednávky pocházejí z centra FM, do vzdálenosti max. 3,3 km od výchozího bodu.
</div>
<div class="highlight warn">
  <strong>Limitace dat:</strong> Analýza vychází z 5 objednávek za první 4 týdny provozu. Statistické závěry o zákaznickém chování jsou orientační — data jsou prezentována jako raná fáze provozu, nikoli reprezentativní vzorek.
</div>
</div>

<!-- ── 2. ROZVOZOVÁ ZÓNA ──────────────────────────────────────────────── -->
<div class="section" id="zona">
<h2>2. Rozvozová zóna</h2>
<div class="two-col">
<div>
<p>Rozvozová zóna VečerkaPlus je definována jako <strong>jízdní vzdálenost ≤ 20 km</strong> z Frýdku-Místku — shodně s logikou na webu vecerkaplus.cz (Google Distance Matrix API, mód <em>driving</em>). Tato definice se zásadně liší od prosté vzdušné vzdálenosti: hornatý terén Beskyd na jihu a jihovýchodě výrazně omezuje reálný dosah.</p>
<p>Porovnání zón ukazuje, že <strong>kruhový buffer 20 km nadhodnocuje reálný dosah o 49 %</strong>. Skutečná rozvozová zóna pokrývá zejména urbanizované území Frýdku-Místku, Havířova, Třince a přilehlých obcí v rovinnější části okresu.</p>
</div>
<div>
<table>
  <tr><th>Zóna</th><th class="num">Plocha</th><th class="num">Odh. obyvatel</th></tr>
  <tr><td>Buffer 20 km (vzdušná)</td><td class="num">{fmt_n(int(buf_m.area/1e6))} km²</td><td class="num">{fmt_n(pop_buf)}</td></tr>
  <tr><td>ORS izochróna 20 min</td><td class="num">803 km²</td><td class="num">386&nbsp;042</td></tr>
  <tr><td><strong>Google zóna ≤ 20 km</strong></td><td class="num"><strong>{round(zone_area_km2)} km²</strong></td><td class="num"><strong>{fmt_n(pop_grid_iso)}</strong></td></tr>
</table>
<p style="font-size:.8rem;color:var(--muted);margin-top:8px;">Google zóna = 1 093 bodů gridu dotázáno přes Google Distance Matrix API, stejný origin jako vecerkaplus.cz.</p>
</div>
</div>
</div>

<!-- ── 3. DEMOGRAFIE ──────────────────────────────────────────────────── -->
<div class="section" id="demografie">
<h2>3. Demografický profil zóny</h2>
<div class="two-col">
<div>
<p>Věková struktura obyvatel v Google rozvozové zóně vychází z dat ČSÚ SLDB 2021 agregovaných na úrovni obcí (centroid v zóně). Klíčová cílová skupina nočního rozvozu alkoholu — osoby ve věku <strong>15–64 let — tvoří 64 % populace</strong>, tj. odhadem <strong>{fmt_n(int(pop_grid_iso * 0.64))} osob</strong> v dosahu.</p>
<p>Průměrný věk obyvatel obcí v zóně je <strong>{avg_vek} let</strong>, což odpovídá průměru Moravskoslezského kraje. Frýdek-Místek jako centrum zóny má rozvinutou noční ekonomiku — {fmt_n(spot_counts.get("pub",0) + spot_counts.get("bar",0) + spot_counts.get("nightclub",0))} nočních podniků (puby, bary, kluby) v dosahu.</p>
</div>
<div class="chart-wrap">
  <canvas id="chartVek" height="180"></canvas>
</div>
</div>

<div style="margin-top:20px;">
<h3>Věková struktura populace v zóně</h3>
<div class="bar-row">
  <div class="bar-label">0–14 let</div>
  <div class="bar-track"><div class="bar-fill" style="width:{round(100*vek_0_14/(vek_0_14+vek_15_64+vek_65p))}%"></div></div>
  <div class="bar-val">{round(100*vek_0_14/(vek_0_14+vek_15_64+vek_65p),1)} %</div>
</div>
<div class="bar-row">
  <div class="bar-label">15–64 let</div>
  <div class="bar-track"><div class="bar-fill" style="width:{round(100*vek_15_64/(vek_0_14+vek_15_64+vek_65p))}%"></div></div>
  <div class="bar-val">{round(100*vek_15_64/(vek_0_14+vek_15_64+vek_65p),1)} %</div>
</div>
<div class="bar-row">
  <div class="bar-label">65+ let</div>
  <div class="bar-track"><div class="bar-fill pink" style="width:{round(100*vek_65p/(vek_0_14+vek_15_64+vek_65p))}%"></div></div>
  <div class="bar-val">{round(100*vek_65p/(vek_0_14+vek_15_64+vek_65p),1)} %</div>
</div>
</div>
</div>

<!-- ── 4. ZÁSTAVBA ────────────────────────────────────────────────────── -->
<div class="section" id="zastavba">
<h2>4. Bytová zástavba — RÚIAN</h2>
<p>Data Registru územní identifikace, adres a nemovitostí (RÚIAN, ČÚZK) umožňují přesné zmapování rezidenční zástavby v rozvozové zóně. Celkem bylo analyzováno <strong>{fmt_n(total_budov)} stavebních objektů</strong> s celkovým počtem <strong>{fmt_n(bytu_celkem)} bytů</strong>.</p>

<div class="kpi-grid" style="margin:20px 0;">
  <div class="kpi"><div class="val">{fmt_n(bytove_domy)}</div><div class="lbl">Bytových domů</div></div>
  <div class="kpi"><div class="val">{fmt_n(bytu_bytove)}</div><div class="lbl">Bytů v byt. domech</div></div>
  <div class="kpi"><div class="val">{fmt_n(rodinne_domy)}</div><div class="lbl">Rodinných domů</div></div>
  <div class="kpi"><div class="val">{fmt_n(bytu_rodinne)}</div><div class="lbl">Bytů v rod. domech</div></div>
  <div class="kpi"><div class="val yellow">{fmt_n(panelaky)}</div><div class="lbl">Budov ≥5 podlaží</div></div>
  <div class="kpi"><div class="val yellow">{fmt_n(bytu_panelaky)}</div><div class="lbl">Bytů v panelákovém fondu</div></div>
</div>

<div class="two-col">
<div>
<p><strong>Panelová zástavba</strong> (budovy s ≥5 nadzemními podlažími) tvoří pouze <strong>{round(100*panelaky/total_budov,1)} % počtu budov</strong>, ale koncentruje <strong>{round(100*bytu_panelaky/bytu_celkem,0):.0f} % všech bytů</strong> — tj. {fmt_n(bytu_panelaky)} bytových jednotek. Tato hustě osídlená zástavba ve Frýdku-Místku, Havířově a Třinci představuje primární geografický cíl pro akvizici zákazníků nočního rozvozu.</p>
<p>Průměrný bytový dům v zóně má <strong>16,7 bytů</strong> a <strong>4,6 nadzemního podlaží</strong>. Rodinné domy mají průměrně 1,3 bytu na objekt — jejich obsluha je sice možná, ale ekonomicky méně efektivní vzhledem k rozptylu adres.</p>
</div>
<div class="chart-wrap">
  <canvas id="chartBudovy" height="220"></canvas>
</div>
</div>
</div>

<!-- ── 5. ZÁKAZNÍCI ───────────────────────────────────────────────────── -->
<div class="section" id="zakaznici">
<h2>5. Zákazníci a objednávky</h2>
<p>V období od 18. dubna do 15. května 2026 bylo přijato a doručeno <strong>5 objednávek</strong>. Všechny objednávky pocházejí z centra Frýdku-Místku, v jízdní vzdálenosti <strong>1,8–3,3 km</strong> od výchozího bodu. Žádná objednávka zatím nepřišla z větší vzdálenosti než 3,3 km, přestože zóna umožňuje rozvoz až na 20 km.</p>

<div class="orders-grid" style="margin:20px 0;">

  <div class="order-card">
    <div class="order-header"><span class="order-id">#1 · 18. 4. 2026 · pátek 20:13</span><span class="order-val">547 Kč</span></div>
    <div class="order-meta">📍 K Hájku 29, FM · 2,8 km · hotově · dopravné zdarma</div>
    <div class="order-items"><span class="tag tag-lihoviny">lihoviny</span> Beefeater Pink Gin 0,7l + Schweppes 1,5l</div>
  </div>

  <div class="order-card">
    <div class="order-header"><span class="order-id">#2 · 19. 4. 2026 · sobota 00:04</span><span class="order-val">325 Kč</span></div>
    <div class="order-meta">📍 Heydukova, FM · 3,2 km · kartou · dopravné 39 Kč</div>
    <div class="order-items"><span class="tag tag-vino">víno</span> Znovín Tramín + Sauvignon 2× 0,75l</div>
  </div>

  <div class="order-card">
    <div class="order-header"><span class="order-id">#3 · 1. 5. 2026 · pátek 21:20</span><span class="order-val">262 Kč</span></div>
    <div class="order-meta">📍 Dr. Vančury 1924, FM · 1,8 km · kartou · dopravné 39 Kč</div>
    <div class="order-items"><span class="tag tag-tabak">tabák</span><span class="tag tag-snack" style="margin-left:4px">sladkosti</span> LM Blue karton + Kinder Bueno White</div>
  </div>

  <div class="order-card">
    <div class="order-header"><span class="order-id">#4 · 8. 5. 2026 · sobota 22:56</span><span class="order-val">547 Kč</span></div>
    <div class="order-meta">📍 Boženy Němcové 568, FM · 3,3 km · kartou · dopravné 39 Kč</div>
    <div class="order-items"><span class="tag tag-lihoviny">lihoviny</span> Captain Morgan Spiced 0,7l + Lay's 60g</div>
  </div>

  <div class="order-card">
    <div class="order-header"><span class="order-id">#5 · 15. 5. 2026 · pátek 21:30</span><span class="order-val">577 Kč</span></div>
    <div class="order-meta">📍 Malý Koloredov 565, FM · 2,5 km · hotově · dopravné 39 Kč</div>
    <div class="order-items"><span class="tag tag-lihoviny">lihoviny</span> 2× Božkov Originál 0,5l</div>
  </div>

</div>

<div class="highlight">
  <strong>Vzorec objednávek:</strong> 3 objednávky přišly v pátek (20:13, 21:20, 21:30), 2 v sobotu (00:04 — tedy v noci z pátku, 22:56). Všechny objednávky jsou v úzkém časovém okně 20–01 hodin — žádná ve druhé polovině noční směny (01–06). Produktový mix dominují lihoviny (3/5 objednávek), jednou víno a jednou tabák se sladkostmi.
</div>
</div>

<!-- ── 6. FINANCE ─────────────────────────────────────────────────────── -->
<div class="section" id="finance">
<h2>6. Finanční přehled</h2>
<div class="two-col">
<div>
<table>
  <tr><th>Metrika</th><th class="num">Hodnota</th></tr>
  <tr><td>Celková tržba (5 obj.)</td><td class="num"><strong style="color:var(--green)">{fmt_n(trzba_total)} Kč</strong></td></tr>
  <tr><td>Průměrná tržba / objednávka</td><td class="num">{int(trzba_avg)} Kč</td></tr>
  <tr><td>Min / Max tržba</td><td class="num">262 / 577 Kč</td></tr>
  <tr><td>Celkové přímé náklady na rozvoz</td><td class="num">{round(naklady_total, 0):.0f} Kč</td></tr>
  <tr><td>Průměrné náklady rozvoz / obj.</td><td class="num">{round(naklady_total/n_objednavek, 1)} Kč</td></tr>
  <tr><td>Průměrná vzdálenost doručení</td><td class="num">{vzdalenost_avg} km</td></tr>
  <tr><td>Objednávky s dopravným zdarma (≥{DOPRAVNE_ZDARMA_KC} Kč)</td><td class="num">{free_delivery} / {n_objednavek} <span style="color:var(--muted);font-size:.8rem">(1× promo/spuštění)</span></td></tr>
  <tr><td>Platba kartou / hotově</td><td class="num">3 / 2</td></tr>
</table>
</div>
<div class="chart-wrap">
  <canvas id="chartTrzby" height="220"></canvas>
</div>
</div>

<div class="highlight positive" style="margin-top:20px;">
  <strong>Nákladová efektivita rozvozu:</strong> Průměrné přímé náklady na jedno doručení jsou <strong>{round(naklady_total/n_objednavek, 1)} Kč</strong> (pohonné hmoty, opotřebení vozidla). Při průměrné tržbě {int(trzba_avg)} Kč a průměrné hrubé marži na zboží ~37 % jde o ekonomicky životaschopný model — klíčem ke škálování je zvýšení četnosti objednávek, nikoli rozšiřování zóny.
</div>
</div>

<!-- ── 7. SORTIMENT ──────────────────────────────────────────────────── -->
<div class="section" id="sortiment">
<h2>7. Sortiment a produktová analýza</h2>
<p>Katalog VečerkaPlus obsahuje celkem <strong>{total_skus} SKU</strong> ve <strong>{len(kat_skus)} kategoriích</strong>. Z toho bylo dosud prodáno <strong>{sold_skus} různých produktů</strong>. Analýza vychází z dat Supabase (products_rows.csv) a přesných emailových notifikací objednávek.</p>

<div class="kpi-grid" style="margin:20px 0;">
  <div class="kpi"><div class="val">{total_skus}</div><div class="lbl">Celkem SKU v katalogu</div></div>
  <div class="kpi"><div class="val pink">{sold_skus}</div><div class="lbl">Prodaných SKU</div></div>
  <div class="kpi"><div class="val yellow">{total_skus - sold_skus}</div><div class="lbl">Neprodaných SKU</div></div>
  <div class="kpi"><div class="val">{fmt_n(trzba_zbozi_celkem)} Kč</div><div class="lbl">Tržba za zboží (bez dopravného)</div></div>
  <div class="kpi"><div class="val pink">{out_of_stock}</div><div class="lbl">SKU skladem 0</div></div>
</div>

<div class="two-col">
<div>
<h3>Prodané produkty a cenové změny</h3>
<table>
  <tr><th>Produkt</th><th>Kategorie</th><th class="num">Cena v obj.</th><th class="num">Cena nyní</th><th class="num">Δ</th></tr>
{"".join(
    f'<tr><td>{r.produkt}</td><td>{r.kategorie}</td>'
    f'<td class="num">{int(r.cena_kc)} Kč</td>'
    f'<td class="num">{int(r.cena_katalog_kc)} Kč</td>'
    f'<td class="num" style="color:var(--green)">+{int(r.rozdil_cena)} Kč</td></tr>'
    for r in price_changed.itertuples()
)}
{"".join(
    f'<tr><td>{r.produkt}</td><td>{r.kategorie}</td>'
    f'<td class="num">{int(r.cena_kc)} Kč</td>'
    f'<td class="num">{int(r.cena_katalog_kc)} Kč</td>'
    f'<td class="num" style="color:var(--muted)">—</td></tr>'
    for r in price_same.itertuples()
)}
  <tr style="background:var(--bg3)"><td><em>Marlboro Red (mimo systém)</em></td><td>Tabák</td>
    <td class="num" style="color:var(--muted)">—</td><td class="num">179 Kč</td><td class="num">—</td></tr>
</table>
</div>
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Tržba za zboží dle kategorie</h3>
  <canvas id="chartKategorie" height="220"></canvas>
</div>
</div>

<div style="margin-top:20px;">
<h3>Neprodané kategorie (nulová tržba)</h3>
<p>Tyto kategorie v katalogu existují, ale zatím nikdo neobjednal: <strong>Pivo</strong>, <strong>Energy drinky</strong>, <strong>Party Mix</strong>, <strong>Doplňky</strong>, <strong>Soft drinky</strong> (jen Schweppes jako mixer). Nejsilnější příležitost je pivo — 5 SKU v katalogu, 0 prodejů, přitom v noční ekonomice standardní produkt.</p>
</div>

<div class="highlight warn">
  <strong>Off-system prodej — Marlboro:</strong> U objednávky #2 (Ladislav Wojnar, 19. 4.) zákazník požadoval i Marlboro, které nebylo přidáno do systémové objednávky. Emailová notifikace zachytila tržbu 286 Kč za víno + 39 Kč dopravné = 325 Kč, reálná hodnota transakce byla ~504 Kč. Tato slepá skvrna v datech bude přetrvávat, dokud nebude sortiment úplný a objednávky budou doplňovány manuálně.
</div>
</div>


<!-- ── 8. CENOVÁ HISTORIE ────────────────────────────────────────────── -->
<div class="section" id="cena-historie">
<h2>8. Cenová historie produktů</h2>
<p>Ceny jsou odvozeny porovnáním <strong>cen z emailových notifikací objednávek</strong> (dubna–května 2026) s aktuálním produktovým katalogem (Supabase, stav {today}). Pro produkty dosud neobjednané nelze historii odvodit.</p>

<div class="two-col">
<div>
<h3>Produkty se zdraženým ceníkem od spuštění</h3>
<table>
  <tr><th>Produkt</th><th class="num">Cena při 1. prodeji</th><th class="num">Cena nyní</th><th class="num">Nárůst</th></tr>
{"".join(
    f'<tr><td>{r.produkt}</td>'
    f'<td class="num">{int(r.cena_launch_kc)} Kč</td>'
    f'<td class="num">{int(r.cena_aktualni_kc)} Kč</td>'
    f'<td class="num" style="color:var(--green)">+{int(r.zmena_kc)} Kč ({r.zmena_pct:.1f} %)</td></tr>'
    for r in changed_hist.itertuples()
)}
</table>

<div class="highlight positive" style="margin-top:16px;">
  <strong>Průměrné zdražení: +{avg_price_change_pct} %</strong> u produktů se změnou. Znovín vína zdražila nejvýrazněji (+25 %), Beefeater a Schweppes o +11 %. Zdražování může být důsledkem rostoucích nákupních cen nebo záměrné optimalizace marže.
</div>
</div>
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Cena při 1. prodeji vs. aktuální (Kč)</h3>
  <canvas id="chartCenaHist" height="280"></canvas>
</div>
</div>

<h3 style="margin-top:20px;">Produkty bez cenové změny (sledované od 1. objednávky)</h3>
<table>
  <tr><th>Produkt</th><th>Kategorie</th><th class="num">Stabilní cena</th><th>1. prodej</th></tr>
{"".join(
    f'<tr><td>{r.produkt}</td><td>{r.kategorie}</td>'
    f'<td class="num">{int(r.cena_aktualni_kc)} Kč</td>'
    f'<td style="color:var(--muted);font-size:.85rem">{r.prvni_objednavka_datum}</td></tr>'
    for r in unchanged_hist.itertuples()
)}
</table>

<div class="highlight warn" style="margin-top:16px;">
  <strong>Slepá skvrna:</strong> Pro 27 z 36 SKU v katalogu (neprodané) nemáme historii cen — nevíme, zda jejich ceny zůstaly stejné od spuštění. Doporučujeme zavést verzování cen v Supabase (přidat sloupec <code>price_updated_at</code>).
</div>
</div>


<!-- ── 9. PREDIKCE ────────────────────────────────────────────────────── -->
<div class="section" id="predikce">
<h2>9. Predikce objednávek a scénáře růstu</h2>
<p>Model vychází z aktuálního trendu: <strong>poslední 3 víkendy vždy 1 objednávka/týden</strong>. Průměrná tržba na objednávku je <strong>{int(trzba_avg)} Kč</strong>, průměrné přímé palivové náklady na doručení <strong>{avg_fuel_per_order:.1f} Kč</strong> (při {SPOTREBA_L_100KM} l/100 km a {CENA_PHM_KC_L} Kč/l, průměrná vzdálenost {vzdalenost_avg} km).</p>

<div class="kpi-grid" style="margin:20px 0;">
  <div class="kpi"><div class="val">{trend_weekly:.0f}</div><div class="lbl">Obj./týden (aktuální trend)</div></div>
  <div class="kpi"><div class="val">{int(trend_weekly * 4)}</div><div class="lbl">Odh. obj./měsíc</div></div>
  <div class="kpi"><div class="val green">{int(trend_weekly * 4 * trzba_avg):,} Kč</div><div class="lbl">Odh. tržba/měsíc</div></div>
  <div class="kpi"><div class="val yellow">{int(trend_weekly * 52 * trzba_avg):,} Kč</div><div class="lbl">Odh. tržba/rok (aktuální)</div></div>
</div>

<div class="charts-2col">
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Projekce tržby — 3 scénáře (12 měsíců)</h3>
  <canvas id="chartPredikce" height="260"></canvas>
</div>
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Počet objednávek od spuštění (týdně)</h3>
  <canvas id="chartTrend" height="260"></canvas>
</div>
</div>

<div style="margin-top:20px;overflow-x:auto;">
<h3>Scénáře výnosů a nákladů (měsíčně, po ustálení)</h3>
<table>
  <tr>
    <th>Scénář</th>
    <th class="num">Obj./týden</th>
    <th class="num">Obj./měsíc</th>
    <th class="num">Tržba/měsíc</th>
    <th class="num">Palivo/měsíc</th>
    <th class="num">Přísp. marže/měsíc</th>
    <th class="num">Tržba/rok</th>
  </tr>
{"".join(
    f'<tr{"style=\"background:var(--bg3);\"" if name == list(scenarios_pred.keys())[0] else ""}>'
    f'<td><strong>{name}</strong></td>'
    f'<td class="num">{sc["weekly"]:.0f}</td>'
    f'<td class="num">{int(sc["weekly"] * 4.3)}</td>'
    f'<td class="num" style="color:var(--green)">{fmt_n(int(sc["weekly"] * 4.3 * trzba_avg))} Kč</td>'
    f'<td class="num" style="color:var(--pink)">{fmt_n(int(sc["weekly"] * 4.3 * avg_fuel_per_order))} Kč</td>'
    f'<td class="num">{fmt_n(int(sc["weekly"] * 4.3 * (trzba_avg - avg_fuel_per_order)))} Kč</td>'
    f'<td class="num">{fmt_n(int(sc["weekly"] * 52 * trzba_avg))} Kč</td>'
    f'</tr>'
    for name, sc in scenarios_pred.items()
)}
</table>
</div>

<div class="highlight" style="margin-top:16px;">
  <strong>Poznámka k modelu:</strong> Příspěvková marže zahrnuje pouze přímé palivové náklady ({SPOTREBA_L_100KM} l/100 km × {CENA_PHM_KC_L} Kč/l). Nezahrnuje odpisy vozidla, čas řidiče, marketing ani provoz Supabase/webu. Při 3 obj./víkend (cílový scénář) jsou roční tržby ~{fmt_n(int(3 * 52 * trzba_avg))} Kč — ekonomicky životaschopná aktivita při stávající nízké režii.
</div>
</div>


<!-- ── 10. MARKETING ───────────────────────────────────────────────────── -->
<div class="section" id="marketing">
<h2>10. Marketingové příležitosti</h2>
<p>Na základě OSM dat bylo v Google rozvozové zóně identifikováno celkem <strong>{fmt_n(sum(spot_counts.get(k,0) for k in ["restaurant","pub","fast_food","cafe","bar","nightclub"]))} podniků</strong> relevantních pro noční rozvoz (restaurace, puby, bary, fast foody, kavárny, noční kluby).</p>

<div class="charts-2col" style="margin:20px 0;">
<div class="chart-wrap">
  <canvas id="chartSpoty" height="260"></canvas>
</div>
<div>
  <h3>Potenciál partnerské spolupráce</h3>
  <p>Restaurace a puby v blízkosti centra FM jsou přirozenými distribučními body — zákazníci odcházející z podniku večer mohou objednat dovoz na cestu. Kavárny a bary s pozdní otevírací dobou představují příležitost pro <strong>spolupráci na cross-promotion</strong>.</p>
  <table style="margin-top:12px;">
    <tr><th>Kategorie</th><th class="num">V zóně</th></tr>
    <tr><td>🍽 Restaurace</td><td class="num">{spot_counts.get("restaurant",0)}</td></tr>
    <tr><td>🍺 Puby</td><td class="num">{spot_counts.get("pub",0)}</td></tr>
    <tr><td>🍔 Fast food</td><td class="num">{spot_counts.get("fast_food",0)}</td></tr>
    <tr><td>☕ Kavárny</td><td class="num">{spot_counts.get("cafe",0)}</td></tr>
    <tr><td>🍸 Bary</td><td class="num">{spot_counts.get("bar",0)}</td></tr>
    <tr><td>🎵 Noční kluby</td><td class="num">{spot_counts.get("nightclub",0)}</td></tr>
  </table>
</div>
</div>

<div class="highlight">
  <strong>Prioritní akvizice:</strong> {fmt_n(bytu_panelaky)} bytů v panelovém fondu (≥5 podlaží) tvoří nejhustší rezidenční zástavbu v zóně. Cílená distribuce letáků nebo QR kódů ve vchodech bytových domů v okruhu 5 km od FM centra má výrazně vyšší návratnost než pokrytí celé 20km zóny.
</div>
</div>

<!-- ── 11. SCÉNÁŘE ─────────────────────────────────────────────────────── -->
<div class="section" id="scenare">
<h2>11. Scénáře rozvozové vzdálenosti</h2>
<p>Analýza porovnává dopad různých limitů jízdní vzdálenosti na dosažitelný trh. Všechny scénáře vychází z reálných Google Distance Matrix dat (1 093 bodů gridu). Aktuální provozní limit VečerkaPlus je <strong>20 km</strong>.</p>

<div style="overflow-x:auto;margin:20px 0;">
<table>
  <tr>
    <th>Limit</th>
    <th class="num">Plocha</th>
    <th class="num">Odh. obyvatel</th>
    <th class="num">Domácností</th>
    <th class="num">Bytů v paneláku</th>
    <th class="num">Nightlife</th>
    <th class="num" title="Průměrná vzdálenost = limit × 35 %">Palivo/doj. (avg)</th>
    <th class="num" title="Doručení na kraj zóny">Palivo/doj. (max)</th>
  </tr>
{"".join(
    f'<tr{_hl(row.limit_km)}>' \
    f'<td><strong>{"▶ " if row.limit_km == 20 else ""}≤ {row.limit_km} km</strong></td>'
    f'<td class="num">{int(row.plocha_km2):,} km²</td>'
    f'<td class="num">{int(row.pop_grid):,}</td>'
    f'<td class="num">{int(row.hh):,}</td>'
    f'<td class="num">{int(row.byty_panel):,}</td>'
    f'<td class="num">{int(row.nightlife)}</td>'
    f'<td class="num" style="color:var(--yellow)">{row.fuel_avg_kc:.1f} Kč</td>'
    f'<td class="num" style="color:var(--pink)">{row.fuel_max_kc:.1f} Kč</td>'
    f'</tr>'
    for row in scenare.itertuples()
)}
</table>
</div>

<div class="charts-2col" style="margin:20px 0;">
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Obyvatelé a domácnosti podle limitu</h3>
  <canvas id="chartScenareOb" height="220"></canvas>
</div>
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Byty v panelovém fondu</h3>
  <canvas id="chartScenarePan" height="220"></canvas>
</div>
</div>

<div class="highlight">
  <strong>Klíčový poznatek:</strong> Přechod z 15 km na 20 km přidá <strong>{int(scenare[scenare.limit_km==20]["pop_grid"].values[0] - scenare[scenare.limit_km==15]["pop_grid"].values[0]):,} obyvatel</strong> a <strong>{int(scenare[scenare.limit_km==20]["byty_panel"].values[0] - scenare[scenare.limit_km==15]["byty_panel"].values[0]):,} bytů v paneláku</strong> — největší skok v celé škále. Přechod z 10 na 15 km pak přidá zejména <strong>{int(scenare[scenare.limit_km==15]["restaurace"].values[0] - scenare[scenare.limit_km==10]["restaurace"].values[0])} restaurací</strong> a podniků — dobré pro B2B partnerství. Zóna ≤ 5 km pokrývá již <strong>{int(scenare[scenare.limit_km==5]["byty_panel"].values[0]):,} bytů v paneláku</strong> — hustou zástavbu centra FM — při minimálních dopravních nákladech.
</div>

<h3 style="margin-top:20px;">Marginalní přínos každého km navíc</h3>
<div style="overflow-x:auto;">
<table>
  <tr><th>Přechod</th><th class="num">+Obyvatel</th><th class="num">+Domácností</th><th class="num">+Bytů panel.</th><th class="num">+Plocha km²</th></tr>
{"".join(
    f'<tr><td>{"▶ " if scenare.iloc[i]["limit_km"]==20 else ""}{int(scenare.iloc[i-1]["limit_km"])} → {int(scenare.iloc[i]["limit_km"])} km</td>'
    f'<td class="num">+{int(scenare.iloc[i]["pop_grid"]-scenare.iloc[i-1]["pop_grid"]):,}</td>'
    f'<td class="num">+{int(scenare.iloc[i]["hh"]-scenare.iloc[i-1]["hh"]):,}</td>'
    f'<td class="num">+{int(scenare.iloc[i]["byty_panel"]-scenare.iloc[i-1]["byty_panel"]):,}</td>'
    f'<td class="num">+{int(scenare.iloc[i]["plocha_km2"]-scenare.iloc[i-1]["plocha_km2"]):,}</td>'
    f'</tr>'
    for i in range(1, len(scenare))
)}
</table>
</div>
</div>

<!-- ── 12. MAPA ─────────────────────────────────────────────────────────── -->
<div class="section" id="mapa">
<h2>12. Interaktivní mapa</h2>
<p>Mapa zobrazuje Google rozvozovou zónu (oranžová), buffer 20 km (modrá přerušovaná), ZUJ hranice, 1km gridy domácností, OSM marketing spoty a geocodované zákazníky. Vrstvy lze přepínat v pravém horním rohu.</p>
<div class="map-container">
  <iframe src="vecerkaplus_mapa.html" loading="lazy"></iframe>
</div>
</div>

<!-- ── 13. ZÁVĚRY ──────────────────────────────────────────────────────── -->
<div class="section" id="zaver">
<h2>13. Závěry a doporučení</h2>

<h3>Silné stránky</h3>
<p>VečerkaPlus operuje v nezaplněné tržní mezeře — noční rozvoz alkoholu a doplňkového zboží v FM nemá přímého konkurenta. Rozvozová zóna pokrývá <strong>{fmt_n(pop_grid_iso)} obyvatel</strong> v <strong>{fmt_n(hh_iso)} domácnostech</strong>. Průměrná tržba {int(trzba_avg)} Kč na objednávku při přímých nákladech rozvozu ~{round(naklady_total/n_objednavek, 0):.0f} Kč zaručuje zdravou základní marži.</p>

<h3>Klíčové výzvy</h3>
<p>Nízká povědomost trhu — 5 objednávek za 4 týdny provozu naznačuje, že hlavní bariérou není logistika ani dosah, ale <strong>zákaznická akvizice</strong>. Žádná objednávka nepřišla po 01:00 ani ze vzdálenosti větší než 3,3 km — potenciál zóny je z 80 % nevyužitý. Druhý Pátku/So vzorec ukazuje velmi koncentrovanou poptávku — rozložení do více nocí bude vyžadovat aktivní marketing.</p>

<h3>Doporučení</h3>
<table>
  <tr><th>#</th><th>Akce</th><th>Dopad</th><th>Obtížnost</th></tr>
  <tr><td>1</td><td>Letákování bytových domů (≥5 podlaží) do 5 km od FM centra — <strong>{fmt_n(bytu_panelaky)} bytů</strong></td><td style="color:var(--green)">Vysoký</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>2</td><td>Partnerství s nočními podniky — QR kódy na stolech v <strong>{spot_counts.get("pub",0) + spot_counts.get("bar",0)}</strong> pubech a barech</td><td style="color:var(--green)">Vysoký</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>3</td><td>Instagram/TikTok cílení na věk 18–35, geolokace FM centrum, aktivní Pá–So 20–00</td><td style="color:var(--green)">Střední</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>4</td><td>Rozšíření sortimentu o energetické nápoje a snacks — 1 ze 5 objednávek cílila na tabák+sladkosti</td><td style="color:#ffd740)">Střední</td><td style="color:var(--green)">Nízká</td></tr>
  <tr><td>5</td><td>Práh dopravného zdarma ≥1 000 Kč motivuje zákazníky navyšovat hodnotu košíku — sledovat průměrnou tržbu, zda roste k tomuto prahu</td><td style="color:var(--yellow)">Střední</td><td style="color:var(--green)">Velmi nízká</td></tr>
</table>

<div class="highlight positive" style="margin-top:20px;">
  <strong>Výhled:</strong> Při úspěšné akvizici 1 % domácností z panelového fondu v 5km okruhu (~{fmt_n(int(bytu_panelaky * 0.01 * 0.3))} aktivních zákazníků, průměr 1 objednávka/měsíc) by tržba dosáhla řádu <strong>stovek tisíc Kč ročně</strong> — a to pouze z centra FM bez využití plného 20km dosahu.
</div>
</div>

</div><!-- /.container -->

<div class="container">
<div class="footer">
  <div>VečerkaPlus · Prostorová analýza dosahu · 19. 5. 2026</div>
  <div>Datové zdroje: Google Maps API · ČSÚ SLDB 2021 · RÚIAN (ČÚZK) · OpenStreetMap · ArcČR 4.3 · OpenRouteService</div>
</div>
</div>

<script>
// ── Věkový koláč ──
new Chart(document.getElementById('chartVek'), {{
  type: 'doughnut',
  data: {{
    labels: ['0–14 let', '15–64 let', '65+ let'],
    datasets: [{{ data: [{vek_0_14}, {vek_15_64}, {vek_65p}],
      backgroundColor: ['#37474f','#29B6F6','#FF3D9A'],
      borderColor: '#111118', borderWidth: 2 }}]
  }},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#bbb', font: {{ size: 12 }} }} }} }},
    cutout: '60%' }}
}});

// ── Budovy koláč ──
new Chart(document.getElementById('chartBudovy'), {{
  type: 'doughnut',
  data: {{
    labels: ['Byty v bytových domech', 'Byty v rodinných domech', 'Ostatní'],
    datasets: [{{ data: [{bytu_bytove}, {bytu_rodinne}, {bytu_celkem - bytu_bytove - bytu_rodinne}],
      backgroundColor: ['#29B6F6','#FF3D9A','#37474f'],
      borderColor: '#111118', borderWidth: 2 }}]
  }},
  options: {{ plugins: {{ legend: {{ labels: {{ color: '#bbb', font: {{ size: 11 }} }} }} }},
    cutout: '55%' }}
}});

// ── Tržby bar ──
new Chart(document.getElementById('chartTrzby'), {{
  type: 'bar',
  data: {{
    labels: ['#1 18.4', '#2 19.4', '#3 1.5', '#4 8.5', '#5 15.5'],
    datasets: [{{
      label: 'Tržba (Kč)',
      data: [547, 325, 262, 547, 577],
      backgroundColor: ['#29B6F6','#29B6F6','#FF3D9A','#29B6F6','#00e676'],
      borderRadius: 2,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }},
           suggestedMin: 0, suggestedMax: 700 }}
    }}
  }}
}});

// ── Spoty horizontální bar ──
new Chart(document.getElementById('chartSpoty'), {{
  type: 'bar',
  data: {{
    labels: ['Restaurace', 'Puby', 'Fast food', 'Kavárny', 'Bary', 'Noční kluby'],
    datasets: [{{
      label: 'Počet v zóně',
      data: [{spot_counts.get('restaurant',0)}, {spot_counts.get('pub',0)}, {spot_counts.get('fast_food',0)}, {spot_counts.get('cafe',0)}, {spot_counts.get('bar',0)}, {spot_counts.get('nightclub',0)}],
      backgroundColor: ['#FF3D9A','#ffd740','#ff6d00','#69f0ae','#e040fb','#f06292'],
      borderRadius: 2,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#bbb' }}, grid: {{ display: false }} }}
    }}
  }}
}});

// ── Scénáře: Obyvatelé a domácnosti ──
new Chart(document.getElementById('chartScenareOb'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f'≤ {int(r.limit_km)} km' for r in scenare.itertuples()])},
    datasets: [
      {{
        label: 'Obyvatelé (odh.)',
        data: {json.dumps(list(scenare['pop_grid'].astype(int)))},
        backgroundColor: '#29B6F6',
        borderRadius: 2,
      }},
      {{
        label: 'Domácnosti',
        data: {json.dumps(list(scenare['hh'].astype(int)))},
        backgroundColor: '#FF3D9A',
        borderRadius: 2,
      }}
    ]
  }},
  options: {{
    plugins: {{ legend: {{ labels: {{ color: '#bbb', font: {{ size: 11 }} }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }}
    }}
  }}
}});


// ── Sortiment: tržba dle kategorie ──
new Chart(document.getElementById('chartKategorie'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(kat_rev.index))},
    datasets: [{{
      label: 'Tržba za zboží (Kč)',
      data: {json.dumps([int(v) for v in kat_rev.values])},
      backgroundColor: ['#FF3D9A','#ffd740','#29B6F6','#00e676','#e040fb'],
      borderRadius: 2,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#bbb' }}, grid: {{ display: false }} }}
    }}
  }}
}});

// ── Scénáře: Byty v panelovém fondu ──
new Chart(document.getElementById('chartScenarePan'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f'≤ {int(r.limit_km)} km' for r in scenare.itertuples()])},
    datasets: [{{
      label: 'Byty v panelovém fondu',
      data: {json.dumps(list(scenare['byty_panel'].astype(int)))},
      backgroundColor: {json.dumps(['#ffd740' if int(r.limit_km) != 20 else '#00e676' for r in scenare.itertuples()])},
      borderRadius: 2,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }}
    }}
  }}
}});
</script>
</body>
</html>
"""

report_path = os.path.join(OUT_DIR, "report.html")
with open(report_path, "w", encoding="utf-8") as f:
    f.write(HTML)
print(f"Report uložen: output/report.html ({len(HTML)//1024} kB)")
