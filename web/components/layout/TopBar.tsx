"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bell,
  Command,
  LogOut,
  Search,
  Sun,
  Moon,
  Activity,
  ShieldAlert,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { useTheme } from "@/lib/theme/ThemeContext";
import { apiClient } from "@/lib/api/client";
import { RoleBadge } from "../ui/Badges";

export function TopBar({
  onOpenSearch,
  sidebarCollapsed,
}: {
  onOpenSearch: () => void;
  sidebarCollapsed: boolean;
}) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);
  const [unreadNotifications, setUnreadNotifications] = useState<number>(0);

  useEffect(() => {
    // Quick background health probe
    apiClient.health
      .get()
      .then((res) => setIsHealthy(res.status === "healthy" || res.status === "ok"))
      .catch(() => setIsHealthy(false));

    // Fetch notifications
    apiClient.notifications
      .list({ limit: 20 })
      .then((res) => {
        const unread = (res.items || []).filter((n) => !n.is_read).length;
        setUnreadNotifications(unread);
      })
      .catch(() => setUnreadNotifications(0));
  }, []);

  return (
    <header
      className={`h-14 border-b fixed top-0 right-0 z-20 flex items-center justify-between px-4 transition-all duration-200 backdrop-blur-md ${
        sidebarCollapsed ? "left-16" : "left-64"
      }`}
      style={{
        backgroundColor: "var(--bg-secondary)",
        borderColor: "var(--border-arch)",
      }}
    >
      {/* Global Architectural Search Bar */}
      <div className="flex items-center gap-3 flex-1 max-w-lg">
        <button
          onClick={onOpenSearch}
          className="w-full flex items-center justify-between px-3 py-1.5 rounded border text-xs text-muted-foreground hover:text-foreground transition-all duration-150"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border-arch)",
          }}
        >
          <div className="flex items-center gap-2 truncate">
            <Search className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
            <span className="truncate">Search MCP tools, agent runs, policies, shipments...</span>
          </div>
          <kbd className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-muted-foreground border border-arch bg-surface flex-shrink-0">
            <Command className="w-2.5 h-2.5" /> K
          </kbd>
        </button>
      </div>

      {/* Right Controls: Health Telemetry, Theme Switch, Notifications, Identity */}
      <div className="flex items-center gap-2.5 sm:gap-3">
        {/* Architectural Live Telemetry Pill */}
        <Link
          href="/system-health"
          className="flex items-center gap-1.5 px-2.5 py-1 rounded border text-[11px] font-mono transition-colors hover:border-[#D95E00]"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border-arch)",
          }}
          title={isHealthy ? "API Gateway & Deterministic Core Online" : "Degraded Connectivity"}
        >
          <Activity
            className={`w-3.5 h-3.5 ${
              isHealthy === true
                ? "text-[#0A7A75]"
                : isHealthy === false
                ? "text-rose-500"
                : "text-amber-400 animate-pulse"
            }`}
          />
          <span className="text-muted-foreground hidden md:inline">SYS:</span>
          <span
            className={`font-bold ${
              isHealthy === true
                ? "text-[#0A7A75]"
                : isHealthy === false
                ? "text-rose-500"
                : "text-amber-400"
            }`}
          >
            {isHealthy === true ? "ONLINE (14ms)" : isHealthy === false ? "OFFLINE" : "PROBING"}
          </span>
        </Link>

        {/* Theme Quick Toggle (Ivory / Obsidian) */}
        <button
          onClick={toggleTheme}
          className="p-1.5 rounded border border-arch text-muted-foreground hover:text-foreground hover:bg-surface transition-colors"
          style={{ backgroundColor: "var(--bg-card)" }}
          title={theme === "ivory" ? "Switch to Obsidian Dark" : "Switch to Warm Ivory"}
        >
          {theme === "ivory" ? (
            <Moon className="w-4 h-4 text-[#D95E00]" />
          ) : (
            <Sun className="w-4 h-4 text-[#E88D00]" />
          )}
        </button>

        {/* Notifications Bell */}
        <Link
          href="/notifications"
          className="relative p-1.5 rounded border border-arch text-muted-foreground hover:text-foreground hover:bg-surface transition-colors"
          style={{ backgroundColor: "var(--bg-card)" }}
          title="Notifications"
        >
          <Bell className="w-4 h-4" />
          {unreadNotifications > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-[#D95E00] text-white font-mono text-[9px] font-bold flex items-center justify-center shadow-sm">
              {unreadNotifications > 9 ? "9+" : unreadNotifications}
            </span>
          )}
        </Link>

        {/* Operator Profile */}
        <div
          className="hidden sm:flex items-center gap-2 pl-2 border-l"
          style={{ borderColor: "var(--border-arch)" }}
        >
          <div className="flex flex-col text-right">
            <span className="text-xs text-foreground font-mono font-medium truncate max-w-[120px]">
              {user?.full_name || "Security Operator"}
            </span>
            <span className="text-[9px] text-muted-foreground font-mono">AUTHORIZED</span>
          </div>
          {user?.role && <RoleBadge role={user.role} />}
        </div>

        {/* Sign Out */}
        <button
          onClick={() => logout()}
          className="p-1.5 rounded border border-arch text-muted-foreground hover:text-rose-400 hover:bg-rose-950/20 transition-colors"
          style={{ backgroundColor: "var(--bg-card)" }}
          title="Sign out of Control Tower"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
