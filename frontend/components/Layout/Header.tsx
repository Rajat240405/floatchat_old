"use client";

import { motion } from "framer-motion";
import { Waves, Activity } from "lucide-react";

export function Header() {
  return (
    <motion.header
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex items-center justify-between px-6 py-4 border-b border-surface-800/60 bg-surface-950/80 backdrop-blur-md sticky top-0 z-50"
    >
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

      <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface-900 border border-surface-800">
        <Activity className="w-3.5 h-3.5 text-emerald-400" />
        <span className="text-xs font-medium text-surface-400">Live</span>
      </div>
    </motion.header>
  );
}
