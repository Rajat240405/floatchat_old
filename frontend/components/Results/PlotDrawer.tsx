"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Download,
  Maximize2,
  Minimize2,
  Pin,
  PinOff,
  ChevronLeft,
  ChevronRight,
  BarChart3,
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
  const [drawerWidth, setDrawerWidth] = useState(420);
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
      const newWidth = Math.max(320, Math.min(800, window.innerWidth - e.clientX));
      setDrawerWidth(newWidth);
    };

    const handleMouseUp = () => {
      setIsResizing(false);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing]);

  // Download plot as PNG
  const downloadPng = useCallback(
    async (plot: PlotItem) => {
      try {
        const Plotly = await import("plotly.js-dist-min");
        const figure = plot.figure;

        await Plotly.downloadImage(
          document.createElement("div"),
          {
            format: "png",
            width: 1200,
            height: 800,
            filename: `floatchat_${plot.variable}_profile`,
          }
        );

        // Alternative: use toImage
        const container = document.createElement("div");
        document.body.appendChild(container);
        container.style.position = "absolute";
        container.style.left = "-9999px";
        container.style.top = "-9999px";

        await Plotly.react(container, figure.data, figure.layout);
        const imgData = await Plotly.toImage(container, {
          format: "png",
          width: 1200,
          height: 800,
        });

        const link = document.createElement("a");
        link.href = imgData;
        link.download = `floatchat_${plot.variable}_profile.png`;
        link.click();

        document.body.removeChild(container);
      } catch (error) {
        console.error("Failed to download PNG:", error);
      }
    },
    []
  );

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

  if (plots.length === 0) {
    return null;
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 z-[900] lg:hidden"
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            ref={containerRef}
            initial={{ x: -drawerWidth - 20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -drawerWidth - 20, opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            style={{
              width: drawerWidth,
              left: 0,
            }}
            className="fixed top-0 bottom-0 z-[950] flex flex-col bg-surface-900/98 backdrop-blur-xl border-r border-surface-700/50 shadow-[20px_0_60px_-10px_rgba(0,0,0,0.5)]"
          >
            {/* Resize handle */}
            <div
              onMouseDown={handleMouseDown}
              className={`absolute right-0 top-0 bottom-0 w-1 cursor-ew-resize transition-colors ${
                isResizing
                  ? "bg-ocean-500"
                  : "hover:bg-ocean-500/50 bg-transparent"
              }`}
            />

            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-surface-800/60 bg-surface-900/90 flex-shrink-0">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-ocean-400" />
                <span className="text-sm font-semibold text-surface-200">
                  Scientific Plots
                </span>
                <span className="text-xs px-1.5 py-0.5 rounded-full bg-ocean-500/15 text-ocean-400 font-medium">
                  {plots.length}
                </span>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800/60 transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Plot Cards */}
            <div className="flex-1 overflow-y-auto scrollbar-thin p-4 flex flex-col gap-4">
              {sortedPlots.map((plot) => (
                <PlotCard
                  key={plot.id}
                  plot={plot}
                  isExpanded={expandedPlot === plot.id}
                  onToggleExpand={() =>
                    setExpandedPlot(
                      expandedPlot === plot.id ? null : plot.id
                    )
                  }
                  onTogglePin={() => onTogglePin(plot.id)}
                  onDownloadPng={() => downloadPng(plot)}
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
  onDownloadPng: () => void;
  onDownloadCsv: () => void;
}

function PlotCard({
  plot,
  isExpanded,
  onToggleExpand,
  onTogglePin,
  onDownloadPng,
  onDownloadCsv,
}: PlotCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);

  // Render plot when expanded
  useEffect(() => {
    if (!isExpanded || !chartRef.current) return;

    let destroyed = false;

    const render = async () => {
      const Plotly = await import("plotly.js-dist-min");
      if (destroyed || !chartRef.current) return;

      await Plotly.react(chartRef.current, plot.figure.data, {
        ...(plot.figure.layout as Record<string, unknown>),
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: {
          family: "Inter, system-ui, sans-serif",
          color: "#94a3b8",
        },
        autosize: true,
        margin: { l: 60, r: 30, t: 40, b: 60 },
      });
    };

    render();

    return () => {
      destroyed = true;
    };
  }, [isExpanded, plot.figure]);

  return (
    <motion.div
      layout
      className={`
        rounded-xl border overflow-hidden transition-colors
        ${plot.pinned
          ? "bg-ocean-950/30 border-ocean-500/30"
          : "bg-surface-800/30 border-surface-700/40"
        }
      `}
    >
      {/* Card Header */}
      <div className="flex items-center justify-between px-3 py-2.5 bg-surface-900/80 border-b border-surface-800/40">
        <div className="flex items-center gap-2 min-w-0">
          {plot.pinned && <Pin className="w-3 h-3 text-ocean-400 shrink-0" />}
          <span className="text-xs font-bold text-surface-200 truncate">
            {plot.title}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onTogglePin}
            className={`
              p-1.5 rounded-lg transition-colors cursor-pointer
              ${plot.pinned
                ? "text-ocean-400 bg-ocean-500/15 hover:bg-ocean-500/25"
                : "text-surface-500 hover:text-surface-300 hover:bg-surface-700/60"
              }
            `}
            title={plot.pinned ? "Unpin" : "Pin"}
          >
            {plot.pinned ? (
              <PinOff className="w-3.5 h-3.5" />
            ) : (
              <Pin className="w-3.5 h-3.5" />
            )}
          </button>
          <button
            onClick={onToggleExpand}
            className="p-1.5 rounded-lg text-surface-500 hover:text-surface-300 hover:bg-surface-700/60 transition-colors cursor-pointer"
            title={isExpanded ? "Collapse" : "Expand"}
          >
            {isExpanded ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Preview or Expanded Chart */}
      {isExpanded ? (
        <div
          ref={chartRef}
          className="w-full bg-surface-900/50"
          style={{ height: "400px" }}
        />
      ) : (
        <div className="px-3 py-2">
          <div className="text-[10px] text-surface-500 italic text-center">
            Click expand to view chart
          </div>
        </div>
      )}

      {/* Action Bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-900/50 border-t border-surface-800/30">
        <button
          onClick={onDownloadPng}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium rounded-lg bg-surface-800/60 border border-surface-700/40 text-surface-400 hover:text-surface-200 hover:bg-surface-700/60 transition-colors cursor-pointer"
        >
          <Download className="w-3 h-3" />
          PNG
        </button>
        <button
          onClick={onDownloadCsv}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium rounded-lg bg-surface-800/60 border border-surface-700/40 text-surface-400 hover:text-surface-200 hover:bg-surface-700/60 transition-colors cursor-pointer"
        >
          <Download className="w-3 h-3" />
          CSV
        </button>
      </div>
    </motion.div>
  );
}
