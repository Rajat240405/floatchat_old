"use client";

import { motion } from "framer-motion";
import { Waves, Activity, BarChart3 } from "lucide-react";

interface HeaderProps {
  floatSearch: string;
  onFloatSearchChange: (value: string) => void;
  onFloatSearchSubmit: () => void;
  isLoading?: boolean;
  plotCount?: number;
  plotsOpen?: boolean;
  onTogglePlots?: () => void;
  isFloatFocusMode?: boolean;
  focusFloatId?: string | null;
}

export function Header({
  plotCount = 0,
  plotsOpen = false,
  onTogglePlots,
  isFloatFocusMode = false,
  focusFloatId = null,
}: HeaderProps) {
  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex items-center px-6 py-3 border-b border-slate-200 bg-white/95 backdrop-blur-sm sticky top-0 z-50 shadow-sm gap-3"
    >
      <div className="flex items-center gap-2.5 min-w-[160px]">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-ocean-500/10 border border-ocean-500/20">
          <Waves className="w-4.5 h-4.5 text-ocean-500" />
        </div>
        <h1 className="text-[17px] font-semibold text-slate-800 tracking-[-0.3px]">
          FloatChat
        </h1>
      </div>

      <div className="flex-1" />

      {isFloatFocusMode && focusFloatId && (
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-full bg-ocean-50 border border-ocean-200">
          <span className="text-xs font-semibold text-ocean-700">
            Float {focusFloatId}
          </span>
        </div>
      )}

      {plotCount > 0 && onTogglePlots && (
        <button
          type="button"
          onClick={onTogglePlots}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors cursor-pointer ${
            plotsOpen
              ? "bg-ocean-500 text-white border-ocean-500 shadow-sm shadow-ocean-500/30"
              : "bg-white text-ocean-700 border-ocean-200 hover:bg-ocean-50"
          }`}
          title={plotsOpen ? "Hide Scientific Plots" : "Show Scientific Plots"}
        >
          <BarChart3 className="w-3.5 h-3.5" />
          Scientific Plots
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded-full font-bold ${
              plotsOpen
                ? "bg-white/20 text-white"
                : "bg-ocean-100 text-ocean-700"
            }`}
          >
            {plotCount}
          </span>
        </button>
      )}

      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-xs">
        <Activity className="w-3.5 h-3.5 text-emerald-600" />
        <span className="font-medium text-emerald-700">Live</span>
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      </div>
    </motion.header>
  );
}
