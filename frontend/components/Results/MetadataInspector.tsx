"use client";

import { motion } from "framer-motion";
import {
  Waves,
  MapPin,
  Calendar,
  Activity,
  Battery,
  Hexagon,
  Layers,
  ChevronDown,
  Download,
  ExternalLink,
  Loader2,
  Star,
} from "lucide-react";
import { FloatRegistryInfo } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";
import { useState } from "react";
import type { AvailablePlotItem } from "@/services/api";

interface MetadataInspectorProps {
  info: FloatRegistryInfo;
  onViewTrajectory: () => void;
  onViewLatestProfile: () => void;
  onDownloadMetadata: () => void;
  isLoading?: boolean;
  availablePlots?: AvailablePlotItem[];
  isLoadingAvailablePlots?: boolean;
  onSelectPlot?: (variable: string) => void;
}

/** Display value or a consistent "Not Available" placeholder. */
function displayValue(v: unknown, opts?: { treatUnknown?: boolean }): string {
  if (v == null) return "Not Available";
  const s = String(v).trim();
  if (!s) return "Not Available";
  if (opts?.treatUnknown !== false) {
    const low = s.toLowerCase();
    if (low === "unknown" || low === "none" || low === "nan" || low === "n/a") {
      return "Not Available";
    }
  }
  return s;
}

const PLOT_EMOJI: Record<string, string> = {
  TEMP: "🌡",
  PSAL: "🧂",
  DOXY: "🫧",
  CHLA: "🌿",
  NITRATE: "🧪",
  BBP700: "✨",
  PH_IN_SITU_TOTAL: "⚗️",
  DOWNWELLING_PAR: "☀️",
};

