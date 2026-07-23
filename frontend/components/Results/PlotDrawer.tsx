"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  X,
  Download,
  Maximize2,
  Minimize2,
  Pin,
  PinOff,
  BarChart3,
  Layers,
} from "lucide-react";
import { PlotItem, PlotlyFigure } from "@/types";

interface PlotDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  plots: PlotItem[];
  onTogglePin: (id: string) => void;
  onRemovePlot?: (id: string) => void;
  /** Float IDs discovered in the current plot set. */
  floatIds?: string[];
  /** null = All Floats overlay. */
  selectedFloatId?: string | null;
  onSelectFloatId?: (id: string | null) => void;
}

/** Filter a figure's traces down to one float (or keep all). */
function filterFigureByFloat(
  figure: PlotlyFigure,
  selectedFloatId: string | null | undefined
): PlotlyFigure {
  if (!selectedFloatId) return figure;
  const target = `Float ${selectedFloatId}`;
  const data = (figure.data || []).filter((t) => {
    const name = String((t as { name?: string }).name || "");
    // Keep traces that match the float, or non-float traces (axes helpers)
    if (!/Float\s+\d+/i.test(name)) return true;
    return name === target || name.includes(selectedFloatId);
  });
  // If filtering removed everything, fall back to original
  if (data.length === 0) return figure;
  return { ...figure, data };
}

