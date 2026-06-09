# VečerkaPlus – prostorová analýza dosahu

Hloubková prostorová a obchodní analýza nočního rozvozu VečerkaPlus (Frýdek-Místek, Pá–Ne 22:00–6:00). Analýza kombinuje reálná data Google Distance Matrix, ČSÚ SLDB 2021, RÚIAN, OSM a skutečné objednávky zákazníků.

## Výsledky (stav 10. 6. 2026)

### Rozvozové zóny

| Zóna | Plocha | Domácností | Odh. obyvatel |
|---|---|---|---|
| Buffer 20 km (vzdušná čára) | 1 255 km² | 232 599 | 551 237 |
| ORS izochróna 20 min autem | 803 km² | 162 894 | 386 042 |
| **Google zóna ≤ 20 km (provozní)** | **630 km²** | **112 145** | **265 783** |
| Google zóna ≤ 30 km | 1 365 km² | 266 351 | 631 251 |
| Google zóna ≤ 35 km | 1 739 km² | 304 272 | 721 124 |

V provozní zóně: 212 restaurací · 85 pubů · 53 fast foodů · 42 kaváren · 35 barů · 43 237 bytů v panelovém fondu.

### Obchodní metriky (7 objednávek, duben–květen 2026)

| Metrika | Hodnota |
|---|---|
| Celková tržba | 3 565 Kč |
| Průměrná tržba / objednávka | 452 Kč |
| Průměrná hrubá marže na zboží | 36,5 % |
| Průměrná vzdálenost doručení | 6,7 km |
| Práh dopravné zdarma | ≥ 1 000 Kč |

### P&L scoring obcí (59 obcí v Google ≤ 20 km zóně)

| Tier | Počet obcí | Kritérium | Příklad |
|---|---|---|---|
| **A – Prioritní** | 14 | ≥ 100 Kč/měs odh. příspěvek | Frýdek-Místek (3 864 Kč), Havířov (1 603 Kč) |
| **B – Výhodné** | 20 | 30–100 Kč/měs | Brušperk, Paskov, Krmelín |
| **C – Marginální** | 25 | < 30 Kč/měs | Malé vesnice < 300 HH |

**Klíčové P&L zjištění:** kurýrský paušál skočí z 120 → 180 Kč na 10 km, ale zákazníkovo dopravné zůstává 39 Kč → čistý příspěvek v 10–20 km pásmu je jen 24 Kč/obj. Zvýšení dopravného na 59 Kč by zlepšilo příspěvek na 44 Kč (+83 %).

## Spuštění

```bash
pip install geopandas folium requests pandas pytest osmnx

python3 analyze.py             # prostorová analýza → output/
python3 analyze_obce.py        # P&L scoring obcí → output/obce_scoring.csv + obce_analyza.html
python3 analyze_network.py     # OSMnx izochróny 5/10/15/20 min → output/network_analyza.html
python3 simulate_monte_carlo.py  # Monte Carlo P&L (5 000 trialů) → output/monte_carlo_summary.json
python3 build_report.py        # HTML report → output/report.html
python3 build_google_zone.py   # přebudovat Google zónu (jen při změně gridu/limitu)
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
| `output/report.html` | Kompletní HTML report (18 sekcí): zóna, výběr obcí, demografie, zástavba, zákazníci, finance, marže, sortiment, cenová historie, predikce, Monte Carlo P&L, síťová dostupnost, marketing, scénáře vzdálenosti, mapa, investor, závěry, sklad |
| `output/obce_analyza.html` | Interaktivní Folium mapa — P&L tier choropleth obcí, popup s P&L rozkladem per obec |
| `output/obce_scoring.csv` | P&L scoring 59 obcí — driving distance, čistý příspěvek/obj, odh. příspěvek/měs, tier |
| `output/network_analyza.html` | Folium mapa s OSMnx izochrónami 5/10/15/20 min jízdy, hustota domácností |
| `output/network_summary.json` | Pokrytí domácností per izochróna vs. Google 20km zóna |
| `output/monte_carlo_summary.json` | P&L percentily (p5/p25/p50/p75/p95) per měsíc per scénář |
| `output/monte_carlo_results.csv` | Vzorkované výsledky simulace (500 trialů × 12 měsíců × 3 scénáře) |
| `output/sensitivity_analysis.csv` | Tornado analýza citlivosti P&L na klíčové parametry |
| `output/vecerkaplus_mapa.html` | Interaktivní Folium mapa — zóny, ZUJ, gridy domácností, zákazníci, marketing spoty |
| `output/sklad_analyza.html` | Scoring 8 kandidátních lokalit skladu |
| `output/scenare_vzdalenosti.csv` | Srovnání 7 scénářů (5–35 km) včetně palivových nákladů |
| `output/obce_v_dosahu.csv` | Obce v bufferu 20 km s demografikou SLDB |
| `output/sklad_scoring.csv` | Scoring lokalit skladu (domácnosti, nightlife, vzdálenost zákazníků) |

## Testy

```bash
python3 -m pytest test_analyze.py -v
```

19 testů pokrývá načítání dat, geometrii zón, prostorové joiny, demografické součty a výstupní soubory.

## Stack

Python 3.13 · GeoPandas · Folium · Shapely · Pandas · Requests · Chart.js · pytest  
Datové zdroje: Google Maps API · ČSÚ SLDB 2021 · RÚIAN (ČÚZK) · OpenStreetMap · ArcČR 4.3 · OpenRouteService
