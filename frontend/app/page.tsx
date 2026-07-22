"use client";

import { useMemo, useCallback, useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { motion, AnimatePresence } from "framer-motion";
import { MessageSquare, X } from "lucide-react";

import { MainLayout } from "@/components/Layout/MainLayout";
import { Header } from "@/components/Layout/Header";
import { SidebarFilters } from "@/components/Layout/Sidebar";
import { ChatPanel } from "@/components/Chat/ChatPanel";
import { PromptInput } from "@/components/Input/PromptInput";

import { MetadataInspector } from "@/components/Results/MetadataInspector";
import { CycleHistory } from "@/components/Map/CycleHistory";
import { PlotDrawer } from "@/components/Results/PlotDrawer";
import { useChat } from "@/hooks/useChat";
import { FloatRegistryInfo } from "@/types";

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
    currentMapData,
    mode,
    chatOpen,
    setChatOpen,
    context,
    cycleData,
    isLoadingCycles,
    highlightCycle,
    setHighlightCycle,
    plotItems,
    plotDrawerOpen,
    setPlotDrawerOpen,
    togglePlotPin,
    filters,
    setFilters,
    filteredMapData,
    availableFilterOptions,
    floatCount,
    floatSearch,
    setFloatSearch,
    submitFloatSearch,
    loadCycleHistory,
  } = useChat();

  // Local state for metadata loading
  const [isLoadingMetadata, setIsLoadingMetadata] = useState(false);
  // Cycle table expand state
  const [cycleTableExpanded, setCycleTableExpanded] = useState(false);

  // Get the most recent assistant message
  const lastAssistantMessage = useMemo(() => {
    return [...messages].reverse().find((m) => m.role === "assistant");
  }, [messages]);

  // Get float info from the most recent response
  const floatInfo: FloatRegistryInfo | null = useMemo(() => {
    const fromMsg = lastAssistantMessage?.summary?.float_info ?? null;
    if (fromMsg) return fromMsg;

    // Fallback: derive immediately from currentMapData on first select (no second click)
    if (selectedFloat && currentMapData.length > 0) {
      const match = currentMapData.find((m: any) => m.float_id === selectedFloat);
      if (match) {
        return {
          float_id: match.float_id,
          wmo_id: match.wmo_id || match.float_id,
          dac: match.dac || "",
          network: match.network || "Core Argo",
          institution: match.dac || "",
          platform_type: "",
          profiler_type: "",
          manufacturer: "",
          first_profile_date: match.profile_date || null,
          last_report_date: match.profile_date || null,
          profile_count: 0,
          status: match.status || "active",
          sensors: match.variables || [],
          battery_status: "",
          battery_percentage: null,
          battery_voltage: null,
          last_lat: match.latitude,
          last_lon: match.longitude,
        } as any;
      }
    }
    return null;
  }, [lastAssistantMessage, selectedFloat, currentMapData]);

  // Radius center for map
  const radiusCenter = useMemo(
    () =>
      lastAssistantMessage?.summary?.center ??
      lastAssistantMessage?.summary?.target_coords ??
      null,
    [lastAssistantMessage]
  );
  const radiusKm = lastAssistantMessage?.summary?.radius_km ?? null;

  // Handlers for Metadata Inspector
  const handleViewTrajectory = useCallback(() => {
    if (selectedFloat) {
      loadCycleHistory(selectedFloat);
      // Send trajectory query
      sendMessage(`Show trajectory of float ${selectedFloat}`);
    }
  }, [selectedFloat, loadCycleHistory, sendMessage]);

  const handleViewLatestProfile = useCallback(() => {
    if (selectedFloat) {
      // Explicit reliable trigger: force chat context + latest profile
      setChatOpen(false); // ensure metadata is visible or will be restored
      sendMessage(`Show latest profile for float ${selectedFloat}`);
    }
  }, [selectedFloat, sendMessage, setChatOpen]);

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

  // Handle cycle selection from CycleHistory
  const handleSelectCycle = useCallback(
    (cycleNumber: number | null) => {
      setHighlightCycle(cycleNumber);
      // If cycle is selected, we could zoom the map to that point
      // This would require additional map state management
    },
    [setHighlightCycle]
  );

  // Open chat overlay
  const handleOpenChat = useCallback(() => {
    setChatOpen(true);
  }, [setChatOpen]);

  // Close chat overlay
  const handleCloseChat = useCallback(() => {
    setChatOpen(false);
  }, [setChatOpen]);

  // Metadata + Cycle History now open on FIRST click via handleSelectFloat + floatInfo fallback.
  // Removed auto-sendMessage useEffect to prevent second-click requirement and race conditions.

  // Workspace content - Chat or Metadata
  const workspaceContent = useMemo(() => {
    if (mode === "metadata" && selectedFloat && floatInfo) {
      return (
        <MetadataInspector
          info={floatInfo}
          onViewTrajectory={handleViewTrajectory}
          onViewLatestProfile={handleViewLatestProfile}
          onDownloadMetadata={handleDownloadMetadata}
          isLoading={isLoadingMetadata}
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
  ]);

  // Sidebar with scientific filters
  const sidebar = (
    <SidebarFilters
      filters={filters}
      onFiltersChange={setFilters}
      availableOptions={availableFilterOptions}
      floatCount={floatCount}
      floatSearch={floatSearch}
      onFloatSearchChange={setFloatSearch}
      onFloatSearchSubmit={submitFloatSearch}
      onRefresh={() => sendMessage()}
      isLoading={isLoading}
    />
  );

  // Render the layout
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

      {/* Chat Overlay (when in metadata mode and chat is open) */}
      <AnimatePresence>
        {mode === "metadata" && chatOpen && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/30 z-[800]"
              onClick={handleCloseChat}
            />

            {/* Chat Panel */}
            <motion.div
              initial={{ x: "100%", opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: "100%", opacity: 0 }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed top-0 right-0 bottom-0 w-[400px] max-w-[90vw] z-[850] bg-white/98 backdrop-blur-xl border-l border-slate-200 shadow-[-20px_0_60px_-10px_rgba(0,0,0,0.15)] flex flex-col"
            >
              {/* Chat Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-slate-50">
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-4 h-4 text-ocean-400" />
                  <span className="text-sm font-semibold text-slate-700">
                    AI Assistant
                  </span>
                </div>
                <button
                  onClick={handleCloseChat}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Chat Content */}
              <div className="flex-1 overflow-hidden">
                <ChatPanel
                  messages={messages}
                  messagesEndRef={messagesEndRef}
                  scrollContainerRef={scrollContainerRef}
                  onScroll={onScroll}
                  onSelectSuggestion={(q) => {
                    sendMessage(q);
                    // Keep chat open after sending
                  }}
                />
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Plot Drawer (slides from left) */}
      <PlotDrawer
        isOpen={plotDrawerOpen}
        onClose={() => setPlotDrawerOpen(false)}
        plots={plotItems}
        onTogglePin={togglePlotPin}
      />
    </>
  );
}