export function PlotDrawer({
  isOpen,
  onClose,
  plots,
  onTogglePin,
  onRemovePlot,
  floatIds = [],
  selectedFloatId = null,
  onSelectFloatId,
}: PlotDrawerProps) {
  const [expandedPlot, setExpandedPlot] = useState<string | null>(null);
  const [fullscreenPlot, setFullscreenPlot] = useState<string | null>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [drawerWidth, setDrawerWidth] = useState(520);
  const containerRef = useRef<HTMLDivElement>(null);

  // Keep expanded state when closing; only clear fullscreen
  useEffect(() => {
    if (!isOpen) {
      setFullscreenPlot(null);
    }
  }, [isOpen]);

  // Auto-expand first plot when drawer opens with plots
  useEffect(() => {
    if (isOpen && plots.length > 0 && !expandedPlot) {
      const sorted = [...plots].sort((a, b) => {
        if (a.pinned && !b.pinned) return -1;
        if (!a.pinned && b.pinned) return 1;
        return a.variable.localeCompare(b.variable);
      });
      setExpandedPlot(sorted[0].id);
    }
  }, [isOpen, plots, expandedPlot]);

  const handleMouseDown = useCallback(() => {
    setIsResizing(true);
  }, []);

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.max(380, Math.min(960, window.innerWidth - e.clientX));
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

  // Download plot data as real CSV (comma-delimited, quoted).
  // Respects the current float filter. Headers: pressure_dbar, value, series, variable.
  const downloadCsv = useCallback(
    (plot: PlotItem) => {
      const fig = filterFigureByFloat(plot.figure, selectedFloatId);
      if (!fig.data || fig.data.length === 0) return;
      // y is pressure (dbar), x is the measured value for profile plots
      const headers = ["pressure_dbar", "value", "series", "variable"];
      const rows: string[][] = [];
      fig.data.forEach((trace: { x?: unknown[]; y?: unknown[]; name?: string }) => {
        const xValues = trace.x || [];
        const yValues = trace.y || [];
        const name = trace.name || "series";
        // Profile convention: x=value, y=pressure
        const n = Math.max(xValues.length, yValues.length);
        for (let i = 0; i < n; i++) {
          const pressure = yValues[i] ?? "";
          const value = xValues[i] ?? "";
          rows.push([
            String(pressure),
            String(value),
            name,
            plot.variable || "",
          ]);
        }
      });
      const escape = (cell: string) => {
        const s = String(cell ?? "");
        if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
        return s;
      };
      const csvContent = [
        headers.join(","),
        ...rows.map((row) => row.map(escape).join(",")),
      ].join("\r\n");
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      const suffix = selectedFloatId ? `_float_${selectedFloatId}` : "_all";
      link.download = `floatchat_${plot.variable || "plot"}${suffix}.csv`;
      link.click();
      URL.revokeObjectURL(link.href);
    },
    [selectedFloatId]
  );

  const sortedPlots = useMemo(
    () =>
      [...plots].sort((a, b) => {
        if (a.pinned && !b.pinned) return -1;
        if (!a.pinned && b.pinned) return 1;
        return a.variable.localeCompare(b.variable);
      }),
    [plots]
  );

  const showFloatSelector = floatIds.length > 1;

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
            className="fixed top-0 bottom-0 z-[950] flex flex-col bg-white border-r border-slate-200 shadow-2xl"
          >
            {/* Resize handle */}
            <div
              onMouseDown={handleMouseDown}
              className={`absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize z-10 transition-colors ${
                isResizing ? "bg-ocean-500" : "hover:bg-ocean-400/60 bg-transparent"
              }`}
              title="Drag to resize"
            />

            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-ocean-50/40 flex-shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-ocean-100 border border-ocean-200 flex items-center justify-center shrink-0">
                  <BarChart3 className="w-4 h-4 text-ocean-600" />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">
                      Scientific Plots
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-700 font-bold border border-ocean-200">
                      {plots.length}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-500 truncate">
                    Profile analysis · pressure vs variable
                  </p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer shrink-0"
                title="Hide plots panel (plots are preserved)"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Float selector — default multi-float workflow */}
            {showFloatSelector && (
              <div className="px-4 py-3 border-b border-slate-200 bg-white flex-shrink-0">
                <div className="flex items-center gap-2 mb-2">
                  <Layers className="w-3.5 h-3.5 text-ocean-500" />
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">
                    Float selection
                  </span>
                </div>
                <div className="flex flex-col gap-1 max-h-40 overflow-y-auto scrollbar-thin pr-1">
                  <label className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-slate-50 cursor-pointer transition-colors">
                    <input
                      type="radio"
                      name="plot-float"
                      checked={selectedFloatId == null}
                      onChange={() => onSelectFloatId?.(null)}
                      className="w-3.5 h-3.5 accent-ocean-500"
                    />
                    <span className="text-xs font-semibold text-slate-700">
                      All Floats
                    </span>
                    <span className="ml-auto text-[10px] text-slate-400">
                      overlay · {floatIds.length}
                    </span>
                  </label>
                  {floatIds.map((fid) => (
                    <label
                      key={fid}
                      className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors ${
                        selectedFloatId === fid
                          ? "bg-ocean-50 border border-ocean-200"
                          : "hover:bg-slate-50 border border-transparent"
                      }`}
                    >
                      <input
                        type="radio"
                        name="plot-float"
                        checked={selectedFloatId === fid}
                        onChange={() => onSelectFloatId?.(fid)}
                        className="w-3.5 h-3.5 accent-ocean-500"
                      />
                      <span className="text-xs font-medium text-slate-700 font-mono">
                        Float {fid}
                      </span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Single-float badge when only one float in set */}
            {!showFloatSelector && floatIds.length === 1 && (
              <div className="px-4 py-2 border-b border-slate-200 bg-ocean-50/50 flex-shrink-0">
                <span className="text-xs font-semibold text-ocean-700">
                  Float {floatIds[0]}
                </span>
              </div>
            )}

            {/* Plot Cards */}
            <div className="flex-1 overflow-y-auto scrollbar-thin p-4 flex flex-col gap-4 bg-slate-50/60">
              {sortedPlots.map((plot) => (
                <PlotCard
                  key={plot.id}
                  plot={plot}
                  filteredFigure={filterFigureByFloat(plot.figure, selectedFloatId)}
                  isExpanded={expandedPlot === plot.id}
                  isFullscreen={fullscreenPlot === plot.id}
                  drawerWidth={drawerWidth}
                  onToggleExpand={() =>
                    setExpandedPlot(expandedPlot === plot.id ? null : plot.id)
                  }
                  onToggleFullscreen={() =>
                    setFullscreenPlot(fullscreenPlot === plot.id ? null : plot.id)
                  }
                  onTogglePin={() => onTogglePin(plot.id)}
                  onRemove={onRemovePlot ? () => onRemovePlot(plot.id) : undefined}
                  onDownloadCsv={() => downloadCsv(plot)}
                />
              ))}
            </div>
          </motion.div>

          {/* True fullscreen overlay for a single plot */}
          <AnimatePresence>
            {fullscreenPlot && (
              <FullscreenPlotOverlay
                plot={sortedPlots.find((p) => p.id === fullscreenPlot) || null}
                filteredFigure={
                  sortedPlots.find((p) => p.id === fullscreenPlot)
                    ? filterFigureByFloat(
                        sortedPlots.find((p) => p.id === fullscreenPlot)!.figure,
                        selectedFloatId
                      )
                    : null
                }
                onClose={() => setFullscreenPlot(null)}
                onDownloadCsv={() => {
                  const p = sortedPlots.find((x) => x.id === fullscreenPlot);
                  if (p) downloadCsv(p);
                }}
              />
            )}
          </AnimatePresence>
        </>
      )}
    </AnimatePresence>
  );
}

// ── Individual Plot Card ────────────────────────────────────────────────────

interface PlotCardProps {
  plot: PlotItem;
  filteredFigure: PlotlyFigure;
  isExpanded: boolean;
  isFullscreen: boolean;
  drawerWidth: number;
  onToggleExpand: () => void;
  onToggleFullscreen: () => void;
  onTogglePin: () => void;
  onRemove?: () => void;
  onDownloadCsv: () => void;
}

function PlotCard({
  plot,
  filteredFigure,
  isExpanded,
  isFullscreen,
  drawerWidth,
  onToggleExpand,
  onToggleFullscreen,
  onTogglePin,
  onRemove,
  onDownloadCsv,
}: PlotCardProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const plotlyRef = useRef<typeof import("plotly.js-dist-min") | null>(null);

  // Render / update chart whenever expanded figure or width changes
  useEffect(() => {
    if (!isExpanded || !chartRef.current || isFullscreen) return;

    let cancelled = false;

    const render = async () => {
      const Plotly = await import("plotly.js-dist-min");
      plotlyRef.current = Plotly;
      if (cancelled || !chartRef.current) return;

      const layout = buildScientificLayout(filteredFigure, {
        height: 440,
      });

      await Plotly.react(
        chartRef.current,
        filteredFigure.data as Plotly.Data[],
        layout,
        {
          responsive: true,
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToRemove: ["lasso2d", "select2d"],
          toImageButtonOptions: {
            format: "png",
            filename: `floatchat_${plot.variable}`,
            height: 800,
            width: 1000,
            scale: 2,
          },
        }
      );

      // Force a resize so legends/axes fit the drawer width
      try {
        if (chartRef.current && chartRef.current.offsetWidth > 0) {
          await Plotly.Plots.resize(chartRef.current).catch(() => { /* ignore */ });
        }
      } catch {
        /* ignore */
      }
    };

    render();

    return () => {
      cancelled = true;
    };
  }, [isExpanded, filteredFigure, plot.variable, drawerWidth, isFullscreen]);

  // Resize observer — keep Plotly in sync with drawer width
  useEffect(() => {
    if (!isExpanded || !chartRef.current) return;
    const el = chartRef.current;
    const ro = new ResizeObserver(() => {
      if (plotlyRef.current && el && el.offsetWidth > 0) {
        try {
          plotlyRef.current.Plots.resize(el).catch(() => { /* ignore */ });
        } catch {
          /* ignore */
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isExpanded]);

  return (
    <div
      className={`rounded-xl border overflow-hidden bg-white shadow-sm transition-shadow hover:shadow-md ${
        plot.pinned ? "border-ocean-300 ring-1 ring-ocean-200" : "border-slate-200"
      }`}
    >
      {/* Card Header */}
      <div
        className={`flex items-center justify-between px-3 py-2.5 border-b ${
          plot.pinned
            ? "bg-ocean-50 border-ocean-200"
            : "bg-slate-50 border-slate-200"
        }`}
      >
        <div className="flex items-center gap-2 min-w-0">
          {plot.pinned && <Pin className="w-3 h-3 text-ocean-500 shrink-0" />}
          <span className="text-xs font-bold text-slate-800 truncate tracking-tight">
            {plot.title}
          </span>
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={onTogglePin}
            className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
              plot.pinned
                ? "text-ocean-500 bg-ocean-100 hover:bg-ocean-200"
                : "text-slate-400 hover:text-slate-600 hover:bg-slate-200"
            }`}
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
            className="p-1.5 rounded-lg text-slate-400 hover:text-ocean-600 hover:bg-ocean-50 transition-colors cursor-pointer"
            title={isExpanded ? "Collapse chart" : "Expand chart"}
          >
            {isExpanded ? (
              <Minimize2 className="w-3.5 h-3.5" />
            ) : (
              <Maximize2 className="w-3.5 h-3.5" />
            )}
          </button>
          {isExpanded && (
            <button
              onClick={onToggleFullscreen}
              className="p-1.5 rounded-lg text-slate-400 hover:text-ocean-600 hover:bg-ocean-50 transition-colors cursor-pointer"
              title="Fullscreen"
            >
              <Maximize2 className="w-3.5 h-3.5 rotate-45" />
            </button>
          )}
          {onRemove && (
            <button
              onClick={onRemove}
              className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors cursor-pointer"
              title="Remove plot"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Chart or Placeholder */}
      {isExpanded ? (
        <div
          ref={chartRef}
          className="w-full bg-white"
          style={{ height: "440px", minHeight: "440px" }}
        />
      ) : (
        <button
          type="button"
          onClick={onToggleExpand}
          className="w-full px-4 py-3 bg-white cursor-pointer text-left"
        >
          <div className="h-11 flex items-center justify-center text-[11px] text-slate-500 border border-dashed border-slate-200 rounded-lg bg-slate-50 hover:bg-ocean-50/40 hover:border-ocean-200 transition-colors">
            Click to expand · {plot.variable}
          </div>
        </button>
      )}

      {/* Action Bar */}
      <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 border-t border-slate-200">
        <button
          onClick={onDownloadCsv}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium rounded-lg bg-white border border-slate-200 text-slate-600 hover:text-slate-800 hover:bg-slate-100 hover:border-slate-300 transition-colors cursor-pointer"
        >
          <Download className="w-3 h-3" />
          Download CSV
        </button>
        {isExpanded && (
          <button
            onClick={onToggleFullscreen}
            className="flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium rounded-lg bg-white border border-slate-200 text-slate-600 hover:text-slate-800 hover:bg-slate-100 transition-colors cursor-pointer"
          >
            <Maximize2 className="w-3 h-3" />
            Fullscreen
          </button>
        )}
      </div>
    </div>
  );
}

// ── Fullscreen overlay ──────────────────────────────────────────────────────

function FullscreenPlotOverlay({
  plot,
  filteredFigure,
  onClose,
  onDownloadCsv,
}: {
  plot: PlotItem | null;
  filteredFigure: PlotlyFigure | null;
  onClose: () => void;
  onDownloadCsv: () => void;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const plotlyRef = useRef<typeof import("plotly.js-dist-min") | null>(null);

  useEffect(() => {
    if (!plot || !filteredFigure || !chartRef.current) return;
    let cancelled = false;

    const render = async () => {
      const Plotly = await import("plotly.js-dist-min");
      plotlyRef.current = Plotly;
      if (cancelled || !chartRef.current) return;

      const layout = buildScientificLayout(filteredFigure, {
        height: Math.max(480, window.innerHeight - 140),
      });

      await Plotly.react(
        chartRef.current,
        filteredFigure.data as Plotly.Data[],
        layout,
        {
          responsive: true,
          displayModeBar: true,
          displaylogo: false,
          modeBarButtonsToRemove: ["lasso2d", "select2d"],
          toImageButtonOptions: {
            format: "png",
            filename: `floatchat_${plot.variable}_fullscreen`,
            height: 1200,
            width: 1600,
            scale: 2,
          },
        }
      );
      try {
        if (chartRef.current && chartRef.current.offsetWidth > 0) {
          await Plotly.Plots.resize(chartRef.current).catch(() => { /* ignore */ });
        }
      } catch {
        /* ignore */
      }
    };

    render();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);

    const onResize = () => {
      if (plotlyRef.current && chartRef.current && chartRef.current.offsetWidth > 0) {
        try {
          plotlyRef.current.Plots.resize(chartRef.current).catch(() => { /* ignore */ });
        } catch {
          /* ignore */
        }
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [plot, filteredFigure, onClose]);

  if (!plot || !filteredFigure) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[1100] bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4 md:p-8"
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.96, opacity: 0 }}
        transition={{ type: "spring", damping: 24, stiffness: 260 }}
        className="w-full max-w-6xl h-full max-h-[92vh] bg-white rounded-2xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 bg-slate-50 flex-shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <BarChart3 className="w-4 h-4 text-ocean-500 shrink-0" />
            <span className="text-sm font-bold text-slate-800 truncate">
              {plot.title}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onDownloadCsv}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-white border border-slate-200 text-slate-600 hover:bg-slate-100 cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" />
              CSV
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-200 cursor-pointer"
              title="Close fullscreen (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 min-h-0 p-3 bg-white">
          <div
            ref={chartRef}
            className="w-full h-full"
            style={{ minHeight: 420 }}
          />
        </div>
      </motion.div>
    </motion.div>
  );
}

// ── Shared scientific layout ────────────────────────────────────────────────

function buildScientificLayout(
  figure: PlotlyFigure,
  opts: { height: number }
): Record<string, unknown> {
  const base = (figure.layout || {}) as Record<string, unknown>;
  const baseX = (base.xaxis || {}) as Record<string, unknown>;
  const baseY = (base.yaxis || {}) as Record<string, unknown>;
  const baseLegend = (base.legend || {}) as Record<string, unknown>;
  const baseTitle = base.title;

  return {
    ...base,
    paper_bgcolor: "#ffffff",
    plot_bgcolor: "#f8fafc",
    font: {
      family: "Inter, system-ui, sans-serif",
      color: "#334155",
      size: 12,
    },
    title: baseTitle
      ? typeof baseTitle === "string"
        ? {
            text: baseTitle,
            font: { size: 14, color: "#0f172a", family: "Inter, system-ui, sans-serif" },
            x: 0.02,
            xanchor: "left",
          }
        : {
            ...(baseTitle as object),
            font: {
              size: 14,
              color: "#0f172a",
              family: "Inter, system-ui, sans-serif",
            },
            x: 0.02,
            xanchor: "left",
          }
      : undefined,
    xaxis: {
      ...baseX,
      gridcolor: "#e2e8f0",
      linecolor: "#94a3b8",
      tickcolor: "#94a3b8",
      zerolinecolor: "#cbd5e1",
      tickfont: { color: "#475569", size: 11 },
      title: {
        ...((baseX.title as object) || {}),
        font: { color: "#334155", size: 12 },
      },
      automargin: true,
    },
    yaxis: {
      ...baseY,
      gridcolor: "#e2e8f0",
      linecolor: "#94a3b8",
      tickcolor: "#94a3b8",
      zerolinecolor: "#cbd5e1",
      tickfont: { color: "#475569", size: 11 },
      title: {
        ...((baseY.title as object) || {}),
        font: { color: "#334155", size: 12 },
      },
      automargin: true,
      // Preserve reversed pressure axis if set by backend
      autorange: baseY.autorange ?? undefined,
    },
    legend: {
      ...baseLegend,
      orientation: "h",
      yanchor: "top",
      y: -0.14,
      xanchor: "center",
      x: 0.5,
      bgcolor: "rgba(255,255,255,0.92)",
      bordercolor: "#e2e8f0",
      borderwidth: 1,
      font: { color: "#475569", size: 11 },
    },
    autosize: true,
    height: opts.height,
    margin: { l: 72, r: 28, t: 48, b: 88 },
    showlegend: true,
  };
}
