"use client";

import { motion } from "framer-motion";
import { Database, Navigation, CheckCircle2, XCircle, ArrowRight } from "lucide-react";
import { DataSummary } from "@/types";

interface CountStatCardProps {
  summary: DataSummary;
  onDrillDown?: (query: string) => void;
}

export function CountStatCard({ summary, onDrillDown }: CountStatCardProps) {
  const hasData = summary.existence ?? (summary.matched_records !== undefined && summary.matched_records > 0);
  const totalProfiles = summary.matched_records ?? 0;
  const uniqueFloats = summary.unique_floats ?? 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="p-4 rounded-xl bg-surface-900 border border-surface-800/80 shadow-md flex flex-col gap-3"
    >
      {/* Header with Existence Indicator */}
      <div className="flex items-center justify-between pb-3 border-b border-surface-800/60">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
            <Database className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-surface-100">
              Data Lake Aggregates
            </h3>
            <p className="text-xs text-surface-500">
              Exact precomputed statistics from local Parquet partitions
            </p>
          </div>
        </div>

        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${
            hasData
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
              : "bg-rose-500/10 text-rose-400 border-rose-500/20"
          }`}
        >
          {hasData ? (
            <>
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Data Available</span>
            </>
          ) : (
            <>
              <XCircle className="w-3.5 h-3.5" />
              <span>No Matching Data</span>
            </>
          )}
        </div>
      </div>

      {/* Uncapped Counts Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-surface-950/60 border border-surface-800/40 flex flex-col">
          <span className="text-xs text-surface-500 font-medium mb-1">
            Total Profiles (Uncapped)
          </span>
          <span className="text-xl font-bold text-ocean-300">
            {totalProfiles.toLocaleString()}
          </span>
        </div>

        <div className="p-3 rounded-lg bg-surface-950/60 border border-surface-800/40 flex flex-col">
          <span className="text-xs text-surface-500 font-medium mb-1">
            Unique Floats
          </span>
          <span className="text-xl font-bold text-emerald-400">
            {uniqueFloats > 0 ? uniqueFloats.toLocaleString() : "—"}
          </span>
        </div>

        <div className="p-3 rounded-lg bg-surface-950/60 border border-surface-800/40 flex flex-col col-span-2 md:col-span-1">
          <span className="text-xs text-surface-500 font-medium mb-1">
            Date Coverage Range
          </span>
          <span className="text-xs font-semibold text-amber-300 truncate">
            {summary.date_range?.min && summary.date_range?.max
              ? `${summary.date_range.min.slice(0, 10)} → ${summary.date_range.max.slice(0, 10)}`
              : "Historical Lake Range"}
          </span>
        </div>
      </div>

      {/* Suggested Drill Down Actions */}
      {hasData && onDrillDown && (
        <div className="flex items-center gap-2 pt-2 border-t border-surface-800/40">
          <button
            onClick={() => onDrillDown("Show oxygen profile in Arabian Sea")}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-ocean-500/10 hover:bg-ocean-500/20 text-ocean-300 text-xs font-medium border border-ocean-500/20 transition-colors"
          >
            <span>Plot Oxygen Profiles</span>
            <ArrowRight className="w-3 h-3" />
          </button>
          <button
            onClick={() => onDrillDown("Show temperature profile in Bay of Bengal")}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 px-3 rounded-lg bg-surface-800 hover:bg-surface-700 text-surface-200 text-xs font-medium border border-surface-700 transition-colors"
          >
            <span>Plot Temperature Profiles</span>
            <ArrowRight className="w-3 h-3" />
          </button>
        </div>
      )}
    </motion.div>
  );
}
