"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  X,
  Download,
  Maximize2,
  Minimize2,
  Pin,
  PinOff,
  BarChart3,
  ChevronUp,
} from "lucide-react";
import { PlotItem } from "@/types";

interface PlotDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  plots: PlotItem[];
  onTogglePin: (id: string) => void;
}

export function PlotDrawer({
  isOpen,
  onClose,
  plots,
  onTogglePin,
}: PlotDrawerProps) {
  const [expandedPlot, setExpandedPlot] = useState<string | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [drawerWidth, setDrawerWidth] = useState(460);
  const containerRef = useRef<HTMLDivElement>(null);

  // Reset expanded when drawer closes
  useEffect(() => {
    if (!isOpen) {
      setExpandedPlot(null);
    }
  }, [isOpen]);

  // Resize handling
  const handleMouseDown = useCallback(() => {
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.max(340, Math.min(860, window.innerWidth - e.clientX));
      setDrawerWidth(newWidth);
    };
    const handleMouseUp = () => setIsResizing(false);
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  // Download data as CSV
  const downloadCsv = useCallback((plot: PlotItem) => {
    if (!plot.figure.data || plot.figure.data.length === 0) return;
    const traces = plot.figure.data;
    const headers = ["x", "y", "name"];
    const rows: string[][] = [];
    traces.forEach((trace: any) => {
      const xValues = trace.x || [];
      const yValues = trace.y || [];
      const name = trace.name || "series";
      xValues.forEach((x: any, i: number) => {
        rows.push([String(x), String(yValues[i] || ""), name]);
      });
    });
    const csvContent = [
      headers.join(","),
      ...rows.map((row) => row.map((cell) => `"${cell}"`).join(",")),
    ].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `floatchat_${plot.variable}_data.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
  }, []);

  // Sort: pinned first, then by variable name
  const sortedPlots = [...plots].sort((a, b) => {
    if (a.pinned && !b.pinned) return -1;
    if (!a.pinned && b.pinned) return 1;
    return a.variable.localeCompare(b.variable);
  });

  if (plots.length === 0) return null;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop (mobile only) */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/10 z-[900] lg:hidden"
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            ref={containerRef}
            initial={{ x: -drawerWidth - 20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -drawerWidth - 20, opacity: 0 }}
            transition={{ type: "spring", damping: 28, stiffness: 220 }}
            style={{ width: drawerWidth, left: 0 }}
            className="fixed top-0 bottom-0 z-[950] flex flex-col bg-white border-r border-slate-200 shadow-xl"
          >
            {/* Resize handle */}
            <div
              onMouseDown={handleMouseDown}
              className={`absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize transition-colors ${
                isResizing ? "bg-ocean-500" : "hover:bg-ocean-400/60 bg-transparent"
              }`}
            />

            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50 flex-shrink-0">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-ocean-500" />
                <span className="text-sm font-semibold text-slate-700">
                  Scientific Plots
                </span>
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-600 font-medium">
                  {plots.length}
                </span>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
                title="Close plots panel"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Plot Cards */}
            <div className="flex-1 overflow-y-auto scrollbar-thin p-4 flex flex-col gap-4 bg-slate-50/50">
              {sortedPlots.map((plot) => (
                <PlotCard
                  key={plot.id}
                  plot={plot}
                  isExpanded={expandedPlot === plot.id}
                  onToggleExpand={() =>
                    setExpandedPlot(expandedPlot === plot.id ? null : plot.id)
                  }
                  onTogglePin={() => onTogglePin(plot.id)}
                  onDownloadCsv={() => downloadCsv(plot)}
                />
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// Individual Plot Card
interface PlotCardProps {
  plot: PlotItem;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onTogglePin: () => void;
  onDownloadCsv: () => void;
}

function PlotCard({
  plot,
  isExpanded,
  onToggleExpand,
  onTogglePin,
  onDownloadCsv,
}: PlotCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const renderedRef = useRef(false);

  // Render Plotly chart once expanded; re-render only if figure changes
  useEffect(() => {
    if (!isExpanded || !chartRef.current) {
      renderedRef.current = false;
      return;
    }

    let cancelled = false;

    const render = async () => {
      const Plotly = await import("plotly.js-dist-min");
      if (cancelled || !chartRef.current) return;

      const lightLayout = {
        ...(plot.figure.layout as Record<string, unknown>),
        paper_bgcolor: "#ffffff",
        plot_bgcolor: "#f8fafc",
        font: {
          family: "Inter, system-ui, sans-serif",
          color: "#334155",
          size: 11,
        },
        xaxis: {
          ...((plot.figure.layout as any)?.xaxis || {}),
          gridcolor: "#e2e8f0",
          linecolor: "#cbd5e1",
          tickcolor: "#94a3b8",
          tickfont: { color: "#475569", size: 10 },
          title: { ...((plot.figure.layout as any)?.xaxis?.title || {}), font: { color: "#475569", size: 11 } },
        },
        yaxis: {
          ...((plot.figure.layout as any)?.yaxis || {}),
          gridcolor: "#e2e8f0",
          linecolor: "#cbd5e1",
          tickcolor: "#94a3b8",
          tickfont: { color: "#475569", size: 10 },
          title: { ...((plot.figure.layout as any)?.yaxis?.title || {}), font: { color: "#475569", size: 11 } },
        },
        legend: {
          ...((plot.figure.layout as any)?.legend || {}),
          bgcolor: "#ffffff",
          bordercolor: "#e2e8f0",
          font: { color: "#475569", size: 10 },
        },
        autosize: true,
        margin: { l: 64, r: 24, t: 36, b: 56 },
      };

      await Plotly.react(chartRef.current, plot.figure.data, lightLayout);
    };

    render();

    return () => { cancelled = true; };
  }, [isExpanded, plot.figure]);

  return (
    <div
      className={`rounded-xl border overflow-hidden bg-white shadow-sm transition-shadow hover:shadow-md ${
        plot.pinned ? "border-ocean-300 ring-1 ring-ocean-200" : "border-slate-200"
      }`}
    >
      {/* Card Header */}
      <div className={`flex items-center justify-between px-3 py-2.5 border-b ${
        plot.pinned ? "bg-ocean-50 border-ocean-200" : "bg-slate-50 border-slate-200"
      }`}>
        <div className="flex items-center gap-2 min-w-0">
          {plot.pinned && <Pin className="w-3 h-3 text-ocean-500 shrink-0" />}
          <span className="text-xs font-bold text-slate-700 truncate">
            {plot.title}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onTogglePin}
            className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
              plot.pinned
                ? "text-ocean-500 bg-ocean-100 hover:bg-ocean-200"
                : "text-slate-400 hover:text-slate-600 hover:bg-slate-200"
            }`}
            title={plot.pinned ? "Unpin" : "Pin"}
          >
            {plot.pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={onToggleExpand}
            className="p-1.5 rounded-lg text-slate-400 hover:text-ocean-600 hover:bg-ocean-50 transition-colors cursor-pointer"
            title={isExpanded ? "Collapse chart" : "Expand chart"}
          >
            {isExpanded ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Chart or Placeholder */}
      {isExpanded ? (
        <div
          ref={chartRef}
          className="w-full bg-white"
          style={{ height: "420px" }}
        />
      ) : (
        <div className="px-4 py-3 bg-white">
          <div className="h-10 flex items-center justify-center text-[11px] text-slate-400 italic border border-dashed border-slate-200 rounded-lg bg-slate-50">
            Click <Maximize2 className="w-3 h-3 mx-1 inline text-ocean-400" /> to expand chart
          </div>
        </div>
      )}

      {/* Action Bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 border-t border-slate-200">
        <button
          onClick={onDownloadCsv}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium rounded-lg bg-white border border-slate-200 text-slate-500 hover:text-slate-700 hover:bg-slate-100 hover:border-slate-300 transition-colors cursor-pointer"
        >
          <Download className="w-3 h-3" />
          Download CSV
        </button>
        {isExpanded && (
          <span className="ml-auto text-[10px] text-slate-400 italic">
            Click ↙ to collapse
          </span>
        )}
      </div>
    </div>
  );
}
