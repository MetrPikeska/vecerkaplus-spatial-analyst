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

# Demografie per rozvozová zóna (area-weighted SLDB + centroid HH grid)
_zone_km_list = [5, 10, 15, 20]
_zone_labels  = {5: "do 5 km", 10: "5–10 km", 15: "10–15 km", 20: "15–20 km"}
_zone_colors  = {5: "#00e676", 10: "#ffd740", 15: "#ff9800", 20: "#e74c3c"}
_demo_num_cols = ["obyvatelstvo_celkem", "muzi", "zeny", "vek_0_14", "vek_15_64", "vek_65plus"]

_obce_aw = obce.to_crs(CRS_METRIC).copy()
for _c in _demo_num_cols + ["prumerny_vek"]:
    if _c in _obce_aw.columns:
        _obce_aw[_c] = pd.to_numeric(_obce_aw[_c], errors="coerce").fillna(0)
    else:
        _obce_aw[_c] = 0
_obce_aw = _obce_aw[_obce_aw["obyvatelstvo_celkem"] > 0].copy()
_obce_aw["_obec_area"] = _obce_aw.geometry.area

def _demo_in_zone(zone_geom):
    cands = _obce_aw[_obce_aw.geometry.intersects(zone_geom)].copy()
    if cands.empty:
        return {c: 0 for c in _demo_num_cols + ["prumerny_vek"]}
    cands["_isect"] = cands.geometry.intersection(zone_geom).area
    cands["_w"] = (cands["_isect"] / cands["_obec_area"]).clip(0, 1)
    res = {c: int(round((cands[c] * cands["_w"]).sum())) for c in _demo_num_cols}
    denom = (cands["_w"] * cands["obyvatelstvo_celkem"]).sum()
    res["prumerny_vek"] = round(
        (cands["_w"] * cands["obyvatelstvo_celkem"] * cands["prumerny_vek"]).sum() / denom, 1
    ) if denom > 0 else 43.0
    return res

# Kumulativní hodnoty per zóna
_cum_demo = {}
_cum_hh   = {}
for _km in _zone_km_list:
    _zpath = os.path.join(DATA_DIR, f"google_zone_{_km}km.geojson")
    _zgeom = gpd.read_file(_zpath).to_crs(CRS_METRIC).geometry.iloc[0]
    _cum_demo[_km] = _demo_in_zone(_zgeom)
    _cum_hh[_km]   = int(gridy_m[gridy_m["c"].within(_zgeom)]["hh_celkem"].sum())

# Prstencové hodnoty (kumulativní - předchozí)
_ring_demo = {}
_ring_hh   = {}
_prev_demo = {c: 0 for c in _demo_num_cols + ["prumerny_vek"]}
_prev_hh   = 0
for _km in _zone_km_list:
    _ring_demo[_km] = {}
    for _c in _demo_num_cols:
        _ring_demo[_km][_c] = _cum_demo[_km][_c] - _prev_demo.get(_c, 0)
    _ring_demo[_km]["prumerny_vek"] = _cum_demo[_km]["prumerny_vek"]
    _ring_hh[_km] = _cum_hh[_km] - _prev_hh
    _prev_demo = {c: _cum_demo[_km][c] for c in _demo_num_cols}
    _prev_demo["prumerny_vek"] = _cum_demo[_km]["prumerny_vek"]
    _prev_hh = _cum_hh[_km]

# HTML tabulka
def _pct(a, b): return round(a / b * 100, 1) if b else 0
def fmt_n(n): return f"{n:,}".replace(",", " ")  # non-breaking space
_zone_demo_rows = ""
for _km in _zone_km_list:
    _r  = _ring_demo[_km]
    _hh = _ring_hh[_km]
    _pop = _r["obyvatelstvo_celkem"]
    _col = _zone_colors[_km]
    _zone_demo_rows += (
        f'<tr>'
        f'<td><span style="color:{_col};font-weight:700">{_zone_labels[_km]}</span></td>'
        f'<td class="num">{fmt_n(_pop)}</td>'
        f'<td class="num">{fmt_n(_hh)}</td>'
        f'<td class="num">{fmt_n(_r["vek_0_14"])}</td>'
        f'<td class="num">{_pct(_r["vek_0_14"], _pop)} %</td>'
        f'<td class="num">{fmt_n(_r["vek_15_64"])}</td>'
        f'<td class="num">{_pct(_r["vek_15_64"], _pop)} %</td>'
        f'<td class="num">{fmt_n(_r["vek_65plus"])}</td>'
        f'<td class="num">{_pct(_r["vek_65plus"], _pop)} %</td>'
        f'<td class="num">{_r["prumerny_vek"]}</td>'
        f'</tr>\n'
    )
_pop_total = sum(_ring_demo[k]["obyvatelstvo_celkem"] for k in _zone_km_list)
_hh_total  = sum(_ring_hh[k] for k in _zone_km_list)
_vek0_total = sum(_ring_demo[k]["vek_0_14"] for k in _zone_km_list)
_vek15_total = sum(_ring_demo[k]["vek_15_64"] for k in _zone_km_list)
_vek65_total = sum(_ring_demo[k]["vek_65plus"] for k in _zone_km_list)
_zone_demo_rows += (
    f'<tr style="border-top:2px solid var(--border);font-weight:600">'
    f'<td>CELKEM ≤ 20 km</td>'
    f'<td class="num">{fmt_n(_pop_total)}</td>'
    f'<td class="num">{fmt_n(_hh_total)}</td>'
    f'<td class="num">{fmt_n(_vek0_total)}</td>'
    f'<td class="num">{_pct(_vek0_total, _pop_total)} %</td>'
    f'<td class="num">{fmt_n(_vek15_total)}</td>'
    f'<td class="num">{_pct(_vek15_total, _pop_total)} %</td>'
    f'<td class="num">{fmt_n(_vek65_total)}</td>'
    f'<td class="num">{_pct(_vek65_total, _pop_total)} %</td>'
    f'<td class="num">{round(sum(_cum_demo[k]["prumerny_vek"] * _cum_demo[k]["obyvatelstvo_celkem"] for k in _zone_km_list) / sum(_cum_demo[k]["obyvatelstvo_celkem"] for k in _zone_km_list), 1)}</td>'
    f'</tr>\n'
)

# Chart.js data pro věkovou strukturu per zóna (stacked bar)
_chart_zone_labels = [_zone_labels[k] for k in _zone_km_list]
_chart_vek0  = [_ring_demo[k]["vek_0_14"] for k in _zone_km_list]
_chart_vek15 = [_ring_demo[k]["vek_15_64"] for k in _zone_km_list]
_chart_vek65 = [_ring_demo[k]["vek_65plus"] for k in _zone_km_list]

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
CENA_PHM_KC_L    = 42.0   # cena pohonných hmot Kč/l
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
min_trzba      = int(df_zak["trzba_kc"].min())
max_trzba      = int(df_zak["trzba_kc"].max())
free_delivery  = int((df_zak["dopravne_zakaznik_kc"] == 0).sum())
kartou_count   = int((df_zak["platba"] == "kartou").sum())
hotove_count   = int((df_zak["platba"] == "hotově").sum())
import datetime as _dt
date_last_order = pd.to_datetime(df_zak["datum"]).max()
n_weeks_since_launch = round((date_last_order.date() - _dt.date(2026, 3, 14)).days / 7)
date_last_str  = date_last_order.strftime("%-d. %-m. %Y")

# Prodejní kategorie
kat_counts = df_zak["produkt_kategorie"].value_counts().to_dict()

# Scénáře vzdáleností
scenare = pd.read_csv(os.path.join(OUT_DIR, "scenare_vzdalenosti.csv"))

# Scoring obcí
obce_scoring_csv = os.path.join(OUT_DIR, "obce_scoring.csv")
if os.path.exists(obce_scoring_csv):
    obce_sc = pd.read_csv(obce_scoring_csv)
    _tier_colors = {"A": "#00e676", "B": "#ffd740", "C": "#e74c3c"}
    _tier_bg     = {"A": "rgba(0,230,118,.08)", "B": "rgba(255,215,64,.06)", "C": "rgba(231,76,60,.06)"}
    _tier_label  = {"A": "Prioritní", "B": "Výhodné", "C": "Marginální"}
    _tier_a = obce_sc[obce_sc["tier"] == "A"].sort_values("monthly_contribution_kc", ascending=False)
    _tier_b = obce_sc[obce_sc["tier"] == "B"].sort_values("monthly_contribution_kc", ascending=False)
    _total_pl_a = int(_tier_a["monthly_contribution_kc"].sum())
    _total_pl_b = int(_tier_b["monthly_contribution_kc"].sum())

    def _obce_rows(df_t, tier):
        color = _tier_colors[tier]
        rows = ""
        for r in df_t.itertuples():
            vyraz = " ⚠️" if r.vyrazeno else ""
            rows += (
                f'<tr>'
                f'<td style="color:{color};font-weight:700">{int(r.rank)}</td>'
                f'<td style="font-weight:600">{r.nazev}{vyraz}</td>'
                f'<td class="num">{r.driving_dist_km:.0f} km</td>'
                f'<td class="num">{int(r.hh_celkem):,}</td>'
                f'<td class="num" style="color:{color}">{r.net_per_order_kc:.0f} Kč</td>'
                f'<td class="num"><strong style="color:{color}">{int(r.monthly_contribution_kc):,} Kč</strong></td>'
                f'</tr>\n'
            )
        return rows

    _obce_rows_a = _obce_rows(_tier_a, "A")
    _obce_rows_b = _obce_rows(_tier_b, "B")
else:
    obce_sc = None
    _obce_rows_a = _obce_rows_b = ""
    _total_pl_a = _total_pl_b = 0

