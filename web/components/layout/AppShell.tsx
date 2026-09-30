"use client";

import React, { useState } from "react";
import { useAuth } from "@/lib/auth/AuthContext";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { GlobalSearchModal } from "./GlobalSearchModal";
import { LoadingState } from "../ui/FeedbackStates";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { isLoading } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  if (isLoading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}
      >
        <LoadingState message="Authenticating Control Tower session..." />
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex flex-col transition-colors duration-200"
      style={{ backgroundColor: "var(--bg-primary)", color: "var(--text-primary)" }}
    >
      {/* Collapsible Navigation Sidebar */}
      <Sidebar
        isCollapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Global Top Bar */}
      <TopBar
        sidebarCollapsed={sidebarCollapsed}
        onOpenSearch={() => setSearchOpen(true)}
      />

      {/* Main Operational Canvas */}
      <main
        className={`flex-1 pt-14 transition-all duration-200 min-h-screen flex flex-col ${
          sidebarCollapsed ? "pl-16" : "pl-64"
        }`}
      >
        <div className="p-4 sm:p-6 flex-1 flex flex-col">{children}</div>
      </main>

      {/* Cmd+K Search Modal */}
      <GlobalSearchModal isOpen={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
