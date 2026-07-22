"use client";

import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard } from "lucide-react";
import { ChatMessage, MapData } from "@/types";
import { SummaryCards } from "./SummaryCards";
import { PlotlyChart } from "./PlotlyChart";
import { FloatDetailCard } from "./FloatDetailCard";
import { FloatMetadataCard } from "./FloatMetadataCard";
import { CountStatCard } from "./CountStatCard";

interface ResultsPanelProps {
  lastAssistantMessage?: ChatMessage;
  selectedFloat: string | null;
  mapData: MapData[];
  onClearSelection: () => void;
  onDrillDown?: (query: string) => void;
}

export function ResultsPanel({
  lastAssistantMessage,
  selectedFloat,
  mapData,
  onClearSelection,
  onDrillDown,
}: ResultsPanelProps) {
  const hasResult = lastAssistantMessage && !lastAssistantMessage.isLoading;
  const selectedFloatData = selectedFloat
    ? mapData.find((m) => m.float_id === selectedFloat)
    : undefined;

  const summary = lastAssistantMessage?.summary;
  const intent = lastAssistantMessage?.intent;
  const figure = lastAssistantMessage?.figure;

  const floatInfo = summary?.float_info;
  const isCountIntent = intent === "count_aggregate";

  return (
    <div className="flex flex-col h-full bg-surface-900/50 border border-surface-800/60 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-800/60 bg-surface-900/80">
        <LayoutDashboard className="w-4 h-4 text-ocean-400" />
        <span className="text-sm font-medium text-surface-300">Results & Analytics</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
        <AnimatePresence mode="wait">
          {!hasResult ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full text-surface-600 gap-3"
            >
              <div className="w-12 h-12 rounded-full bg-surface-800 flex items-center justify-center">
                <LayoutDashboard className="w-5 h-5 text-surface-500" />
              </div>
              <p className="text-sm">Results will appear here after you send a query.</p>
              <p className="text-xs text-surface-700">
                Try: &quot;nearest float to 15.5, 72.3&quot; or &quot;sensors on float 6903091&quot;
              </p>
            </motion.div>
          ) : (
            <motion.div
              key="result"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col gap-4"
            >
              {!isCountIntent && !floatInfo && (
                <SummaryCards summary={summary} intent={intent} />
              )}

              {floatInfo && (
                <FloatMetadataCard info={floatInfo} onDrillDown={onDrillDown} />
              )}

              {isCountIntent && summary && (
                <CountStatCard summary={summary} onDrillDown={onDrillDown} />
              )}

              <AnimatePresence>
                {selectedFloatData && !floatInfo && (
                  <FloatDetailCard
                    float={selectedFloatData}
                    onClear={onClearSelection}
                  />
                )}
              </AnimatePresence>

              {figure && (
                <PlotlyChart
                  figure={figure}
                  selectedFloat={selectedFloat}
                  onClearSelection={onClearSelection}
                />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
