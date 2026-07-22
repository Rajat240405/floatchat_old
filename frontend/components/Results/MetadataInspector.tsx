"use client";

import { motion } from "framer-motion";
import {
  Waves,
  MapPin,
  Calendar,
  Activity,
  Battery,
  Factory,
  Hexagon,
  Layers,
  Building2,
  ChevronDown,
  Download,
  ExternalLink,
  Loader2,
  Star,
} from "lucide-react";
import { FloatRegistryInfo } from "@/types";
import { formatDate, formatLat, formatLon } from "@/lib/utils";
import { useState } from "react";

interface MetadataInspectorProps {
  info: FloatRegistryInfo;
  onViewTrajectory: () => void;
  onViewLatestProfile: () => void;
  onDownloadMetadata: () => void;
  isLoading?: boolean;
}

export function MetadataInspector({
  info,
  onViewTrajectory,
  onViewLatestProfile,
  onDownloadMetadata,
  isLoading = false,
}: MetadataInspectorProps) {
  const [showAllSensors, setShowAllSensors] = useState(false);
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    platform: true,
    position: true,
    sensors: true,
    status: true,
    actions: true,
  });

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  // Status styling — light theme
  const statusConfig = {
    active: {
      bg: "bg-emerald-50", border: "border-emerald-300", text: "text-emerald-700",
      dot: "bg-emerald-500 animate-pulse", label: "Active",
    },
    drifted: {
      bg: "bg-amber-50", border: "border-amber-300", text: "text-amber-700",
      dot: "bg-amber-500", label: "Drifted",
    },
    inactive: {
      bg: "bg-slate-100", border: "border-slate-300", text: "text-slate-500",
      dot: "bg-slate-400", label: "Inactive",
    },
  };

  const status = info.status || "unknown";
  const resolvedStatus = statusConfig[status as keyof typeof statusConfig] || {
    bg: "bg-slate-100", border: "border-slate-200", text: "text-slate-500",
    dot: "bg-slate-400", label: "Unknown",
  };

  // Battery styling
  const batteryPct = info.battery_percentage ?? 0;
  const batteryStatus = info.battery_status || "Unknown";
  const batteryColor =
    batteryStatus === "Good"
      ? "bg-emerald-500"
      : batteryStatus === "Fair"
        ? "bg-sky-500"
        : batteryStatus === "Low"
          ? "bg-amber-500"
          : "bg-red-500";

  const sensorsList =
    info.sensors && info.sensors.length > 0
      ? info.sensors
      : ["TEMP", "PSAL", "PRES"];
  const hasManySensors = sensorsList.length > 6;

  // Network badge
  const network = info.network || (sensorsList.some((s) =>
    ["DOXY", "CHLA", "NITRATE", "BBP", "PH", "PAR"].some((b) =>
      s.toUpperCase().includes(b)
    )
  ) ? "BGC Argo" : "Core Argo");

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
            <h2 className="text-base font-extrabold text-slate-800 tracking-tight">
              Float {info.float_id}
            </h2>
            <div className="flex items-center gap-2 mt-0.5">
              {info.wmo_id && info.wmo_id !== info.float_id && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-ocean-100 text-ocean-600 font-medium">
                  WMO: {info.wmo_id}
                </span>
              )}
              <span className={`text-[10px] px-1.5 py-0.5 rounded ${resolvedStatus.bg} ${resolvedStatus.border} ${resolvedStatus.text} font-bold border`}>
                <span className={`inline-block w-1.5 h-1.5 rounded-full mr-1 ${resolvedStatus.dot}`} />
                {resolvedStatus.label}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Platform Metadata Section */}
        <CollapsibleSection
          title="Platform Metadata"
          icon={<Hexagon className="w-3.5 h-3.5" />}
          isOpen={expandedSections.platform}
          onToggle={() => toggleSection("platform")}
        >
          <div className="grid grid-cols-2 gap-3">
            <MetadataField
              label="Float ID"
              value={info.float_id}
              mono
            />
            {info.wmo_id && (
              <MetadataField
                label="WMO ID"
                value={info.wmo_id}
                mono
              />
            )}
            <MetadataField
              label="DAC"
              value={info.dac || info.institution || "N/A"}
              highlight
            />
            <MetadataField
              label="Network"
              value={network}
              badge
            />
            <MetadataField
              label="Institution"
              value={info.institution !== "unknown" ? info.institution : "N/A"}
              span
            />
            <MetadataField
              label="Platform Type"
              value={info.platform_type !== "unknown" ? info.platform_type : "N/A"}
              span
            />
            <MetadataField
              label="Profiler"
              value={info.profiler_type !== "unknown" ? info.profiler_type : "N/A"}
              span
            />
            {info.manufacturer && info.manufacturer !== "unknown" && (
              <MetadataField
                label="Manufacturer"
                value={info.manufacturer}
                span
              />
            )}
          </div>
        </CollapsibleSection>

        {/* Position & Time Section */}
        <CollapsibleSection
          title="Position & Time"
          icon={<MapPin className="w-3.5 h-3.5" />}
          isOpen={expandedSections.position}
          onToggle={() => toggleSection("position")}
        >
          <div className="grid grid-cols-2 gap-3">
            <MetadataField
              label="Latitude"
              value={info.last_lat != null ? formatLat(info.last_lat) : "N/A"}
              mono
            />
            <MetadataField
              label="Longitude"
              value={info.last_lon != null ? formatLon(info.last_lon) : "N/A"}
              mono
            />
            <MetadataField
              label="First Profile"
              value={formatDate(info.first_profile_date || info.deployment_date)}
              icon={<Calendar className="w-3 h-3" />}
            />
            <MetadataField
              label="Last Report"
              value={formatDate(info.last_report_date)}
              icon={<Calendar className="w-3 h-3" />}
              highlight={info.last_report_date !== info.first_profile_date}
            />
            {info.last_global_report_date && (
              <MetadataField
                label="Global Report"
                value={formatDate(info.last_global_report_date)}
                span
              />
            )}
            <MetadataField
              label="Profiles"
              value={info.profile_count > 0 ? info.profile_count.toLocaleString() : "N/A"}
              highlight
            />
          </div>
        </CollapsibleSection>

        {/* Sensors & Variables Section */}
        <CollapsibleSection
          title="Sensors & Variables"
          icon={<Layers className="w-3.5 h-3.5" />}
          isOpen={expandedSections.sensors}
          onToggle={() => toggleSection("sensors")}
          badge={sensorsList.length.toString()}
        >
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {sensorsList.slice(0, showAllSensors ? undefined : 8).map((sensor) => (
                <span
                  key={sensor}
                  className="px-2 py-1 rounded-lg text-[11px] font-semibold bg-ocean-50 text-ocean-600 border border-ocean-200"
                >
                  {sensor}
                </span>
              ))}
            </div>
            {hasManySensors && (
              <button
                onClick={() => setShowAllSensors(!showAllSensors)}
                className="w-full py-1.5 text-center text-[10px] font-bold text-ocean-400 hover:text-ocean-300 hover:bg-ocean-500/10 rounded-lg transition-colors cursor-pointer"
              >
                {showAllSensors
                  ? "Show fewer sensors"
                  : `Show all sensors (${sensorsList.length})`}
              </button>
            )}
          </div>
        </CollapsibleSection>

        {/* Status Section */}
        <CollapsibleSection
          title="Status"
          icon={<Activity className="w-3.5 h-3.5" />}
          isOpen={expandedSections.status}
          onToggle={() => toggleSection("status")}
        >
          {/* Battery */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold flex items-center gap-1.5">
                <Battery className="w-3.5 h-3.5 text-amber-500" />
                Battery Status
              </span>
              <span
                className={`text-[11px] font-bold ${
                  batteryStatus === "Good"
                    ? "text-emerald-600"
                    : batteryStatus === "Fair"
                      ? "text-sky-600"
                      : batteryStatus === "Low"
                        ? "text-amber-600"
                        : "text-slate-400"
                }`}
              >
                {batteryStatus}
              </span>
            </div>
            <div className="relative h-2.5 bg-slate-200 rounded-full overflow-hidden border border-slate-300">
              <div
                className={`absolute left-0 top-0 h-full ${batteryColor} transition-all`}
                style={{ width: `${Math.max(3, batteryPct)}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-slate-500">
              <span>{batteryPct > 0 ? `~${batteryPct}%` : "N/A"}</span>
              <span>{info.battery_voltage != null ? `${info.battery_voltage}V` : "N/A"}</span>
            </div>
            {info.battery_note && !info.battery_note.includes("Estimated from") && (
              <p className="text-[9px] text-slate-400 italic leading-tight">{info.battery_note}</p>
            )}
          </div>
        </CollapsibleSection>
      </div>

      {/* Actions Footer */}
      <div className="px-4 py-3 border-t border-slate-200 bg-slate-50 flex-shrink-0">
        <div className="grid grid-cols-1 gap-2">
          <button
            onClick={onViewTrajectory}
            disabled={isLoading}
            className="w-full min-h-[40px] py-2.5 px-3 rounded-xl bg-gradient-to-r from-ocean-600 to-ocean-500 hover:from-ocean-500 hover:to-ocean-400 active:from-ocean-700 active:to-ocean-600 text-white font-bold text-xs transition-all flex items-center justify-center gap-2 shadow-lg shadow-ocean-500/20 border border-ocean-500/25 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
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
            className="w-full min-h-[36px] py-2 px-3 rounded-xl bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-700 font-bold text-xs transition-all flex items-center justify-center gap-2 border border-slate-200 hover:border-slate-300 cursor-pointer shadow-sm"
          >
            <ExternalLink className="w-4 h-4" />
            View Latest Profile
          </button>
          <button
            onClick={onDownloadMetadata}
            className="w-full min-h-[36px] py-2 px-3 rounded-xl bg-white hover:bg-slate-50 text-slate-500 hover:text-slate-700 font-medium text-xs transition-all flex items-center justify-center gap-2 border border-slate-200 cursor-pointer"
          >
            <Download className="w-4 h-4" />
            Download Metadata
          </button>
        </div>
      </div>
    </motion.div>
  );
}

// Collapsible Section Component
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
          <span className="text-xs font-semibold text-slate-600">{title}</span>
          {badge && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-600 font-bold">
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

// Metadata Field Component
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
  return (
    <div className={span ? "col-span-2" : ""}>
      <span className="text-[9px] uppercase tracking-wider text-slate-400 font-semibold block mb-0.5">
        {label}
      </span>
      <span
        className={`
          text-xs font-medium block truncate
          ${mono ? "font-mono text-slate-700" : "text-slate-600"}
          ${highlight ? "text-ocean-600 font-semibold" : ""}
          ${badge ? "inline-flex items-center gap-1 px-2 py-0.5 rounded bg-ocean-50 border border-ocean-200 text-ocean-600" : ""}
        `}
      >
        {icon && <span className="opacity-60">{icon}</span>}
        {value}
      </span>
    </div>
  );
}
