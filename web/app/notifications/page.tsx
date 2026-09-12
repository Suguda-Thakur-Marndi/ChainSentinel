"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  Bell,
  CheckCircle2,
  Clock,
  ExternalLink,
  Filter,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { NotificationResponse } from "@/lib/api/types";

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<NotificationResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");

  const fetchNotifications = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.notifications.list({ limit: 100 });
      setNotifications(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load notifications");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchNotifications();
  }, []);

  const handleMarkRead = async (id: string) => {
    try {
      await apiClient.notifications.markRead(id);
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
    } catch {
      // Fallback optimistic update
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
    }
  };

  const filtered = notifications.filter(
    (n) => categoryFilter === "ALL" || n.category === categoryFilter
  );

  // Group notifications by Today, This Week, Earlier
  const now = new Date().getTime();
  const oneDay = 24 * 60 * 60 * 1000;
  const sevenDays = 7 * oneDay;

  const todayItems: NotificationResponse[] = [];
  const thisWeekItems: NotificationResponse[] = [];
  const earlierItems: NotificationResponse[] = [];

  filtered.forEach((n) => {
    const diff = now - new Date(n.created_at).getTime();
    if (diff <= oneDay) todayItems.push(n);
    else if (diff <= sevenDays) thisWeekItems.push(n);
    else earlierItems.push(n);
  });

  const renderItem = (item: NotificationResponse) => {
    const Icon =
      item.category === "RISK_ALERT"
        ? AlertOctagon
        : item.category === "RECOMMENDATION"
        ? UserCheck
        : item.category === "SHIPMENT_DELAY"
        ? Clock
        : ShieldCheck;

    return (
      <div
        key={item.id}
        className={`p-3.5 rounded-lg border transition-all flex items-start justify-between gap-4 ${
          item.is_read
            ? "bg-[#111827]/60 border-[#243044]"
            : "bg-[#1A2332] border-blue-500/50 shadow-sm"
        }`}
      >
        <div className="flex items-start gap-3">
          <div
            className={`p-2 rounded-md ${
              item.severity === "CRITICAL"
                ? "bg-rose-950 text-rose-400"
                : item.severity === "WARNING"
                ? "bg-amber-950 text-amber-400"
                : "bg-blue-950 text-blue-400"
            }`}
          >
            <Icon className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-xs font-semibold text-slate-100">{item.title}</h4>
              {!item.is_read && (
                <span className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0" />
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1">{item.message}</p>
            <span className="text-[10px] font-mono text-slate-500 mt-1 block">
              {new Date(item.created_at).toLocaleString()}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {item.link_url && (
            <Link
              href={item.link_url}
              className="p-1.5 rounded hover:bg-slate-800 text-blue-400"
              title="Navigate to incident / approval"
            >
              <ExternalLink className="w-4 h-4" />
            </Link>
          )}
          {!item.is_read && (
            <button
              onClick={() => handleMarkRead(item.id)}
              className="text-[11px] text-slate-400 hover:text-slate-200 px-2 py-1 rounded bg-slate-800"
            >
              Mark Read
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-4xl">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Operational Notifications & Alerts
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {notifications.filter((n) => !n.is_read).length} Unread
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Priority alerts for threshold breaches, required governance sign-offs, and verification results.
              </p>
            </div>

            <button
              onClick={fetchNotifications}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchNotifications} />}

          {/* Filter options */}
          <div className="flex items-center gap-2">
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
            >
              <option value="ALL">All Notification Categories</option>
              <option value="RISK_ALERT">Risk Alerts</option>
              <option value="RECOMMENDATION">Approval Requests</option>
              <option value="SHIPMENT_DELAY">Shipment Delays</option>
              <option value="SYSTEM">System Notices</option>
            </select>
          </div>

          {/* Notifications Sections */}
          {notifications.length === 0 && !isLoading ? (
            <EmptyState
              title="Zero Notifications"
              message="No telemetry alerts or approval notices currently pending."
            />
          ) : (
            <div className="space-y-6">
              {todayItems.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Today
                  </h3>
                  <div className="space-y-2">{todayItems.map(renderItem)}</div>
                </div>
              )}

              {thisWeekItems.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    This Week
                  </h3>
                  <div className="space-y-2">{thisWeekItems.map(renderItem)}</div>
                </div>
              )}

              {earlierItems.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                    Earlier
                  </h3>
                  <div className="space-y-2">{earlierItems.map(renderItem)}</div>
                </div>
              )}
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