export function MetadataInspector({
  info,
  onViewTrajectory,
  onViewLatestProfile,
  onDownloadMetadata,
  isLoading = false,
  availablePlots = [],
  isLoadingAvailablePlots = false,
  onSelectPlot,
}: MetadataInspectorProps) {
  const [showAllSensors, setShowAllSensors] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    platform: true,
    position: true,
    sensors: true,
    plots: true,
    status: true,
    actions: true,
  });

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const statusConfig = {
    active: {
      bg: "bg-emerald-50",
      border: "border-emerald-300",
      text: "text-emerald-700",
      dot: "bg-emerald-500 animate-pulse",
      label: "Active",
    },
    drifted: {
      bg: "bg-amber-50",
      border: "border-amber-300",
      text: "text-amber-700",
      dot: "bg-amber-500",
      label: "Drifted",
    },
    inactive: {
      bg: "bg-slate-100",
      border: "border-slate-300",
      text: "text-slate-500",
      dot: "bg-slate-400",
      label: "Inactive",
    },
  };

  const status = (info.status || "unknown").toLowerCase();
  const resolvedStatus = statusConfig[status as keyof typeof statusConfig] || {
    bg: "bg-slate-100",
    border: "border-slate-200",
    text: "text-slate-500",
    dot: "bg-slate-400",
    label: "Unknown",
  };

  // Battery: only show gauge when we have a real percentage estimate
  const batteryPct =
    typeof info.battery_percentage === "number" ? info.battery_percentage : null;
  const batteryStatus = info.battery_status || "";
  const hasBattery =
    batteryPct != null &&
    batteryStatus !== "" &&
    batteryStatus.toLowerCase() !== "unknown";

  const sensorsList =
    info.sensors && info.sensors.length > 0 ? info.sensors : [];
  const hasManySensors = sensorsList.length > 6;

  const network =
    info.network ||
    (sensorsList.some((s) =>
      ["DOXY", "CHLA", "NITRATE", "BBP", "PH", "PAR"].some((b) =>
        s.toUpperCase().includes(b)
      )
    )
      ? "BGC Argo"
      : "Core Argo");

  const firstProfile = formatDate(info.first_profile_date || info.deployment_date);
  const lastReport = formatDate(info.last_report_date);
  const profileCount =
    info.profile_count && info.profile_count > 0
      ? info.profile_count.toLocaleString()
      : "Not Available";

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col h-full overflow-hidden"
    >
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-ocean-50 to-slate-50 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-ocean-100 border border-ocean-200 flex items-center justify-center shadow-sm">
            <Waves className="w-5 h-5 text-ocean-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="fc-title">Float {info.float_id}</h2>
            <div className="flex items-center gap-2 mt-0.5">
              {info.wmo_id && info.wmo_id !== info.float_id && (
                <span className="fc-meta px-1.5 py-0.5 rounded bg-ocean-100 text-ocean-600">
                  WMO: {info.wmo_id}
                </span>
              )}
              <span
                className={`fc-meta px-1.5 py-0.5 rounded font-bold border ${resolvedStatus.bg} ${resolvedStatus.border} ${resolvedStatus.text}`}
              >
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${resolvedStatus.dot}`}
                />
                {resolvedStatus.label}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Platform */}
        <CollapsibleSection
          title="Platform Metadata"
          icon={<Hexagon className="w-3.5 h-3.5" />}
          isOpen={expandedSections.platform}
          onToggle={() => toggleSection("platform")}
        >
          <div className="grid grid-cols-2 gap-3">
            <MetadataField label="Float ID" value={info.float_id} mono />
            {info.wmo_id && (
              <MetadataField label="WMO ID" value={info.wmo_id} mono />
            )}
            <MetadataField
              label="DAC"
              value={displayValue(info.dac || info.institution)}
              highlight
            />
            <MetadataField label="Network" value={network} badge />
            <MetadataField
              label="Institution"
              value={displayValue(info.institution)}
              span
            />
            <MetadataField
              label="Platform Type"
              value={displayValue(info.platform_type)}
              span
            />
            <MetadataField
              label="Profiler"
              value={displayValue(info.profiler_type)}
              span
            />
            <MetadataField
              label="Manufacturer"
              value={displayValue(info.manufacturer)}
              span
            />
          </div>
        </CollapsibleSection>

        {/* Position & Time */}
        <CollapsibleSection
          title="Position & Time"
          icon={<MapPin className="w-3.5 h-3.5" />}
          isOpen={expandedSections.position}
          onToggle={() => toggleSection("position")}
        >
          <div className="grid grid-cols-2 gap-3">
            <MetadataField
              label="Latitude"
              value={
                info.last_lat != null ? formatLat(info.last_lat) : "Not Available"
              }
              mono
            />
            <MetadataField
              label="Longitude"
              value={
                info.last_lon != null ? formatLon(info.last_lon) : "Not Available"
              }
              mono
            />
            <MetadataField
              label="First Profile"
              value={firstProfile === "—" ? "Not Available" : firstProfile}
              icon={<Calendar className="w-3 h-3" />}
            />
            <MetadataField
              label="Last Report"
              value={lastReport === "—" ? "Not Available" : lastReport}
              icon={<Calendar className="w-3 h-3" />}
              highlight={
                !!info.last_report_date &&
                info.last_report_date !== info.first_profile_date
              }
            />
            {info.last_global_report_date && (
              <MetadataField
                label="Global Report"
                value={formatDate(info.last_global_report_date)}
                span
              />
            )}
            <MetadataField label="Profiles" value={profileCount} highlight />
          </div>
        </CollapsibleSection>

        {/* Sensors */}
        <CollapsibleSection
          title="Sensors & Variables"
          icon={<Layers className="w-3.5 h-3.5" />}
          isOpen={expandedSections.sensors}
          onToggle={() => toggleSection("sensors")}
          badge={sensorsList.length > 0 ? sensorsList.length.toString() : undefined}
        >
          {sensorsList.length === 0 ? (
            <p className="fc-meta">Not Available</p>
          ) : (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                {sensorsList
                  .slice(0, showAllSensors ? undefined : 8)
                  .map((sensor) => (
                    <span
                      key={sensor}
                      className="px-2 py-1 rounded-lg fc-meta font-semibold bg-ocean-50 text-ocean-600 border border-ocean-200"
                    >
                      {sensor}
                    </span>
                  ))}
              </div>
              {hasManySensors && (
                <button
                  onClick={() => setShowAllSensors(!showAllSensors)}
                  className="w-full py-1.5 text-center fc-meta font-bold text-ocean-500 hover:text-ocean-600 hover:bg-ocean-50 rounded-lg transition-colors cursor-pointer"
                >
                  {showAllSensors
                    ? "Show fewer sensors"
                    : `Show all sensors (${sensorsList.length})`}
                </button>
              )}
            </div>
          )}
        </CollapsibleSection>

        {/* Available Scientific Plots — deterministic catalogue */}
        <CollapsibleSection
          title="Available Scientific Plots"
          icon={<Layers className="w-3.5 h-3.5" />}
          isOpen={expandedSections.plots}
          onToggle={() => toggleSection("plots")}
          badge={
            availablePlots.length > 0
              ? String(availablePlots.length)
              : undefined
          }
        >
          {isLoadingAvailablePlots ? (
            <div className="flex items-center gap-2 fc-meta text-slate-500 py-2">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Detecting available measurements…
            </div>
          ) : availablePlots.length === 0 ? (
            <p className="fc-meta">No plottable variables found for this float.</p>
          ) : (
            <div className="grid grid-cols-1 gap-2">
              {availablePlots.map((plot) => (
                <button
                  key={plot.variable}
                  type="button"
                  onClick={() => onSelectPlot?.(plot.variable)}
                  disabled={isLoading}
                  className="w-full flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl bg-white hover:bg-ocean-50 border border-slate-200 hover:border-ocean-300 text-left transition-colors cursor-pointer disabled:opacity-50"
                >
                  <span className="flex items-center gap-2 min-w-0">
                    <span className="text-base leading-none" aria-hidden>
                      {PLOT_EMOJI[plot.variable] || "📊"}
                    </span>
                    <span className="fc-value text-slate-800 truncate">
                      {plot.title}
                    </span>
                  </span>
                  <span className="fc-meta shrink-0 tabular-nums">
                    {plot.profiles.toLocaleString()} profile
                    {plot.profiles === 1 ? "" : "s"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </CollapsibleSection>

        {/* Status / Battery */}
        <CollapsibleSection
          title="Status"
          icon={<Activity className="w-3.5 h-3.5" />}
          isOpen={expandedSections.status}
          onToggle={() => toggleSection("status")}
        >
          <div className="space-y-2">
            <p className="fc-meta leading-snug bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
              Status from registry: <span className="font-semibold capitalize">{status}</span>.
              {" "}Active = last report (in-region or global) within 365 days;
              Drifted = reporting globally but not in-region recently;
              Inactive = no reports for 365+ days.
            </p>
            <div className="flex items-center justify-between">
              <span className="fc-label flex items-center gap-1.5">
                <Battery className="w-3.5 h-3.5 text-amber-500" />
                Battery
              </span>
              {hasBattery ? (
                <span className="fc-meta font-bold text-slate-600">
                  {batteryStatus}
                  {info.battery_voltage != null
                    ? ` · ${info.battery_voltage}V`
                    : ""}
                </span>
              ) : (
                <span className="fc-meta">Not Available</span>
              )}
            </div>
            {hasBattery ? (
              <>
                <div className="relative h-2.5 bg-slate-200 rounded-full overflow-hidden border border-slate-300">
                  <div
                    className={`absolute left-0 top-0 h-full transition-all ${
                      batteryStatus === "Good"
                        ? "bg-emerald-500"
                        : batteryStatus === "Fair"
                          ? "bg-sky-500"
                          : batteryStatus === "Low"
                            ? "bg-amber-500"
                            : "bg-red-500"
                    }`}
                    style={{ width: `${Math.max(3, batteryPct ?? 0)}%` }}
                  />
                </div>
                <div className="flex items-center justify-between fc-meta">
                  <span>~{batteryPct}%</span>
                  <span>
                    {info.battery_voltage != null
                      ? `${info.battery_voltage}V`
                      : ""}
                  </span>
                </div>
                {info.battery_note &&
                  !String(info.battery_note).includes("Estimated from") && (
                    <p className="fc-meta italic leading-tight">
                      {info.battery_note}
                    </p>
                  )}
              </>
            ) : (
              <p className="fc-meta bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                Battery information unavailable
              </p>
            )}
          </div>
        </CollapsibleSection>
      </div>

      {/* Actions */}
      <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 flex-shrink-0">
        <div className="grid grid-cols-1 gap-2">
          <button
            onClick={onViewTrajectory}
            disabled={isLoading}
            className="w-full min-h-[40px] py-2.5 px-3 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 text-white fc-btn transition-all flex items-center justify-center gap-2 shadow-lg shadow-ocean-500/20 border border-ocean-500/25 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading...
              </>
            ) : (
              <>
                <Star className="w-4 h-4" />
                View Trajectory
              </>
            )}
          </button>
          <button
            onClick={onViewLatestProfile}
            className="w-full min-h-[36px] py-2 px-3 rounded-xl bg-white hover:bg-slate-50 text-slate-700 fc-btn transition-all flex items-center justify-center gap-2 border border-slate-200 hover:border-slate-300 cursor-pointer shadow-sm"
          >
            <ExternalLink className="w-4 h-4" />
            Show Latest Profile
          </button>
          <button
            onClick={onDownloadMetadata}
            className="w-full min-h-[36px] py-2 px-3 rounded-xl bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-700 fc-btn font-medium transition-all flex items-center justify-center gap-2 border border-slate-200 cursor-pointer"
          >
            <Download className="w-4 h-4" />
            Download Metadata
          </button>
        </div>
      </div>
    </motion.div>
  );
}

interface CollapsibleSectionProps {
  title: string;
  icon: React.ReactNode;
  isOpen: boolean;
  onToggle: () => void;
  badge?: string;
  children: React.ReactNode;
}

function CollapsibleSection({
  title,
  icon,
  isOpen,
  onToggle,
  badge,
  children,
}: CollapsibleSectionProps) {
  return (
    <div className="border-b border-slate-200">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-slate-50 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <span className="text-ocean-500">{icon}</span>
          <span className="fc-heading">{title}</span>
          {badge && (
            <span className="fc-meta px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-600 font-bold">
              {badge}
            </span>
          )}
        </div>
        <ChevronDown
          className={`w-4 h-4 text-slate-400 transition-transform ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </button>
      {isOpen && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="px-4 pb-4">{children}</div>
        </motion.div>
      )}
    </div>
  );
}

interface MetadataFieldProps {
  label: string;
  value: string;
  mono?: boolean;
  highlight?: boolean;
  icon?: React.ReactNode;
  badge?: boolean;
  span?: boolean;
}

function MetadataField({
  label,
  value,
  mono,
  highlight,
  icon,
  badge,
  span,
}: MetadataFieldProps) {
  const isNA = value === "Not Available" || value === "—";
  return (
    <div className={span ? "col-span-2" : ""}>
      <span className="fc-label block mb-0.5">{label}</span>
      <span
        className={`
          fc-value block truncate
          ${mono ? "font-mono" : ""}
          ${highlight && !isNA ? "text-ocean-600 font-semibold" : ""}
          ${isNA ? "text-slate-400 italic font-normal" : ""}
          ${
            badge
              ? "inline-flex items-center gap-1 px-2 py-0.5 rounded bg-ocean-50 border border-ocean-200 text-ocean-600"
              : ""
          }
        `}
      >
        {icon && !isNA && <span className="opacity-60 mr-1">{icon}</span>}
        {value}
      </span>
    </div>
  );
}
