import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { FilterState, MapData, EMPTY_FILTERS } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export function formatTime(date: Date): string {
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** Format an ISO date string as e.g. "14 Mar 2024"; tolerant of bad/NaT. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso || iso === "NaT" || iso === "Unknown") return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** Format a signed latitude as "15.32° N". */
export function formatLat(lat: number | null | undefined): string {
  if (typeof lat !== "number" || isNaN(lat)) return "—";
  return `${Math.abs(lat).toFixed(2)}° ${lat >= 0 ? "N" : "S"}`;
}

/** Format a signed longitude as "73.10° E". */
export function formatLon(lon: number | null | undefined): string {
  if (typeof lon !== "number" || isNaN(lon)) return "—";
  return `${Math.abs(lon).toFixed(2)}° ${lon >= 0 ? "E" : "W"}`;
}

/** Title-case a region_tag like "arabian_sea" -> "Arabian Sea". */
export function prettyRegion(tag: string | null | undefined): string {
  if (!tag) return "—";
  return tag.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Apply the scientific sidebar filters to a list of map markers.
 * Filtering is client-side over the latest mapData. A marker passes when it
 * satisfies every active (non-empty) filter dimension. Empty dimensions pass
 * all markers, so this composes cleanly.
 */
export function applyFilters(markers: MapData[], filters: FilterState): MapData[] {
  const has = (arr: string[]) => arr.length > 0;
  return markers.filter((m) => {
    if (filters.region) {
      // Region not carried on MapData; matched via the query that produced
      // markers. When a region filter is active we cannot drop markers
      // reliably, so we leave region to query-time and do not filter here.
    }
    if (has(filters.networks)) {
      const net = (m.network || "Core Argo").toLowerCase();
      if (!filters.networks.some((n) => n.toLowerCase() === net)) return false;
    }
    if (has(filters.dacs)) {
      const dac = (m.dac || "").toLowerCase();
      if (!filters.dacs.some((d) => d.toLowerCase() === dac || dac.includes(d.toLowerCase())))
        return false;
    }
    if (has(filters.variables)) {
      const vars = (m.variables || []).map((v) => v.toUpperCase());
      if (!filters.variables.some((v) => vars.includes(v.toUpperCase()))) return false;
    }
    if (has(filters.statuses)) {
      const st = (m.status || "unknown").toLowerCase();
      if (!filters.statuses.some((s) => s.toLowerCase() === st)) return false;
    }
    if (filters.dateFrom || filters.dateTo) {
      const t = m.profile_date ? new Date(m.profile_date).getTime() : NaN;
      if (isNaN(t)) return false;
      if (filters.dateFrom && t < new Date(filters.dateFrom).getTime()) return false;
      if (filters.dateTo && t > new Date(filters.dateTo + "T23:59:59").getTime()) return false;
    }
    return true;
  });
}

/** Whether any filter dimension is active. */
export function hasActiveFilters(filters: FilterState): boolean {
  return (
    filters.region !== EMPTY_FILTERS.region ||
    filters.networks.length > 0 ||
    filters.dacs.length > 0 ||
    filters.variables.length > 0 ||
    filters.statuses.length > 0 ||
    filters.dateFrom !== "" ||
    filters.dateTo !== "" ||
    !!filters.deepFloats
  );
}

