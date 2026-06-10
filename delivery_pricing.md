# Delivery Pricing — VečerkaPlus

> Edituj tuto tabulku a pak ručně synchronizuj hodnoty do souborů níže.

## Zóny a ceník

| Zóna | Prstenec | Dopravné | Min. objednávka | Dopravné zdarma od |
|------|----------|----------|-----------------|---------------------|
| 1    | 0–5 km   | 39 Kč    | 500 Kč          | 1 000 Kč            |
| 2    | 5–10 km  | 69 Kč    | 500 Kč          | 1 000 Kč            |
| 3    | 10–15 km | 99 Kč    | 700 Kč          | 1 200 Kč            |
| 4    | 15–20 km | 149 Kč   | 700 Kč          | 1 500 Kč            |

## ETA odhady (kurýr)

| Zóna | Od  | Do  |
|------|-----|-----|
| 0–5 km   | 20 min | 35 min |
| 5–10 km  | 25 min | 45 min |
| 10–15 km | 35 min | 55 min |
| 15–20 km | 45 min | 70 min |

## Ekonomika (informativně, nemění se v kódu)

Kurýrní paušál: 120 Kč/obj pro zóny 1–2, 180 Kč/obj pro zóny 3–4.

| Prstenec | Dopravné | Kurýr/obj | Hrubá marže | **Příspěvek/obj** |
|----------|----------|-----------|-------------|-------------------|
| 0–5 km   | 39 Kč    | 120 Kč    | 165 Kč      | **84 Kč**         |
| 5–10 km  | 69 Kč    | 120 Kč    | 165 Kč      | **114 Kč**        |
| 10–15 km | 99 Kč    | 180 Kč    | 165 Kč      | **84 Kč**         |
| 15–20 km | 149 Kč   | 180 Kč    | 165 Kč      | **134 Kč**        |

---

## Kde aktualizovat

### 1. VečerkaPlus app — zóny a poplatky

**Soubor:** `VecerkaPlus/src/lib/delivery-zones.ts`

```ts
export const DELIVERY_TIERS: DeliveryTier[] = [
  { maxKm: 5,  fee: 39,  etaMin: 20, etaMax: 35, label: "do 5 km"   },
  { maxKm: 10, fee: 69,  etaMin: 25, etaMax: 45, label: "5–10 km"   },
  { maxKm: 15, fee: 99,  etaMin: 35, etaMax: 55, label: "10–15 km"  },
  { maxKm: 20, fee: 149, etaMin: 45, etaMax: 70, label: "15–20 km"  },
];
```

**Práhy dopravného zdarma a min. objednávky:**

```ts
export function getFreeDeliveryThreshold(km: number | null): number {
  if (km === null) return 1000;
  if (km <= 10) return 1000;
  if (km <= 15) return 1200;
  return 1500;
}

export function getMinOrder(km: number | null): number {
  if (km === null || km <= 10) return 500;
  return 700;
}
```

### 2. Spatial analyst — P&L model

**Soubor:** `analyze_obce.py` (kurýrní paušál)

```python
COURIER_FEE_Z1 = 120  # Kč, ≤10 km
COURIER_FEE_Z2 = 180  # Kč, 10–20 km
DELIVERY_FEE_Z12 = 39  # ← aktualizuj na správnou výchozí hodnotu pokud měníš
```

**Soubor:** `build_zone_policy.py` a `build_report.py` (blok `_POLICY_ZONES`)

```python
_POLICY_ZONES = [
    {"km": 5,  "ring": "0–5 km",   "fee": 39,  "free_from": 1000, "min_order": 500,  "courier": 120, ...},
    {"km": 10, "ring": "5–10 km",  "fee": 69,  "free_from": 1000, "min_order": 500,  "courier": 120, ...},
    {"km": 15, "ring": "10–15 km", "fee": 99,  "free_from": 1200, "min_order": 700,  "courier": 180, ...},
    {"km": 20, "ring": "15–20 km", "fee": 149, "free_from": 1500, "min_order": 700,  "courier": 180, ...},
]
```

### 3. Testy

**Soubor:** `VecerkaPlus/src/lib/checkout-logic.test.ts`

Po změně hranic nebo poplatků aktualizuj testovací případy pro `calcDeliveryFee` a `canSubmitOrder`.

Po změně spusť:
```bash
cd VecerkaPlus && npm test
```

---

## Rozvozová politika — doporučení

| Prstenec | Status | Kdy obsloužit |
|----------|--------|---------------|
| 0–5 km   | ✅ Aktivně | Vždy, agresivní propagace |
| 5–10 km  | ✅ Aktivně | Vždy — nejlepší marže (114 Kč/obj) |
| 10–15 km | ⚠️ Podmínečně | Jen urbanizovaná sídla (Frýdlant n.O., Petřvald, Brušperk), pokud není vytíženost v 0–10 km |
| 15–20 km | 🔶 Prémium | Pouze objednávky ≥ 1 500 Kč, bez jiné zakázky |
