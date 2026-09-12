"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  DollarSign,
  RefreshCw,
  Scale,
  Sparkles,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { RecommendationResponse, RecommendationStatus } from "@/lib/api/types";

export default function RecommendationsPage() {
  const router = useRouter();
  const [recommendations, setRecommendations] = useState<RecommendationResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");

  const fetchRecommendations = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.recommendations.list({ limit: 100 });
      setRecommendations(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load recommendations");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRecommendations();
  }, []);

  const filtered = recommendations.filter((r) => {
    const matchesSearch =
      r.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (r.rationale && r.rationale.toLowerCase().includes(searchQuery.toLowerCase()));
    const matchesStatus = statusFilter === "ALL" || r.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const columns: Column<RecommendationResponse>[] = [
    {
      key: "id",
      header: "Recommendation ID",
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
      header: "Mitigation Strategy",
      sortable: true,
      render: (row) => (
        <div className="max-w-md">
          <span className="font-semibold text-slate-200 block truncate">{row.title}</span>
          <span className="text-[11px] text-slate-400 block truncate">
            {row.rationale || "Formulated mitigation strategy"}
          </span>
        </div>
      ),
    },
    {
      key: "estimated_cost",
      header: "Cost Impact",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.estimated_cost !== null && row.estimated_cost !== undefined
            ? `$${row.estimated_cost.toLocaleString()}`
            : "—"}
        </span>
      ),
    },
    {
      key: "confidence",
      header: "Confidence",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-emerald-400">
          {row.confidence !== null && row.confidence !== undefined
            ? `${(row.confidence * 100).toFixed(0)}%`
            : "—"}
        </span>
      ),
    },
    {
      key: "status",
      header: "Governance Status",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.status === "APPROVED" || row.status === "EXECUTED") variant = "success";
        else if (row.status === "REJECTED") variant = "error";
        else if (row.status === "PENDING") variant = "warning";
        return <StatusBadge status={row.status} variant={variant} />;
      },
    },
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Operational Recommendations
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  Phase 15
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic solver mitigation strategies synthesized with RAG policy evidence.
              </p>
            </div>

            <button
              onClick={fetchRecommendations}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchRecommendations} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search recommendations..."
          >
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
            >
              <option value="ALL">All Statuses</option>
              <option value="PENDING">Pending Approval</option>
              <option value="APPROVED">Approved</option>
              <option value="EXECUTED">Executed</option>
              <option value="REJECTED">Rejected</option>
            </select>
          </TableToolbar>

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Recommendations"
            emptyMessage="No mitigation recommendations formulated yet."
            onRowClick={(row) => router.push(`/recommendations/${row.id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
