"use client";

import { motion } from "framer-motion";
import { Compass, Cpu, Database, LineChart, Sparkles, MessageCircle, BookOpen, MapPin } from "lucide-react";
import { ChatMessage } from "@/types";
import { ChatMessageItem } from "./ChatMessage";

interface ChatHistoryProps {
  messages: ChatMessage[];
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onSelectSuggestion?: (query: string) => void;
}

export function ChatHistory({
  messages,
  messagesEndRef,
  scrollContainerRef,
  onScroll,
  onSelectSuggestion,
}: ChatHistoryProps) {
  if (messages.length === 0) {
    // Phase 6 Part D: Prominent suggested question chips (4-6) for onboarding
    const suggestedQuestions = [
      { label: "Show floats near Kerala", icon: MapPin, color: "from-sky-500/20 to-ocean-500/20 border-sky-500/30 hover:border-sky-400/50" },
      { label: "T-S diagram for float 2902403", icon: LineChart, color: "from-violet-500/20 to-purple-500/20 border-violet-500/30 hover:border-violet-400/50" },
      { label: "What is an Argo float?", icon: BookOpen, color: "from-emerald-500/20 to-teal-500/20 border-emerald-500/30 hover:border-emerald-400/50" },
      { label: "What is a BGC float?", icon: BookOpen, color: "from-amber-500/20 to-orange-500/20 border-amber-500/30 hover:border-amber-400/50" },
      { label: "Oxygen profile in Arabian Sea for 2024", icon: Compass, color: "from-blue-500/20 to-cyan-500/20 border-blue-500/30 hover:border-blue-400/50" },
      { label: "How long do Argo floats last?", icon: MessageCircle, color: "from-pink-500/20 to-rose-500/20 border-pink-500/30 hover:border-pink-400/50" },
    ];

    const categories = [
      {
        title: "Spatial Search",
        icon: Compass,
        color: "text-sky-400",
        bg: "bg-sky-500/10",
        border: "border-sky-500/20",
        queries: [
          "Nearest float to 15.5, 72.3",
          "Floats within 100km of 15.5, 72.3",
        ],
      },
      {
        title: "Float Registry Metadata",
        icon: Cpu,
        color: "text-emerald-400",
        bg: "bg-emerald-500/10",
        border: "border-emerald-500/20",
        queries: [
          "Sensors on float 6903091",
          "Status of float 6903091",
        ],
      },
      {
        title: "Data Lake Aggregates",
        icon: Database,
        color: "text-amber-400",
        bg: "bg-amber-500/10",
        border: "border-amber-500/20",
        queries: [
          "How many profiles in Bay of Bengal for 2023",
          "Is there oxygen data in Arabian Sea",
        ],
      },
      {
        title: "BGC Profile Plots",
        icon: LineChart,
        color: "text-violet-400",
        bg: "bg-violet-500/10",
        border: "border-violet-500/20",
        queries: [
          "Oxygen profile in Arabian Sea for 2024",
          "Show temperature in Bay of Bengal",
        ],
      },
    ];

    return (
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto scrollbar-thin px-5 py-6 flex flex-col items-center justify-start min-h-0 gap-5"
      >
        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="w-full max-w-2xl text-center flex flex-col items-center gap-5"
        >
          <div className="w-12 h-12 rounded-2xl bg-ocean-500/10 border border-ocean-500/20 flex items-center justify-center text-ocean-400 shadow-inner">
            <Sparkles className="w-6 h-6" />
          </div>

          <div>
            <h2 className="text-base font-bold text-surface-100 mb-1">
              Welcome to FloatChat (India Region)
            </h2>
            <p className="text-xs text-surface-400 max-w-lg">
              I&apos;m a specialized oceanographic assistant built for INCOIS. Query local DuckDB/Parquet Argo data across the Arabian Sea, Bay of Bengal, and North Indian Ocean — or ask about Argo floats themselves.
            </p>
          </div>

          {/* Phase 6: Prominent Suggested Questions Chips */}
          <div className="w-full flex flex-col items-center gap-3">
            <p className="text-[11px] font-semibold tracking-wider text-surface-500 uppercase">Try these — click to send instantly</p>
            <div className="flex flex-wrap justify-center gap-2 w-full">
              {suggestedQuestions.map((chip) => (
                <motion.button
                  key={chip.label}
                  whileHover={{ scale: 1.03, y: -1 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => onSelectSuggestion && onSelectSuggestion(chip.label)}
                  className={`group flex items-center gap-1.5 px-3 py-2 rounded-full text-[12px] font-medium bg-gradient-to-br ${chip.color} border backdrop-blur-sm text-surface-200 hover:text-white transition-all shadow-sm hover:shadow`}
                >
                  <chip.icon className="w-3.5 h-3.5 opacity-80 group-hover:opacity-100" />
                  <span>{chip.label}</span>
                </motion.button>
              ))}
            </div>
          </div>

          {/* Existing category quick-start grid — secondary */}
          <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-3 text-left mt-1">
            {categories.map((cat) => (
              <div
                key={cat.title}
                className={`p-3 rounded-xl border ${cat.bg} ${cat.border} flex flex-col gap-2`}
              >
                <div className="flex items-center gap-2">
                  <cat.icon className={`w-3.5 h-3.5 ${cat.color}`} />
                  <span className="text-xs font-semibold text-surface-200">
                    {cat.title}
                  </span>
                </div>
                <div className="flex flex-col gap-1.5">
                  {cat.queries.map((q) => (
                    <button
                      key={q}
                      onClick={() => onSelectSuggestion && onSelectSuggestion(q)}
                      className="text-left text-[11px] text-surface-300 hover:text-ocean-300 bg-surface-950/60 hover:bg-surface-800/80 p-2 rounded-lg border border-surface-800/40 transition-colors"
                    >
                      &quot;{q}&quot;
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </motion.div>
        <div ref={messagesEndRef} />
      </div>
    );
  }

  return (
    <div
      ref={scrollContainerRef}
      onScroll={onScroll}
      className="flex-1 overflow-y-auto scrollbar-thin px-4 py-5 flex flex-col gap-5 min-h-0"
    >
      {messages.map((message) => (
        <ChatMessageItem key={message.id} message={message} />
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
}
