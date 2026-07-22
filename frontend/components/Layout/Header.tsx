"use client";

import { motion } from "framer-motion";
import { Waves, Activity, Search, X, Compass } from "lucide-react";
import { useState, useCallback, useEffect } from "react";

interface HeaderProps {
  floatSearch: string;
  onFloatSearchChange: (value: string) => void;
  onFloatSearchSubmit: () => void;
  isLoading?: boolean;
}

export function Header({
  floatSearch,
  onFloatSearchChange,
  onFloatSearchSubmit,
  isLoading = false,
}: HeaderProps) {
  const [isFocused, setIsFocused] = useState(false);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        onFloatSearchSubmit();
      }
    },
    [onFloatSearchSubmit]
  );

  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex items-center justify-between px-6 py-3 border-b border-surface-800/60 bg-surface-950/80 backdrop-blur-md sticky top-0 z-50"
    >
      {/* Logo & Brand */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg bg-ocean-500/10 border border-ocean-500/20">
          <Waves className="w-5 h-5 text-ocean-400" />
        </div>
        <div>
          <h1 className="text-lg font-semibold text-surface-100 tracking-tight">
            FloatChat
          </h1>
          <p className="text-xs text-surface-500 font-medium">
            AI Ocean Intelligence Platform
          </p>
        </div>
      </div>

      {/* Global Float Search */}
      <div className="flex-1 max-w-md mx-8">
        <div
          className={`
            relative flex items-center rounded-xl border transition-all
            ${
              isFocused
                ? "border-ocean-500/50 bg-ocean-950/30 ring-2 ring-ocean-500/10"
                : "border-surface-700/60 bg-surface-900/50"
            }
          `}
        >
          <Search className="w-4 h-4 text-surface-500 ml-3 shrink-0" />
          <input
            type="text"
            value={floatSearch}
            onChange={(e) => onFloatSearchChange(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsFocused(true)}
            onBlur={() => setIsFocused(false)}
            placeholder="Search float by ID (e.g., 2902403)..."
            className="flex-1 px-3 py-2 bg-transparent text-sm text-surface-200 placeholder:text-surface-600 focus:outline-none"
          />
          {floatSearch && (
            <button
              onClick={() => onFloatSearchChange("")}
              className="p-1.5 mr-2 rounded-lg text-surface-500 hover:text-surface-300 hover:bg-surface-800/60 transition-colors cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={onFloatSearchSubmit}
            disabled={!floatSearch.trim() || isLoading}
            className="mr-2 px-3 py-1.5 rounded-lg bg-ocean-600 hover:bg-ocean-500 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-bold text-white transition-colors cursor-pointer"
          >
            {isLoading ? "..." : "Search"}
          </button>
        </div>
      </div>

      {/* Status Indicator */}
      <div className="flex items-center gap-4">
        {/* Quick Stats */}
        <div className="hidden md:flex items-center gap-4 text-xs text-surface-500">
          <div className="flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            <span>Live</span>
          </div>
        </div>

        {/* Status Badge */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-900 border border-surface-800">
          <Activity className="w-3.5 h-3.5 text-emerald-400" />
          <span className="text-xs font-medium text-surface-400">Live</span>
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        </div>
      </div>
    </motion.header>
  );
}
