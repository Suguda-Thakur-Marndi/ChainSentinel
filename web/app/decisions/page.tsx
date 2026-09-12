"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Plus,
  RefreshCw,
  Scale,
  Sparkles,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { DecisionResult } from "@/lib/api/types";

export default function DecisionsPage() {
  const router = useRouter();
  const [decisions, setDecisions] = useState<DecisionResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDecisions = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.decisions.list({ limit: 50 });
      setDecisions(Array.isArray(data) ? data : (data as any)?.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load decisions");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDecisions();
  }, []);

  const columns: Column<DecisionResult>[] = [
    {
      key: "decision_id",
      header: "Decision ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.decision_id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "title",
      header: "Decision Strategy",
      sortable: true,
      render: (row) => (
        <div className="max-w-md">
          <span className="font-semibold text-slate-200 block truncate">{row.title}</span>
          <span className="text-[11px] text-slate-400 block truncate">{row.rationale}</span>
        </div>
      ),
    },
    {
      key: "decision_status",
      header: "Status",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.decision_status === "APPROVED") variant = "success";
        else if (row.decision_status === "REJECTED") variant = "error";
        else if (row.decision_status === "SUBMITTED") variant = "warning";
        return <StatusBadge status={row.decision_status} variant={variant} />;
      },
    },
    {
      key: "candidates",
      header: "Alternatives",
      align: "center",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.candidates?.length ?? 0} candidates
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Formulated At",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {new Date(row.created_at).toLocaleString()}
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
                Decision Formulation Subsystem
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  Phase 15
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic synthesis of risk, prediction, scenario, and solver outcomes into actionable candidates.
              </p>
            </div>

            <button
              onClick={fetchDecisions}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchDecisions} />}

          <DataTable
            columns={columns}
            data={decisions}
            isLoading={isLoading}
            emptyTitle="No Formulated Decisions"
            emptyMessage="Decisions formulate automatically from active disruption incidents."
            onRowClick={(row) => router.push(`/decisions/${row.decision_id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
