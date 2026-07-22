"use client";

import { motion } from "framer-motion";
import { User, Bot, AlertCircle } from "lucide-react";
import { ChatMessage as ChatMessageType } from "@/types";
import { formatTime } from "@/lib/utils";
import { TypingIndicator } from "./TypingIndicator";

interface ChatMessageProps {
  message: ChatMessageType;
}

export function ChatMessageItem({ message }: ChatMessageProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}
    >
      {/* Avatar */}
      <div
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
          isUser
            ? "bg-ocean-500/15 border border-ocean-500/25"
            : "bg-surface-800 border border-surface-700"
        }`}
      >
        {isUser ? (
          <User className="w-4 h-4 text-ocean-400" />
        ) : (
          <Bot className="w-4 h-4 text-surface-400" />
        )}
      </div>

      {/* Content */}
      <div className={`flex flex-col ${isUser ? "items-end" : "items-start"} max-w-[85%]`}>
        <div
          className={`relative px-4 py-3 rounded-2xl text-sm leading-relaxed ${
            isUser
              ? "bg-ocean-500/10 border border-ocean-500/20 text-surface-100 rounded-br-md"
              : "bg-surface-800/80 border border-surface-700/50 text-surface-200 rounded-bl-md"
          }`}
        >
          {message.isLoading ? (
            <TypingIndicator />
          ) : (
            <div className="whitespace-pre-wrap">{message.content}</div>
          )}

          {message.error && (
            <div className="flex items-center gap-2 mt-2 text-xs text-red-400">
              <AlertCircle className="w-3.5 h-3.5" />
              <span>Error</span>
            </div>
          )}
        </div>

        <span className="mt-1.5 text-[10px] text-surface-600 font-medium">
          {formatTime(message.timestamp)}
        </span>
      </div>
    </motion.div>
  );
}
