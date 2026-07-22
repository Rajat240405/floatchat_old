"use client";

import { ChatMessage } from "@/types";
import { ChatHistory } from "./ChatHistory";
import { MessageSquare } from "lucide-react";

interface ChatPanelProps {
  messages: ChatMessage[];
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  onScroll: () => void;
  onSelectSuggestion?: (query: string) => void;
}

export function ChatPanel({
  messages,
  messagesEndRef,
  scrollContainerRef,
  onScroll,
  onSelectSuggestion,
}: ChatPanelProps) {
  return (
    <div className="flex flex-col h-full bg-surface-900/50 border border-surface-800/60 rounded-xl overflow-hidden">
      {/* Panel Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-surface-800/60 bg-surface-900/80 flex-shrink-0">
        <MessageSquare className="w-4 h-4 text-ocean-400" />
        <span className="text-sm font-medium text-surface-300">Conversation</span>
        <span className="ml-auto text-xs text-surface-600">
          {messages.filter((m) => m.role === "user").length} queries
        </span>
      </div>

      {/* Messages — scrollable */}
      <ChatHistory
        messages={messages}
        messagesEndRef={messagesEndRef}
        scrollContainerRef={scrollContainerRef}
        onScroll={onScroll}
        onSelectSuggestion={onSelectSuggestion}
      />
    </div>
  );
}
