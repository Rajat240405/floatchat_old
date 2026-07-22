"use client";

import { motion } from "framer-motion";
import { Waves, Activity, Compass } from "lucide-react";
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
      className="flex items-center px-6 py-3 border-b border-slate-200 bg-white/95 backdrop-blur-sm sticky top-0 z-50 shadow-sm"
    >
      {/* Left: Logo only (Float ID search moved to Scientific Filters sidebar) */}
      <div className="flex items-center gap-2.5 min-w-[180px]">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-ocean-500/10 border border-ocean-500/20">
          <Waves className="w-4.5 h-4.5 text-ocean-500" />
        </div>
        <h1 className="text-[17px] font-semibold text-slate-800 tracking-[-0.3px]">
          FloatChat
        </h1>
      </div>

      <div className="flex-1" />

      {/* Single Live indicator only */}
      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-xs">
        <Activity className="w-3.5 h-3.5 text-emerald-600" />
        <span className="font-medium text-emerald-700">Live</span>
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      </div>

    </motion.header>
  );
}
