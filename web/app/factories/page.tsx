"use client";

import React, { useEffect, useState } from "react";
import { Factory, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { FactoryResponse } from "@/lib/api/types";

export default function FactoriesPage() {
  const [factories, setFactories] = useState<FactoryResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchFactories = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.factories.list({ limit: 100 });
      setFactories(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load factories");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchFactories();
  }, []);

  const filtered = factories.filter((f) => {
    const q = searchQuery.toLowerCase();
    return (
      f.name.toLowerCase().includes(q) ||
      f.country.toLowerCase().includes(q) ||
      (f.city && f.city.toLowerCase().includes(q))
    );
  });

  const columns: Column<FactoryResponse>[] = [
    {
      key: "name",
      header: "Factory / Plant Name",
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
      header: "Utilization",
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
      header: "Plant Status",
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
                Manufacturing Plants & Factories
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {factories.length} Facilities
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Primary assembly lines, component fabrication plants, and OEM manufacturing nodes.
              </p>
            </div>

            <button
              onClick={fetchFactories}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchFactories} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search factories by name, city, country..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Factories Found"
            emptyMessage="No manufacturing plants registered in active tenant supply chain."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
