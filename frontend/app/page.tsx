"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";
import { MainLayout } from "@/components/Layout/MainLayout";
import { ChatPanel } from "@/components/Chat/ChatPanel";
import { ResultsPanel } from "@/components/Results/ResultsPanel";
import { PromptInput } from "@/components/Input/PromptInput";
import { useChat } from "@/hooks/useChat";

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
    selectedFloat,
    setSelectedFloat,
    currentMapData,
  } = useChat();

  const lastAssistantMessage = useMemo(() => {
    return [...messages].reverse().find((m) => m.role === "assistant");
  }, [messages]);

  const radiusCenter =
    lastAssistantMessage?.summary?.center ?? lastAssistantMessage?.summary?.target_coords ?? null;
  const radiusKm = lastAssistantMessage?.summary?.radius_km ?? null;

  return (
    <MainLayout>
      <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 gap-3 min-h-0">
        <div className="lg:col-span-2 min-h-[300px] lg:min-h-0">
          <MapPanel
            mapData={currentMapData}
            selectedFloat={selectedFloat}
            onSelectFloat={setSelectedFloat}
            onDrillDown={(q) => sendMessage(q)}
            radiusCenter={radiusCenter}
            radiusKm={radiusKm}
          />
        </div>

        <div className="lg:col-span-3 min-h-[300px] lg:min-h-0">
          <ChatPanel
            messages={messages}
            messagesEndRef={messagesEndRef}
            scrollContainerRef={scrollContainerRef}
            onScroll={onScroll}
            onSelectSuggestion={(q) => sendMessage(q)}
          />
        </div>
      </div>

      <div className="h-[320px] min-h-[320px]">
        <ResultsPanel
          lastAssistantMessage={lastAssistantMessage}
          selectedFloat={selectedFloat}
          mapData={currentMapData}
          onClearSelection={() => setSelectedFloat(null)}
          onDrillDown={(q) => sendMessage(q)}
        />
      </div>

      <div className="flex-shrink-0">
        <PromptInput
          input={input}
          setInput={setInput}
          isLoading={isLoading}
          onSend={() => sendMessage()}
          onKeyDown={handleKeyDown}
        />
      </div>
    </MainLayout>
  );
}
