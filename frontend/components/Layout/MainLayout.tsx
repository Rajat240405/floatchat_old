"use client";

import { ReactNode } from "react";

interface MainLayoutProps {
  header: ReactNode;
  sidebar?: ReactNode;
  map: ReactNode;
  workspace: ReactNode;
  cycleHistory?: ReactNode;
  promptInput: ReactNode;
}

export function MainLayout({
  header,
  sidebar,
  map,
  workspace,
  cycleHistory,
  promptInput,
}: MainLayoutProps) {
  return (
    <div className="flex flex-col h-screen bg-surface-950 text-surface-100 overflow-hidden">
      {/* Header */}
      {header}

      {/* Main Content */}
      <main className="flex-1 flex overflow-hidden p-4 pt-3 gap-3">
        {/* Left Sidebar - Scientific Filters (20%) */}
        {sidebar && (
          <aside className="w-[20%] min-w-[200px] max-w-[280px] h-full rounded-2xl overflow-hidden flex-shrink-0">
            {sidebar}
          </aside>
        )}

        {/* Center Content - Map (55%) */}
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          {/* Map takes remaining space */}
          <div className="flex-1 min-h-0 rounded-2xl overflow-hidden">
            {map}
          </div>

          {/* Bottom - Cycle History (spans width of map) */}
          {cycleHistory && (
            <div className="h-[240px] min-h-[240px] rounded-2xl overflow-hidden bg-surface-900/50 border border-surface-800/60">
              {cycleHistory}
            </div>
          )}
        </div>

        {/* Right Workspace - Chat/Metadata (25%) */}
        <aside className="w-[25%] min-w-[280px] max-w-[380px] h-full rounded-2xl overflow-hidden flex-shrink-0">
          {workspace}
        </aside>
      </main>

      {/* Prompt Input */}
      <div className="px-4 pb-4 flex-shrink-0">
        {promptInput}
      </div>
    </div>
  );
}
