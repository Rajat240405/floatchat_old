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
    <div className="flex flex-col h-full bg-white/80 border border-slate-200 rounded-xl overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-200 bg-slate-50">
        <LayoutDashboard className="w-4 h-4 text-ocean-400" />
        <span className="text-sm font-medium text-slate-700">Results & Analytics</span>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-4">
        <AnimatePresence mode="wait">
          {!hasResult ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full text-slate-400 gap-3"
            >
              <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center">
                <LayoutDashboard className="w-5 h-5 text-slate-500" />
              </div>
              <p className="text-sm">Results will appear here after you send a query.</p>
              <p className="text-xs text-slate-400">
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
