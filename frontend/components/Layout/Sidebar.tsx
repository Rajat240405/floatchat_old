"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Filter,
  MapPin,
  Layers,
  Activity,
  Calendar,
  ChevronDown,
  X,
  RefreshCw,
  Search,
} from "lucide-react";
import { FilterState, EMPTY_FILTERS } from "@/types";
import { cn, hasActiveFilters } from "@/lib/utils";

interface SidebarFiltersProps {
  filters: FilterState;
  onFiltersChange: (f: FilterState) => void;
  /** Full application reset (filters + selection + panels). */
  onClearAll?: () => void;
  availableOptions: {
    networks: string[];
    dacs: string[];
    variables: string[];
    statuses: string[];
  };
  floatCount: number;
  floatSearch: string;
  onFloatSearchChange: (value: string) => void;
  onFloatSearchSubmit: () => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export function SidebarFilters({
  filters,
  onFiltersChange,
  onClearAll,
  availableOptions,
  floatCount,
  floatSearch,
  onFloatSearchChange,
  onFloatSearchSubmit,
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

  const toggleArrayFilter = (key: keyof FilterState, value: string) => {
    const current = filters[key] as string[];
    const updated = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onFiltersChange({ ...filters, [key]: updated });
  };

  const clearFilters = () => {
    if (onClearAll) onClearAll();
    else onFiltersChange(EMPTY_FILTERS);
  };

  return (
    <div className="flex flex-col h-full bg-white border-r border-slate-200 overflow-hidden shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-white">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-ocean-500" />
          <span className="fc-heading">
            Scientific Filters
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {activeFilters && (
            <button
              onClick={clearFilters}
              className="text-xs px-2 py-1 rounded-md bg-ocean-50 text-ocean-600 hover:bg-ocean-100 border border-ocean-200 transition-colors cursor-pointer"
            >
              Clear
            </button>
          )}
          <button
            onClick={onRefresh}
            disabled={isLoading}
            className={cn(
              "p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer",
              isLoading && "animate-spin"
            )}
            title="Refresh data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Float Count */}
      <div className="px-4 py-2.5 border-b border-slate-200 bg-slate-50">
        <div className="flex items-center justify-between">
          <span className="fc-meta">Floats shown</span>
          <span className="fc-title text-ocean-600 tabular-nums">
            {floatCount.toLocaleString()}
          </span>
        </div>
      </div>

      {/* Float ID Search */}
      <div className="px-4 py-2.5 border-b border-slate-200 bg-slate-50">
        <div className="text-[10px] uppercase tracking-wider text-slate-400 font-medium mb-1.5">
          Float ID Search
        </div>
        <div className="flex items-center gap-0 rounded-lg border text-sm transition-all border-slate-300 bg-white overflow-hidden focus-within:border-ocean-400 focus-within:ring-1 focus-within:ring-ocean-400/20">
          <Search className="w-3.5 h-3.5 text-slate-400 ml-2.5 flex-shrink-0" />
          <input
            type="text"
            value={floatSearch}
            onChange={(e) => onFloatSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onFloatSearchSubmit();
            }}
            placeholder="e.g. 5906471"
            className="flex-1 min-w-0 px-2 py-1.5 bg-transparent text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none"
          />
          {floatSearch && (
            <button
              onClick={() => onFloatSearchChange("")}
              className="p-1 flex-shrink-0 text-slate-400 hover:text-slate-600"
            >
              <X className="w-3 h-3" />
            </button>
          )}
          <button
            onClick={onFloatSearchSubmit}
            disabled={!floatSearch.trim() || isLoading}
            className="flex-shrink-0 px-2.5 py-1.5 bg-ocean-500 hover:bg-ocean-400 disabled:opacity-50 text-[10px] font-semibold text-white whitespace-nowrap"
          >
            Go
          </button>
        </div>
      </div>

      {/* Scrollable Filter Sections */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {/* Quick Regions — primary geographic filter */}
        <FilterSection
          title="Quick Regions"
          icon={<MapPin className="w-3.5 h-3.5" />}
          activeCount={filters.region ? 1 : 0}
        >
          <div className="flex flex-col gap-1.5">
            {(
              [
                { id: "arabian_sea", label: "Arabian Sea" },
                { id: "bay_of_bengal", label: "Bay of Bengal" },
                { id: "indian_ocean", label: "Indian Ocean" },
                { id: "", label: "All Regions" },
              ] as const
            ).map((r) => (
              <button
                key={r.id || "all"}
                onClick={() => updateFilter("region", r.id)}
                className={cn(
                  "w-full text-left px-3 py-2 text-xs rounded-lg border transition-all cursor-pointer",
                  filters.region === r.id
                    ? r.id === ""
                      ? "bg-slate-100 border-slate-300 text-slate-800 font-medium"
                      : "bg-ocean-50 border-ocean-300 text-ocean-700 font-medium"
                    : "bg-white border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300"
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </FilterSection>

        {/* Network */}
        <FilterSection
          title="Network"
          icon={<Layers className="w-3.5 h-3.5" />}
          activeCount={filters.networks.length}
        >
          {availableOptions.networks.length > 0 ? (
            availableOptions.networks.map((net) => (
              <label
                key={net}
                className="flex items-center gap-2 text-xs cursor-pointer py-0.5"
              >
                <input
                  type="checkbox"
                  checked={filters.networks.includes(net)}
                  onChange={() => toggleArrayFilter("networks", net)}
                  className="w-3.5 h-3.5 accent-ocean-500"
                />
                <span className="text-slate-700">{net}</span>
              </label>
            ))
          ) : (
            <span className="text-xs text-slate-400">No networks available</span>
          )}
        </FilterSection>

        {/* DAC */}
        <FilterSection
          title="Data Assembly Centre"
          icon={<MapPin className="w-3.5 h-3.5" />}
          activeCount={filters.dacs.length}
        >
          {availableOptions.dacs.length > 0 ? (
            availableOptions.dacs.map((dac) => (
              <label
                key={dac}
                className="flex items-center gap-2 text-xs cursor-pointer py-0.5"
              >
                <input
                  type="checkbox"
                  checked={filters.dacs.includes(dac)}
                  onChange={() => toggleArrayFilter("dacs", dac)}
                  className="w-3.5 h-3.5 accent-ocean-500"
                />
                <span className="text-slate-700">{dac}</span>
              </label>
            ))
          ) : (
            <span className="text-xs text-slate-400">No DACs available</span>
          )}
        </FilterSection>

        {/* Status */}
        <FilterSection
          title="Status"
          icon={<Activity className="w-3.5 h-3.5" />}
          activeCount={filters.statuses.length}
        >
          {availableOptions.statuses.length > 0 ? (
            availableOptions.statuses.map((status) => (
              <label
                key={status}
                className="flex items-center gap-2 text-xs cursor-pointer py-0.5"
              >
                <input
                  type="checkbox"
                  checked={filters.statuses.includes(status)}
                  onChange={() => toggleArrayFilter("statuses", status)}
                  className="w-3.5 h-3.5 accent-ocean-500"
                />
                <span className="text-slate-700 capitalize">{status}</span>
              </label>
            ))
          ) : (
            <span className="text-xs text-slate-400">No statuses available</span>
          )}
        </FilterSection>

        {/* Date Range — modern dual date inputs */}
        <FilterSection
          title="Date Range"
          icon={<Calendar className="w-3.5 h-3.5" />}
          activeCount={(filters.dateFrom ? 1 : 0) + (filters.dateTo ? 1 : 0)}
        >
          <div className="flex flex-col gap-2.5">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                From
              </label>
              <div className="relative">
                <Calendar className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
                <input
                  type="date"
                  value={filters.dateFrom}
                  max={filters.dateTo || undefined}
                  onChange={(e) => updateFilter("dateFrom", e.target.value)}
                  className="w-full pl-8 pr-2 py-2 text-xs rounded-lg bg-white border border-slate-300 text-slate-700 focus:outline-none focus:border-ocean-400 focus:ring-2 focus:ring-ocean-400/20 transition-shadow"
                />
              </div>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">
                To
              </label>
              <div className="relative">
                <Calendar className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
                <input
                  type="date"
                  value={filters.dateTo}
                  min={filters.dateFrom || undefined}
                  onChange={(e) => updateFilter("dateTo", e.target.value)}
                  className="w-full pl-8 pr-2 py-2 text-xs rounded-lg bg-white border border-slate-300 text-slate-700 focus:outline-none focus:border-ocean-400 focus:ring-2 focus:ring-ocean-400/20 transition-shadow"
                />
              </div>
            </div>
            {(filters.dateFrom || filters.dateTo) && (
              <button
                type="button"
                onClick={() =>
                  onFiltersChange({ ...filters, dateFrom: "", dateTo: "" })
                }
                className="text-[11px] text-ocean-600 hover:text-ocean-700 font-medium self-start cursor-pointer"
              >
                Clear dates
              </button>
            )}
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
    <div className="border-b border-slate-200">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-slate-50 transition-colors cursor-pointer"
      >
        <div className="flex items-center gap-2">
          {icon && <span className="text-ocean-500">{icon}</span>}
          <span className="fc-heading">{title}</span>
          {activeCount > 0 && (
            <span className="fc-meta px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-600 font-bold">
              {activeCount}
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            "w-3.5 h-3.5 text-slate-400 transition-transform",
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
