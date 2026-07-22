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
        className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center shadow-sm ${
          isUser
            ? "bg-ocean-500 border border-ocean-600"
            : "bg-slate-100 border border-slate-200"
        }`}
      >
        {isUser ? (
          <User className="w-4 h-4 text-white" />
        ) : (
          <Bot className="w-4 h-4 text-ocean-500" />
        )}
      </div>

      {/* Content */}
      <div className={`flex flex-col ${isUser ? "items-end" : "items-start"} max-w-[92%] min-w-0`}>
        <div
          className={`relative px-4 py-3 rounded-2xl text-sm leading-relaxed break-words overflow-visible w-full shadow-sm ${
            isUser
              ? "bg-ocean-500 text-white rounded-br-md"
              : "bg-white border border-slate-200 text-slate-700 rounded-bl-md"
          }`}
        >
          {message.isLoading ? (
            <TypingIndicator />
          ) : (
            <div className="whitespace-pre-wrap break-words">{message.content}</div>
          )}

          {message.error && (
            <div className="flex items-center gap-2 mt-2 text-xs text-red-500">
              <AlertCircle className="w-3.5 h-3.5" />
              <span>Error sending message</span>
            </div>
          )}
        </div>

        <span className="mt-1.5 text-[10px] text-slate-400 font-medium">
          {formatTime(message.timestamp)}
        </span>
      </div>
    </motion.div>
  );
}
