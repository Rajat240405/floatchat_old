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
  if (isNaN(d.getTime())) return String(iso).slice(0, 10);
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

/** Extract YYYY-MM-DD from various date representations (timezone-safe). */
function toDateKey(value: string | null | undefined): string | null {
  if (!value) return null;
  const s = String(value).trim();
  // Already ISO date or datetime
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  const d = new Date(s);
  if (isNaN(d.getTime())) return null;
  // Use UTC components to avoid off-by-one from local TZ
  const y = d.getUTCFullYear();
  const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${mo}-${day}`;
}

/**
 * Apply the scientific sidebar filters to a list of map markers.
 * Filtering is client-side over the latest mapData.
 */
export function applyFilters(markers: MapData[], filters: FilterState): MapData[] {
  const has = (arr: string[]) => arr.length > 0;
  const fromKey = filters.dateFrom || null;
  const toKey = filters.dateTo || null;

  return markers.filter((m) => {
    // Region via region_tag
    if (filters.region) {
      const tag = (m.region_tag || "").toLowerCase();
      const want = filters.region.toLowerCase();
      // indian_ocean is a query alias for all IO leaf tags (+ legacy stored tag).
      if (want === "indian_ocean") {
        const ioLeaves = new Set([
          "arabian_sea",
          "bay_of_bengal",
          "equatorial_indian_ocean",
          "southern_indian_ocean",
          "indian_ocean", // legacy stored open-basin tag
        ]);
        if (tag && !ioLeaves.has(tag)) return false;
        // empty tag: keep (incomplete marker metadata)
      } else if (tag) {
        if (tag !== want) return false;
      } else {
        return false;
      }
    }
    if (has(filters.networks)) {
      const net = (m.network || "Core Argo").toLowerCase();
      if (!filters.networks.some((n) => n.toLowerCase() === net)) return false;
    }
    if (has(filters.dacs)) {
      const dac = (m.dac || "").toLowerCase();
      if (
        !filters.dacs.some(
          (d) => d.toLowerCase() === dac || dac.includes(d.toLowerCase())
        )
      )
        return false;
    }
    if (has(filters.statuses)) {
      const st = (m.status || "unknown").toLowerCase();
      if (!filters.statuses.some((s) => s.toLowerCase() === st)) return false;
    }
    // Date range — compare calendar dates as YYYY-MM-DD strings (lexicographic)
    if (fromKey || toKey) {
      const key = toDateKey(m.profile_date);
      if (!key) return false;
      if (fromKey && key < fromKey) return false;
      if (toKey && key > toKey) return false;
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
    filters.statuses.length > 0 ||
    filters.dateFrom !== "" ||
    filters.dateTo !== ""
  );
}
