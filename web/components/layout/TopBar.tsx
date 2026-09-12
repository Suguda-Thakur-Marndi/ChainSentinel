"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bell,
  CheckCircle2,
  Command,
  HelpCircle,
  LogOut,
  Search,
  Shield,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
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
      className={`h-14 border-b border-[#243044] bg-[#0F172A]/90 backdrop-blur fixed top-0 right-0 z-20 flex items-center justify-between px-4 transition-all duration-200 ${
        sidebarCollapsed ? "left-16" : "left-64"
      }`}
    >
      {/* Global Quick Search Button */}
      <div className="flex items-center gap-3 flex-1 max-w-md">
        <button
          onClick={onOpenSearch}
          className="w-full flex items-center justify-between px-3 py-1.5 rounded-md bg-[#111827] border border-[#243044] text-xs text-slate-400 hover:text-slate-200 hover:border-slate-600 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Search className="w-3.5 h-3.5 text-slate-500" />
            <span>Search shipments, risks, suppliers, decisions...</span>
          </div>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-400 border border-slate-700">
            <Command className="w-2.5 h-2.5" /> K
          </kbd>
        </button>
      </div>

      {/* Right controls: Health, Notifications, User info, Logout */}
      <div className="flex items-center gap-3">
        {/* System Health */}
        <div
          className="flex items-center gap-1.5 px-2 py-1 rounded bg-[#111827] border border-[#243044] text-[11px] font-mono"
          title={isHealthy ? "API Gateway Connected & Deterministic Engine Online" : "Degraded connectivity"}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              isHealthy === true
                ? "bg-emerald-400"
                : isHealthy === false
                ? "bg-rose-500"
                : "bg-amber-400 animate-pulse"
            }`}
          />
          <span className="text-slate-400 hidden sm:inline">
            {isHealthy === true ? "SYS ONLINE" : isHealthy === false ? "CONN ERR" : "CHECKING"}
          </span>
        </div>

        {/* Notifications Bell */}
        <Link
          href="/notifications"
          className="relative p-2 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title="Notifications"
        >
          <Bell className="w-4 h-4" />
          {unreadNotifications > 0 && (
            <span className="absolute top-1 right-1 w-4 h-4 rounded-full bg-blue-600 text-white font-mono text-[10px] font-bold flex items-center justify-center">
              {unreadNotifications > 9 ? "9+" : unreadNotifications}
            </span>
          )}
        </Link>

        {/* User Identity & Role */}
        <div className="hidden sm:flex items-center gap-2 pl-2 border-l border-[#243044]">
          <span className="text-xs text-slate-300 font-medium">{user?.full_name || "Operator"}</span>
          {user?.role && <RoleBadge role={user.role} />}
        </div>

        {/* Logout */}
        <button
          onClick={() => logout()}
          className="p-1.5 rounded-md text-slate-400 hover:text-rose-400 hover:bg-rose-950/30 transition-colors"
          title="Sign out"
        >
          <LogOut className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
}
