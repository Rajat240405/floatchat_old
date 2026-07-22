"use client";

import { motion } from "framer-motion";
import { Database, Ruler, Calendar, FileText, Navigation, Compass } from "lucide-react";
import { DataSummary } from "@/types";

interface SummaryCardsProps {
  summary?: DataSummary;
  intent?: string;
}

export function SummaryCards({ summary, intent }: SummaryCardsProps) {
  if (!summary) return null;

  const isNearest = intent === "nearest_float";
  const isRadius = intent === "radius_search";

  const cards = [
    {
      icon: Database,
      label: isNearest ? "Matching Floats" : isRadius ? "Floats Found" : "Profiles",
      value: summary.matched_records ?? 0,
      color: "text-ocean-400",
      bg: "bg-ocean-500/10",
      border: "border-ocean-500/20",
    },
    {
      icon: isNearest || isRadius ? Compass : Ruler,
      label: isNearest
        ? "Nearest Distance"
        : isRadius
        ? "Search Radius"
        : "Measurements",
      value: isNearest
        ? `${summary.distance_km?.toFixed(1) ?? "—"} km`
        : isRadius
        ? `${summary.radius_km ?? 100} km`
        : (summary.total_measurements ?? 0).toLocaleString(),
      color: "text-emerald-400",
      bg: "bg-emerald-500/10",
      border: "border-emerald-500/20",
      isText: isNearest || isRadius,
    },
    {
      icon: isNearest || isRadius ? Navigation : Calendar,
      label: isNearest || isRadius ? "Target Coords" : "Date Range",
      value:
        isNearest && summary.target_coords
          ? `${summary.target_coords.lat.toFixed(1)}°, ${summary.target_coords.lon.toFixed(1)}°`
          : isRadius && summary.center
          ? `${summary.center.lat.toFixed(1)}°, ${summary.center.lon.toFixed(1)}°`
          : summary.date_range?.min && summary.date_range?.max
          ? `${summary.date_range.min.slice(0, 10)} → ${summary.date_range.max.slice(0, 10)}`
          : "Historical Range",
      color: "text-amber-400",
      bg: "bg-amber-500/10",
      border: "border-amber-500/20",
      isText: true,
    },
    {
      icon: FileText,
      label: "Intent",
      value: intent ? intent.replace(/_/g, " ") : "—",
      color: "text-violet-400",
      bg: "bg-violet-500/10",
      border: "border-violet-500/20",
      isText: true,
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {cards.map((card, i) => (
        <motion.div
          key={card.label}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: i * 0.08 }}
          className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${card.bg} ${card.border}`}
        >
          <card.icon className={`w-4 h-4 ${card.color}`} />
          <div className="min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-surface-500 font-semibold">
              {card.label}
            </p>
            <p className={`text-sm font-semibold text-surface-100 truncate ${card.isText ? "text-xs" : ""}`}>
              {typeof card.value === "number" ? card.value.toLocaleString() : card.value}
            </p>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
