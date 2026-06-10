# VečerkaPlus — analytické shrnutí

Zpracováno: 2026-06-10 · základ: 5 reálných objednávek (duben–červen 2026)

---

## Soubory

| Soubor | Obsah |
|---|---|
| `network_analyza.html` | Interaktivní mapa — OSMnx izochróny + Google 20 km zóna |
| `network_summary.json` | Pokrytí domácností dle izochróny (5/10/15/20 min jízdy) |
| `osm_isochrones.geojson` | GeoJSON polygony izochróny (EPSG:4326) |
| `monte_carlo_summary.json` | P&L percentily (p5–p95) po měsících, 3 scénáře × 5 000 iterací |
| `monte_carlo_results.csv` | Surová Monte Carlo data — iterace × měsíce |
| `sensitivity_analysis.csv` | Tornádo analýza — vliv ±30 % každého parametru na p50 |
| `zone_scenarios.html` | Interaktivní mapa — 400 náhodných adres per zóna + P&L tabulka |
| `zone_scenarios.json` | P&L per zóna × scénář (roční p5/p25/p50/p75/p95) |
| `zone_distances.csv` | Empirická distribuce jízdních vzdáleností per zóna |
| `obce_scoring.csv` | Scoring 59 obcí — vzdálenost, HH, marže, nightlife, tier |

---

## 1. Provozní realita (5 objednávek)

| Metrika | Hodnota |
|---|---|
| Průměrná tržba / objednávka | 452 Kč |
| Průměrná hrubá marže | 36.5 % (gross 165 Kč) |
| Průměrná vzdálenost doručení | 2.7 km |
| Kurýrní náklad / doručení | 120 Kč (všechny objednávky ≤ 10 km) |
| Čistý příspěvek / objednávku | ~84 Kč |
| Palivové náklady / doručení | ~16 Kč |

Produktový mix dle marže: snacky ~75 % · soft drinky ~56 % · lihoviny ~48 % · tabák ~17 %.

---

## 2. Síťová dostupnost (OSMnx izochróny)

Počítáno z bydliště řidiče (FM) přes reálnou silniční síť. Reference: Google zóna ≤ 20 km = 130 264 domácností.

| Čas jízdy | Plocha | Domácností | % Google zóny |
|---|---|---|---|
| 5 min | 22.6 km² | 23 974 | 18 % |
| 10 min | 167.3 km² | 49 171 | 38 % |
| **15 min** | **532.1 km²** | **140 271** | **108 %** |
| 20 min | 923.0 km² | 254 387 | 195 % |

Izochróna 15 min silniční sítí pokrývá celou provozní Google zónu — reálný dostupnostní práh pro doručení do 75 min.

---

## 3. P&L dle šířky rozvozové zóny

400 náhodných adres per zóna, jízdní vzdálenosti přes Dijkstra na OSM grafu. Monte Carlo 5 000 iterací × 12 měsíců.

### Proč na vzdálenosti záleží

| Pásmo | Kurýr paušál | Dopravné zákazník | Net / objednávku |
|---|---|---|---|
| ≤ 10 km | 120 Kč | 39 Kč | **84 Kč** |
| 10–20 km | 180 Kč | 39 Kč | **24 Kč** |
| > 20 km | 250 Kč | 164 Kč | **79 Kč** |

Rozšíření z 5 km na 20 km zónu sníží roční P50 o ~47 %, přestože zákazník platí stejných 39 Kč.

### Roční P50 zisku dle zóny (Kč)

| Scénář | λ obj/týden | 5 km | 10 km | 15 km | 20 km |
|---|---|---|---|---|---|
| Konzervativní | 1 | 4 359 | 3 859 | 2 797 | 2 328 |
| Cílový | 3 | 13 094 | 11 604 | 8 466 | 7 032 |
| Optimistický | 7 | 30 622 | 27 070 | 19 830 | 16 389 |

---

## 4. Tornádo analýza — největší páky zisku

Vliv ±30 % změny parametru na roční P50 (cílový scénář, λ = 3/týden):

| Parametr | Základní hodnota | Swing ± Kč/rok |
|---|---|---|
| Hrubá marže | 36.5 % | ±15 478 |
| Průměrná tržba / obj | 452 Kč | ±14 540 |
| Kurýr paušál 10–20 km | 180 Kč | ±4 808 |
| Dopravné zákazníka | 39 Kč | ±3 566 |
| Průměrná vzdálenost | 6.7 km | ±1 758 |

