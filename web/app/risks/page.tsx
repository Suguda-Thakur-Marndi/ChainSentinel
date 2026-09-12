"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  Filter,
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
import type { RiskResponse, RiskSeverity } from "@/lib/api/types";

export default function RisksPage() {
  const router = useRouter();
  const [risks, setRisks] = useState<RiskResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");

  const fetchRisks = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.risks.list({ limit: 100 });
      setRisks(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load risk register");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRisks();
  }, []);

  const filteredRisks = risks.filter((r) => {
    const matchesSearch =
      r.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (r.location && r.location.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (r.source && r.source.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesSeverity = severityFilter === "ALL" || r.severity === severityFilter;

    return matchesSearch && matchesSeverity;
  });

  const columns: Column<RiskResponse>[] = [
    {
      key: "id",
      header: "Risk ID",
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
      header: "Threat Assessment",
      sortable: true,
      render: (row) => (
        <div className="max-w-md">
          <span className="font-semibold text-slate-200 block truncate">{row.title}</span>
          <span className="text-[11px] text-slate-400 block truncate">{row.location || "Global"}</span>
        </div>
      ),
    },
    {
      key: "severity",
      header: "Severity & Score",
      sortable: true,
      render: (row) => <RiskBadge severity={row.severity} score={row.risk_score} />,
    },
    {
      key: "trend",
      header: "Trend",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-300 px-2 py-0.5 rounded bg-slate-800 border border-slate-700">
          {row.trend}
        </span>
      ),
    },
    {
      key: "source",
      header: "Ingestion Source",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">{row.source || "SYSTEM"}</span>
      ),
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
                Authoritative Risk Register
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                  {risks.filter((r) => r.severity === "CRITICAL").length} Critical
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic Bayesian and empirical risk scoring across supplier, port, route, and cargo vectors.
              </p>
            </div>

            <button
              onClick={fetchRisks}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Sync Risk Engine"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchRisks} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search risk signals, locations, sources..."
          >
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
            >
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
          </TableToolbar>

          <DataTable
            columns={columns}
            data={filteredRisks}
            isLoading={isLoading}
            emptyTitle="Zero Active Threats"
            emptyMessage="Risk register has no signals matching selected criteria."
            onRowClick={(row) => router.push(`/risks/${row.id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
