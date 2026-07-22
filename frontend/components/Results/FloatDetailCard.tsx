"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Anchor, MapPin, Calendar, Activity, Hash } from "lucide-react";
import { MapData } from "@/types";

interface FloatDetailCardProps {
  float: MapData;
  onClear: () => void;
  onDrillDown?: (query: string) => void;
}

export function FloatDetailCard({ float, onClear, onDrillDown }: FloatDetailCardProps) {
  const [showAllSensors, setShowAllSensors] = useState(false);
  const sensorsList = float.variables && float.variables.length > 0 ? float.variables : ["TEMP", "PSAL", "PRES"];
  const hasManySensors = sensorsList.length > 4;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      onPointerDown={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      className="rounded-2xl border border-surface-800/80 bg-surface-900 p-5 shadow-xl flex flex-col gap-4 text-surface-100 font-sans select-none pointer-events-auto"
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-surface-800/60">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-xl bg-ocean-500/15 border border-ocean-500/30 flex items-center justify-center text-ocean-400 shadow-2xs shrink-0">
            <Anchor className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <h3 className="text-base font-extrabold text-surface-100 tracking-tight truncate">
              Float {float.float_id}
            </h3>
            <p className="text-xs font-semibold text-surface-400 uppercase">
              {float.dac || "N/A"} · Selected Profile
            </p>
          </div>
        </div>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => {
            e.stopPropagation();
            onClear();
          }}
          className="text-xs font-bold text-surface-400 hover:text-surface-100 transition-colors px-3 py-1.5 rounded-xl bg-surface-800 hover:bg-surface-700 cursor-pointer shrink-0"
        >
          ✕ View All
        </button>
      </div>

      {/* Grid Specs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div className="p-3 rounded-xl bg-surface-950/60 border border-surface-800/60">
          <span className="text-surface-400 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[10px]">
            <Hash className="w-3.5 h-3.5 text-ocean-400" /> Float ID
          </span>
          <span className="font-extrabold text-surface-100 text-sm font-mono">
            {float.float_id}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-surface-950/60 border border-surface-800/60">
          <span className="text-surface-400 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[10px]">
            <Calendar className="w-3.5 h-3.5 text-emerald-400" /> Date
          </span>
          <span className="font-extrabold text-surface-100 text-xs truncate block">
            {float.profile_date
              ? new Date(float.profile_date).toLocaleDateString("en-GB", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                })
              : "N/A"}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-surface-950/60 border border-surface-800/60">
          <span className="text-surface-400 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[10px]">
            <MapPin className="w-3.5 h-3.5 text-amber-400" /> Latitude
          </span>
          <span className="font-extrabold text-surface-100 text-xs truncate block font-mono">
            {typeof float.latitude === "number"
              ? `${Math.abs(float.latitude).toFixed(2)}° ${float.latitude >= 0 ? "N" : "S"}`
              : "N/A"}
          </span>
        </div>

        <div className="p-3 rounded-xl bg-surface-950/60 border border-surface-800/60">
          <span className="text-surface-400 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[10px]">
            <MapPin className="w-3.5 h-3.5 text-violet-400" /> Longitude
          </span>
          <span className="font-extrabold text-surface-100 text-xs truncate block font-mono">
            {typeof float.longitude === "number"
              ? `${Math.abs(float.longitude).toFixed(2)}° ${float.longitude >= 0 ? "E" : "W"}`
              : "N/A"}
          </span>
        </div>
      </div>

      {/* Collapsible Sensors */}
      <div className="py-2 border-t border-surface-800/60">
        <p className="text-[11px] uppercase tracking-wider text-surface-400 font-bold mb-2">
          Payload Sensors ({sensorsList.length})
        </p>
        <div className="text-xs font-semibold text-surface-200 bg-surface-950/60 px-3.5 py-2.5 rounded-xl border border-surface-800/60 leading-relaxed text-center break-words max-h-[110px] overflow-y-auto scrollbar-thin">
          {(() => {
            if (!hasManySensors || showAllSensors) {
              return sensorsList.join(" • ");
            }
            return sensorsList.slice(0, 4).join(" • ") + ` • +${sensorsList.length - 4} more`;
          })()}
        </div>
        {hasManySensors && (
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setShowAllSensors(!showAllSensors);
            }}
            className="w-full mt-2 py-1.5 text-center text-xs font-bold text-ocean-400 hover:text-ocean-300 hover:bg-surface-800/60 rounded-xl transition-colors cursor-pointer flex items-center justify-center gap-1 select-none"
          >
            {showAllSensors ? "Show fewer sensors ▲" : `Show all sensors (${sensorsList.length}) ▼`}
          </button>
        )}
      </div>

      {/* Quick Actions (Minimum 44px Height) */}
      {onDrillDown && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-3 border-t border-surface-800/60">
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onClear();
              onDrillDown(`Sensors on float ${float.float_id}`);
            }}
            className="w-full min-h-[44px] py-2.5 px-4 rounded-xl bg-surface-800 hover:bg-surface-700 active:bg-surface-600 text-surface-100 font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-2xs border border-surface-700 cursor-pointer select-none"
          >
            🔍 View Metadata
          </button>
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              onClear();
              onDrillDown(`Show trajectory of float ${float.float_id}`);
            }}
            className="w-full min-h-[44px] py-2.5 px-4 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 active:from-ocean-700 active:to-ocean-600 text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-md shadow-ocean-500/25 border border-ocean-500/30 cursor-pointer select-none"
          >
            🛰 Show Trajectory
          </button>
        </div>
      )}
    </motion.div>
  );
}
