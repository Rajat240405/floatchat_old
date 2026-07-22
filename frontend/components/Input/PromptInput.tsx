"use client";

import { motion } from "framer-motion";
import { Send, Loader2 } from "lucide-react";

interface PromptInputProps {
  input: string;
  setInput: (value: string) => void;
  isLoading: boolean;
  onSend: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

export function PromptInput({
  input,
  setInput,
  isLoading,
  onSend,
  onKeyDown,
}: PromptInputProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
      className="relative"
    >
      <div className="flex items-end gap-3 p-3 bg-surface-900 border border-surface-800/60 rounded-xl shadow-lg shadow-black/20">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask anything about Argo ocean data..."
          rows={1}
          disabled={isLoading}
          className="flex-1 resize-none bg-transparent text-sm text-surface-100 placeholder:text-surface-600 focus:outline-none min-h-[40px] max-h-[120px] py-2.5 px-1 scrollbar-thin"
          style={{ fieldSizing: "content" }}
        />

        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={onSend}
          disabled={isLoading || !input.trim()}
          className="flex items-center justify-center w-10 h-10 rounded-lg bg-ocean-500 hover:bg-ocean-400 disabled:bg-surface-700 disabled:text-surface-500 text-white transition-colors flex-shrink-0"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </motion.button>
      </div>

      {/* Hint */}
      <p className="mt-2 text-center text-[11px] text-surface-700">
        Press Enter to send · Shift+Enter for new line
      </p>
    </motion.div>
  );
}
