"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw, Warehouse } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { WarehouseResponse } from "@/lib/api/types";

export default function WarehousesPage() {
  const [warehouses, setWarehouses] = useState<WarehouseResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchWarehouses = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.warehouses.list({ limit: 100 });
      setWarehouses(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load warehouses");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchWarehouses();
  }, []);

  const filtered = warehouses.filter((w) => {
    const q = searchQuery.toLowerCase();
    return (
      w.name.toLowerCase().includes(q) ||
      w.country.toLowerCase().includes(q) ||
      (w.city && w.city.toLowerCase().includes(q))
    );
  });

  const columns: Column<WarehouseResponse>[] = [
    {
      key: "name",
      header: "Warehouse / DC Hub",
      sortable: true,
      render: (row) => <span className="font-semibold text-slate-200">{row.name}</span>,
    },
    {
      key: "country",
      header: "Location",
      sortable: true,
      render: (row) => (
        <span className="text-slate-300">
          {row.city ? `${row.city}, ` : ""}
          {row.country}
        </span>
      ),
    },
    {
      key: "capacity_utilization",
      header: "Storage Utilization",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-200">
          {row.capacity_utilization !== null && row.capacity_utilization !== undefined
            ? `${(row.capacity_utilization * 100).toFixed(0)}%`
            : "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "DC Status",
      sortable: true,
      render: (row) => (
        <StatusBadge
          status={row.status}
          variant={row.status === "OPERATIONAL" ? "success" : "warning"}
        />
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
                Warehouses & Distribution Centers
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {warehouses.length} Hubs
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Regional fulfillment nodes, buffer inventory storage, and bonded cross-dock centers.
              </p>
            </div>

            <button
              onClick={fetchWarehouses}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchWarehouses} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search warehouses by name, city, country..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Warehouses Found"
            emptyMessage="No storage or distribution centers configured in current network."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
