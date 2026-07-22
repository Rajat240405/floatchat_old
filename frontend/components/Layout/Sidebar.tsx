"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Filter,
  MapPin,
  Layers,
  Activity,
  Calendar,
  Crosshair,
  ChevronDown,
  X,
  RefreshCw,
} from "lucide-react";
import { FilterState, EMPTY_FILTERS } from "@/types";
import { cn, hasActiveFilters } from "@/lib/utils";

interface SidebarFiltersProps {
  filters: FilterState;
  onFiltersChange: (f: FilterState) => void;
  availableOptions: {
    networks: string[];
    dacs: string[];
    variables: string[];
    statuses: string[];
  };
  floatCount: number;
  onRefresh: () => void;
  isLoading: boolean;
}

export function SidebarFilters({
  filters,
  onFiltersChange,
  availableOptions,
  floatCount,
  onRefresh,
  isLoading,
}: SidebarFiltersProps) {
  const activeFilters = hasActiveFilters(filters);

  const updateFilter = <K extends keyof FilterState>(
    key: K,
    value: FilterState[K]
  ) => {
    onFiltersChange({ ...filters, [key]: value });
  };

  const toggleArrayFilter = (
    key: keyof FilterState,
    value: string
  ) => {
    const current = filters[key] as string[];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [key]: updated });
  };

  const clearFilters = () => {
    onFiltersChange(EMPTY_FILTERS);
  };

  return (
    <div className="flex flex-col h-full bg-surface-900/80 border-r border-surface-800/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-surface-800/60 bg-surface-900/90">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-ocean-400" />
          <span className="text-sm font-semibold text-surface-200">
            Scientific Filters
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {activeFilters && (
            <button
              onClick={clearFilters}
              className="text-xs px-2 py-1 rounded-md bg-ocean-500/10 text-ocean-400 hover:bg-ocean-500/20 border border-ocean-500/20 transition-colors cursor-pointer"
            >
              Clear
            </button>
          )}
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className={cn(
              "p-1.5 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800/60 transition-colors cursor-pointer",
              isLoading && "animate-spin"
            )}
            title="Refresh data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Float Count */}
      <div className="px-4 py-2.5 border-b border-surface-800/40 bg-surface-900/50">
        <div className="flex items-center justify-between">
          <span className="text-xs text-surface-500 font-medium">Active Floats</span>
          <span className="text-sm font-bold text-ocean-400">{floatCount}</span>
        </div>
      </div>

      {/* Scrollable Filter Sections */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Network Filter */}
        <FilterSection
          title="Network"
          icon={<Layers className="w-3.5 h-3.5" />}
          activeCount={filters.networks.length}
        >
          {availableOptions.networks.length > 0 ? (
            availableOptions.networks.map((net) => (
              <FilterChip
                key={net}
                label={net}
                active={filters.networks.includes(net)}
                onClick={() => toggleArrayFilter("networks", net)}
              />
            ))
          ) : (
            <span className="text-xs text-surface-600">No networks available</span>
          )}
        </FilterSection>

        {/* DAC Filter */}
        <FilterSection
          title="Data Assembly Centre"
          icon={<MapPin className="w-3.5 h-3.5" />}
          activeCount={filters.dacs.length}
        >
          {availableOptions.dacs.length > 0 ? (
            availableOptions.dacs.map((dac) => (
              <FilterChip
                key={dac}
                label={dac}
                active={filters.dacs.includes(dac)}
                onClick={() => toggleArrayFilter("dacs", dac)}
              />
            ))
          ) : (
            <span className="text-xs text-surface-600">No DACs available</span>
          )}
        </FilterSection>

        {/* Status Filter */}
        <FilterSection
          title="Status"
          icon={<Activity className="w-3.5 h-3.5" />}
          activeCount={filters.statuses.length}
        >
          {availableOptions.statuses.length > 0 ? (
            availableOptions.statuses.map((status) => (
              <FilterChip
                key={status}
                label={status}
                active={filters.statuses.includes(status)}
                onClick={() => toggleArrayFilter("statuses", status)}
                color={
                  status === "active"
                    ? "emerald"
                    : status === "drifted"
                      ? "amber"
                      : "slate"
                }
              />
            ))
          ) : (
            <span className="text-xs text-surface-600">No statuses available</span>
          )}
        </FilterSection>

        {/* Variables Filter */}
        <FilterSection
          title="Variables"
          icon={<Crosshair className="w-3.5 h-3.5" />}
          activeCount={filters.variables.length}
        >
          {availableOptions.variables.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {availableOptions.variables.map((v) => (
                <FilterChip
                  key={v}
                  label={v}
                  active={filters.variables.includes(v)}
                  onClick={() => toggleArrayFilter("variables", v)}
                  small
                />
              ))}
            </div>
          ) : (
            <span className="text-xs text-surface-600">No variables available</span>
          )}
        </FilterSection>

        {/* Date Range Filter */}
        <FilterSection
          title="Date Range"
          icon={<Calendar className="w-3.5 h-3.5" />}
          activeCount={
            (filters.dateFrom ? 1 : 0) + (filters.dateTo ? 1 : 0)
          }
        >
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <label className="text-xs text-surface-500 w-8">From</label>
              <input
                type="date"
                value={filters.dateFrom}
                onChange={(e) => updateFilter("dateFrom", e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs rounded-lg bg-surface-800 border border-surface-700/60 text-surface-200 focus:outline-none focus:border-ocean-500/50 focus:ring-1 focus:ring-ocean-500/20"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-surface-500 w-8">To</label>
              <input
                type="date"
                value={filters.dateTo}
                onChange={(e) => updateFilter("dateTo", e.target.value)}
                className="flex-1 px-2 py-1.5 text-xs rounded-lg bg-surface-800 border border-surface-700/60 text-surface-200 focus:outline-none focus:border-ocean-500/50 focus:ring-1 focus:ring-ocean-500/20"
              />
            </div>
          </div>
        </FilterSection>

        {/* Region Quick Filters */}
        <FilterSection title="Quick Regions" activeCount={0}>
          <div className="flex flex-col gap-1.5">
            <button
              onClick={() => updateFilter("region", "arabian_sea")}
              className={cn(
                "w-full text-left px-3 py-2 text-xs rounded-lg border transition-all",
                filters.region === "arabian_sea"
                  ? "bg-ocean-500/15 border-ocean-500/40 text-ocean-300"
                  : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60 hover:border-surface-600/40"
              )}
            >
              Arabian Sea
            </button>
            <button
              onClick={() => updateFilter("region", "bay_of_bengal")}
              className={cn(
                "w-full text-left px-3 py-2 text-xs rounded-lg border transition-all",
                filters.region === "bay_of_bengal"
                  ? "bg-ocean-500/15 border-ocean-500/40 text-ocean-300"
                  : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60 hover:border-surface-600/40"
              )}
            >
              Bay of Bengal
            </button>
            <button
              onClick={() => updateFilter("region", "")}
              className={cn(
                "w-full text-left px-3 py-2 text-xs rounded-lg border transition-all",
                filters.region === ""
                  ? "bg-surface-700/60 border-surface-600/50 text-surface-200"
                  : "bg-surface-800/40 border-surface-700/30 text-surface-500 hover:bg-surface-800/60 hover:border-surface-600/40"
              )}
            >
              All Regions
            </button>
          </div>
        </FilterSection>
      </div>
    </div>
  );
}

