# VečerkaPlus – prostorová analýza dosahu

Hloubková prostorová a obchodní analýza nočního rozvozu VečerkaPlus (Frýdek-Místek, Pá–Ne 22:00–6:00). Analýza kombinuje reálná data Google Distance Matrix, ČSÚ SLDB 2021, RÚIAN, OSM a skutečné objednávky zákazníků.

## Výsledky (stav 19. 5. 2026)

### Rozvozové zóny

| Zóna | Plocha | Domácností | Odh. obyvatel |
|---|---|---|---|
| Buffer 20 km (vzdušná čára) | 1 255 km² | 232 599 | 551 237 |
| ORS izochróna 20 min autem | 803 km² | 162 894 | 386 042 |
| **Google zóna ≤ 20 km (provozní)** | **630 km²** | **112 145** | **265 783** |
| Google zóna ≤ 30 km | 1 365 km² | 266 351 | 631 251 |
| Google zóna ≤ 35 km | 1 739 km² | 304 272 | 721 124 |

V provozní zóně: 212 restaurací · 85 pubů · 53 fast foodů · 42 kaváren · 35 barů · 43 237 bytů v panelovém fondu.

### Obchodní metriky (5 objednávek, duben–květen 2026)

| Metrika | Hodnota |
|---|---|
| Celková tržba | 2 258 Kč |
| Průměrná tržba / objednávka | 452 Kč |
| Průměrná hrubá marže na zboží | 36,5 % |
| Průměrná kontribuční marže | ~191 Kč/objednávku |
| Průměrná vzdálenost doručení | 2,7 km |
| Práh dopravné zdarma | ≥ 1 000 Kč |

## Spuštění

```bash
pip install geopandas folium requests pandas pytest

python3 analyze.py       # prostorová analýza → output/
python3 build_report.py  # HTML report → output/report.html
python3 -m pytest test_analyze.py -v
```

Palivové parametry jsou nastavitelné přímo v `build_report.py`:

```python
SPOTREBA_L_100KM = 7.0   # spotřeba vozidla l/100 km
CENA_PHM_KC_L    = 42.0  # cena pohonných hmot Kč/l
```

## Datové soubory

| Soubor | Zdroj | Sledován v gitu |
|---|---|---|
| `data/zakaznici.csv` | Reálné objednávky (jméno, GPS, tržba, vzdálenost) | ✓ |
| `data/polozky.csv` | Položky objednávek s prodejní a katalogovou cenou | ✓ |
| `data/nakupni_ceny.csv` | Nákupní ceny z faktur (31 SKU) | ✓ |
| `data/cena_historie.csv` | Cenové změny produktů od spuštění | ✓ |
| `data/products_rows.csv` | Produktový katalog ze Supabase (36 SKU) | ✓ |
| `data/google_zone_{5,10,15,20,25,30,35}km.geojson` | Google Distance Matrix zóny | ✓ |
| `data/marketing-spots-fm.gpkg` | OSM restaurace, puby, bary, zastávky | ✓ |
| `data/isochrone_20min.geojson` | ORS izochróna 20 min autem (srovnávací) | ✓ |
| `data/google_distance_cache.json` | Cache 1 093 API volání, vzdálenosti do 65 km | ✗ |
| `data/gridy_domacnosti/` | ČSÚ SLDB 2021 — 1km grid domácností | ✗ |
| `data/obce_sldb/` | ČSÚ SLDB 2021 — demografika obcí | ✗ |
| `data/ruian_budovy_fm.gpkg` | RÚIAN budovy FM (počet bytů, podlaží) | ✗ |

Soubory bez git sledování je třeba stáhnout nebo vygenerovat lokálně — viz `CLAUDE.md`.

## Výstupy

| Soubor | Obsah |
|---|---|
| `output/report.html` | Kompletní HTML report (15 sekcí): zóna, demografie, zástavba, zákazníci, finance, marže, sortiment, cenová historie, predikce, marketing, scénáře vzdálenosti, mapa, investor, závěry |
| `output/vecerkaplus_mapa.html` | Interaktivní Folium mapa — zóny, ZUJ, gridy domácností, zákazníci, marketing spoty |
| `output/scenare_vzdalenosti.csv` | Srovnání 7 scénářů (5–35 km) včetně palivových nákladů |
| `output/obce_v_dosahu.csv` | Obce v bufferu 20 km s demografikou SLDB |
| `output/google_grid_distances.csv` | Vzdálenosti všech 1 093 grid bodů |

## Testy

```bash
python3 -m pytest test_analyze.py -v
```

19 testů pokrývá načítání dat, geometrii zón, prostorové joiny, demografické součty a výstupní soubory.

## Stack

Python 3.13 · GeoPandas · Folium · Shapely · Pandas · Requests · Chart.js · pytest  
Datové zdroje: Google Maps API · ČSÚ SLDB 2021 · RÚIAN (ČÚZK) · OpenStreetMap · ArcČR 4.3 · OpenRouteService
