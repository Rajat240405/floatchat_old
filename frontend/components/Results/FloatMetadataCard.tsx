"use client";

import React, { useState } from "react";
import { motion } from "framer-motion";
import { Cpu, Calendar, Hash, Building2, Activity, Battery, Factory, Waves } from "lucide-react";
import { FloatRegistryInfo } from "@/types";

interface FloatMetadataCardProps {
  info: FloatRegistryInfo;
  onDrillDown?: (query: string) => void;
}

export function FloatMetadataCard({ info, onDrillDown }: FloatMetadataCardProps) {
  const [showAllSensors, setShowAllSensors] = useState(false);

  const statusStyle =
    info.status === "active"
      ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/25"
      : info.status === "drifted"
        ? "bg-amber-500/10 text-amber-400 border-amber-500/25"
        : "bg-slate-100 text-slate-500 border-slate-200";

  const dotStyle =
    info.status === "active"
      ? "bg-emerald-400 animate-pulse"
      : info.status === "drifted"
        ? "bg-amber-400"
        : "bg-surface-500";

  const sensorsList = info.sensors && info.sensors.length > 0 ? info.sensors : ["TEMP", "PSAL", "PRES"];
  const hasManySensors = sensorsList.length > 4;

  // Battery status
  const batteryPct = info.battery_percentage;
  const batteryVoltage = info.battery_voltage;
  const batteryStatus = info.battery_status || "Unknown";

  const batteryColorClass =
    batteryStatus === "Good" ? "text-emerald-400" :
      batteryStatus === "Fair" ? "text-sky-400" :
        batteryStatus === "Low" ? "text-amber-400" :
          batteryStatus === "Critical" ? "text-red-400" :
            batteryStatus === "Depleted" ? "text-red-500" :
              "text-slate-500";

  const batteryBarColor =
    batteryStatus === "Good" ? "bg-emerald-500" :
      batteryStatus === "Fair" ? "bg-sky-500" :
        batteryStatus === "Low" ? "bg-amber-500" :
          batteryStatus === "Critical" || batteryStatus === "Depleted" ? "bg-red-500" :
            "bg-surface-700";

  const manufacturer = info.manufacturer && info.manufacturer !== "unknown"
    ? info.manufacturer
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      onClick={(e) => e.stopPropagation()}
      className="p-5 rounded-2xl bg-white border border-slate-200 shadow-[0_16px_48px_-8px_rgba(0,0,0,0.5)] flex flex-col gap-4 text-slate-800 pointer-events-auto select-none font-sans"
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-slate-200">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-ocean-500/20 to-ocean-700/10 border border-ocean-500/25 flex items-center justify-center shadow-inner">
            <Waves className="w-5 h-5 text-ocean-400" />
          </div>
          <div>
            <h3 className="text-base font-extrabold text-slate-900 tracking-tight flex items-center gap-2">
              Float {info.float_id}
            </h3>
            <p className="text-[11px] font-semibold text-slate-500">
              {info.institution !== "unknown" ? info.institution.toUpperCase() : "Argo Registry"} · {info.platform_type !== "unknown" ? info.platform_type : "Profiler"}
            </p>
          </div>
        </div>

        <span className={`flex items-center gap-1.5 text-[10px] px-2.5 py-1 rounded-full uppercase font-bold border shadow-sm ${statusStyle}`}>
          <span className={`w-2 h-2 rounded-full shrink-0 ${dotStyle}`} />
          {info.status || "unknown"}
        </span>
      </div>

      {/* Manufacturer Bar */}
      {manufacturer && (
        <div className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-ocean-950/40 border border-ocean-700/25">
          <Factory className="w-4 h-4 text-ocean-400 shrink-0" />
          <div className="flex-1 min-w-0">
            <span className="text-[9px] uppercase tracking-wider text-ocean-500/70 font-bold block">Manufacturer</span>
            <p className="text-xs font-bold text-ocean-200 truncate">{manufacturer}</p>
          </div>
        </div>
      )}

      {/* Grid Specs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 text-xs">
        <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-slate-500 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[9px]">
            <Hash className="w-3 h-3 text-ocean-400" /> Profiles
          </span>
          <span className="font-extrabold text-slate-800 text-sm">
            {info.profile_count > 0 ? info.profile_count.toLocaleString() : "N/A"}
          </span>
        </div>

        <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-slate-500 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[9px]">
            <Calendar className="w-3 h-3 text-emerald-400" /> First
          </span>
          <span className="font-bold text-slate-700 text-[11px] truncate block">
            {info.first_profile_date
              ? new Date(info.first_profile_date).toLocaleDateString("en-GB", {
                  day: "2-digit", month: "short", year: "numeric",
                })
              : "N/A"}
          </span>
        </div>

        <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-slate-500 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[9px]">
            <Activity className="w-3 h-3 text-amber-400" /> Last Report
          </span>
          <span className="font-bold text-slate-700 text-[11px] truncate block">
            {info.last_report_date
              ? new Date(info.last_report_date).toLocaleDateString("en-GB", {
                  day: "2-digit", month: "short", year: "numeric",
                })
              : "N/A"}
          </span>
        </div>

        <div className="p-2.5 rounded-xl bg-slate-50 border border-slate-200">
          <span className="text-slate-500 font-semibold flex items-center gap-1.5 mb-1 uppercase tracking-wider text-[9px]">
            <Building2 className="w-3 h-3 text-violet-400" /> Profiler
          </span>
          <span className="font-bold text-slate-700 text-[11px] truncate block">
            {info.profiler_type !== "unknown" ? info.profiler_type : "N/A"}
          </span>
        </div>
      </div>

      {/* Battery Status */}
      <div className="px-3 py-3 rounded-xl bg-slate-50 border border-slate-200">
        <div className="flex items-center justify-between mb-2">
          <span className="text-slate-500 font-semibold flex items-center gap-1.5 uppercase tracking-wider text-[9px]">
            <Battery className="w-3.5 h-3.5 text-amber-400" /> Battery Status
          </span>
          <span className={`text-[11px] font-extrabold ${batteryColorClass}`}>
            {batteryStatus}
          </span>
        </div>

        {/* Battery bar */}
        <div className="relative h-2.5 bg-slate-100 rounded-full overflow-hidden border border-slate-200">
          <div
            className={`absolute left-0 top-0 h-full rounded-full transition-all ${batteryBarColor}`}
            style={{ width: `${Math.max(3, batteryPct ?? 0)}%` }}
          />
        </div>

        <div className="flex items-center justify-between mt-1.5 text-[10px]">
          <span className="text-slate-500 font-medium">
            {batteryPct !== null && batteryPct !== undefined ? `~${batteryPct}%` : "N/A"}
          </span>
          <span className="text-slate-700 font-bold">
            {batteryVoltage !== null && batteryVoltage !== undefined ? `${batteryVoltage}V` : "N/A"}
          </span>
        </div>

        {info.battery_note && !info.battery_note.includes("Estimated from operational data") && (
          <p className="text-[9px] text-slate-500 mt-1 italic leading-tight">{info.battery_note}</p>
        )}
      </div>

      {/* Sensors Section */}
      <div className="py-2 border-t border-slate-200">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-2">
          Payload Sensors ({sensorsList.length})
        </p>
        <div className="text-[11px] font-semibold text-slate-700 bg-slate-100 px-3 py-2 rounded-lg border border-slate-200 leading-relaxed text-center break-words max-h-[80px] overflow-y-auto scrollbar-thin">
          {(() => {
            if (!hasManySensors || showAllSensors) return sensorsList.join(" • ");
            return sensorsList.slice(0, 4).join(" • ") + ` • +${sensorsList.length - 4} more`;
          })()}
        </div>
        {hasManySensors && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setShowAllSensors(!showAllSensors);
            }}
            className="w-full mt-2 py-1.5 text-center text-[10px] font-bold text-ocean-400 hover:text-ocean-300 hover:bg-ocean-500/10 rounded-lg transition-colors cursor-pointer"
          >
            {showAllSensors ? "Show fewer sensors ▲" : `Show all sensors (${sensorsList.length}) ▼`}
          </button>
        )}
      </div>

      {/* Action Buttons */}
      {onDrillDown && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-3 border-t border-slate-200">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDrillDown(`Sensors on float ${info.float_id}`);
            }}
            className="w-full min-h-[42px] py-2.5 px-3 rounded-xl bg-slate-100 hover:bg-surface-700 active:bg-surface-600 text-slate-800 font-bold text-[11px] transition-all flex items-center justify-center gap-2 border border-slate-200 cursor-pointer"
          >
            🔍 View Metadata
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDrillDown(`Show trajectory of float ${info.float_id}`);
            }}
            className="w-full min-h-[42px] py-2.5 px-3 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 active:from-ocean-700 active:to-ocean-600 text-white font-bold text-[11px] transition-all flex items-center justify-center gap-2 shadow-lg shadow-ocean-500/20 border border-ocean-500/25 cursor-pointer"
          >
            🛰 Show Trajectory
          </button>
        </div>
      )}
    </motion.div>
  );
}