# Síťová dostupnost (OSMnx)
network_json = os.path.join(OUT_DIR, "network_summary.json")
if os.path.exists(network_json):
    with open(network_json, encoding="utf-8") as f:
        network_data = json.load(f)
else:
    network_data = None

# Monte Carlo P&L
mc_json = os.path.join(OUT_DIR, "monte_carlo_summary.json")
if os.path.exists(mc_json):
    with open(mc_json, encoding="utf-8") as f:
        mc_data = json.load(f)
else:
    mc_data = None
mc_sens_csv = os.path.join(OUT_DIR, "sensitivity_analysis.csv")
if os.path.exists(mc_sens_csv):
    mc_sens = pd.read_csv(mc_sens_csv).sort_values("swing_kc", ascending=False)
else:
    mc_sens = None

# ── Rozvozová politika ───────────────────────────────────────────────────
_POLICY_ZONES = [
    {"km": 5,  "ring": "0–5 km",   "fee": 39,  "free_from": 1000, "min_order": 500,  "courier": 120, "color": "#00e676"},
    {"km": 10, "ring": "5–10 km",  "fee": 69,  "free_from": 1000, "min_order": 500,  "courier": 120, "color": "#ffd740"},
    {"km": 15, "ring": "10–15 km", "fee": 99,  "free_from": 1200, "min_order": 700,  "courier": 180, "color": "#ff9800"},
    {"km": 20, "ring": "15–20 km", "fee": 149, "free_from": 1500, "min_order": 700,  "courier": 180, "color": "#e74c3c"},
]
_GROSS_KC = round(452 * 0.365)  # 165 Kč — hrubá marže z průměrné objednávky
for _z in _POLICY_ZONES:
    _z["net_kc"] = _GROSS_KC + _z["fee"] - _z["courier"]

# Nightlife POI per ring
_NIGHTLIFE_CATS = {"pub", "bar", "nightclub", "cafe", "restaurant", "fast_food"}
_nl_spots = spots_m[spots_m["amenity"].isin(_NIGHTLIFE_CATS)].copy()
_prev_pzgeom = None
_ring_poi = {}
for _z in _POLICY_ZONES:
    _pzg = gpd.read_file(os.path.join(DATA_DIR, f"google_zone_{_z['km']}km.geojson")).to_crs(CRS_METRIC).geometry.iloc[0]
    _n_cum = int(_nl_spots.geometry.within(_pzg).sum())
    _ring_poi[_z["km"]] = _n_cum - (int(_nl_spots.geometry.within(_prev_pzgeom).sum()) if _prev_pzgeom is not None else 0)
    _prev_pzgeom = _pzg

# Doporučení obcí
_rzone_json = os.path.join(OUT_DIR, "recommended_zone.json")
if os.path.exists(_rzone_json):
    with open(_rzone_json, encoding="utf-8") as f:
        _rzone = json.load(f)
else:
    _rzone = {"ponechat": [], "podmínečně": [], "vyřadit": [],
              "souhrn": {"ponechat_count": 0, "podmínečně_count": 0, "vyřadit_count": 0}}

# HTML tabulka zón
_policy_rows = ""
for _z in _POLICY_ZONES:
    _net = _z["net_kc"]
    _nc  = "#2ecc71" if _net >= 100 else "#f39c12" if _net >= 80 else "#e74c3c"
    _hh  = _ring_hh.get(_z["km"], 0)
    _poi = _ring_poi.get(_z["km"], 0)
    _policy_rows += (
        f'<tr>'
        f'<td><span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
        f'background:{_z["color"]};margin-right:6px;vertical-align:middle"></span>'
        f'<strong>{_z["ring"]}</strong></td>'
        f'<td class="num">{_z["fee"]} Kč</td>'
        f'<td class="num">{_z["min_order"]} Kč</td>'
        f'<td class="num">{_z["free_from"]} Kč</td>'
        f'<td class="num">{_z["courier"]} Kč</td>'
        f'<td class="num" style="color:{_nc};font-weight:700">{_net} Kč</td>'
        f'<td class="num">{fmt_n(_hh)}</td>'
        f'<td class="num">{_poi}</td>'
        f'</tr>\n'
    )

def _muni_badges(names, color):
    return " ".join(
        f'<span style="display:inline-block;background:rgba(255,255,255,.07);border:1px solid {color}33;'
        f'border-radius:4px;padding:2px 8px;font-size:.8rem;margin:2px">{n}</span>'
        for n in names
    )

_badge_ponechat  = _muni_badges(_rzone["ponechat"], "#2ecc71")
_badge_podmn     = _muni_badges(_rzone["podmínečně"], "#f39c12")
_badge_vyradit   = _muni_badges(_rzone["vyřadit"], "#e74c3c")

# Analýza skladu
sklad_csv = os.path.join(OUT_DIR, "sklad_scoring.csv")
if os.path.exists(sklad_csv):
    sklad_df = pd.read_csv(sklad_csv)
    _rank_colors = {0: "#ffd740", 1: "#95a5a6", 2: "#cd7f32"}
    _sklad_rows_html = "\n".join(
        '<tr{top_style}>'
        '<td style="color:{rc};font-weight:700">{rank}</td>'
        '<td><strong>{id}</strong></td>'
        '<td style="font-size:.88rem">{nazev}<br>'
        '<span style="color:var(--muted);font-size:.78rem">{pozn}</span></td>'
        '<td class="num">{hh}</td>'
        '<td class="num">{nl}</td>'
        '<td class="num">{dist}</td>'
        '<td class="num"><strong style="color:{rc}">{score:.1f}</strong></td>'
        '<td style="color:{zc}">{zs}</td>'
        '</tr>'.format(
            top_style=' style="background:var(--bg3);border-top:1px solid var(--cyan)"' if i == 0 else "",
            rc=_rank_colors.get(i, "#888"),
            rank=int(r.rank), id=r.id,
            nazev=r.nazev, pozn=r.poznamka,
            hh=f"{int(r.hh_3km):,}".replace(",", " "),
            nl=int(r.nightlife_3km),
            dist=f"{r.avg_dist_zak_m/1000:.1f} km",
            score=r.skore_total,
            zc="var(--green)" if r.in_zone else "var(--pink)",
            zs="✓" if r.in_zone else "✗",
        )
        for i, r in enumerate(sklad_df.itertuples())
    )
else:
    sklad_df = None
    _sklad_rows_html = ""

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

# Nákupní ceny a marže
nak_ceny = pd.read_csv(os.path.join(DATA_DIR, "nakupni_ceny.csv"))
nak_dict = dict(zip(nak_ceny["produkt"], nak_ceny["nakupni_cena_kc"]))

# Marže na každou položku objednávek
pol_sys2 = pol_sys.copy()
pol_sys2["nak_cena"] = pol_sys2["produkt"].map(nak_dict)
pol_sys2["marze_kc"] = pol_sys2["cena_kc"] - pol_sys2["nak_cena"]
pol_sys2["marze_pct"] = (pol_sys2["marze_kc"] / pol_sys2["cena_kc"] * 100).round(1)

# Marže na každou objednávku
order_marze = pol_sys2.groupby("order_id").agg(
    trzba=("cena_kc", "sum"),
    naklady_zbozi=("nak_cena", "sum"),
    marze_kc=("marze_kc", "sum"),
).reset_index()
order_marze = order_marze.merge(
    df_zak[["id","vzdalenost_km","dopravne_zakaznik_kc","naklady_rozvoz_kc"]].rename(columns={"id":"order_id"}),
    on="order_id", how="left"
)
order_marze["fuel_kc"] = (order_marze["vzdalenost_km"] * 2 * cost_per_km).round(2)
order_marze["kontribuce_kc"] = (order_marze["marze_kc"] + order_marze["dopravne_zakaznik_kc"] - order_marze["fuel_kc"]).round(1)
order_marze["marze_pct"] = (order_marze["marze_kc"] / order_marze["trzba"] * 100).round(1)

# Marže na produkt (top table)
prod_marze = pol_sys2.dropna(subset=["nak_cena"]).drop_duplicates("produkt")[
    ["produkt","kategorie","cena_kc","nak_cena","marze_kc","marze_pct"]
].sort_values("marze_pct", ascending=False)

# Katalog s marží (všechny produkty kde máme nákupní cenu)
kat_marze = nak_ceny.merge(
    pd.DataFrame({"produkt": katalog["name"].str.replace(",",".", regex=False),
                  "prodejni_cena": katalog["price"]}),
    on="produkt", how="inner"
)
kat_marze["marze_kc"] = kat_marze["prodejni_cena"] - kat_marze["nakupni_cena_kc"]
kat_marze["marze_pct"] = (kat_marze["marze_kc"] / kat_marze["prodejni_cena"] * 100).round(1)
kat_marze_grp = kat_marze.groupby("kategorie")["marze_pct"].mean().round(1).sort_values(ascending=False)

avg_marze_pct = round(order_marze["marze_pct"].mean(), 1)
avg_kontribuce = round(order_marze["kontribuce_kc"].mean(), 1)
total_kontribuce = round(order_marze["kontribuce_kc"].sum(), 1)
changed_hist = cena_hist[cena_hist["zmena_kc"] > 0].copy()
unchanged_hist = cena_hist[cena_hist["zmena_kc"] == 0].copy()
avg_price_change_pct = round(cena_hist[cena_hist["zmena_kc"] > 0]["zmena_pct"].mean(), 1)

# Predikce objednávek
import numpy as np
# Týdenní data: týden od spuštění (14.3.2026), počet objednávek
weeks_data = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 2),   # první objednávky v týdnu 5
    (6, 0), (7, 1), (8, 1), (9, 1),             # stabilní 1/týden (3. týdny v řadě)
    (10, 0), (11, 0), (12, 2),                   # pauza a nárůst na 2 obj. v týdnu 12 (31.5.)
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


