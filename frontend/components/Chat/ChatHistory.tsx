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
    // Reduced to 4–6 high-quality examples (per latest UX refinement)
    const suggestedQuestions = [
      { label: "Show floats near Kerala", icon: MapPin, color: "from-sky-50 to-blue-50 border-sky-200 hover:border-sky-300" },
      { label: "Temperature profile in Arabian Sea", icon: Compass, color: "from-blue-50 to-cyan-50 border-blue-200 hover:border-blue-300" },
      { label: "T-S diagram for float 2902403", icon: LineChart, color: "from-violet-50 to-purple-50 border-violet-200 hover:border-violet-300" },
      { label: "What is an Argo float?", icon: BookOpen, color: "from-emerald-50 to-teal-50 border-emerald-200 hover:border-emerald-300" },
      { label: "Show trajectory of float 2902771", icon: MapPin, color: "from-amber-50 to-orange-50 border-amber-200 hover:border-amber-300" },
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
          <div className="w-12 h-12 rounded-2xl bg-ocean-50 border border-ocean-200 flex items-center justify-center text-ocean-500 shadow-sm">
            <Sparkles className="w-6 h-6" />
          </div>

          <div>
            <h2 className="text-base font-bold text-slate-800 mb-1">
              Welcome to FloatChat (India Region)
            </h2>
            <p className="text-xs text-slate-500 max-w-lg">
              I&apos;m a specialized oceanographic assistant built for INCOIS. Query local DuckDB/Parquet Argo data across the Arabian Sea, Bay of Bengal, and North Indian Ocean — or ask about Argo floats themselves.
            </p>
          </div>

          {/* Reduced high-quality suggested question chips (no large category cards) */}
          <div className="w-full flex flex-col items-center gap-3">
            <p className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">Try these — click to send instantly</p>
            <div className="flex flex-wrap justify-center gap-2 w-full">
              {suggestedQuestions.map((chip) => (
                <motion.button
                  key={chip.label}
                  whileHover={{ scale: 1.03, y: -1 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => onSelectSuggestion && onSelectSuggestion(chip.label)}
                  className={`group flex items-center gap-1.5 px-3 py-2 rounded-full text-[12px] font-medium bg-gradient-to-br ${chip.color} border backdrop-blur-sm hover:text-ocean-700 text-slate-700 transition-all shadow-sm hover:shadow`}
                >
                  <chip.icon className="w-3.5 h-3.5 opacity-80 group-hover:opacity-100" />
                  <span>{chip.label}</span>
                </motion.button>
              ))}
            </div>
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
      className="flex-1 overflow-y-auto scrollbar-thin px-4 py-5 flex flex-col gap-5 min-h-0 w-full"
    >
      {messages.map((message) => (
        <ChatMessageItem key={message.id} message={message} />
      ))}
      <div ref={messagesEndRef} />
    </div>
  );
}
