# CLAUDE.md

Prostorová analýza dosahu rozvozu VečerkaPlus (FM, Pá–Ne 22–6).

## Spuštění

```bash
python3 analyze.py           # hlavní analýza → output/
python3 analyze_obce.py      # P&L scoring obcí → output/obce_scoring.csv + obce_analyza.html
python3 build_report.py      # HTML report → output/report.html
python3 build_google_zone.py # přebudovat Google zónu (volat jen při změně gridu/limitu)
python3 -m pytest test_analyze.py -v
```

## Stack

Python 3.13 · GeoPandas 1.1 · Folium 0.20 · Pandas 3.0 · Shapely · Requests · pytest

## Klíčové konstanty (analyze.py)

```python
FM_LAT, FM_LON = 49.6754886, 18.3389397  # byt řidiče (výchozí bod)
BUFFER_DIST_M  = 20_000                   # 20 km vzdušná čára
CRS_METRIC     = "EPSG:5514"              # S-JTSK pro výpočty vzdáleností
AVG_HH_SIZE    = 2.37                     # průměr ČR SLDB 2021
ARCCR_GDB      = "/media/petr-mikeska/8A9A950B9A94F4C3/Skola/DATA/ČR/arcčr_4_3.gdb"
```

## Klíčové konstanty (build_report.py)

```python
SPOTREBA_L_100KM    = 7.0     # spotřeba vozidla l/100 km (nastavitelné)
CENA_PHM_KC_L       = 42.0    # cena pohonných hmot Kč/l (nastavitelné)
DOPRAVNE_ZDARMA_KC  = 1000    # práh pro dopravné zdarma
```

## Datové soubory

| Soubor | Popis | Sledován v gitu |
|---|---|---|
| `data/marketing-spots-fm.gpkg` | OSM bary, restaurace, zastávky (EPSG:4326) | ✓ |
| `data/zakaznici.csv` | Objednávky — jméno, telefon, adresa, GPS, tržba, dopravné, vzdálenost | ✓ |
| `data/polozky.csv` | Položky objednávek s cenou v době prodeje a cenou v katalogu | ✓ |
| `data/nakupni_ceny.csv` | Nákupní ceny z faktur (31 SKU) | ✓ |
| `data/cena_historie.csv` | Cenové změny produktů od spuštění (odvozeno z emailů vs. katalog) | ✓ |
| `data/products_rows.csv` | Produktový katalog ze Supabase (36 SKU, aktuální prodejní ceny) | ✓ |
| `data/isochrone_20min.geojson` | ORS izochróna 20 min autem (srovnávací) | ✓ |
| `data/google_zone_5km.geojson` | Google Distance Matrix zóna ≤ 5 km | ✓ |
| `data/google_zone_10km.geojson` | Google Distance Matrix zóna ≤ 10 km | ✓ |
| `data/google_zone_15km.geojson` | Google Distance Matrix zóna ≤ 15 km | ✓ |
| `data/google_zone_20km.geojson` | **Provozní rozvozová zóna** ≤ 20 km | ✓ |
| `data/google_zone_25km.geojson` | Google Distance Matrix zóna ≤ 25 km | ✓ |
| `data/google_zone_30km.geojson` | Google Distance Matrix zóna ≤ 30 km | ✓ |
| `data/google_zone_35km.geojson` | Google Distance Matrix zóna ≤ 35 km | ✓ |
| `data/google_distance_cache.json` | Cache API volání — 1 093 bodů, vzdálenosti až 65 km (generovat lokálně) | ✗ |
| `data/obce_sldb/` | ČSÚ SLDB 2021 — demografika obcí (stáhnout ručně) | ✗ |
| `data/gridy_domacnosti/` | ČSÚ SLDB 2021 — 1km grid domácností (stáhnout ručně) | ✗ |
| `data/ruian_budovy_fm.gpkg` | RÚIAN budovy FM — počet bytů, podlaží, typ (generovat lokálně) | ✗ |
| `projekt.qgz` | QGIS projekt | ✓ |

ArcČR 4.3 GDB je na externím disku — vrstva `ZUJ` (základní územní jednotky).

## Rozvozová zóna