# ── Chart.js data pro Monte Carlo ──────────────────────────────────────────
_mc_chart_html = ""
_mc_table_html = ""
_mc_tornado_html = ""
if mc_data:
    _scenario_cfg = {
        "konzervativni": {"label": "Konzervativni (1/tyden)", "color": "#888888"},
        "cilovy":        {"label": "Cilovy (3/tyden)",        "color": "#29B6F6"},
        "optimisticky":  {"label": "Optimisticky (7/tyden)",   "color": "#00e676"},
    }
    _month_labels = json.dumps([f"M{i}" for i in range(1, 13)])
    _datasets = []
    for sc_key, sc_cfg in _scenario_cfg.items():
        sc = mc_data.get(sc_key, {})
        months = sc.get("months", {})
        if not months:
            continue
        c = sc_cfg["color"]
        p25 = [months[str(m)]["p25"] for m in range(1, 13)]
        p50 = [months[str(m)]["p50"] for m in range(1, 13)]
        p75 = [months[str(m)]["p75"] for m in range(1, 13)]
        _datasets.append({
            "label": sc_cfg["label"] + " p75",
            "data": p75,
            "borderColor": "transparent",
            "backgroundColor": c + "33",
            "fill": "+1",
            "tension": 0.4,
            "pointRadius": 0,
        })
        _datasets.append({
            "label": sc_cfg["label"] + " p25",
            "data": p25,
            "borderColor": "transparent",
            "backgroundColor": c + "33",
            "fill": False,
            "tension": 0.4,
            "pointRadius": 0,
        })
        _datasets.append({
            "label": sc_cfg["label"],
            "data": p50,
            "borderColor": c,
            "backgroundColor": "transparent",
            "fill": False,
            "tension": 0.4,
            "borderWidth": 2.5,
            "pointRadius": 3,
            "pointHoverRadius": 5,
        })
    _datasets_js = json.dumps(_datasets)
    _mc_chart_html = (
        '<canvas id="mcChart" style="max-height:340px;"></canvas>\n'
        '<script>\n'
        '(function(){\n'
        '  var ctx = document.getElementById(\'mcChart\').getContext(\'2d\');\n'
        '  new Chart(ctx, {\n'
        '    type: \'line\',\n'
        '    data: { labels: ' + _month_labels + ', datasets: ' + _datasets_js + ' },\n'
        '    options: {\n'
        '      responsive: true,\n'
        '      interaction: { intersect: false, mode: \'index\' },\n'
        '      plugins: {\n'
        '        legend: { labels: { color: \'#bbb\', filter: function(item) { return !item.text.endsWith(\' p75\') && !item.text.endsWith(\' p25\'); } } },\n'
        '        tooltip: { callbacks: { label: function(ctx) { return ctx.dataset.label + \': \' + Math.round(ctx.parsed.y) + \' Kc\'; } } }\n'
        '      },\n'
        '      scales: {\n'
        '        x: { ticks: { color: \'#888\' }, grid: { color: \'#1a1a28\' } },\n'
        '        y: { ticks: { color: \'#888\', callback: function(v){return v+\' Kc\';} }, grid: { color: \'#1a1a28\' } }\n'
        '      }\n'
        '    }\n'
        '  });\n'
        '})();\n'
        '</script>'
    )
    _mc_rows = ""
    for sc_key, sc_cfg in _scenario_cfg.items():
        sc = mc_data.get(sc_key, {})
        if not sc:
            continue
        be = mc_data.get("breakeven", {}).get(sc_key, {})
        p25_ok = be.get("breakeven_positive", False)
        _mc_rows += (
            f'<tr>'
            f'<td style="color:{sc_cfg["color"]};font-weight:600">{sc_cfg["label"]}</td>'
            f'<td class="num">{sc.get("annual_p5", 0):,.0f} Kc</td>'
            f'<td class="num" style="color:{sc_cfg["color"]}">{sc.get("annual_p50", 0):,.0f} Kc</td>'
            f'<td class="num">{sc.get("annual_p95", 0):,.0f} Kc</td>'
            f'<td class="num" style=\'color:{"var(--green)" if p25_ok else "var(--pink)"}\'>'
            f'{"&check;" if p25_ok else "&times;"}</td>'
            f'</tr>\n'
        )
    _mc_table_html = (
        '<table style="width:100%;border-collapse:collapse;margin:16px 0">\n'
        '<tr style="color:#888;font-size:.85rem;border-bottom:1px solid var(--border)">'
        '<th style="text-align:left;padding:6px 8px">Scenar</th>'
        '<th class="num">Rocni p5</th><th class="num">Rocni median</th>'
        '<th class="num">Rocni p95</th><th class="num">p25&gt;0?</th></tr>\n'
        + _mc_rows + '</table>'
    )
    if mc_sens is not None:
        _tornado_labels = json.dumps(list(mc_sens["parameter"]))
        _tornado_low    = json.dumps(list(mc_sens["delta_low_kc"].round(0).astype(int)))
        _tornado_high   = json.dumps(list(mc_sens["delta_high_kc"].round(0).astype(int)))
        _mc_tornado_html = (
            '<canvas id="tornadoChart" style="max-height:280px;margin-top:24px"></canvas>\n'
            '<script>\n'
            '(function(){\n'
            '  var ctx = document.getElementById(\'tornadoChart\').getContext(\'2d\');\n'
            '  new Chart(ctx, {\n'
            '    type: \'bar\',\n'
            '    data: {\n'
            '      labels: ' + _tornado_labels + ',\n'
            '      datasets: [\n'
            '        { label: \'-30% variace\', data: ' + _tornado_low + ', backgroundColor: \'#FF3D9A99\', borderColor: \'#FF3D9A\', borderWidth: 1 },\n'
            '        { label: \'+30% variace\', data: ' + _tornado_high + ', backgroundColor: \'#00e67699\', borderColor: \'#00e676\', borderWidth: 1 }\n'
            '      ]\n'
            '    },\n'
            '    options: {\n'
            '      indexAxis: \'y\',\n'
            '      responsive: true,\n'
            '      plugins: { legend: { labels: { color: \'#bbb\' } } },\n'
            '      scales: {\n'
            '        x: { ticks: { color: \'#888\', callback: function(v){return v+\' Kc\';} }, grid: { color: \'#1a1a28\' } },\n'
            '        y: { ticks: { color: \'#bbb\' } }\n'
            '      }\n'
            '    }\n'
            '  });\n'
            '})();\n'
            '</script>'
        )

# ── data pro síťovou dostupnost ───────────────────────────────────────────────
_net_table_html = ""
if network_data:
    _net_rows = ""
    _iso_colors = {5: "#00e676", 10: "#ffd740", 15: "#ff9800", 20: "#e74c3c"}
    for minutes in [5, 10, 15, 20]:
        s = network_data.get(str(minutes), {})
        if not s:
            continue
        c = _iso_colors[minutes]
        _net_rows += (
            f'<tr>'
            f'<td style="color:{c};font-weight:600">{minutes} min</td>'
            f'<td class="num">{s["area_km2"]:.0f} km&sup2;</td>'
            f'<td class="num">{s["hh_count"]:,}</td>'
            f'<td class="num">{s["pop_est"]:,}</td>'
            f'<td class="num">{s["pct_google20"]:.0f} %</td>'
            f'<td class="num">+{s["incremental_hh"]:,}</td>'
            f'</tr>\n'
        )
    g20 = network_data.get("google20", {})
    _net_table_html = (
        '<table style="width:100%;border-collapse:collapse;margin:16px 0">\n'
        '<tr style="color:#888;font-size:.85rem;border-bottom:1px solid var(--border)">'
        '<th style="text-align:left;padding:6px 8px">Izochrona</th>'
        '<th class="num">Plocha</th><th class="num">Domacnosti</th>'
        '<th class="num">Odh. obyvatel</th><th class="num">% Google 20km</th>'
        '<th class="num">Prirůstek HH</th></tr>\n'
        + _net_rows +
        f'<tr style="border-top:1px solid var(--border);color:#3388ff">'
        f'<td>Google &le;20 km (ref.)</td>'
        f'<td class="num">{g20.get("area_km2", "-")} km&sup2;</td>'
        f'<td class="num">{g20.get("hh_count", 0):,}</td>'
        f'<td class="num">-</td><td class="num">100 %</td><td class="num">-</td>'
        f'</tr>\n</table>'
    )

    # KPI proměnné pro HTML sekci
    _net_5min_hh  = f"{network_data.get('5', {}).get('hh_count', 0):,}"
    _net_10min_hh = f"{network_data.get('10', {}).get('hh_count', 0):,}"
    _net_15min_hh = f"{network_data.get('15', {}).get('hh_count', 0):,}"
    _net_20min_hh = f"{network_data.get('20', {}).get('hh_count', 0):,}"
    _pct_10min = f"{network_data.get('10', {}).get('pct_google20', 0):.0f}"
    _net_15_over = f"{max(0, network_data.get('15', {}).get('pct_google20', 0) - 100):.0f}"
else:
    _net_5min_hh = _net_10min_hh = _net_15min_hh = _net_20min_hh = "–"
    _pct_10min = "–"
    _net_15_over = "–"

try:
    import osmnx as _ox_ver
    _osmnx_ver = _ox_ver.__version__
