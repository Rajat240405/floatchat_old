"use client";

import { motion } from "framer-motion";
import {
  Table,
  Clock,
  MapPin,
  Anchor,
  Star,
  ChevronRight,
  Loader2,
} from "lucide-react";
import { CyclePoint } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";

interface CycleHistoryProps {
  cycles: CyclePoint[] | null;
  isLoading: boolean;
  highlightedCycle: number | null;
  onSelectCycle: (cycleNumber: number | null) => void;
  floatId: string | null;
}

export function CycleHistory({
  cycles,
  isLoading,
  highlightedCycle,
  onSelectCycle,
  floatId,
}: CycleHistoryProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-3 text-surface-500">
        <Loader2 className="w-5 h-5 animate-spin text-ocean-400" />
        <span className="text-sm">Loading trajectory history...</span>
      </div>
    );
  }

  if (!cycles || cycles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-surface-600">
        <Table className="w-6 h-6" />
        <p className="text-sm">No cycle history available</p>
        <p className="text-xs">Click &quot;View Trajectory&quot; to load trajectory data</p>
      </div>
    );
  }

  // Find max values for progress bars
  const maxCycle = cycles.length;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-surface-800/60 bg-surface-900/90 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-ocean-400" />
          <span className="text-sm font-semibold text-surface-200">
            Float Cycle History
          </span>
          {floatId && (
            <span className="text-xs text-surface-500 ml-1">
              (Float {floatId})
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-surface-500">
          <span>{cycles.length} cycles</span>
          {cycles.find((c) => c.isDeployment) && (
            <span className="flex items-center gap-1">
              <Anchor className="w-3 h-3" />
              Deployment
            </span>
          )}
          {cycles.find((c) => c.isCurrent) && (
            <span className="flex items-center gap-1">
              <Star className="w-3 h-3 text-amber-400" />
              Current
            </span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto scrollbar-thin">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface-900/95 backdrop-blur-sm z-10">
            <tr className="border-b border-surface-800/60">
              <th className="text-left px-3 py-2 text-surface-500 font-semibold uppercase tracking-wider w-16">
                Cycle
              </th>
              <th className="text-left px-3 py-2 text-surface-500 font-semibold uppercase tracking-wider">
                Date
              </th>
              <th className="text-left px-3 py-2 text-surface-500 font-semibold uppercase tracking-wider">
                Position
              </th>
              <th className="text-left px-3 py-2 text-surface-500 font-semibold uppercase tracking-wider">
                Variables
              </th>
              <th className="text-left px-3 py-2 text-surface-500 font-semibold uppercase tracking-wider w-24">
                Type
              </th>
            </tr>
          </thead>
          <tbody>
            {cycles.map((cycle, idx) => {
              const isHighlighted = highlightedCycle === cycle.cycleNumber;
              const isDeployment = cycle.isDeployment;
              const isCurrent = cycle.isCurrent;

              return (
                <motion.tr
                  key={`${cycle.cycleNumber}-${idx}`}
                  initial={false}
                  animate={{
                    backgroundColor: isHighlighted
                      ? "rgba(14, 165, 233, 0.15)"
                      : idx % 2 === 0
                        ? "transparent"
                        : "rgba(30, 41, 59, 0.3)",
                  }}
                  className={`
                    border-b border-surface-800/30 cursor-pointer
                    hover:bg-ocean-500/10 transition-colors
                    ${isHighlighted ? "ring-1 ring-ocean-500/40" : ""}
                    ${isDeployment ? "border-l-2 border-l-emerald-500" : ""}
                    ${isCurrent ? "border-l-2 border-l-amber-500" : ""}
                  `}
                  onClick={() =>
                    onSelectCycle(isHighlighted ? null : cycle.cycleNumber)
                  }
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className={`
                          font-bold min-w-[2.5rem]
                          ${isHighlighted ? "text-ocean-300" : "text-surface-300"}
                        `}
                      >
                        #{cycle.cycleNumber}
                      </span>
                      {/* Progress indicator */}
                      <div className="w-12 h-1.5 bg-surface-800 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-ocean-500 rounded-full transition-all"
                          style={{
                            width: `${(cycle.cycleNumber / maxCycle) * 100}%`,
                          }}
                        />
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <span className="text-surface-300 font-medium">
                      {formatDate(cycle.date)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-3 text-surface-400">
                      <span className="font-mono text-[11px]">
                        {formatLat(cycle.latitude)}
                      </span>
                      <span className="font-mono text-[11px]">
                        {formatLon(cycle.longitude)}
                      </span>
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1 flex-wrap max-w-[200px]">
                      {cycle.variables.slice(0, 4).map((v) => (
                        <span
                          key={v}
                          className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-ocean-500/10 text-ocean-400 border border-ocean-500/20"
                        >
                          {v}
                        </span>
                      ))}
                      {cycle.variables.length > 4 && (
                        <span className="text-[10px] text-surface-500">
                          +{cycle.variables.length - 4}
                        </span>
                      )}
                      {cycle.variables.length === 0 && (
                        <span className="text-surface-600 italic">
                          Standard CTD
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2">
                    {isDeployment && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                        <Anchor className="w-2.5 h-2.5" />
                        Deploy
                      </span>
                    )}
                    {isCurrent && !isDeployment && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/15 text-amber-400 border border-amber-500/30">
                        <Star className="w-2.5 h-2.5" />
                        Current
                      </span>
                    )}
                    {!isDeployment && !isCurrent && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-surface-800/60 text-surface-500 border border-surface-700/40">
                        <MapPin className="w-2.5 h-2.5" />
                        Profile
                      </span>
                    )}
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
