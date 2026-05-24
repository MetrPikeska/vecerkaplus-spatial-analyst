# VečerkaPlus — Delivery Zones: Prostorová analýza

> Kontext pro implementaci `src/lib/delivery-zones.ts` ve vecerkaplus.cz projektu.
> Zdroj dat: repozitář `vecerkaplus-spatial-analyst`, analýza spuštěna 2026-05-24.

---

## Provoz a kritéria

- **Provozní hodiny:** čtvrtek–neděle 22:00–6:00
- **Kurýr:** jeden, základna Frýdek-Místek (49.6754886N, 18.3389397E)
- **Max čas doručení:** 60 min od objednávky = ~10 min příprava + max 45–50 min jízda
- **Origin pro Distance Matrix:** `"Frýdek-Místek, Česká republika"` (shodně s `VecerkaPlus/api/distance.ts`)

---

## Architektura zóny — dva stupně

Whitelist je **pre-filter**. Definitivní check provádí Google Distance Matrix API (stejně jako na vecerkaplus.cz). Zákazník mimo whitelist dostane zamítnutí ještě před voláním Distance Matrix API.

```
Zákazník zadá adresu
  → Google Places API vrátí locality
  → locality v ZONE_PRIMARY? → zobrazit "~30 min, doprava X Kč"
  → locality v ZONE_EXTENDED? → zobrazit "~45 min, doprava Y Kč / na dotaz"
  → jinak → "Mimo rozvozovou zónu"
  → Distance Matrix API provede finální ověření vzdálenosti
```

---

## Metodologie prostorové analýzy

### Datové zdroje
- **Google Distance Matrix API** — driving distance z FM origin ke 1 093 grid bodům (krok 1,5 km, rádius 28 km)
- Cache uložena v `data/google_distance_cache.json` (pokrytí lat 49.44–49.93, lon 17.99–18.74)
- **SLDB 2021** — demografika a polygony obcí (ČSÚ GeoPortál)
- **CRS:** výpočty v EPSG:5514 (S-JTSK), export v EPSG:4326

### Postup přiřazení obce → driving distance
1. Centroid každé obce vypočten v EPSG:5514, převeden do WGS84
2. Centroid přiřazen k nejbližšímu grid bodu v cache (snap chyba ≤ 1,5 km)
3. Driving distance interpolována jako vážený průměr 3 nejbližších bodů

### Poznámka k Google zone polygonu
Soubory `data/google_zone_Xkm.geojson` jsou sestaveny z grid bodů s mřížkovým krokem 1,5 km. **Havířov** má centroid těsně mimo polygon (mezera v mřížce), přestože driving distance = 16,6 km. Centroid-based analýza z cache je přesnější než polygon.

---

## ZONE_PRIMARY — ≤ 20 km driving

**56 obcí | 233 153 obyvatel | ~15–30 min jízdy**

```typescript
export const ZONE_PRIMARY: string[] = [
  // FM a bezprostřední okolí (≤ 10 km)
  "Frýdek-Místek",
  "Staré Město",
  "Dobrá",
  "Sedliště",
  "Sviadnov",
  "Baška",
  "Žabeň",
  "Pazderna",
  "Bruzovice",
  "Nižní Lhoty",
  "Horní Domaslavice",
  "Kaňovice",
  "Staříč",
  "Pržno",
  "Řepiště",
  "Václavovice",
  "Nošovice",
  "Vojkovice",
  "Dolní Tošanovice",

  // 10–15 km
  "Lučina",
  "Janovice",
  "Vyšní Lhoty",
  "Horní Tošanovice",
  "Horní Bludovice",
  "Palkovice",
  "Raškovice",
  "Žermanice",
  "Vratimov",
  "Dobratice",
  "Paskov",
  "Metylovice",
  "Šenov",
  "Frýdlant nad Ostravicí",
  "Hnojník",
  "Fryčovice",
  "Pražmo",
  "Soběšovice",
  "Hukvaldy",
  "Havířov",    // ⚠ 16.6 km — chybí v zone polygonu (chyba mřížky), správně patří sem

  // 15–20 km
  "Střítež",
  "Dolní Domaslavice",
  "Krmelín",
  "Kozlovice",
  "Pstruží",
  "Lhotka",
  "Kateřinice",
  "Smilovice",
  "Třanovice",
  "Brušperk",
  "Vělopolí",
  "Komorní Lhotka",
  "Příbor",
  "Krásná",
  "Malenovice",
  "Trnávka",
  "Petřvald",   // ⚠ viz sekce "Hraniční případy" — dva katastry stejného jména
];
```

---

## ZONE_EXTENDED — 20–30 km driving

**35 obcí | 463 678 obyvatel | ~25–40 min jízdy**

Zákazník vidí delší odhadovaný čas. Vhodné pro příplatek za dopravu nebo zobrazení upozornění.

