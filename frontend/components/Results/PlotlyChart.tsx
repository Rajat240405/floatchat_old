"use client";

import { useEffect, useRef, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BarChart3, Layers, Eye } from "lucide-react";
import { PlotlyFigure } from "@/types";

interface PlotlyChartProps {
  figure: PlotlyFigure | null | undefined;
  selectedFloat: string | null;
  onClearSelection: () => void;
}

export function PlotlyChart({
  figure,
  selectedFloat,
  onClearSelection,
}: PlotlyChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Filter traces when a float is selected
  const filteredFigure = useMemo(() => {
    if (!figure) return null;
    if (!selectedFloat) return figure;

    const targetName = `Float ${selectedFloat}`;
    const filteredData = figure.data.filter(
      (trace) => trace.name === targetName
    );

    if (filteredData.length === 0) return figure; // fallback

    return {
      ...figure,
      data: filteredData,
    };
  }, [figure, selectedFloat]);

  useEffect(() => {
    if (!filteredFigure || !containerRef.current) return;

    let destroyed = false;

    const render = async () => {
      const Plotly = await import("plotly.js-dist-min");
      if (destroyed || !containerRef.current) return;

      const layout = {
        ...(filteredFigure.layout as Partial<Plotly.Layout>),
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: {
          family: "Inter, system-ui, sans-serif",
          color: "#94a3b8",
        },
        autosize: true,
        xaxis: {
          ...(((filteredFigure.layout as Record<string, unknown>)?.xaxis || {}) as Record<string, unknown>),
          gridcolor: "rgba(148, 163, 184, 0.1)",
          zerolinecolor: "rgba(148, 163, 184, 0.2)",
        },
        yaxis: {
          ...(((filteredFigure.layout as Record<string, unknown>)?.yaxis || {}) as Record<string, unknown>),
          gridcolor: "rgba(148, 163, 184, 0.1)",
          zerolinecolor: "rgba(148, 163, 184, 0.2)",
        },
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
        }
      );
    };

    render();

    return () => {
      destroyed = true;
    };
  }, [filteredFigure]);

  if (!figure) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-surface-600">
        <BarChart3 className="w-8 h-8" />
        <p className="text-sm">No visualization available for this query.</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.2 }}
      className="w-full"
    >
      {/* Chart header with view toggle */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-ocean-400" />
          <span className="text-sm font-medium text-surface-300">
            Visualization
          </span>
        </div>

        <AnimatePresence mode="wait">
          {selectedFloat ? (
            <motion.button
              key="selected"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              onClick={onClearSelection}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ocean-500/10 border border-ocean-500/20 text-xs font-medium text-ocean-400 hover:bg-ocean-500/20 transition-colors"
            >
              <Eye className="w-3 h-3" />
              Float {selectedFloat}
              <span className="text-ocean-600 ml-0.5">✕</span>
            </motion.button>
          ) : (
            <motion.div
              key="all"
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9 }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-surface-800 border border-surface-700 text-xs font-medium text-surface-500"
            >
              <Layers className="w-3 h-3" />
              All Profiles
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div
        ref={containerRef}
        className="w-full rounded-lg border border-surface-800/60 bg-surface-900/30"
        style={{ minHeight: 480 }}
      />
    </motion.div>
  );
}
