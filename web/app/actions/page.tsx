"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  RefreshCw,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { ActionResponse } from "@/lib/api/types";

export default function ActionsPage() {
  const router = useRouter();
  const [actions, setActions] = useState<ActionResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchActions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.actions.list({ limit: 50 });
      setActions(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load actions");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchActions();
  }, [fetchActions]);

  const columns: Column<ActionResponse>[] = [
    {
      key: "id",
      header: "Action ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "action_type",
      header: "Execution Type",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-200 font-semibold uppercase">
          {row.action_type}
        </span>
      ),
    },
    {
      key: "status",
      header: "Execution Status",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.status === "SUCCEEDED") {
          variant = "success";
        } else if (row.status === "SUBMITTED") {
          variant = "info";
        } else if (row.status === "FAILED" || row.status === "TIMEOUT") {
          variant = "error";
        } else if (row.status === "EXECUTING" || row.status === "VALIDATING" || row.status === "PENDING") {
          variant = "warning";
        }
        return (
          <div className="flex items-center gap-1.5">
            <StatusBadge status={row.status} variant={variant} />
            {row.status === "SUBMITTED" && (
              <span className="text-[10px] text-amber-400/90 font-mono">(Unverified)</span>
            )}
          </div>
        );
      },
    },
    {
      key: "target_entity_id",
      header: "Target Entity",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {row.target_entity_type || "ENTITY"}: {row.target_entity_id || "GLOBAL"}
        </span>
      ),
    },
    {
      key: "executed_at",
      header: "Execution Ping",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {row.executed_at ? new Date(row.executed_at).toLocaleString() : "—"}
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
                Operational Action Execution Monitor
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  Phase 17
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Idempotent operational dispatch via ERP, TMS, and carrier execution adapters.
              </p>
            </div>

            <button
              onClick={fetchActions}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchActions} />}

          {/* Stepper Banner Notice */}
          <div className="p-3 rounded-md bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between text-xs text-slate-400 gap-2">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-slate-200">Execution Stepper:</span>
              <span className="font-mono text-[11px]">
                Queued → Validation → Approval Binding → Idempotency → Execution → Adapter Ack
              </span>
            </div>
            <span className="text-amber-400/90 font-mono text-[11px] font-semibold">
              SUBMITTED != VERIFIED
            </span>
          </div>

          <DataTable
            columns={columns}
            data={actions}
            isLoading={isLoading}
            emptyTitle="No Dispatched Actions"
            emptyMessage="No operational mitigations have been dispatched to execution adapters."
            onRowClick={(row) => router.push(`/actions/${row.id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
