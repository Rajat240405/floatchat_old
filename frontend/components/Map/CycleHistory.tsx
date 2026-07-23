"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Table,
  Clock,
  MapPin,
  Anchor,
  Star,
  Loader2,
  Maximize2,
  Minimize2,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { CyclePoint } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";

interface CycleHistoryProps {
  cycles: CyclePoint[] | null;
  isLoading: boolean;
  highlightedCycle: number | null;
  onSelectCycle: (cycleNumber: number | null) => void;
  floatId: string | null;
  onExpandToggle?: () => void;
  isExpanded?: boolean;
}

type SortKey = "cycle" | "date" | "depth";
type SortDir = "asc" | "desc";

export function CycleHistory({
  cycles,
  isLoading,
  highlightedCycle,
  onSelectCycle,
  floatId,
  onExpandToggle,
  isExpanded = false,
}: CycleHistoryProps) {
  const rowRefs = useRef<Map<number, HTMLTableRowElement>>(new Map());
  // Default: newest cycle first
  const [sortKey, setSortKey] = useState<SortKey>("cycle");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Auto-scroll highlighted cycle into view
  useEffect(() => {
    if (highlightedCycle == null) return;
    const el = rowRefs.current.get(highlightedCycle);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlightedCycle, cycles, sortKey, sortDir]);

  const hasDepth = useMemo(
    () => !!cycles?.some((c) => c.maxDepth != null),
    [cycles]
  );
  const hasTemp = useMemo(
    () => !!cycles?.some((c) => c.temp != null),
    [cycles]
  );
  const hasSalinity = useMemo(
    () => !!cycles?.some((c) => c.salinity != null),
    [cycles]
  );

  const sorted = useMemo(() => {
    if (!cycles) return [];
    const arr = [...cycles];
    arr.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "cycle") {
        cmp = (a.cycleNumber ?? 0) - (b.cycleNumber ?? 0);
      } else if (sortKey === "date") {
        cmp = (a.date || "").localeCompare(b.date || "");
      } else if (sortKey === "depth") {
        const da = a.maxDepth ?? -1;
        const db = b.maxDepth ?? -1;
        cmp = da - db;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [cycles, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Sensible defaults per column
      setSortDir(key === "date" || key === "cycle" ? "desc" : "desc");
    }
  };

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col)
      return <ArrowUpDown className="w-3 h-3 text-slate-300" />;
    return sortDir === "asc" ? (
      <ArrowUp className="w-3 h-3 text-ocean-500" />
    ) : (
      <ArrowDown className="w-3 h-3 text-ocean-500" />
    );
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full gap-3 text-slate-500 bg-white">
        <Loader2 className="w-5 h-5 animate-spin text-ocean-500" />
        <span className="fc-body">Loading cycle history...</span>
      </div>
    );
  }

  if (!cycles || cycles.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-400 bg-white">
        <Table className="w-6 h-6" />
        <p className="fc-heading text-slate-500">No cycle history available</p>
        <p className="fc-meta">Click a float marker to load cycle history</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden bg-white">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-slate-50 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-ocean-500" />
          <span className="fc-heading">Float Cycle History</span>
          {floatId && (
            <span className="fc-meta ml-1">(Float {floatId})</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-3 fc-meta">
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

      <div className="flex-1 overflow-auto scrollbar-thin">
        <table className="w-full fc-table">
          <thead className="sticky top-0 bg-white/95 backdrop-blur-sm z-10 shadow-sm">
            <tr className="border-b-2 border-slate-200">
              <th className="text-left px-3 py-2 w-16">
                <button
                  type="button"
                  onClick={() => toggleSort("cycle")}
                  className="fc-label inline-flex items-center gap-1 hover:text-ocean-600 cursor-pointer"
                >
                  CYCLE <SortIcon col="cycle" />
                </button>
              </th>
              <th className="text-left px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggleSort("date")}
                  className="fc-label inline-flex items-center gap-1 hover:text-ocean-600 cursor-pointer"
                >
                  DATE (UTC) <SortIcon col="date" />
                </button>
              </th>
              <th className="text-left px-3 py-2">
                <span className="fc-label">LOCATION</span>
              </th>
              {hasDepth && (
                <th className="text-left px-3 py-2 w-24">
                  <button
                    type="button"
                    onClick={() => toggleSort("depth")}
                    className="fc-label inline-flex items-center gap-1 hover:text-ocean-600 cursor-pointer"
                  >
                    MAX DEPTH (M) <SortIcon col="depth" />
                  </button>
                </th>
              )}
              {hasTemp && (
                <th className="text-left px-3 py-2 w-20">
                  <span className="fc-label">TEMP (°C)</span>
                </th>
              )}
              {hasSalinity && (
                <th className="text-left px-3 py-2 w-24">
                  <span className="fc-label">SALINITY (PSU)</span>
                </th>
              )}
              <th className="text-left px-3 py-2 w-20">
                <span className="fc-label">TYPE</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((cycle, idx) => {
              const isHighlighted = highlightedCycle === cycle.cycleNumber;
              const isDeployment = cycle.isDeployment;
              const isCurrent = cycle.isCurrent;

              return (
                <tr
                  key={`${cycle.cycleNumber}-${idx}`}
                  ref={(el) => {
                    if (el) rowRefs.current.set(cycle.cycleNumber, el);
                    else rowRefs.current.delete(cycle.cycleNumber);
                  }}
                  className={`
                    border-b border-slate-100 cursor-pointer transition-colors
                    ${
                      isHighlighted
                        ? "bg-ocean-50 border-ocean-200 ring-1 ring-inset ring-ocean-200"
                        : idx % 2 === 0
                          ? "bg-white hover:bg-slate-50"
                          : "bg-slate-50/60 hover:bg-slate-100"
                    }
                    ${isDeployment ? "border-l-2 border-l-emerald-500" : ""}
                    ${isCurrent && !isDeployment ? "border-l-2 border-l-amber-500" : ""}
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
                    {cycle.hasPosition !== false &&
                    cycle.latitude != null &&
                    cycle.longitude != null ? (
                      <div className="flex items-center gap-2 text-slate-600 font-mono text-[11px]">
                        <span>{formatLat(cycle.latitude)}</span>
                        <span>{formatLon(cycle.longitude)}</span>
                      </div>
                    ) : (
                      <span className="fc-meta italic">No position</span>
                    )}
                  </td>
                  {hasDepth && (
                    <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                      {cycle.maxDepth != null
                        ? Math.round(cycle.maxDepth)
                        : "—"}
                    </td>
                  )}
                  {hasTemp && (
                    <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                      {cycle.temp != null ? cycle.temp.toFixed(2) : "—"}
                    </td>
                  )}
                  {hasSalinity && (
                    <td className="px-3 py-2 text-slate-700 font-medium tabular-nums">
                      {cycle.salinity != null
                        ? cycle.salinity.toFixed(2)
                        : "—"}
                    </td>
                  )}
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