// Filter Section Component
interface FilterSectionProps {
  title: string;
  icon?: React.ReactNode;
  activeCount: number;
  children: React.ReactNode;
}

function FilterSection({
  title,
  icon,
  activeCount,
  children,
}: FilterSectionProps) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <div className="border-b border-surface-800/40">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-surface-800/30 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          {icon && <span className="text-ocean-400">{icon}</span>}
          <span className="text-xs font-semibold text-surface-300">{title}</span>
          {activeCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-ocean-500/20 text-ocean-400 font-bold">
              {activeCount}
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 text-surface-500 transition-transform",
            isOpen && "rotate-180"
          )}
        />
      </button>
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 pt-1">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// Filter Chip Component
interface FilterChipProps {
  label: string;
  active: boolean;
  onClick: () => void;
  color?: "ocean" | "emerald" | "amber" | "slate";
  small?: boolean;
}

function FilterChip({
  label,
  active,
  onClick,
  color = "ocean",
  small = false,
}: FilterChipProps) {
  const colorClasses = {
    ocean: active
      ? "bg-ocean-500/20 border-ocean-500/50 text-ocean-300"
      : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60",
    emerald: active
      ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-300"
      : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60",
    amber: active
      ? "bg-amber-500/20 border-amber-500/50 text-amber-300"
      : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60",
    slate: active
      ? "bg-surface-700/60 border-surface-600/50 text-surface-200"
      : "bg-surface-800/40 border-surface-700/30 text-surface-400 hover:bg-surface-800/60",
  };

  return (
    <button
      onClick={onClick}
      className={cn(
        "rounded-full border transition-all cursor-pointer",
        small ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-xs",
        colorClasses[color]
      )}
    >
      {label}
    </button>
  );
}
