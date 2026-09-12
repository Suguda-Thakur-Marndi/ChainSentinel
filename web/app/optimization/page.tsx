"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Cpu,
  Play,
  RefreshCw,
  Sliders,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { OptimizationStatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { OptimizationRequest, OptimizationResult } from "@/lib/api/types";

export default function OptimizationPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<OptimizationResult[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSolving, setIsSolving] = useState(false);

  const fetchRuns = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await apiClient.optimization.list({ limit: 50 });
      setRuns(Array.isArray(data) ? data : (data as any)?.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load optimization runs");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleTriggerRun = async () => {
    setIsSolving(true);
    setError(null);
    try {
      const payload: OptimizationRequest = {
        objective: "MULTI_OBJECTIVE",
      };
      const res = await apiClient.optimization.create(payload);
      router.push(`/optimization/${res.optimization_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Optimization solver failed");
      setIsSolving(false);
    }
  };

  const columns: Column<OptimizationResult>[] = [
    {
      key: "optimization_id",
      header: "Optimization Run ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.optimization_id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "status",
      header: "Solver Status",
      sortable: true,
      render: (row) => <OptimizationStatusBadge status={row.status} />,
    },
    {
      key: "objective",
      header: "Optimization Objective",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-300 uppercase">{row.objective}</span>
      ),
    },
    {
      key: "runtime_ms",
      header: "Solver Latency",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-400">{row.runtime_ms} ms</span>
      ),
    },
    {
      key: "created_at",
      header: "Triggered At",
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
                Mathematical Optimization Engine
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  Google OR-Tools
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic Mixed-Integer Linear Programming (MILP) solver for multi-objective cost, delay & risk trade-offs.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={fetchRuns}
                disabled={isLoading}
                className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              </button>
              <button
                onClick={handleTriggerRun}
                disabled={isSolving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors disabled:opacity-50"
              >
                <Play className="w-3.5 h-3.5" />
                <span>{isSolving ? "Solving MILP..." : "Trigger Optimization Run"}</span>
              </button>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchRuns} />}

          <DataTable
            columns={columns}
            data={runs}
            isLoading={isLoading}
            emptyTitle="Zero Optimization Runs"
            emptyMessage="Trigger an optimization run to solve operational rerouting or supplier reallocation."
            onRowClick={(row) => router.push(`/optimization/${row.optimization_id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
