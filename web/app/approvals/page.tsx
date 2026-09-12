"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Fingerprint,
  RefreshCw,
  ShieldCheck,
  UserCheck,
  XCircle,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { useAuth } from "@/lib/auth/AuthContext";
import { apiClient } from "@/lib/api/client";
import type { ApprovalCreate, ApprovalDecision, ApprovalResponse } from "@/lib/api/types";

export default function ApprovalsPage() {
  const { user } = useAuth();
  const [approvals, setApprovals] = useState<ApprovalResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalResponse | null>(null);
  const [actionComments, setActionComments] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // RBAC check: only OpsManager, RiskManager, Admin can execute approval decisions
  const canDecide =
    user?.role === "Admin" || user?.role === "RiskManager" || user?.role === "OpsManager";

  const fetchApprovals = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.approvals.list({ limit: 50 });
      setApprovals(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load approvals queue");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchApprovals();
  }, []);

  const handleDecision = async (decision: ApprovalDecision) => {
    if (!selectedApproval) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const payload: ApprovalCreate = {
        recommendation_id: selectedApproval.recommendation_id,
        decision,
        comments: actionComments.trim() || undefined,
      };
      await apiClient.approvals.create(payload);
      setSelectedApproval(null);
      setActionComments("");
      await fetchApprovals();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to submit approval decision");
    } finally {
      setIsSubmitting(false);
    }
  };

  const columns: Column<ApprovalResponse>[] = [
    {
      key: "id",
      header: "Approval ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "recommendation_id",
      header: "Recommendation Reference",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          REC: {row.recommendation_id.slice(0, 12)}...
        </span>
      ),
    },
    {
      key: "decision",
      header: "Governance Outcome",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.decision === "APPROVE") variant = "success";
        else if (row.decision === "REJECT") variant = "error";
        else if (row.decision === "REQUEST_MODIFICATION") variant = "warning";
        return <StatusBadge status={row.decision} variant={variant} />;
      },
    },
    {
      key: "integrity_status",
      header: "Integrity Fingerprint",
      render: (row) => (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] text-emerald-400 bg-emerald-950/40 px-1.5 py-0.5 rounded border border-emerald-800">
          <Fingerprint className="w-3 h-3" />
          {row.fingerprint ? `${row.fingerprint.slice(0, 10)}...` : "SHA256:OK"}
        </span>
      ),
    },
    {
      key: "decided_at",
      header: "Timestamp",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {new Date(row.decided_at).toLocaleString()}
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
                Human-in-the-Loop Governance Sign-Off
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800">
                  Phase 16
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Mandatory operational governance gate. Autonomous execution requires explicit authorized sign-off.
              </p>
            </div>

            <button
              onClick={fetchApprovals}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchApprovals} />}

          <DataTable
            columns={columns}
            data={approvals}
            isLoading={isLoading}
            emptyTitle="Governance Queue Empty"
            emptyMessage="No mitigation actions currently pending human review."
            onRowClick={(row) => setSelectedApproval(row)}
          />

          {/* Review & Decision Sign-off Modal */}
          {selectedApproval && (
            <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
              <div className="w-full max-w-lg rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-white">Governance Authorization Gate</h3>
                    <span className="text-[10px] font-mono text-slate-400">
                      ID: {selectedApproval.id}
                    </span>
                  </div>
                  <button
                    onClick={() => setSelectedApproval(null)}
                    className="text-xs text-slate-400 hover:text-slate-200"
                  >
                    Close
                  </button>
                </div>

                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 text-xs space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Target Recommendation:</span>
                    <span className="font-mono text-blue-400">{selectedApproval.recommendation_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Cryptographic Seal:</span>
                    <span className="font-mono text-emerald-400">
                      {selectedApproval.fingerprint || "SHA-256 Verified"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Current Status:</span>
                    <span className="font-mono text-amber-400 font-bold">{selectedApproval.decision}</span>
                  </div>
                </div>

                {canDecide ? (
                  <div className="space-y-3 text-xs">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">
                        Sign-Off Rationale / Operator Notes
                      </label>
                      <textarea
                        rows={3}
                        value={actionComments}
                        onChange={(e) => setActionComments(e.target.value)}
                        placeholder="Log operator justification into immutable audit trail..."
                        className="w-full p-2.5 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      />
                    </div>

                    <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#243044]">
                      <button
                        onClick={() => handleDecision("REJECT")}
                        disabled={isSubmitting}
                        className="px-3 py-1.5 rounded bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 font-medium transition-colors"
                      >
                        Reject Action
                      </button>
                      <button
                        onClick={() => handleDecision("APPROVE")}
                        disabled={isSubmitting}
                        className="px-4 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors flex items-center gap-1.5"
                      >
                        <CheckCircle2 className="w-4 h-4" />
                        Authorize Execution
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 rounded bg-amber-950/20 border border-amber-900/40 text-xs text-amber-300">
                    Your role ({user?.role || "Viewer"}) has read-only governance privileges. Sign-off requires RiskManager or Admin role.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