Zóna je definována jako **driving distance ≤ 20 km** z origin `"Frýdek-Místek, Česká republika"` přes Google Distance Matrix API — **shodně s vecerkaplus.cz** (viz `VecerkaPlus/api/distance.ts` a `App.tsx` řádek 698).

`build_google_zone.py` dotáže grid 1 093 bodů (1.5 km krok, 28 km rádius) a sestaví polygon. Cache pokrývá vzdálenosti až 65 km — zóny 5–35 km lze sestavit bez nových API volání. Výsledek cachuje do `data/google_distance_cache.json`.

## API klíče

| Klíč | Kde | Poznámka |
|---|---|---|
| Google Maps | `VecerkaPlus/.env.local` → `VITE_GOOGLE_MAPS_API_KEY` | Geocoding + Distance Matrix |
| ORS | env `ORS_API_KEY` | Pouze srovnávací izochróna |

## Výstupy (output/)

| Soubor | Obsah |
|---|---|
| `report.html` | Kompletní HTML report (15 sekcí) — mapa, demografie, marže, scénáře, predikce, investor |
| `vecerkaplus_mapa.html` | Interaktivní Folium mapa — zóny, ZUJ, gridy, zákazníci, spoty |
| `scenare_vzdalenosti.csv` | Srovnání 7 scénářů (5–35 km) — obyvatelé, domácnosti, byty, nightlife, palivo |
| `obce_v_dosahu.csv` | Obce v bufferu 20 km s demografikou SLDB |
| `marketing_spots_kategorie.csv` | Počty spotů dle kategorie |
| `souhrn.csv` | Souhrnné metriky |
| `google_grid_distances.csv` | Vzdálenosti všech 1 093 grid bodů |
| `zuj_v_dosahu.gpkg` | ZUJ polygony v bufferu (pro QGIS) |

## Výsledky (naposledy spuštěno 2026-05-19)

### Rozvozové zóny

| Zóna | Plocha | Domácností | Odh. obyvatel |
|---|---|---|---|
| Buffer 20 km (vzdušná) | 1 255 km² | 232 599 | 551 237 |
| ORS izochróna 20 min | 803 km² | 162 894 | 386 042 |
| **Google zóna ≤ 20 km** | **630 km²** | **112 145** | **265 783** |
| Google zóna ≤ 30 km | 1 365 km² | 266 351 | 631 251 |
| Google zóna ≤ 35 km | 1 739 km² | 304 272 | 721 124 |

V Google zóně ≤ 20 km: 212 restaurací · 85 pubů · 53 fast foodů · 42 kaváren · 35 barů.

### Obchodní metriky (5 objednávek, duben–květen 2026)

| Metrika | Hodnota |
|---|---|
| Celková tržba | 2 258 Kč |
| Průměrná tržba / objednávka | 452 Kč |
| Průměrná hrubá marže | 36,5 % |
| Průměrná kontribuční marže | ~191 Kč/objednávku |
| Průměrná vzdálenost doručení | 2,7 km |
| Palivové náklady / doručení | ~16 Kč (7 l/100 km × 42 Kč/l) |
| Práh dopravné zdarma | ≥ 1 000 Kč |

### Maržová analýza (prodané produkty)

| Kategorie | Průměrná marže |
|---|---|
| Snacky | ~75 % |
| Soft drinky | ~56 % |
| Lihoviny | ~48 % |
| Víno | neznámá (nákupní cena chybí) |
| Tabák | ~17 % |

## Stažení chybějících dat

```bash
# 1km grid domácností (ČSÚ GIS portál)
wget "https://geodata.csu.gov.cz/as/data/distribuce/Hosted/Gridy_SLDB2021/FeatureServer/3/gpkg.zip" \
     -O data/gridy_domacnosti.zip && unzip data/gridy_domacnosti.zip -d data/gridy_domacnosti/

# SLDB obce — stáhnout ručně z geodata.csu.gov.cz → uložit do data/obce_sldb/

# RÚIAN budovy FM — vygenerovat skriptem (načítá z ČÚZK AGS REST API)
python3 analyze.py  # sekce RÚIAN uloží data/ruian_budovy_fm.gpkg
```
