"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Flame,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { RiskBadge, StatusBadge } from "@/components/ui/Badges";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { IncidentResponse, IncidentStatus, RiskSeverity } from "@/lib/api/types";

export default function IncidentsPage() {
  const router = useRouter();
  const [incidents, setIncidents] = useState<IncidentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const fetchIncidents = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.incidents.list({ limit: 100 });
      setIncidents(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load incidents");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchIncidents();
  }, []);

  const filteredIncidents = incidents.filter((inc) => {
    const matchesSearch =
      inc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inc.description && inc.description.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesStatus = statusFilter === "ALL" || inc.status === statusFilter;

    return matchesSearch && matchesStatus;
  });

  const columns: Column<IncidentResponse>[] = [
    {
      key: "id",
      header: "Incident ID",
      sortable: true,
      width: "120px",
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "title",
      header: "Disruption Title & Scope",
      sortable: true,
      render: (row) => (
        <div className="max-w-md">
          <span className="font-semibold text-slate-200 block truncate">{row.title}</span>
          <span className="text-[11px] text-slate-400 block truncate">
            {row.description || "Operational disruption incident"}
          </span>
        </div>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      sortable: true,
      render: (row) => <RiskBadge severity={row.severity} />,
    },
    {
      key: "status",
      header: "War Room Status",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.status === "RESOLVED" || row.status === "CLOSED") variant = "success";
        else if (row.status === "MITIGATING") variant = "warning";
        else if (row.status === "DETECTED") variant = "error";
        return <StatusBadge status={row.status} variant={variant} />;
      },
    },
    {
      key: "detected_at",
      header: "Detected",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {new Date(row.detected_at).toLocaleDateString()}
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
                Incident War Room Register
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                  {incidents.filter((i) => i.status !== "RESOLVED" && i.status !== "CLOSED").length} Active
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time disruption events triggering automated root-cause research, simulation & mitigation.
              </p>
            </div>

            <button
              onClick={fetchIncidents}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchIncidents} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search incidents, disruptions..."
          >
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
            >
              <option value="ALL">All Statuses</option>
              <option value="DETECTED">Detected</option>
              <option value="INVESTIGATING">Investigating</option>
              <option value="MITIGATING">Mitigating</option>
              <option value="RESOLVED">Resolved</option>
            </select>
          </TableToolbar>

          <DataTable
            columns={columns}
            data={filteredIncidents}
            isLoading={isLoading}
            emptyTitle="Zero Active Incidents"
            emptyMessage="No disruption incidents reported across active network."
            onRowClick={(row) => router.push(`/incidents/${row.id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
