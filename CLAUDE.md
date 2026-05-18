# CLAUDE.md

Prostorová analýza dosahu rozvozu VečerkaPlus (FM, Pá–Ne 22–6).

## Spuštění

```bash
python3 analyze.py           # hlavní analýza → output/
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

## Datové soubory

| Soubor | Popis | Sledován v gitu |
|---|---|---|
| `data/marketing-spots-fm.gpkg` | OSM bary, restaurace, zastávky (EPSG:4326) | ✓ |
| `data/zakaznici.csv` | Reálné adresy zákazníků geocodované přes Google | ✓ |
| `data/isochrone_20min.geojson` | ORS izochróna 20 min autem (srovnávací) | ✓ |
| `data/google_zone_20km.geojson` | **Reálná rozvozová zóna** — Google Distance Matrix ≤ 20 km | ✓ |
| `data/google_distance_cache.json` | Cache API volání (generovat lokálně) | ✗ |
| `data/obce_sldb/` | ČSÚ SLDB 2021 — demografika obcí (stáhnout ručně) | ✗ |
| `data/gridy_domacnosti/` | ČSÚ SLDB 2021 — 1km grid domácností (stáhnout ručně) | ✗ |
| `projekt.qgz` | QGIS projekt | ✓ |

ArcČR 4.3 GDB je na externím disku — vrstva `ZUJ` (základní územní jednotky).

## Rozvozová zóna

Zóna je definována jako **driving distance ≤ 20 km** z origin `"Frýdek-Místek, Česká republika"` přes Google Distance Matrix API — **shodně s vecerkaplus.cz** (viz `VecerkaPlus/api/distance.ts` a `App.tsx` řádek 698).

`build_google_zone.py` dotáže grid 1 093 bodů (1.5 km krok, 28 km rádius) a sestaví polygon. Výsledek cachuje do `data/google_distance_cache.json` — při opětovném spuštění přeskočí již dotázané body.

## API klíče

| Klíč | Kde | Poznámka |
|---|---|---|
| Google Maps | `VecerkaPlus/.env.local` → `VITE_GOOGLE_MAPS_API_KEY` | Geocoding + Distance Matrix |
| ORS | env `ORS_API_KEY` | Pouze srovnávací izochróna |

## Výstupy (output/)

| Soubor | Obsah |
|---|---|
| `vecerkaplus_mapa.html` | Interaktivní mapa — Google zóna, buffer, ZUJ, gridy, zákazníci, spoty |
| `obce_v_dosahu.csv` | Obce v bufferu 20 km s demografikou SLDB |
| `marketing_spots_kategorie.csv` | Počty spotů dle kategorie — buffer vs. Google zóna |
| `souhrn.csv` | Souhrnné metriky |
| `google_grid_distances.csv` | Vzdálenosti všech grid bodů |
| `zuj_v_dosahu.gpkg` | ZUJ polygony v bufferu (pro QGIS) |

## Výsledky (naposledy spuštěno 2026-05-18)

| Zóna | Plocha | Domácností | Odh. obyvatel |
|---|---|---|---|
| Buffer 20 km (vzdušná) | 1 255 km² | 232 599 | 551 237 |
| ORS izochróna 20 min | 803 km² | 162 894 | 386 042 |
| **Google zóna ≤ 20 km** | **630 km²** | **112 145** | **265 770** |

V Google zóně: 212 restaurací · 85 pubů · 53 fast foodů · 42 kaváren · 35 barů.

## Stažení chybějících dat

```bash
# 1km grid domácností (ČSÚ GIS portál)
wget "https://geodata.csu.gov.cz/as/data/distribuce/Hosted/Gridy_SLDB2021/FeatureServer/3/gpkg.zip" \
     -O data/gridy_domacnosti.zip && unzip data/gridy_domacnosti.zip -d data/gridy_domacnosti/

# SLDB obce — stáhnout ručně z geodata.csu.gov.cz → uložit do data/obce_sldb/
```
