# VečerkaPlus – prostorová analýza dosahu

Prostorová analýza dosahu nočního rozvozu VečerkaPlus (Frýdek-Místek, Pá–Ne 22–6).

## Výsledky

| Zóna | Plocha | Domácností | Odh. obyvatel |
|---|---|---|---|
| Buffer 20 km | 1 255 km² | 232 599 | 551 237 |
| Izochróna 20 min autem | 803 km² | 162 894 | 386 042 |

**Výchozí bod:** byt řidiče (49.6755°N, 18.3389°E)

Marketing spoty v dosahu izochrony: 202 restaurací · 106 pubů · 55 fast foodů · 38 kaváren · 32 barů.

## Spuštění

```bash
pip install geopandas folium requests pandas pytest

# Volitelně pro stažení nové izochrony:
export ORS_API_KEY='...'   # https://openrouteservice.org/dev

python3 analyze.py
```

Výstupy se uloží do `/output/`.

## Data

| Soubor | Zdroj | Popis |
|---|---|---|
| `data/obce_sldb/` | ČSÚ SLDB 2021 | Polygony obcí + demografika (obyvatelstvo, věk) |
| `data/marketing-spots-fm.gpkg` | OpenStreetMap | Restaurace, puby, fast food, zastávky aj. |
| `data/gridy_domacnosti/` | ČSÚ SLDB 2021 | Domácnosti za 1km čtvercové gridy |
| `data/isochrone_20min.geojson` | OpenRouteService | Izochróna 20 min autem (cached) |

## Výstupy

| Soubor | Obsah |
|---|---|
| `output/vecerkaplus_mapa.html` | Interaktivní folium mapa (choropleth obcí, grid hustota, spoty) |
| `output/obce_v_dosahu.csv` | 82 obcí s demografikou |
| `output/marketing_spots_kategorie.csv` | Počty spotů dle kategorie (buffer vs. izochróna) |
| `output/souhrn.csv` | Souhrnná tabulka metrik |

## Testy

```bash
python3 -m pytest test_analyze.py -v
```

16 testů pokrývá načítání dat, geometrii bufferu, prostorové joiny a výstupní soubory.

## Stack

Python · GeoPandas · Folium · OpenRouteService API · ČSÚ GIS Portál
