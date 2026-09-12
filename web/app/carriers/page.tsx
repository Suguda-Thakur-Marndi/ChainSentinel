"use client";

import React, { useEffect, useState } from "react";
import { RefreshCw, Ship } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { CarrierResponse } from "@/lib/api/types";

export default function CarriersPage() {
  const [carriers, setCarriers] = useState<CarrierResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchCarriers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.carriers.list({ limit: 100 });
      setCarriers(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load carriers");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCarriers();
  }, []);

  const filtered = carriers.filter((c) => {
    const q = searchQuery.toLowerCase();
    return c.name.toLowerCase().includes(q) || c.code.toLowerCase().includes(q);
  });

  const columns: Column<CarrierResponse>[] = [
    {
      key: "code",
      header: "Carrier Code",
      sortable: true,
      width: "140px",
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-bold">{row.code}</span>
      ),
    },
    {
      key: "name",
      header: "Carrier Line",
      sortable: true,
      render: (row) => <span className="font-semibold text-slate-200">{row.name}</span>,
    },
    {
      key: "mode",
      header: "Operational Mode",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
          {row.mode}
        </span>
      ),
    },
    {
      key: "reliability_rating",
      header: "Reliability",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs font-bold text-slate-200">
          {row.reliability_rating !== null && row.reliability_rating !== undefined
            ? `${row.reliability_rating}/10`
            : "—"}
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
                Carriers & Freight Forwarders
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {carriers.length} Active
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Contracted ocean shipping lines, airfreight forwarders, and intermodal drayage carriers.
              </p>
            </div>

            <button
              onClick={fetchCarriers}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchCarriers} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search carriers by name or code..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Carriers Registered"
            emptyMessage="No logistics carriers configured in current network."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
