// delivery-zones.ts — point-in-polygon lookup pro rozvozové zóny VečerkaPlus
// Závislosti: @turf/boolean-point-in-polygon @turf/helpers
// GeoJSON: data/delivery_zones_simplified.geojson (zkopírovat do public/ nebo assets/)

import booleanPointInPolygon from "@turf/boolean-point-in-polygon";
import { point } from "@turf/helpers";
import type { Feature, Polygon, MultiPolygon } from "geojson";
import zonesGeoJson from "./delivery_zones_simplified.geojson";

export interface DeliveryZone {
  zone_km: number;
  label: string;
  delivery_fee: number;   // Kč
  free_from: number;      // Kč — dopravné zdarma od této částky
  min_order: number;      // Kč — minimální objednávka
  description: string;
}

export function getDeliveryZone(lat: number, lon: number): DeliveryZone | null {
  const pt = point([lon, lat]);
  // Zóny jsou seřazeny od nejmenší (5 km) — vrátíme první shodu
  const feature = (zonesGeoJson.features as Feature<Polygon | MultiPolygon, DeliveryZone>[])
    .find((f) => booleanPointInPolygon(pt, f));
  return feature?.properties ?? null;
}

export function calcDeliveryFee(lat: number, lon: number, orderValue: number): {
  fee: number;
  zone: DeliveryZone | null;
  served: boolean;
} {
  const zone = getDeliveryZone(lat, lon);
  if (!zone) return { fee: 0, zone: null, served: false };
  const fee = orderValue >= zone.free_from ? 0 : zone.delivery_fee;
  return { fee, zone, served: true };
}
