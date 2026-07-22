"use client";

import { ReactNode } from "react";

interface MainLayoutProps {
  header: ReactNode;
  sidebar?: ReactNode;
  map: ReactNode;
  workspace: ReactNode;
  cycleHistory?: ReactNode;
  promptInput?: ReactNode;
  cycleExpanded?: boolean;
}

export function MainLayout({
  header,
  sidebar,
  map,
  workspace,
  cycleHistory,
  promptInput,
  cycleExpanded = false,
}: MainLayoutProps) {
  const cycleHeight = cycleExpanded ? "480px" : "240px";

  return (
    <div className="flex flex-col h-screen bg-slate-100 text-slate-800 overflow-hidden">
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
            <div
              className="rounded-2xl overflow-hidden bg-white border border-slate-200 shadow-sm flex-shrink-0 transition-all duration-300 ease-in-out"
              style={{ height: cycleHeight, minHeight: cycleHeight }}
            >
              {cycleHistory}
            </div>
          )}
        </div>

        {/* Right Workspace - Chat/Metadata (25%) */}
        <aside className="w-[25%] min-w-[280px] max-w-[380px] h-full flex-shrink-0 flex flex-col gap-2">
          <div className="flex-1 min-h-0 overflow-hidden rounded-2xl">
            {workspace}
          </div>
          {/* Prompt Input always shown below the workspace panel */}
          {promptInput && (
            <div className="flex-shrink-0">
              {promptInput}
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
