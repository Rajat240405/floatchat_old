"use client";

import { useEffect, useRef, useMemo, useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart3, Layers, Eye, Maximize2, Minimize2 } from "lucide-react";
import { PlotlyFigure } from "@/types";

interface PlotlyChartProps {
  figure: PlotlyFigure | null | undefined;
  selectedFloat: string | null;
  onClearSelection: () => void;
  /** Optional list of float IDs for an inline selector. */
  floatIds?: string[];
  onSelectFloat?: (id: string | null) => void;
}

export function PlotlyChart({
  figure,
  selectedFloat,
  onClearSelection,
  floatIds = [],
  onSelectFloat,
}: PlotlyChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const plotlyRef = useRef<typeof import("plotly.js-dist-min") | null>(null);
  const [isExpanded, setIsExpanded] = useState(false);

  // Filter traces when a float is selected
  const filteredFigure = useMemo(() => {
    if (!figure) return null;
    if (!selectedFloat) return figure;

    const targetName = `Float ${selectedFloat}`;
    const filteredData = figure.data.filter((trace) => {
      const name = String(trace.name || "");
      if (!/Float\s+\d+/i.test(name)) return true;
      return name === targetName || name.includes(selectedFloat);
    });

    if (filteredData.length === 0) return figure;

    return {
      ...figure,
      data: filteredData,
    };
  }, [figure, selectedFloat]);

  const renderChart = useCallback(async () => {
    if (!filteredFigure || !containerRef.current) return;
    const Plotly = await import("plotly.js-dist-min");
    plotlyRef.current = Plotly;
    if (!containerRef.current) return;

    const height = isExpanded ? Math.max(640, window.innerHeight - 220) : 480;

    const layout = {
      ...(filteredFigure.layout as Partial<Plotly.Layout>),
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#f8fafc",
      font: {
        family: "Inter, system-ui, sans-serif",
        color: "#334155",
        size: 12,
      },
      autosize: true,
      height,
      margin: { l: 72, r: 28, t: 48, b: 88 },
      legend: {
        ...(((filteredFigure.layout as Record<string, unknown>)?.legend ||
          {}) as object),
        orientation: "h" as const,
        y: -0.14,
        x: 0.5,
        xanchor: "center" as const,
        bgcolor: "rgba(255,255,255,0.92)",
        bordercolor: "#e2e8f0",
        borderwidth: 1,
        font: { color: "#475569", size: 11 },
      },
      xaxis: {
        ...(((filteredFigure.layout as Record<string, unknown>)?.xaxis ||
          {}) as Record<string, unknown>),
        gridcolor: "#e2e8f0",
        zerolinecolor: "#cbd5e1",
        automargin: true,
      },
      yaxis: {
        ...(((filteredFigure.layout as Record<string, unknown>)?.yaxis ||
          {}) as Record<string, unknown>),
        gridcolor: "#e2e8f0",
        zerolinecolor: "#cbd5e1",
        automargin: true,
      },
      showlegend: true,
    };

    await Plotly.react(
      containerRef.current,
      filteredFigure.data as Plotly.Data[],
      layout,
      {
        responsive: true,
        displayModeBar: true,
        displaylogo: false,
        modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
        toImageButtonOptions: {
          format: "png",
          filename: "floatchat_plot",
          height: 900,
          width: 1200,
          scale: 2,
        },
      }
    );
    try {
      await Plotly.Plots.resize(containerRef.current);
    } catch {
      /* ignore */
    }
  }, [filteredFigure, isExpanded]);

  useEffect(() => {
    let destroyed = false;
    (async () => {
      if (destroyed) return;
      await renderChart();
    })();
    return () => {
      destroyed = true;
    };
  }, [renderChart]);

  // ResizeObserver keeps plot responsive inside flex layouts
  useEffect(() => {
    if (!containerRef.current) return;
    const el = containerRef.current;
    const ro = new ResizeObserver(() => {
      if (plotlyRef.current && el) {
        try {
          plotlyRef.current.Plots.resize(el);
        } catch {
          /* ignore */
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (!figure) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400">
        <BarChart3 className="w-8 h-8" />
        <p className="text-sm">No visualization available for this query.</p>
      </div>
    );
  }

  const ids =
    floatIds.length > 0
      ? floatIds
      : Array.from(
          new Set(
            (figure.data || [])
              .map((t) => {
                const m = String(t.name || "").match(/Float\s+(\d{5,})/i);
                return m ? m[1] : null;
              })
              .filter(Boolean) as string[]
          )
        );

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2 }}
      className="w-full"
    >
      {/* Chart header with view toggle */}
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-ocean-400" />
          <span className="text-sm font-medium text-slate-700">
            Visualization
          </span>
        </div>

        <div className="flex items-center gap-2">
          <AnimatePresence mode="wait">
            {selectedFloat ? (
              <motion.button
                key="selected"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                onClick={onClearSelection}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ocean-500/10 border border-ocean-500/20 text-xs font-medium text-ocean-600 hover:bg-ocean-500/20 transition-colors cursor-pointer"
              >
                <Eye className="w-3 h-3" />
                Float {selectedFloat}
                <span className="text-ocean-500 ml-0.5">✕</span>
              </motion.button>
            ) : (
              <motion.div
                key="all"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-slate-100 border border-slate-300 text-xs font-medium text-slate-500"
              >
                <Layers className="w-3 h-3" />
                All Profiles
              </motion.div>
            )}
          </AnimatePresence>

          <button
            type="button"
            onClick={() => setIsExpanded((v) => !v)}
            className="p-1.5 rounded-lg border border-slate-200 text-slate-500 hover:text-ocean-600 hover:bg-ocean-50 cursor-pointer"
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

      {/* Inline float selector for multi-float figures */}
      {ids.length > 1 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          <button
            type="button"
            onClick={() => onSelectFloat?.(null) ?? onClearSelection()}
            className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border cursor-pointer ${
              !selectedFloat
                ? "bg-ocean-500 text-white border-ocean-500"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
            }`}
          >
            All Floats
          </button>
          {ids.map((fid) => (
            <button
              key={fid}
              type="button"
              onClick={() => onSelectFloat?.(fid)}
              className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border cursor-pointer font-mono ${
                selectedFloat === fid
                  ? "bg-ocean-500 text-white border-ocean-500"
                  : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50"
              }`}
            >
              {fid}
            </button>
          ))}
        </div>
      )}

      <div
        ref={containerRef}
        className="w-full rounded-lg border border-slate-200 bg-white"
        style={{ minHeight: isExpanded ? 640 : 480 }}
      />
    </motion.div>
  );
}
