"use client";

import React, { useEffect, useState } from "react";
import { GitFork, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { RouteResponse } from "@/lib/api/types";

export default function RoutesPage() {
  const [routes, setRoutes] = useState<RouteResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchRoutes = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.routes.list({ limit: 100 });
      setRoutes(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load routes");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRoutes();
  }, []);

  const filtered = routes.filter((r) => {
    const q = searchQuery.toLowerCase();
    return (
      r.origin_id.toLowerCase().includes(q) ||
      r.destination_id.toLowerCase().includes(q) ||
      r.mode.toLowerCase().includes(q)
    );
  });

  const columns: Column<RouteResponse>[] = [
    {
      key: "id",
      header: "Route ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-bold">{row.id.slice(0, 8)}...</span>
      ),
    },
    {
      key: "origin_id",
      header: "Origin Hub",
      sortable: true,
      render: (row) => <span className="font-mono text-xs text-slate-200">{row.origin_id}</span>,
    },
    {
      key: "destination_id",
      header: "Destination Hub",
      sortable: true,
      render: (row) => <span className="font-mono text-xs text-slate-200">{row.destination_id}</span>,
    },
    {
      key: "mode",
      header: "Transit Mode",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
          {row.mode}
        </span>
      ),
    },
    {
      key: "transit_time_days",
      header: "Lead Time (Days)",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.transit_time_days !== null && row.transit_time_days !== undefined
            ? `${row.transit_time_days} days`
            : "—"}
        </span>
      ),
    },
    {
      key: "cost_usd",
      header: "Baseline Cost",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.cost_usd !== null && row.cost_usd !== undefined ? `$${row.cost_usd.toLocaleString()}` : "—"}
        </span>
      ),
    },
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Logistics Corridors & Shipping Lanes
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {routes.length} Active Lanes
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Authoritative multi-modal transit corridors with benchmark costs and lead-time bounds.
              </p>
            </div>

            <button
              onClick={fetchRoutes}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchRoutes} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search routes by origin, destination, mode..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Shipping Lanes"
            emptyMessage="No transit corridors configured in current network topology."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