except Exception:
    _osmnx_ver = "2.x"

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
  .tag-pivo {{ background: #0a100a; color: #aed581; border: 1px solid #aed581; }}
  .tag-nealko {{ background: #0a0f15; color: #4dd0e1; border: 1px solid #4dd0e1; }}

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
      Zpracováno: {date_last_str}<br>
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
    <li><a href="#obce">Výběr obcí pro rozvoz</a></li>
    <li><a href="#demografie">Demografický profil</a></li>
    <li><a href="#zastavba">Bytová zástavba (RÚIAN)</a></li>
    <li><a href="#zakaznici">Zákazníci a objednávky</a></li>
    <li><a href="#finance">Finanční přehled</a></li>
    <li><a href="#marze">Maržová analýza</a></li>
    <li><a href="#sortiment">Sortiment a produkty</a></li>
    <li><a href="#cena-historie">Cenová historie</a></li>
    <li><a href="#predikce">Predikce a scénáře růstu</a></li>
    <li><a href="#monte-carlo">Monte Carlo P&L projekce</a></li>
    <li><a href="#sit-dostupnost">Síťová dostupnost (OSM)</a></li>
    <li><a href="#marketing">Marketingové příležitosti</a></li>
    <li><a href="#scenare">Scénáře vzdálenosti + palivo</a></li>
    <li><a href="#politika">Rozvozová politika</a></li>
    <li><a href="#mapa">Interaktivní mapa</a></li>
    <li><a href="#investori">Pro investory</a></li>
    <li><a href="#zaver">Závěry a doporučení</a></li>
    <li><a href="#sklad">Analýza umístění skladu</a></li>
  </ol>
</div>

<!-- ── 1. EXECUTIVE SUMMARY ──────────────────────────────────────────────── -->
<div class="section" id="summary">
<h2>1. Executive summary</h2>
<p class="lead">VečerkaPlus je první noční rozvozová služba ve Frýdku-Místku specializovaná na alkohol a doplňkové zboží. Provoz byl zahájen 14. března 2026; první objednávka přišla 18. dubna 2026 po&nbsp;pěti týdnech od spuštění. Do {date_last_str} bylo doručeno <strong>{n_objednavek} objednávek</strong> celkové tržby <strong>{fmt_n(trzba_total)} Kč</strong>.</p>

<div class="kpi-grid" style="margin:24px 0;">
  <div class="kpi"><div class="val">{fmt_n(pop_grid_iso)}</div><div class="lbl">Odh. obyvatel v dosahu</div></div>
  <div class="kpi"><div class="val">{fmt_n(hh_iso)}</div><div class="lbl">Domácností v dosahu</div></div>
  <div class="kpi"><div class="val">{fmt_n(bytu_celkem)}</div><div class="lbl">Bytů (RÚIAN)</div></div>
  <div class="kpi"><div class="val pink">{fmt_n(n_objednavek)}</div><div class="lbl">Objednávek (celkem)</div></div>
  <div class="kpi"><div class="val green">{int(trzba_avg)} Kč</div><div class="lbl">Průměrná tržba</div></div>
  <div class="kpi"><div class="val yellow">{round(zone_area_km2)} km²</div><div class="lbl">Plocha rozvozové zóny</div></div>
</div>

<div class="highlight positive">
  <strong>Potenciál:</strong> V reálné rozvozové zóně žije odhadem <strong>{fmt_n(pop_grid_iso)} obyvatel</strong> v <strong>{fmt_n(hh_iso)} domácnostech</strong>. Bytové domy (panelová zástavba ≥5 podlaží) koncentrují <strong>{fmt_n(bytu_panelaky)} bytů</strong> — to je hlavní cílový segment pro noční rozvoz. Nejdelší dosavadní doručení bylo na <strong>{vzdalenost_max} km</strong> (Ostrava-Polanka nad Odrou), první objednávka mimo 20km zónu.
</div>
<div class="highlight warn">
  <strong>Limitace dat:</strong> Analýza vychází z {n_objednavek} objednávek za prvních {n_weeks_since_launch} týdnů provozu. Statistické závěry o zákaznickém chování jsou orientační — data jsou prezentována jako raná fáze provozu, nikoli reprezentativní vzorek.
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

<!-- ── VÝBĚR OBCÍ PRO ROZVOZ ────────────────────────────────────────── -->
<div class="section" id="obce">
<h2>Výběr obcí pro rozvoz — P&amp;L analýza</h2>
<p>Každá obec v rozvozové zóně je klasifikována do tří tierů podle odhadovaného měsíčního příspěvku na pokrytí (tržba − náklady zboží − kurýr paušál + dopravné od zákazníka), při předpokladu konverzního poměru <strong>0,2 % domácností/měsíc</strong> a průměrné objednávce <strong>452 Kč</strong>.</p>

<div style="display:flex;gap:16px;flex-wrap:wrap;margin:20px 0;">
  <div style="flex:1;min-width:220px;background:rgba(0,230,118,.08);border:1px solid #00e676;border-radius:6px;padding:16px">
    <div style="color:#00e676;font-size:1.2rem;font-weight:700">Tier A — Prioritní</div>
    <div style="font-size:.85rem;color:var(--muted);margin:4px 0 10px">≥ 100 Kč/měsíc odhadovaný příspěvek</div>
    <div style="font-size:1.8rem;font-weight:700;color:#00e676">{"{"}{len(_tier_a) if obce_sc is not None else "–"}{"}"} obcí</div>
    <div style="color:#00e676">Celkem: {fmt_n(_total_pl_a)} Kč/měs</div>
    <div style="font-size:.8rem;color:var(--muted);margin-top:6px">→ Aktivně marketovat, letáky, Instagram cílení</div>
  </div>
  <div style="flex:1;min-width:220px;background:rgba(255,215,64,.06);border:1px solid #ffd740;border-radius:6px;padding:16px">
    <div style="color:#ffd740;font-size:1.2rem;font-weight:700">Tier B — Výhodné</div>
    <div style="font-size:.85rem;color:var(--muted);margin:4px 0 10px">30–100 Kč/měsíc odhadovaný příspěvek</div>
    <div style="font-size:1.8rem;font-weight:700;color:#ffd740">{"{"}{len(_tier_b) if obce_sc is not None else "–"}{"}"} obcí</div>
    <div style="color:#ffd740">Celkem: {fmt_n(_total_pl_b)} Kč/měs</div>
    <div style="font-size:.8rem;color:var(--muted);margin-top:6px">→ Doručovat na objednávku, bez aktivního marketingu</div>
  </div>
  <div style="flex:1;min-width:220px;background:rgba(231,76,60,.06);border:1px solid #e74c3c;border-radius:6px;padding:16px">
    <div style="color:#e74c3c;font-size:1.2rem;font-weight:700">Tier C — Marginální</div>
    <div style="font-size:.85rem;color:var(--muted);margin:4px 0 10px">&lt; 30 Kč/měsíc odhadovaný příspěvek</div>
    <div style="font-size:1.8rem;font-weight:700;color:#e74c3c">{"{"}{len(obce_sc[obce_sc["tier"]=="C"]) if obce_sc is not None else "–"}{"}"} obcí</div>
    <div style="color:var(--muted)">Malé vesnice, &lt; 1 obj/měsíc</div>
    <div style="font-size:.8rem;color:var(--muted);margin-top:6px">→ Doručit pokud zákazník sám objedná</div>
  </div>
</div>

<div class="highlight warn">
  <strong>P&amp;L upozornění:</strong> Kurýrský paušál skokově roste z 120 Kč (≤10 km) na 180 Kč (10–20 km), zatímco zákazníkovo dopravné zůstává 39 Kč.
  Čistý příspěvek v 10–20km pásmu je jen <strong>24 Kč/obj</strong> vs. 84 Kč u ≤10 km.
  Zvýšení dopravného pro 10–20 km zónu z 39 → 59 Kč by zlepšilo příspěvek na <strong>44 Kč/obj</strong> (+83 %).
</div>

{"" if obce_sc is None else f"""
<div class="two-col" style="margin-top:24px;">
<div>
<h3 style="color:#00e676;margin-bottom:8px">Tier A — Prioritní obce</h3>
<table>
  <tr><th>#</th><th>Obec</th><th class="num">Vzdál.</th><th class="num">Domác.</th><th class="num">Kč/obj</th><th class="num">Kč/měs</th></tr>
  {_obce_rows_a}
</table>
</div>
<div>
<h3 style="color:#ffd740;margin-bottom:8px">Tier B — Výhodné obce</h3>
<table>
  <tr><th>#</th><th>Obec</th><th class="num">Vzdál.</th><th class="num">Domác.</th><th class="num">Kč/obj</th><th class="num">Kč/měs</th></tr>
  {_obce_rows_b}
</table>
</div>
</div>
<p style="font-size:.8rem;color:var(--muted);margin-top:8px">
  Konverzní poměr 0,2 % HH/měsíc = base rate odhad; driving distance z Google Distance Matrix cache;
  náklady zboží 36,5 % z tržby; kurýr paušál 120/180/250 Kč; zákazník platí 39/164 Kč.
  Interaktivní mapa: <a href="obce_analyza.html" style="color:var(--cyan)">obce_analyza.html</a>
</p>
"""}
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

<div style="margin-top:32px;">
<h3>Demografie per rozvozová zóna (SLDB 2021 · area-weighted)</h3>
<p style="font-size:.85rem;color:var(--muted);margin-bottom:14px;">
  Věková struktura a domácnosti pro každý dopravní prsten. Hodnoty jsou prstencové (každá zóna bez předchozí).
  Zdroj: ČSÚ SLDB 2021, Google Distance Matrix zóny.
</p>
<div style="overflow-x:auto;">
<table>
  <tr>
    <th>Zóna</th>
    <th class="num">Obyvatelé</th>
    <th class="num">Domácností</th>
    <th class="num">0–14</th>
    <th class="num">%</th>
    <th class="num">15–64</th>
    <th class="num">%</th>
    <th class="num">65+</th>
    <th class="num">%</th>
    <th class="num">Ø věk</th>
  </tr>
  {_zone_demo_rows}
</table>
</div>

<div style="margin-top:24px;" class="chart-wrap">
  <h3 style="margin-bottom:16px;">Věková struktura per zóna — absolutní počty (SLDB 2021)</h3>
  <canvas id="chartZoneDemo" style="max-height:300px;"></canvas>
</div>

<div class="highlight" style="margin-top:20px;">
  <strong>Klíčové zjištění:</strong> Věková struktura je napříč zónami prakticky identická (~43 let Ø věk, ~20 % seniorů, ~15 % dětí).
  Vzdálenost <strong>není demografickým segmentačním faktorem</strong> — cílová skupina 15–64 let tvoří stabilně
  ~64 % v každé zóně. Největší absolutní rezervoár zákazníků je v prstenci 15–20 km
  ({fmt_n(_ring_demo[20]["vek_15_64"])} osob ve věku 15–64), ale průměrná kontribuční marže je zde nejnižší.
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
<p>V období od 18. dubna do {date_last_str} bylo přijato a doručeno <strong>{n_objednavek} objednávek</strong>. Prvních 5 objednávek pochází z centra Frýdku-Místku (1,8–3,3 km). Objednávka #6 (Žabeň, 6,0 km) je první mimo centrum a objednávka #7 (Ostrava-Polanka, 22,3 km) je první za hranicí standardní 20km zóny.</p>

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

  <div class="order-card">
    <div class="order-header"><span class="order-id">#6 · 31. 5. 2026 · neděle 00:01</span><span class="order-val">678 Kč</span></div>
    <div class="order-meta">📍 Žabeň · 6,0 km · hotově · dopravné zdarma</div>
    <div class="order-items"><span class="tag tag-tabak">tabák</span><span class="tag tag-lihoviny" style="margin-left:4px">lihoviny</span> Marlboro Red + Finlandia Vodka 0,7l</div>
  </div>

  <div class="order-card" style="border-color:var(--yellow);">
    <div class="order-header"><span class="order-id">#7 · 31. 5. 2026 · neděle 21:08</span><span class="order-val">629 Kč</span></div>
    <div class="order-meta">📍 Za Humny 882, Ostrava-Polanka · <strong style="color:var(--yellow)">22,3 km ⚠ mimo zónu</strong> · kartou · dopravné 79 Kč</div>
    <div class="order-items"><span class="tag tag-pivo">pivo</span> 10× Radegast 0,5 12</div>
  </div>

</div>

<div class="highlight">
  <strong>Vzorec objednávek:</strong> 3 objednávky přišly v pátek (20:13, 21:20, 21:30), 2 v sobotu (00:04, 22:56), 2 v neděli (00:01, 21:08). Produktový mix dominují lihoviny (4/7 objednávek). Objednávka #7 (Ostrava, 22,3 km) je první za hranicí 20km zóny a zároveň první objednávka piva — 10× Radegast za 550 Kč + 79 Kč dopravné. Kontribuční marže −52 Kč (palivo 131 Kč > marže + dopravné) — doručení za tuto vzdálenost je ztrátové při standardní ceně piva.
</div>
</div>

<!-- ── 6. FINANCE ─────────────────────────────────────────────────────── -->
<div class="section" id="finance">
<h2>6. Finanční přehled</h2>
<div class="two-col">
<div>
<table>
  <tr><th>Metrika</th><th class="num">Hodnota</th></tr>
  <tr><td>Celková tržba ({n_objednavek} obj.)</td><td class="num"><strong style="color:var(--green)">{fmt_n(trzba_total)} Kč</strong></td></tr>
  <tr><td>Průměrná tržba / objednávka</td><td class="num">{int(trzba_avg)} Kč</td></tr>
  <tr><td>Min / Max tržba</td><td class="num">{min_trzba} / {max_trzba} Kč</td></tr>
  <tr><td>Celkové přímé náklady na rozvoz</td><td class="num">{round(naklady_total, 0):.0f} Kč</td></tr>
  <tr><td>Průměrné náklady rozvoz / obj.</td><td class="num">{round(naklady_total/n_objednavek, 1)} Kč</td></tr>
  <tr><td>Průměrná vzdálenost doručení</td><td class="num">{vzdalenost_avg} km</td></tr>
  <tr><td>Objednávky s dopravným zdarma (≥{DOPRAVNE_ZDARMA_KC} Kč)</td><td class="num">{free_delivery} / {n_objednavek} <span style="color:var(--muted);font-size:.8rem">(1× promo/spuštění)</span></td></tr>
  <tr><td>Platba kartou / hotově</td><td class="num">{kartou_count} / {hotove_count}</td></tr>
</table>
</div>
<div class="chart-wrap">
  <canvas id="chartTrzby" height="220"></canvas>
</div>
</div>

<div class="highlight positive" style="margin-top:20px;">
  <strong>Nákladová efektivita rozvozu:</strong> Průměrné palivové náklady na doručení jsou <strong>{avg_fuel_per_order:.1f} Kč</strong> ({SPOTREBA_L_100KM} l/100 km × {CENA_PHM_KC_L} Kč/l, průměr {vzdalenost_avg} km). Průměrná kontribuční marže po odečtení pohonných hmot a zboží je <strong>{avg_kontribuce} Kč/objednávku</strong>.
</div>
</div>

<!-- ── 7. MARŽE ───────────────────────────────────────────────────────── -->
<div class="section" id="marze">
<h2>7. Maržová analýza</h2>
<p>Na základě skutečných nákupních cen (faktury) byla vypočtena přesná hrubá marže pro každý prodaný produkt a každou objednávku. Průměrná hrubá marže na zboží je <strong>{avg_marze_pct} %</strong>, průměrná kontribuční marže (marže + dopravné zákazníka − palivo) je <strong>{avg_kontribuce} Kč/objednávku</strong>.</p>

<div class="kpi-grid" style="margin:20px 0;">
  <div class="kpi"><div class="val">{avg_marze_pct} %</div><div class="lbl">Průměrná hrubá marže na zboží</div></div>
  <div class="kpi"><div class="val green">{avg_kontribuce} Kč</div><div class="lbl">Kontribuční marže/objednávku</div></div>
  <div class="kpi"><div class="val green">{total_kontribuce} Kč</div><div class="lbl">Celková kontribuce ({n_objednavek} obj.)</div></div>
  <div class="kpi"><div class="val pink">{avg_fuel_per_order:.1f} Kč</div><div class="lbl">Průměrné palivo/doručení</div></div>
</div>

<div class="two-col">
<div>
<h3>Marže na objednávku</h3>
<table>
  <tr><th>Obj.</th><th class="num">Tržba zboží</th><th class="num">Nákl. zboží</th><th class="num">Hrubá marže</th><th class="num">Marže %</th><th class="num">+Dopravné zák.</th><th class="num">−Palivo</th><th class="num"><strong>Kontribuce</strong></th></tr>
{"".join(
    f'<tr><td>#{int(r.order_id)}</td>'
    f'<td class="num">{r.trzba:.0f} Kč</td>'
    f'<td class="num" style="color:var(--pink)">{r.naklady_zbozi:.0f} Kč</td>'
    f'<td class="num">{r.marze_kc:.0f} Kč</td>'
    f'<td class="num">{r.marze_pct:.1f} %</td>'
    f'<td class="num" style="color:var(--green)">+{r.dopravne_zakaznik_kc:.0f} Kč</td>'
    f'<td class="num" style="color:var(--pink)">−{r.fuel_kc:.1f} Kč</td>'
    f'<td class="num"><strong>{r.kontribuce_kc:.0f} Kč</strong></td></tr>'
    for r in order_marze.itertuples() if not pd.isna(r.naklady_zbozi)
)}
</table>
<p style="font-size:.8rem;color:var(--muted);margin-top:6px;">Kontribuce = hrubá marže + dopravné zákazníka − palivové náklady ({SPOTREBA_L_100KM} l/100 km × {CENA_PHM_KC_L} Kč/l)</p>
</div>
<div class="chart-wrap">
  <h3 style="margin-bottom:14px;">Průměrná marže dle kategorie</h3>
  <canvas id="chartMarzeKat" height="260"></canvas>
</div>
</div>

<div style="margin-top:20px;">
<h3>Top 10 produktů dle hrubé marže</h3>
<table>
  <tr><th>Produkt</th><th>Kategorie</th><th class="num">Prodejní cena</th><th class="num">Nákupní cena</th><th class="num">Marže</th><th class="num">Marže %</th></tr>
{"".join(
    f'<tr><td>{r.produkt}</td><td>{r.kategorie}</td>'
    f'<td class="num">{r.cena_kc:.0f} Kč</td>'
    f'<td class="num" style="color:var(--pink)">{r.nak_cena:.0f} Kč</td>'
    f'<td class="num" style="color:var(--green)">{r.marze_kc:.0f} Kč</td>'
    f'<td class="num"><strong style="color:{"var(--green)" if r.marze_pct >= 50 else "var(--yellow)" if r.marze_pct >= 30 else "var(--muted)"}">{r.marze_pct:.1f} %</strong></td></tr>'
    for r in prod_marze.itertuples()
)}
</table>
</div>

<div class="highlight positive" style="margin-top:16px;">
  <strong>Nejziskovější kategorie:</strong> Snacky a soft drinky mají marži 56–75 % — ideální přídavné produkty. Lihoviny (klíčová kategorie, 60 % objednávek) mají marži 38–64 %. Tabák má nejnižší marži ~17 % — ale funguje jako trigger objednávky (zákazník objedná tabák a přidá lihoviny). Optimální strategie: zvyšovat průměrnou hodnotu košíku cross-sellem snacků a nealko ke každé objednávce s lihovinami.
</div>
</div>

<!-- ── 8. SORTIMENT ──────────────────────────────────────────────────── -->
<div class="section" id="sortiment">
<h2>8. Sortiment a produktová analýza</h2>
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
<p>Tyto kategorie v katalogu existují, ale zatím nikdo neobjednal: <strong>Energy drinky</strong>, <strong>Party Mix</strong>, <strong>Doplňky</strong>. Pivo bylo dosud bez prodeje, ale objednávka #7 (10× Radegast) tuto mezeru prolomila — byť s negativní kontribuční marží kvůli vzdálenosti 22,3 km.</p>
</div>

<div class="highlight warn">
  <strong>Off-system prodej — Marlboro:</strong> U objednávky #2 (Ladislav Wojnar, 19. 4.) zákazník požadoval i Marlboro, které nebylo přidáno do systémové objednávky. Emailová notifikace zachytila tržbu 286 Kč za víno + 39 Kč dopravné = 325 Kč, reálná hodnota transakce byla ~504 Kč. Tato slepá skvrna v datech bude přetrvávat, dokud nebude sortiment úplný a objednávky budou doplňovány manuálně.
</div>
</div>


<!-- ── 9. CENOVÁ HISTORIE ────────────────────────────────────────────── -->
<div class="section" id="cena-historie">
<h2>9. Cenová historie produktů</h2>
<p>Ceny jsou odvozeny porovnáním <strong>cen z emailových notifikací objednávek</strong> (dubna–května 2026) s aktuálním produktovým katalogem (Supabase, stav {date_last_str}). Pro produkty dosud neobjednané nelze historii odvodit.</p>

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


<!-- ── 10. PREDIKCE ────────────────────────────────────────────────────── -->
<div class="section" id="predikce">
<h2>10. Predikce objednávek a scénáře růstu</h2>
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


<!-- ── 11. MONTE CARLO P&L PROJEKCE ────────────────────────────────────── -->
<div class="section" id="monte-carlo">
<h2>11. Monte Carlo P&amp;L projekce</h2>
<p>Simulace 5 000 scénářů × 12 měsíců pro tři úrovně poptávky. Příchod objednávek modelován Poissonovým procesem; hodnota objednávky a vzdálenost jako normální rozdělení tažené z dat (n=7).</p>

{_mc_chart_html}
<p style="color:var(--muted);font-size:.82rem;margin-top:8px;">Šrafovaná pásma = mezikvartiálový rozsah p25–p75. Linie = medián (p50). Čistý příspěvek / objednávku = hrubá marže + dopravné zákazníka − paušál kurýrovi.</p>

<h3 style="margin-top:24px;">Roční souhrn per scénář</h3>
{_mc_table_html}

<h3 style="margin-top:24px;">Analýza citlivosti — tornado chart (cílový scénář, ±30 %)</h3>
<p style="color:#bbb;margin-bottom:8px;">Vliv ±30% odchylky každého parametru na roční P50. Delší sloupec = větší citlivost.</p>
{_mc_tornado_html}

<div class="highlight" style="margin-top:20px;">
  <strong>Klíčové zjištění:</strong> Největší páku na P&amp;L má hrubá marže na zboží a průměrná tržba/objednávka — oba parametry jsou ovlivnitelné volbou sortimentu s vyšší marží. Dopravné zákazníka (39 Kč) má výrazně menší vliv než kurýrský paušál. Model je ilustrativní (n=7 historických objednávek).
</div>
</div>


<!-- ── 12. SÍŤOVÁ DOSTUPNOST (OSM) ───────────────────────────────────────── -->
<div class="section" id="sit-dostupnost">
<h2>12. Síťová dostupnost (OpenStreetMap)</h2>
<p>Izochróny jízdní dostupnosti vypočteny z výchozího bodu řidiče (Frýdek-Místek) na základě OSM silniční sítě (OSMnx {_osmnx_ver}). Pokrytí domácností porovnáno s provozní Google Distance Matrix zónou ≤ 20 km.</p>

{_net_table_html}

<div class="kpi-grid" style="margin:20px 0;">
  <div class="kpi"><div class="val" style="color:#00e676">{_net_5min_hh}</div><div class="lbl">Domácností do 5 min</div></div>
  <div class="kpi"><div class="val" style="color:#ffd740">{_net_10min_hh}</div><div class="lbl">Domácností do 10 min</div></div>
  <div class="kpi"><div class="val" style="color:#ff9800">{_net_15min_hh}</div><div class="lbl">Domácností do 15 min</div></div>
  <div class="kpi"><div class="val" style="color:#e74c3c">{_net_20min_hh}</div><div class="lbl">Domácností do 20 min</div></div>
</div>

<div class="highlight">
  <strong>Operační závěr:</strong> Do 10 min jízdy je dostupných {_pct_10min} % domácností provozní zóny (Google ≤ 20 km). Izochróna 15 min ji překrývá o {_net_15_over} % — část zákazníků v Google zóně leží v oblastech s delší jízdní dobou. 
  Mapa: <a href="network_analyza.html" target="_blank">network_analyza.html</a>
</div>
</div>


<!-- ── 11. MARKETING ───────────────────────────────────────────────────── -->
<div class="section" id="marketing">
<h2>11. Marketingové příležitosti</h2>
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

<!-- ── 12. SCÉNÁŘE ─────────────────────────────────────────────────────── -->
<div class="section" id="scenare">
<h2>12. Scénáře rozvozové vzdálenosti</h2>
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

<!-- ── ROZVOZOVÁ POLITIKA ────────────────────────────────────────────── -->
<div class="section" id="politika">
<h2>13. Rozvozová politika</h2>
<p>Každý prstenec je ekonomicky kladný. Limitujícím faktorem není marže, ale <strong>čas kurýra</strong> — jedno doručení do 15–20 km trvá 45–70 min, tedy 2–3× déle než jízda do centra FM.</p>

<h3 style="margin:24px 0 10px">Ekonomika zón (průměrná objednávka {int(trzba_avg)} Kč)</h3>
<table>
  <thead>
    <tr>
      <th>Prstenec</th>
      <th class="num">Dopravné</th>
      <th class="num">Min. obj.</th>
      <th class="num">Zdarma od</th>
      <th class="num">Kurýr/obj</th>
      <th class="num">Příspěvek/obj</th>
      <th class="num">Domácností</th>
      <th class="num">Nightlife POI</th>
    </tr>
  </thead>
  <tbody>{_policy_rows}</tbody>
</table>
<p style="font-size:.8rem;color:var(--muted);margin-top:6px">Příspěvek/obj = hrubá marže ({_GROSS_KC} Kč) + dopravné − kurýrní paušál. Domácnosti z SLDB 2021 / ČÚZK gridu.</p>

<h3 style="margin:28px 0 12px">Doporučení per zóna</h3>
<div style="display:grid;gap:12px">

<div style="background:var(--bg2);border-left:4px solid #2ecc71;border-radius:6px;padding:14px 16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span style="background:#2ecc71;color:#000;font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:99px">Aktivně obsloužit</span>
    <strong>0–5 km — Jádro FM</strong>
  </div>
  <p style="margin:0;font-size:.88rem;color:var(--muted)">Základní operační zóna. Nejnižší dopravné (39 Kč) přitahuje impulzivní objednávky, husté osídlení, nejvyšší koncentrace nightlife POI. Frýdek-Místek centrum, Staré Město, Sviadnov. Doporučena agresivní propagace.</p>
</div>

<div style="background:var(--bg2);border-left:4px solid #27ae60;border-radius:6px;padding:14px 16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span style="background:#27ae60;color:#fff;font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:99px">Aktivně obsloužit</span>
    <strong>5–10 km — Rozšířená zóna</strong>
  </div>
  <p style="margin:0;font-size:.88rem;color:var(--muted)">Nejvyšší příspěvková marže (114 Kč/obj) ze všech zón — stejné kurýrní náklady jako v pásu 0–5 km při vyšším dopravném. Zahrnuje Havířov, Bašku, Paskov, Dobrá, Šenov. Aktivní marketingová kampaň.</p>
</div>

<div style="background:var(--bg2);border-left:4px solid #f39c12;border-radius:6px;padding:14px 16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span style="background:#f39c12;color:#000;font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:99px">Podmínečně</span>
    <strong>10–15 km — Selektivní obsluha</strong>
  </div>
  <p style="margin:0;font-size:.88rem;color:var(--muted)">Marže 84 Kč/obj je solidní tam, kde poptávka přichází. Prioritizovat Frýdlant n.O., Petřvald, Brušperk, Příbor. Pro venkovské obce obsloužit jen pokud není vytíženost v pásu 0–10 km. Min. objednávka 700 Kč.</p>
</div>

<div style="background:var(--bg2);border-left:4px solid #e67e22;border-radius:6px;padding:14px 16px">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
    <span style="background:#e67e22;color:#fff;font-size:.72rem;font-weight:700;padding:2px 9px;border-radius:99px">Pouze prémium</span>
    <strong>15–20 km — Prémiové doručení</strong>
  </div>
  <p style="margin:0;font-size:.88rem;color:var(--muted)">Marže 134 Kč/obj ale doručení trvá 45–70 min — kurýr stráví čas, ve kterém by zvládl 2–3 objednávky v centru. Přijímat pouze ≥ 1 500 Kč (dopravné zdarma) a pouze bez jiné zakázky. Aktivně nemarketovat.</p>
</div>

</div>

<h3 style="margin:28px 0 12px">Doporučení obcí ({_rzone["souhrn"]["ponechat_count"]} / {_rzone["souhrn"]["podmínečně_count"]} / {_rzone["souhrn"]["vyřadit_count"]})</h3>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;font-size:.85rem">
  <div>
    <div style="color:#2ecc71;font-weight:600;margin-bottom:6px">✅ Vždy obsloužit ({_rzone["souhrn"]["ponechat_count"]})</div>
    <div style="line-height:1.9">{_badge_ponechat}</div>
  </div>
  <div>
    <div style="color:#f39c12;font-weight:600;margin-bottom:6px">⚠️ Podmínečně ({_rzone["souhrn"]["podmínečně_count"]})</div>
    <div style="line-height:1.9">{_badge_podmn}</div>
  </div>
  <div>
    <div style="color:#e74c3c;font-weight:600;margin-bottom:6px">🚫 Neobsloužit ({_rzone["souhrn"]["vyřadit_count"]})</div>
    <div style="line-height:1.9">{_badge_vyradit}</div>
  </div>
</div>
</div>

<!-- ── 14. MAPA ─────────────────────────────────────────────────────────── -->
<div class="section" id="mapa">
<h2>14. Interaktivní mapa</h2>
<p>Mapa zobrazuje Google rozvozovou zónu (oranžová), buffer 20 km (modrá přerušovaná), ZUJ hranice, 1km gridy domácností, OSM marketing spoty a geocodované zákazníky. Vrstvy lze přepínat v pravém horním rohu.</p>
<div class="map-container">
  <iframe src="vecerkaplus_mapa.html" loading="lazy"></iframe>
</div>
</div>

<!-- ── 14. PRO INVESTORY ─────────────────────────────────────────────── -->
<div class="section" id="investori">
<h2>14. Pro investory — shrnutí</h2>
<p style="color:#bbb;">VečerkaPlus, spuštění 14. 3. 2026 · Frýdek-Místek · noční rozvoz alkoholu a doplňkového zboží · Pá–Ne 22:00–6:00</p>

<div class="kpi-grid" style="margin:24px 0;">
  <div class="kpi"><div class="val pink">{n_objednavek}</div><div class="lbl">Objednávek ({n_weeks_since_launch} týdnů)</div></div>
  <div class="kpi"><div class="val">{fmt_n(trzba_total)} Kč</div><div class="lbl">Celková tržba</div></div>
  <div class="kpi"><div class="val green">{avg_marze_pct} %</div><div class="lbl">Průměrná hrubá marže</div></div>
  <div class="kpi"><div class="val green">{avg_kontribuce:.0f} Kč</div><div class="lbl">Kontribuce/objednávku</div></div>
  <div class="kpi"><div class="val">{fmt_n(hh_iso)}</div><div class="lbl">Domácností v dosahu</div></div>
  <div class="kpi"><div class="val">{round(zone_area_km2)} km²</div><div class="lbl">Plocha rozvozové zóny</div></div>
</div>

<div class="two-col" style="gap:20px;">

<div>
<div class="highlight positive">
<h3 style="color:var(--green);margin-bottom:12px;">✓ Proč ano</h3>
<ul style="padding-left:18px;line-height:1.9;color:#ccc;">
  <li><strong>Nezaplněná mezera.</strong> Přímý noční rozvoz alkoholu v FM neexistuje — Bolt Food ani Wolt tuto kategorii v tomto městě neprovozují.</li>
  <li><strong>Zdravá jednotková ekonomika.</strong> Průměrná kontribuce {avg_kontribuce:.0f} Kč/objednávku při průměrné tržbě {int(trzba_avg)} Kč. Hrubá marže {avg_marze_pct} % je udržitelná.</li>
  <li><strong>Velký adresovatelný trh.</strong> {fmt_n(hh_iso)} domácností v dosahu, z toho {fmt_n(bytu_panelaky)} bytů v panelovém fondu — hustá zástavba ideální pro noční rozvoz.</li>
  <li><strong>Ověřená ochota platit.</strong> Zákazníci platí 39 Kč dopravné bez stížností; průměrná hodnota košíku {int(trzba_avg)} Kč naznačuje prémiové nákupy.</li>
  <li><strong>Nízké provozní náklady.</strong> Přímé náklady na doručení ~{avg_fuel_per_order:.0f} Kč (palivo). Žádný sklad, žádní zaměstnanci, žádný pronájem.</li>
  <li><strong>Stabilizující se trend.</strong> Poslední 3 víkendy konsistentně 1 objednávka/týden — základ pro růst.</li>
  <li><strong>Škálovatelnost.</strong> Přidání druhého řidiče zdvojnásobí kapacitu bez změny infrastruktury.</li>
</ul>
</div>
</div>

<div>
<div class="highlight warn">
<h3 style="color:var(--yellow);margin-bottom:12px;">✗ Proč ne (rizika)</h3>
<ul style="padding-left:18px;line-height:1.9;color:#ccc;">
  <li><strong>Malý dataset.</strong> {n_objednavek} objednávek za {n_weeks_since_launch} týdnů je příliš málo pro spolehlivé závěry o poptávce, retenci ani sezónnosti.</li>
  <li><strong>Nulová retence dat.</strong> Žádná z {n_objednavek} objednávek nepochází od zákazníka, který by objednal podruhé — LTV neznámé.</li>
  <li><strong>Operační single-point-of-failure.</strong> Celý provoz závisí na jednom člověku — nemoc, dovolená nebo jiná práce zastaví rozvoz.</li>
  <li><strong>Geografická koncentrace.</strong> 5 z {n_objednavek} objednávek stále pochází z okruhu 3,3 km od FM; první doručení na 6 km (Žabeň) a 22,3 km (Ostrava) — mimo standardní zónu.</li>
  <li><strong>Regulatorní riziko.</strong> Zákon o prodeji alkoholu, případné licenční změny nebo omezení nočního prodeje.</li>
  <li><strong>Sezónní neznámá.</strong> Provoz od března — letní měsíce ani zimní vrchol ještě neproběhly.</li>
</ul>
</div>
</div>

</div>

<div style="margin-top:24px;">
<h3>Scénáře výnosů při různých úrovních poptávky</h3>
<table>
  <tr>
    <th>Scénář</th>
    <th class="num">Obj./týden</th>
    <th class="num">Tržba/rok</th>
    <th class="num">Kontribuce/rok</th>
    <th class="num">Co by to vyžadovalo</th>
  </tr>
  <tr>
    <td>Aktuální stav</td>
    <td class="num">1</td>
    <td class="num">{fmt_n(int(1 * 52 * trzba_avg))} Kč</td>
    <td class="num">{fmt_n(int(1 * 52 * avg_kontribuce))} Kč</td>
    <td style="color:var(--muted)">Pouze organický provoz</td>
  </tr>
  <tr style="background:var(--bg3);">
    <td><strong>Cílový (6 měs.)</strong></td>
    <td class="num"><strong>3</strong></td>
    <td class="num" style="color:var(--green)"><strong>{fmt_n(int(3 * 52 * trzba_avg))} Kč</strong></td>
    <td class="num" style="color:var(--green)"><strong>{fmt_n(int(3 * 52 * avg_kontribuce))} Kč</strong></td>
    <td>Letákování + sociální sítě</td>
  </tr>
  <tr>
    <td>Růstový (12 měs.)</td>
    <td class="num">7</td>
    <td class="num">{fmt_n(int(7 * 52 * trzba_avg))} Kč</td>
    <td class="num">{fmt_n(int(7 * 52 * avg_kontribuce))} Kč</td>
    <td>2 řidiči + aktivní marketing</td>
  </tr>
</table>
</div>

<div class="highlight" style="margin-top:20px;border-color:var(--cyan);">
  <strong>Klíčová otázka pro investora:</strong> Dokáže VečerkaPlus překonat "cold-start" problém — dostat první zákazníky do fáze opakovaných objednávek a word-of-mouth? Jednotková ekonomika to ospravedlňuje. Největší riziko není marže ani dosah, ale <strong>akvizice zákazníků</strong>. Kapitalová injekce v řádu desítek tisíc Kč by pokryla 3–6 měsíců cíleného marketingu (letáky, sociální sítě, partnerství s podniky) — a výsledek by dal jasnou odpověď.
</div>
</div>


<!-- ── 15. ZÁVĚRY ──────────────────────────────────────────────────────── -->
<div class="section" id="zaver">
<h2>15. Závěry a doporučení</h2>

<h3>Silné stránky</h3>
<p>VečerkaPlus operuje v nezaplněné tržní mezeře — noční rozvoz alkoholu a doplňkového zboží v FM nemá přímého konkurenta. Rozvozová zóna pokrývá <strong>{fmt_n(pop_grid_iso)} obyvatel</strong> v <strong>{fmt_n(hh_iso)} domácnostech</strong>. Průměrná tržba {int(trzba_avg)} Kč na objednávku při přímých nákladech rozvozu ~{round(naklady_total/n_objednavek, 0):.0f} Kč zaručuje zdravou základní marži.</p>

<h3>Klíčové výzvy</h3>
<p>Nízká povědomost trhu — {n_objednavek} objednávek za {n_weeks_since_launch} týdnů provozu naznačuje, že hlavní bariérou není logistika ani dosah, ale <strong>zákaznická akvizice</strong>. Objednávky pokrývají všechny tři provozní noci (Pá/So/Ne). První doručení za 20km zónu (Ostrava, 22,3 km) proběhlo se ztrátou — upozorňuje na nutnost přezkoumat cenu dopravného pro vzdálené doručení.</p>

<h3>Doporučení</h3>
<table>
  <tr><th>#</th><th>Akce</th><th>Dopad</th><th>Obtížnost</th></tr>
  <tr><td>1</td><td>Letákování bytových domů (≥5 podlaží) do 5 km od FM centra — <strong>{fmt_n(bytu_panelaky)} bytů</strong></td><td style="color:var(--green)">Vysoký</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>2</td><td>Partnerství s nočními podniky — QR kódy na stolech v <strong>{spot_counts.get("pub",0) + spot_counts.get("bar",0)}</strong> pubech a barech</td><td style="color:var(--green)">Vysoký</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>3</td><td>Instagram/TikTok cílení na věk 18–35, geolokace FM centrum, aktivní Pá–So 20–00</td><td style="color:var(--green)">Střední</td><td style="color:var(--yellow)">Nízká</td></tr>
  <tr><td>4</td><td>Rozšíření sortimentu o energetické nápoje a snacks — 1 z {n_objednavek} objednávek cílila na tabák+sladkosti</td><td style="color:#ffd740)">Střední</td><td style="color:var(--green)">Nízká</td></tr>
  <tr><td>5</td><td>Práh dopravného zdarma ≥1 000 Kč motivuje zákazníky navyšovat hodnotu košíku — sledovat průměrnou tržbu, zda roste k tomuto prahu</td><td style="color:var(--yellow)">Střední</td><td style="color:var(--green)">Velmi nízká</td></tr>
</table>

<div class="highlight positive" style="margin-top:20px;">
  <strong>Výhled:</strong> Při úspěšné akvizici 1 % domácností z panelového fondu v 5km okruhu (~{fmt_n(int(bytu_panelaky * 0.01 * 0.3))} aktivních zákazníků, průměr 1 objednávka/měsíc) by tržba dosáhla řádu <strong>stovek tisíc Kč ročně</strong> — a to pouze z centra FM bez využití plného 20km dosahu.
</div>
</div>


<!-- ── 16. SKLAD ─────────────────────────────────────────────────────────── -->
<div class="section" id="sklad">
<h2>16. Analýza umístění skladu</h2>

<p>Výběr lokality skladu je hodnocen dle čtyř prostorových kritérií s váhami přizpůsobenými nočnímu rozvozovému byznysu. Výsledek je <strong>skóre 0–10</strong> pro každou kandidátní lokalitu.</p>

<div class="highlight" style="margin-bottom:20px;">
  <strong>Metodika hodnocení</strong><br>
  <span style="color:#bbb">
  Domácnosti ≤ 3 km (30 %) · Nightlife podniky ≤ 3 km (30 %) · Průměrná vzdálenost ke stávajícím zákazníkům (25 %) · Centralita v rozvozové zóně (15 %).
  Bod mimo zónu ≤ 20 km → penalizace −2 body.
  </span>
</div>

{'<p style="color:var(--muted)">Scoring tabulka nebyla nalezena — spusťte nejprve analyze_sklad.py.</p>' if sklad_df is None else f"""
<div class="kpi-grid" style="margin-bottom:24px;">
  <div class="kpi" style="border-color:var(--yellow)">
    <div class="val yellow">#{int(sklad_df.iloc[0]["rank"])} {sklad_df.iloc[0]["id"]}</div>
    <div class="lbl">Doporučená lokalita</div>
    <div style="color:#bbb;font-size:.82rem;margin-top:6px">{sklad_df.iloc[0]["nazev"]}</div>
  </div>
  <div class="kpi">
    <div class="val">{sklad_df.iloc[0]["skore_total"]:.1f}/10</div>
    <div class="lbl">Celkové skóre #1</div>
  </div>
  <div class="kpi">
    <div class="val">{fmt_n(int(sklad_df.iloc[0]["hh_3km"]))}</div>
    <div class="lbl">Domácností ≤ 3 km (#1)</div>
  </div>
  <div class="kpi">
    <div class="val pink">{int(sklad_df.iloc[0]["nightlife_3km"])}</div>
    <div class="lbl">Nightlife podniků ≤ 3 km (#1)</div>
  </div>
</div>

<table>
  <tr>
    <th>#</th><th>ID</th><th>Lokalita</th>
    <th class="num">Domácností ≤ 3 km</th>
    <th class="num">Nightlife ≤ 3 km</th>
    <th class="num">Průměr k zákazníkům</th>
    <th class="num">Skóre</th>
    <th>V zóně</th>
  </tr>
  {_sklad_rows_html}
</table>

<div class="highlight positive" style="margin-top:20px;">
  <strong>Závěr:</strong>
  Optimální oblast pro sklad je pás <strong>{sklad_df.iloc[0]["nazev"].split("(")[0].strip()} ↔ {sklad_df.iloc[1]["nazev"].split("(")[0].strip()}</strong>
  — obě lokality mají prakticky stejné skóre ({sklad_df.iloc[0]["skore_total"]:.1f} vs. {sklad_df.iloc[1]["skore_total"]:.1f}).
  Pokrývá ~{fmt_n(int(sklad_df.iloc[0]["hh_3km"]))} domácností a {int(sklad_df.iloc[0]["nightlife_3km"])} nightlife podniků v dosahu 3 km.
  Průmyslová zóna Chlebovice a okolí Třince jsou nevhodné — buď mimo rozvozovou zónu, nebo příliš vzdálené od zákazníků.
</div>

<p style="margin-top:16px;color:var(--muted);font-size:.88rem;">
  Interaktivní mapa kandidátů: <a href="sklad_analyza.html">sklad_analyza.html</a>
  (heatmapa domácností, nightlife, 3km buffery, těžiště analýzy).
</p>
"""}
</div>

</div><!-- /.container -->

<div class="container">
<div class="footer">
  <div>VečerkaPlus · Prostorová analýza dosahu · {date_last_str}</div>
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

// ── Demografie per zóna ──
new Chart(document.getElementById('chartZoneDemo'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(_chart_zone_labels)},
    datasets: [
      {{ label: '0–14 let',  data: {json.dumps(_chart_vek0)},  backgroundColor: '#37474f', stack: 's' }},
      {{ label: '15–64 let', data: {json.dumps(_chart_vek15)}, backgroundColor: '#29B6F6', stack: 's' }},
      {{ label: '65+ let',   data: {json.dumps(_chart_vek65)}, backgroundColor: '#FF3D9A', stack: 's' }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ color: '#bbb' }} }},
      tooltip: {{ callbacks: {{ label: function(ctx) {{
        var v = ctx.parsed.y;
        return ctx.dataset.label + ': ' + v.toLocaleString('cs-CZ');
      }} }} }}
    }},
    scales: {{
      x: {{ ticks: {{ color: '#bbb' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ stacked: true, ticks: {{ color: '#888', callback: function(v) {{ return (v/1000).toFixed(0) + ' tis.'; }} }}, grid: {{ color: '#1a1a28' }} }}
    }}
  }}
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
// ── Marže dle kategorie ──
new Chart(document.getElementById('chartMarzeKat'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(kat_marze_grp.index))},
    datasets: [{{
      label: 'Průměrná marže %',
      data: {json.dumps(list(kat_marze_grp.values))},
      backgroundColor: {json.dumps(['#00e676' if v >= 50 else '#ffd740' if v >= 30 else '#FF3D9A' for v in kat_marze_grp.values])},
      borderRadius: 2,
    }}]
  }},
  options: {{
    indexAxis: 'y',
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ctx.parsed.x.toFixed(1) + ' %' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888', callback: v => v + ' %' }}, grid: {{ color: '#1a1a28' }}, suggestedMax: 80 }},
      y: {{ ticks: {{ color: '#bbb' }}, grid: {{ display: false }} }}
    }}
  }}
}});

