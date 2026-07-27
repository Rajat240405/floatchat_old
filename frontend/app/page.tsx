"use client";

import { useMemo, useCallback, useState } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, X, BarChart3 } from "lucide-react";

import { MainLayout } from "@/components/Layout/MainLayout";
import { Header } from "@/components/Layout/Header";
import { SidebarFilters } from "@/components/Layout/Sidebar";
import { ChatPanel } from "@/components/Chat/ChatPanel";
import { PromptInput } from "@/components/Input/PromptInput";

import { MetadataInspector } from "@/components/Results/MetadataInspector";
import { CycleHistory } from "@/components/Map/CycleHistory";
import { PlotDrawer } from "@/components/Results/PlotDrawer";
import { useChat } from "@/hooks/useChat";
import { CyclePoint, FloatRegistryInfo } from "@/types";

const MapPanel = dynamic(
  () => import("@/components/Map/MapPanel").then((mod) => mod.MapPanel),
  { ssr: false }
);

export default function HomePage() {
  const {
    messages,
    input,
    setInput,
    isLoading,
    sendMessage,
    handleKeyDown,
    messagesEndRef,
    scrollContainerRef,
    onScroll,
    onSelectSuggestion,
    selectedFloat,
    setSelectedFloat,
    floatInfo: authoritativeFloatInfo,
    isLoadingMetadata,
    currentMapData,
    mode,
    chatOpen,
    setChatOpen,
    context,
    cycleData,
    selectedProfileNumber,
    selectProfile,
    isLoadingCycles,
    highlightCycle,
    setHighlightCycle,
    trajectoryVisible,
    showTrajectory,
    loadLatestProfile,
    availablePlots,
    isLoadingAvailablePlots,
    loadVariablePlot,
    plotItems,
    plotDrawerOpen,
    setPlotDrawerOpen,
    togglePlotPin,
    removePlot,
    plotFloatIds,
    plotSelectedFloat,
    setPlotSelectedFloat,
    filters,
    setFilters,
    updateFilters,
    clearAll,
    filteredMapData,
    availableFilterOptions,
    floatCount,
    floatSearch,
    setFloatSearch,
    submitFloatSearch,
    isFloatFocusMode,
  } = useChat();

  const [cycleTableExpanded, setCycleTableExpanded] = useState(false);

  const lastAssistantMessage = useMemo(() => {
    return [...messages].reverse().find((m) => m.role === "assistant");
  }, [messages]);

  // Prefer REST metadata. While loading, show a minimal stub WITHOUT
  // inventing first/last profile dates or profile_count from a single marker.
  const floatInfo: FloatRegistryInfo | null = useMemo(() => {
    if (authoritativeFloatInfo) return authoritativeFloatInfo;

    // Only build a minimal stub so the panel can open; dates/counts stay empty
    // until REST metadata arrives (prevents "both dates = last report" bug).
    if (selectedFloat && currentMapData.length > 0) {
      const match =
        [...currentMapData].reverse().find((m) => m.float_id === selectedFloat) ||
        currentMapData.find((m) => m.float_id === selectedFloat);
      if (match) {
        return {
          float_id: match.float_id,
          found: true,
          wmo_id: match.wmo_id || match.float_id,
          dac: match.dac || "",
          network: match.network || "Core Argo",
          institution: match.dac || "",
          platform_type: "",
          profiler_type: match.profiler_type || "",
          manufacturer: match.manufacturer || "",
          // Intentionally null — do NOT copy marker.profile_date here
          first_profile_date: null,
          last_report_date: null,
          profile_count: 0,
          status: match.status || "unknown",
          sensors: match.variables || [],
          battery_status: "",
          battery_percentage: null,
          battery_voltage: null,
          last_lat: match.latitude,
          last_lon: match.longitude,
        } as FloatRegistryInfo;
      }
    }
    return null;
  }, [authoritativeFloatInfo, selectedFloat, currentMapData]);

  const radiusCenter = useMemo(
    () =>
      lastAssistantMessage?.summary?.center ??
      lastAssistantMessage?.summary?.target_coords ??
      null,
    [lastAssistantMessage]
  );
  const radiusKm = lastAssistantMessage?.summary?.radius_km ?? null;
  // Sprint 5 (Bug 6): named-region scope → the map frames the region itself.
  const regionBounds = lastAssistantMessage?.summary?.region_bounds ?? null;

  // View Trajectory — only draws path when user clicks the button
  const handleViewTrajectory = useCallback(() => {
    showTrajectory();
  }, [showTrajectory]);

  const handleViewLatestProfile = useCallback(() => {
    if (selectedFloat) {
      setChatOpen(false);
      loadLatestProfile();
    }
  }, [selectedFloat, loadLatestProfile, setChatOpen]);

  const handleDownloadMetadata = useCallback(() => {
    if (floatInfo) {
      const metadata = {
        floatId: floatInfo.float_id,
        wmoId: floatInfo.wmo_id,
        dac: floatInfo.dac,
        network: floatInfo.network,
        institution: floatInfo.institution,
        platformType: floatInfo.platform_type,
        profilerType: floatInfo.profiler_type,
        manufacturer: floatInfo.manufacturer,
        firstProfileDate: floatInfo.first_profile_date,
        lastReportDate: floatInfo.last_report_date,
        profileCount: floatInfo.profile_count,
        status: floatInfo.status,
        sensors: floatInfo.sensors,
        batteryStatus: floatInfo.battery_status,
        batteryPercentage: floatInfo.battery_percentage,
      };

      const blob = new Blob([JSON.stringify(metadata, null, 2)], {
        type: "application/json",
      });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `float_${floatInfo.float_id}_metadata.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    }
  }, [floatInfo]);

  const handleSelectCycle = useCallback(
    (cycleNumber: number | null) => {
      setHighlightCycle(cycleNumber);
    },
    [setHighlightCycle]
  );

  /** Trajectory point click → highlight + scroll cycle table */
  const handleSelectTrajectoryPoint = useCallback(
    (cycleNumber: number | null) => {
      setHighlightCycle(cycleNumber);
    },
    [setHighlightCycle]
  );

  const handleOpenChat = useCallback(() => {
    setChatOpen(true);
  }, [setChatOpen]);

  const handleCloseChat = useCallback(() => {
    setChatOpen(false);
  }, [setChatOpen]);

  const workspaceContent = useMemo(() => {
    if (mode === "metadata" && selectedFloat && floatInfo) {
      return (
        <MetadataInspector
          info={floatInfo}
          onViewTrajectory={handleViewTrajectory}
          onViewLatestProfile={handleViewLatestProfile}
          onDownloadMetadata={handleDownloadMetadata}
          isLoading={isLoadingMetadata || isLoadingCycles}
          availablePlots={availablePlots}
          isLoadingAvailablePlots={isLoadingAvailablePlots}
          onSelectPlot={(variable) => loadVariablePlot(variable)}
        />
      );
    }
    return (
      <ChatPanel
        messages={messages}
        messagesEndRef={messagesEndRef}
        scrollContainerRef={scrollContainerRef}
        onScroll={onScroll}
        onSelectSuggestion={onSelectSuggestion}
      />
    );
  }, [
    mode,
    selectedFloat,
    floatInfo,
    messages,
    messagesEndRef,
    scrollContainerRef,
    onScroll,
    onSelectSuggestion,
    handleViewTrajectory,
    handleViewLatestProfile,
    handleDownloadMetadata,
    isLoadingMetadata,
    isLoadingCycles,
    availablePlots,
    isLoadingAvailablePlots,
    loadVariablePlot,
  ]);

  const sidebar = (
    <SidebarFilters
      filters={filters}
      onFiltersChange={updateFilters}
      onClearAll={clearAll}
      availableOptions={availableFilterOptions}
      floatCount={floatCount}
      floatSearch={floatSearch}
      onFloatSearchChange={setFloatSearch}
      onFloatSearchSubmit={submitFloatSearch}
      onRefresh={() => sendMessage()}
      isLoading={isLoading}
    />
  );

  return (
    <>
      <MainLayout
        cycleExpanded={cycleTableExpanded}
        header={
          <Header
            floatSearch={floatSearch}
            onFloatSearchChange={setFloatSearch}
            onFloatSearchSubmit={submitFloatSearch}
            isLoading={isLoading}
            plotCount={plotItems.length}
            plotsOpen={plotDrawerOpen}
            onTogglePlots={() => setPlotDrawerOpen(!plotDrawerOpen)}
            isFloatFocusMode={isFloatFocusMode}
            focusFloatId={
              // Show focused float id even before marker click (pin only)
              selectedFloat ||
              (isFloatFocusMode && filteredMapData[0]?.float_id) ||
              null
            }
          />
        }
        sidebar={sidebar}
        map={
          <MapPanel
            mapData={filteredMapData}
            selectedFloat={selectedFloat}
            onSelectFloat={setSelectedFloat}
            onDrillDown={(q) => sendMessage(q)}
            radiusCenter={radiusCenter}
            radiusKm={radiusKm}
            regionBounds={regionBounds}
            focusMode={isFloatFocusMode}
            trajectoryVisible={trajectoryVisible}
            highlightedCycle={highlightCycle}
            onSelectTrajectoryPoint={handleSelectTrajectoryPoint}
          />
        }
        workspace={workspaceContent}
        cycleHistory={
          selectedFloat ? (
            <CycleHistory
              cycles={cycleData}
              isLoading={isLoadingCycles}
              highlightedCycle={highlightCycle}
              onSelectCycle={handleSelectCycle}
              floatId={selectedFloat}
              onExpandToggle={() => setCycleTableExpanded((v) => !v)}
              isExpanded={cycleTableExpanded}
            />
          ) : undefined
        }
        promptInput={
          <PromptInput
            input={input}
            setInput={setInput}
            isLoading={isLoading}
            onSend={() => sendMessage()}
            onKeyDown={handleKeyDown}
          />
        }
      />

      {/* Floating Chat Button (when in metadata mode) */}
      <AnimatePresence>
        {mode === "metadata" && !chatOpen && (
          <motion.button
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: "spring", damping: 15, stiffness: 200 }}
            onClick={handleOpenChat}
            className="fixed bottom-24 right-8 z-[500] w-14 h-14 rounded-full bg-ocean-600 hover:bg-ocean-500 shadow-lg shadow-ocean-500/30 flex items-center justify-center border-2 border-ocean-400/30 cursor-pointer"
            title="Open Chat"
          >
            <MessageSquare className="w-6 h-6 text-white" />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Scientific Plots reopen chip */}
      <AnimatePresence>
        {plotItems.length > 0 && !plotDrawerOpen && (
          <motion.button
            initial={{ y: 24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 24, opacity: 0 }}
            transition={{ type: "spring", damping: 18, stiffness: 220 }}
            onClick={() => setPlotDrawerOpen(true)}
            className="fixed bottom-6 left-6 z-[500] flex items-center gap-2 px-4 py-2.5 rounded-full bg-white border border-ocean-200 shadow-lg shadow-ocean-500/15 hover:bg-ocean-50 hover:border-ocean-300 cursor-pointer"
            title="Reopen Scientific Plots"
          >
            <BarChart3 className="w-4 h-4 text-ocean-600" />
            <span className="text-sm font-semibold text-slate-700">
              Scientific Plots
            </span>
            <span className="text-[11px] font-bold px-1.5 py-0.5 rounded-full bg-ocean-100 text-ocean-700 border border-ocean-200">
              {plotItems.length}
            </span>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Chat Overlay */}
      <AnimatePresence>
        {mode === "metadata" && chatOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/30 z-[800]"
              onClick={handleCloseChat}
            />

            <motion.div
              initial={{ x: "100%", opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: "100%", opacity: 0 }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed top-0 right-0 bottom-0 w-[400px] max-w-[90vw] z-[850] bg-white/98 backdrop-blur-xl border-l border-slate-200 shadow-[-20px_0_60px_-10px_rgba(0,0,0,0.15)] flex flex-col"
            >
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-ocean-400" />
                  <span className="text-sm font-semibold text-slate-700">
                    AI Assistant
                  </span>
                  {context.floatId && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-ocean-50 text-ocean-600 border border-ocean-200 font-medium">
                      Float {context.floatId}
                    </span>
                  )}
                </div>
                <button
                  onClick={handleCloseChat}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="flex-1 overflow-hidden">
                <ChatPanel
                  messages={messages}
                  messagesEndRef={messagesEndRef}
                  scrollContainerRef={scrollContainerRef}
                  onScroll={onScroll}
                  onSelectSuggestion={(q) => {
                    sendMessage(q);
                  }}
                />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      <PlotDrawer
        isOpen={plotDrawerOpen}
        onClose={() => setPlotDrawerOpen(false)}
        plots={plotItems}
        onTogglePin={togglePlotPin}
        onRemovePlot={removePlot}
        floatIds={plotFloatIds}
        selectedFloatId={plotSelectedFloat}
        onSelectFloatId={setPlotSelectedFloat}
        profileNumber={selectedProfileNumber}
        profiles={cycleData || []}
        onSelectProfile={selectProfile}
      />
    </>
  );
}