```typescript
export const ZONE_EXTENDED: string[] = [
  // 20–23 km — přijatelný čas
  "Stará Ves nad Ondřejnicí",  // 20.1 km
  "Skotnice",                   // 20.5 km
  "Ostravice",                  // 21.1 km — horské údolí, jedna silnice
  "Ropice",                     // 21.2 km
  "Tichá",                      // 21.4 km
  "Těrlicko",                   // 21.6 km
  "Horní Suchá",                // 21.9 km
  "Morávka",                    // 22.6 km — ⚠ horská silnice, reálně 30–35 min
  "Ostrava",                    // 23.3 km — ⚠ viz "Hraniční případy"
  "Orlová",                     // 23.6 km
  "Kunčice pod Ondřejníkem",    // 23.7 km
  "Závišice",                   // 24.3 km
  "Libhošť",                    // 24.5 km
  "Řeka",                       // 24.6 km
  "Sedlnice",                   // 24.7 km
  "Český Těšín",                // 24.7 km

  // 25–30 km — počítat s 30–40 min
  "Mošnov",                     // 25.1 km
  "Frenštát pod Radhoštěm",     // 25.3 km
  "Rychvald",                   // 25.4 km
  "Lichnov",                    // 25.5 km
  "Kopřivnice",                 // 25.5 km
  "Albrechtice",                // 25.6 km
  "Doubrava",                   // 26.9 km
  "Čeladná",                    // 26.9 km — ⚠ kopce a zatáčky, reálně 30–35 min
  "Třinec",                     // 27.2 km
  "Jistebník",                  // 27.6 km
  "Bordovice",                  // 28.2 km
  "Chotěbuz",                   // 28.5 km
  "Štramberk",                  // 28.5 km
  "Albrechtičky",               // 29.0 km
  "Vendryně",                   // 29.4 km
  "Rybí",                       // 29.5 km
  "Bartošovice",                // 29.7 km
  "Klimkovice",                 // 29.7 km — rychlé přes D56
];

export const ALL_DELIVERY_MUNICIPALITIES: string[] = [
  ...ZONE_PRIMARY,
  ...ZONE_EXTENDED,
];
```

---

## Hraniční případy — povinné komentáře v kódu

### Ostrava (23.3 km, 282 450 obyv)
Google Places API vrací `locality: "Ostrava"` pro naprostou většinu adres v celém městě. Městské části jako Poruba, Vítkovice, Jih, Slezská Ostrava jsou v API `sublocality`, nikoli samostatná `locality`. **Jeden záznam `"Ostrava"` pokrývá celé město.**

Pokud se v praxi ukáže, že zákazníci z některých čtvrtí mají problémy, přidat:
```typescript
"Ostrava-Poruba", "Ostrava-Jih", "Ostrava-Vítkovice"
```

### Petřvald — duplicitní název
V ČR existují dvě obce jménem "Petřvald":

| Kód SLDB | Lokalita | Driving km | Poblíž |
|---|---|---|---|
| 599085 | Petřvald | 20.0 km | Havířov |
| 599743 | Petřvald | 26.4 km | Nový Jičín / Příbor |

Google Places API může vrátit `"Petřvald"` pro obě. Jeden záznam v poli pokrývá obě — to je žádoucí, obě jsou v zóně. Distance Matrix API provede finální ověření.

### Havířov (16.6 km, 68 153 obyv)
Navzdory driving distance 16,6 km **chybí v `data/google_zone_20km.geojson`** kvůli mezeře v konstrukční mřížce polygonu. Centroid leží těsně mimo polygon. Do `ZONE_PRIMARY` patří.

### Morávka a Čeladná
Obě mají driving distance < 27 km, ale terén způsobuje vyšší reálný čas:
- **Morávka** — horská silnice přes Staré Hamry, úzká, zatáčky → 30–35 min
- **Čeladná** — přístup přes Frýdlant n. O., kopce → 30–35 min

Zařazeny do `ZONE_EXTENDED` záměrně, Distance Matrix API potvrdí.

### Záměrně vynecháno
- **Karviná** (36.5 km, 48 473 obyv) — za hranicí 30 km
- **Nový Jičín** (30.5 km, 22 656 obyv) — těsně za hranicí, lze přidat
- **Studénka** (33.7 km, 8 981 obyv) — za hranicí
- **Opava** (46.8 km) — příliš daleko

---

## Doporučená logika v kódu

```typescript
export function getDeliveryZone(locality: string): "primary" | "extended" | null {
  if (ZONE_PRIMARY.includes(locality)) return "primary";
  if (ZONE_EXTENDED.includes(locality)) return "extended";
  return null;
}

export function isDeliverable(locality: string): boolean {
  return getDeliveryZone(locality) !== null;
}
```

UI pak zobrazí:
- **primary** → "Doručíme do ~30 min"
- **extended** → "Doručíme do ~45 min" (+ případný příplatek)
- **null** → "Mimo rozvozovou zónu"

---

## Statistiky

| Zóna | Obce | Obyvatelé | Driving |
|---|---|---|---|
| ZONE_PRIMARY | 56 | 233 153 | ≤ 20 km |
| ZONE_EXTENDED | 35 | 463 678 | 20–30 km |
| **Celkem** | **91** | **696 831** | ≤ 30 km |

Největší jednotlivé obce v zóně:

| Obec | Obyvatelé | Driving km | Zóna |
|---|---|---|---|
| Ostrava | 282 450 | 23.3 | extended |
| Frýdek-Místek | 53 698 | 3.3 | primary |
| Havířov | 68 153 | 16.6 | primary |
| Třinec | 33 782 | 27.2 | extended |
| Orlová | 27 581 | 23.6 | extended |
| Český Těšín | 23 130 | 24.7 | extended |
| Kopřivnice | 21 019 | 25.5 | extended |
| Frýdlant n. O. | 9 789 | 14.3 | primary |
| Příbor | 8 222 | 18.8 | primary |
| Petřvald | 7 460 | 20.0 | primary |

---

## Jak aktualizovat zónu

Pokud se změní origin (např. sklad místo bytu), nebo se rozšíří provoz:

```bash
# V repozitáři vecerkaplus-spatial-analyst:
python3 build_google_zone.py   # dotáže Google API, aktualizuje cache + GeoJSON
python3 analyze.py             # přepočítá demografiku
```

Cache `data/google_distance_cache.json` pokrývá vzdálenosti až 65 km — zóny 5–35 km lze sestavit bez nových API volání.