// ── Cenová historie: grouped bar ──
new Chart(document.getElementById('chartCenaHist'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(changed_hist["produkt"]))},
    datasets: [
      {{ label: 'Cena při 1. prodeji', data: {json.dumps(list(changed_hist["cena_launch_kc"].astype(int)))},
         backgroundColor: '#29B6F6', borderRadius: 2 }},
      {{ label: 'Cena aktuální', data: {json.dumps(list(changed_hist["cena_aktualni_kc"].astype(int)))},
         backgroundColor: '#00e676', borderRadius: 2 }}
    ]
  }},
  options: {{
    plugins: {{ legend: {{ labels: {{ color: '#bbb', font: {{ size: 11 }} }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888', maxRotation: 20 }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#888', callback: v => v + ' Kč' }}, grid: {{ color: '#1a1a28' }} }}
    }}
  }}
}});

// ── Predikce tržby: 3 scénáře ──
(function() {{
  const months = {json.dumps(pred_months)};
  const labels = months.map(m => 'M+' + m);
  const scenarios = {json.dumps({name: [round(sc["weekly"] * 4.3 * trzba_avg * (1 + 0.03 * m)) for m in pred_months] for name, sc in scenarios_pred.items()})};
  const colors = {json.dumps({name: sc["color"] for name, sc in scenarios_pred.items()})};
  new Chart(document.getElementById('chartPredikce'), {{
    type: 'line',
    data: {{
      labels,
      datasets: Object.entries(scenarios).map(([name, data]) => ({{
        label: name, data,
        borderColor: colors[name], backgroundColor: colors[name] + '22',
        borderWidth: 2, pointRadius: 3, tension: 0.3, fill: false
      }}))
    }},
    options: {{
      plugins: {{ legend: {{ labels: {{ color: '#bbb', font: {{ size: 11 }} }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
        y: {{ ticks: {{ color: '#888', callback: v => (v/1000).toFixed(0) + ' tis. Kč' }}, grid: {{ color: '#1a1a28' }} }}
      }}
    }}
  }});
}})();

// ── Trend objednávek (týdně) ──
new Chart(document.getElementById('chartTrend'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps([f'T{w}' for w, _ in weeks_data])},
    datasets: [{{
      label: 'Objednávky/týden',
      data: {json.dumps([c for _, c in weeks_data])},
      backgroundColor: {json.dumps(['#00e676' if c > 0 else '#222' for _, c in weeks_data])},
      borderRadius: 2,
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#888' }}, grid: {{ color: '#1a1a28' }} }},
      y: {{ ticks: {{ color: '#888', stepSize: 1 }}, grid: {{ color: '#1a1a28' }}, max: 3 }}
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
