"use client";

import { ReactNode } from "react";
import { Header } from "./Header";

interface MainLayoutProps {
  children: ReactNode;
}

export function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="flex flex-col h-screen bg-surface-950 text-surface-100 overflow-hidden">
      <Header />
      <main className="flex-1 overflow-hidden p-4 pt-3">
        <div className="h-full max-w-[1600px] mx-auto flex flex-col gap-3">
          {children}
        </div>
      </main>
    </div>
  );
}
