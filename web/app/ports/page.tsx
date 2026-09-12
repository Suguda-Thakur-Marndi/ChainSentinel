"use client";

import React, { useEffect, useState } from "react";
import { Anchor, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { PortResponse } from "@/lib/api/types";

export default function PortsPage() {
  const [ports, setPorts] = useState<PortResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchPorts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.ports.list({ limit: 100 });
      setPorts(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load ports");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchPorts();
  }, []);

  const filtered = ports.filter((p) => {
    const q = searchQuery.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      p.code.toLowerCase().includes(q) ||
      p.country.toLowerCase().includes(q)
    );
  });

  const columns: Column<PortResponse>[] = [
    {
      key: "code",
      header: "UN/LOCODE",
      sortable: true,
      width: "120px",
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-bold">{row.code}</span>
      ),
    },
    {
      key: "name",
      header: "Port / Terminal Name",
      sortable: true,
      render: (row) => <span className="font-semibold text-slate-200">{row.name}</span>,
    },
    {
      key: "country",
      header: "Country",
      sortable: true,
      render: (row) => <span className="text-slate-300">{row.country}</span>,
    },
    {
      key: "port_type",
      header: "Modal Type",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
          {row.port_type}
        </span>
      ),
    },
    {
      key: "is_operational",
      header: "Status",
      render: (row) => (
        <StatusBadge
          status={row.is_operational ? "OPERATIONAL" : "DISRUPTED"}
          variant={row.is_operational ? "success" : "error"}
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
                Ports & Terminal Hubs
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {ports.length} Hubs
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Global maritime gateways, airport airfreight terminals, and inland dry ports.
              </p>
            </div>

            <button
              onClick={fetchPorts}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchPorts} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search ports by LOCODE, name, country..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Ports Found"
            emptyMessage="No maritime or aviation ports registered in current tenant network."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