Marže a průměrná hodnota košíku dohromady tvoří ~65 % celkové citlivosti. Vzdálenost je nejméně ovlivnitelná.

---

## 5. Doporučení k obcím a zónám

### Ostrava — nevypláci se ze současné základny

Z FM je Ostrava ~30–35 km jízdní vzdálenosti → kurýrní paušál 250 Kč.

```
gross = 452 × 36.5 % = 165 Kč
+ dopravné zákazník (aktuálně 39 Kč)
− kurýr 250 Kč
──────────────────
čistý P&L = −46 Kč / objednávku
```

Každá objednávka z Ostravy za aktuálních podmínek prodělává. Možnosti:
- **Suspend** — dokud nebude druhý řidič přímo v Ostravě
- **Vlastní zóna** — min. objednávka 800 Kč + dopravné 119 Kč → net = +161 Kč

### Obce k ponechání

**Jádro ≤ 10 km (net 84 Kč/obj) — ponechat vše:**
FM, Dobrá, Staré Město, Sviadnov, Baška, Staříč, Žabeň, Bruzovice, Horní Domaslavice, Pržno, Nošovice, Sedliště, Pazderna, Nižní Lhoty

**Střední pásmo 10–20 km (net 24 Kč/obj) — jen velká sídla:**

| Obec | Vzdálenost | Domácností | Měs. příspěvek |
|---|---|---|---|
| Havířov | 16.8 km | 33 388 | 1 603 Kč |
| Frýdlant nad Ostravicí | 14.5 km | 3 936 | 190 Kč |
| Příbor | 19.2 km | 3 423 | 163 Kč |
| Petřvald | 19.2 km | 2 815 | 134 Kč |
| Šenov | 14.1 km | 2 439 | 118 Kč |
| Vratimov | 12.9 km | 2 881 | 139 Kč |

### Obce k vyřazení (~20 malých vesnic)

Tier C, méně než 400 domácností, vzdálenost > 12 km — realisticky 0–1 objednávek za měsíc:

Pstruží · Kateřinice · Vojkovice · Hnojník · Horní Tošanovice · Lhotka · Soběšovice · Pražmo · Malenovice · Vyšní Lhoty · Dolní Tošanovice · Žermanice · Kaňovice · Třanovice · Smilovice · Komorní Lhotka · Dobratice · Střítež · Metylovice · Vělopolí

Z webu navíc bez scoring dat (pravděpodobně > 20 km — ověřit): Čeladná · Lichnov · Jistebník · Mošnov · Sedlnice · Petřvald u Nového Jičína · Trojanovice · Bordovice · Ostravice

### Dopravné — přejít na vzdálenostní pásma

Aktuální flat 39 Kč do 20 km nekryje nárůst kurýrního nákladu. Navrhovaná struktura:

| Vzdálenost | Dopravné | Zdarma od |
|---|---|---|
| ≤ 8 km | 39 Kč | 1 000 Kč |
| 8–15 km | 69 Kč | 1 000 Kč |
| 15–20 km | 99 Kč | 1 200 Kč |
| > 20 km | 149 Kč | 1 500 Kč |

Efekt: Havířov (17 km) se po přenastavení dostane z 24 Kč na ~84 Kč net/objednávku — srovnatelné s jádrem.

---

## 6. Prioritní kroky

| Priorita | Akce | Dopad |
|---|---|---|
| 🔴 1 | Vypnout Ostravu nebo nastavit vlastní podmínky | Zastavit ztrátu na každé objednávce |
| 🔴 2 | Implementovat vzdálenostní dopravné (4 pásma) | +60 Kč net na každé doručení do Havířova |
| 🟡 3 | Vyřadit ~20 Tier C vesnic z webu a appky | Čistší zóna, méně edge cases |
| 🟡 4 | Zaměřit marketing na FM (5 km okruh) | Nejlepší ekonomika, nejkratší doručení |
| 🟢 5 | Zvýšit průměrnou hodnotu košíku (upsell, doporučení) | Největší páka na celkový zisk |

---

*Analýza: OSMnx · Dijkstra · Monte Carlo 5 000 iterací · ČSÚ SLDB 2021 grid domácností · Google Distance Matrix*
