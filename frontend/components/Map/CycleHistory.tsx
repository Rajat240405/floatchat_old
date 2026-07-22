"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Table,
  Clock,
  MapPin,
  Anchor,
  Star,
  Loader2,
  ChevronUp,
  ChevronDown,
  Maximize2,
  Minimize2,
} from "lucide-react";
import { CyclePoint } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";

interface CycleHistoryProps {
  cycles: CyclePoint[] | null;
  isLoading: boolean;
  highlightedCycle: number | null;
  onSelectCycle: (cycleNumber: number | null) => void;
  floatId: string | null;
  /** Optional: callback to request expanding upward (handled by parent) */
  onExpandToggle?: () => void;
  isExpanded?: boolean;
}

export function CycleHistory({
  cycles,
  isLoading,
  highlightedCycle,
  onSelectCycle,
  floatId,
  onExpandToggle,
  isExpanded = false,
}: CycleHistoryProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-3 text-slate-500 bg-white">
        <Loader2 className="w-5 h-5 animate-spin text-ocean-500" />
        <span className="text-sm font-medium">Loading trajectory history...</span>
      </div>
    );
  }

  if (!cycles || cycles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-400 bg-white">
        <Table className="w-6 h-6" />
        <p className="text-sm font-medium">No cycle history available</p>
        <p className="text-xs text-slate-400">Click &quot;View Trajectory&quot; to load trajectory data</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-slate-50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-ocean-500" />
          <span className="text-sm font-semibold text-slate-700">
            Float Cycle History
          </span>
          {floatId && (
            <span className="text-xs text-slate-400 ml-1">
              (Float {floatId})
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span className="font-medium">{cycles.length} cycles</span>
            {cycles.find((c) => c.isDeployment) && (
              <span className="flex items-center gap-1">
                <Anchor className="w-3 h-3 text-emerald-500" />
                <span className="text-emerald-600 font-medium">Deployment</span>
              </span>
            )}
            {cycles.find((c) => c.isCurrent) && (
              <span className="flex items-center gap-1">
                <Star className="w-3 h-3 text-amber-400" />
                <span className="text-amber-600 font-medium">Current</span>
              </span>
            )}
          </div>
          {/* Expand/Collapse upward */}
          {onExpandToggle && (
            <button
              onClick={onExpandToggle}
              className="p-1.5 rounded-lg text-slate-400 hover:text-ocean-600 hover:bg-ocean-50 border border-transparent hover:border-ocean-200 transition-all cursor-pointer"
              title={isExpanded ? "Collapse table" : "Expand table upward"}
            >
              {isExpanded ? (
                <Minimize2 className="w-4 h-4" />
              ) : (
                <Maximize2 className="w-4 h-4" />
              )}
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto scrollbar-thin">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-white/95 backdrop-blur-sm z-10 shadow-sm">
            <tr className="border-b-2 border-slate-200">
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider w-14">CYCLE</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider">DATE (UTC)</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider">LOCATION</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider w-20">MAX DEPTH (M)</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider w-16">TEMP (°C)</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider w-20">SALINITY (PSU)</th>
              <th className="text-left px-3 py-2 text-slate-500 font-bold uppercase tracking-wider w-20">TYPE</th>
            </tr>
          </thead>
          <tbody>
            {cycles.map((cycle, idx) => {
              const isHighlighted = highlightedCycle === cycle.cycleNumber;
              const isDeployment = cycle.isDeployment;
              const isCurrent = cycle.isCurrent;

              return (
                <tr
                  key={`${cycle.cycleNumber}-${idx}`}
                  className={`
                    border-b border-slate-100 cursor-pointer transition-colors
                    ${isHighlighted
                      ? "bg-ocean-50 border-ocean-200"
                      : idx % 2 === 0
                        ? "bg-white hover:bg-slate-50"
                        : "bg-slate-50/60 hover:bg-slate-100"
                    }
                    ${isDeployment ? "border-l-2 border-l-emerald-500" : ""}
                    ${isCurrent ? "border-l-2 border-l-amber-500" : ""}
                  `}
                  onClick={() =>
                    onSelectCycle(isHighlighted ? null : cycle.cycleNumber)
                  }
                >
                  <td className="px-3 py-2">
                    <span
                      className={`font-bold ${
                        isHighlighted ? "text-ocean-600" : "text-slate-700"
                      }`}
                    >
                      #{cycle.cycleNumber}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-slate-700 font-medium">
                      {formatDate(cycle.date)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2 text-slate-600 font-mono text-[11px]">
                      <span>{formatLat(cycle.latitude)}</span>
                      <span>{formatLon(cycle.longitude)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                    {cycle.maxDepth != null ? Math.round(cycle.maxDepth) : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                    {cycle.temp != null ? cycle.temp.toFixed(2) : "—"}
                  </td>
                  <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                    {cycle.salinity != null ? cycle.salinity.toFixed(2) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    {isDeployment && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                        <Anchor className="w-2.5 h-2.5" />
                        Deploy
                      </span>
                    )}
                    {isCurrent && !isDeployment && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                        <Star className="w-2.5 h-2.5" />
                        Current
                      </span>
                    )}
                    {!isDeployment && !isCurrent && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-500 border border-slate-200">
                        <MapPin className="w-2.5 h-2.5" />
                        Profile
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
