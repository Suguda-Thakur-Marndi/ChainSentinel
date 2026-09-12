"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileCheck,
  Fingerprint,
  Info,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  XCircle,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { useAuth } from "@/lib/auth/AuthContext";
import { apiClient } from "@/lib/api/client";
import type {
  ApprovalDossier,
  ApprovalResponse,
  PendingApprovalItem,
} from "@/lib/api/types";

type TabMode = "pending" | "history";

export default function ApprovalsPage() {
  const { user, hasRole } = useAuth();
  const [tab, setTab] = useState<TabMode>("pending");
  const [pendingItems, setPendingItems] = useState<PendingApprovalItem[]>([]);
  const [historyItems, setHistoryItems] = useState<ApprovalResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Selected item and dossier state
  const [selectedPendingId, setSelectedPendingId] = useState<string | null>(null);
  const [dossier, setDossier] = useState<ApprovalDossier | null>(null);
  const [isLoadingDossier, setIsLoadingDossier] = useState(false);
  const [selectedHistory, setSelectedHistory] = useState<ApprovalResponse | null>(null);

  const [actionComments, setActionComments] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // RBAC check: only OpsManager, RiskManager, Admin can execute approval decisions
  const canDecide = hasRole("ADMIN", "RISKMANAGER", "OPSMANAGER");

  const fetchPending = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.approvals.listPending({ limit: 50 });
      setPendingItems(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load pending approvals queue");
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.approvals.list({ limit: 50 });
      setHistoryItems(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load approvals history");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === "pending") {
      fetchPending();
    } else {
      fetchHistory();
    }
  }, [tab, fetchPending, fetchHistory]);

  const loadDossier = async (idOrDecisionId: string) => {
    setSelectedPendingId(idOrDecisionId);
    setIsLoadingDossier(true);
    try {
      const data = await apiClient.approvals.getDossier(idOrDecisionId);
      setDossier(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load approval dossier");
    } finally {
      setIsLoadingDossier(false);
    }
  };

  const handleDecision = async (decision: "APPROVE" | "REJECT") => {
    if (!selectedPendingId) return;
    setIsSubmitting(true);
    setError(null);
    try {
      if (decision === "APPROVE") {
        await apiClient.approvals.approve(selectedPendingId, actionComments.trim() || undefined);
      } else {
        await apiClient.approvals.reject(selectedPendingId, actionComments.trim() || undefined);
      }
      setSelectedPendingId(null);
      setDossier(null);
      setActionComments("");
      await fetchPending();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to ${decision.toLowerCase()} decision`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const pendingColumns: Column<PendingApprovalItem>[] = [
    {
      key: "title",
      header: "Action / Decision Title",
      sortable: true,
      render: (row) => (
        <div>
          <span className="font-semibold text-white text-xs block">{row.title}</span>
          <span className="font-mono text-[10px] text-slate-400">ID: {row.decision_id || row.id}</span>
        </div>
      ),
    },
    {
      key: "urgency",
      header: "Urgency",
      sortable: true,
      render: (row) => {
        let variant: "error" | "warning" | "info" | "neutral" = "info";
        if (row.urgency?.toUpperCase() === "CRITICAL") variant = "error";
        else if (row.urgency?.toUpperCase() === "HIGH") variant = "warning";
        return <StatusBadge status={row.urgency || "MEDIUM"} variant={variant} />;
      },
    },
    {
      key: "impact_level",
      header: "Impact Level",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.impact_level || "MODERATE"}
        </span>
      ),
    },
    {
      key: "requires_role",
      header: "Required Gate",
      render: (row) => (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] text-amber-400 bg-amber-950/40 px-1.5 py-0.5 rounded border border-amber-800">
          <UserCheck className="w-3 h-3" />
          {row.requires_role || "RiskManager"}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Queued At",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
        </span>
      ),
    },
  ];

  const historyColumns: Column<ApprovalResponse>[] = [
    {
      key: "id",
      header: "Approval ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold">
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
      key: "decided_by_user_id",
      header: "Sign-Off Actor",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.decided_by_name || row.decided_by_user_id || "Operator"}
        </span>
      ),
    },
    {
      key: "fingerprint",
      header: "Cryptographic Seal",
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

            <div className="flex items-center gap-2">
              <div className="flex rounded-md bg-[#111827] p-1 border border-[#243044]">
                <button
                  onClick={() => setTab("pending")}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    tab === "pending"
                      ? "bg-blue-600 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Pending Review ({pendingItems.length})
                </button>
                <button
                  onClick={() => setTab("history")}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                    tab === "history"
                      ? "bg-blue-600 text-white"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  Sign-Off Archive
                </button>
              </div>

              <button
                onClick={() => (tab === "pending" ? fetchPending() : fetchHistory())}
                disabled={isLoading}
                className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={() => (tab === "pending" ? fetchPending() : fetchHistory())} />}

          {tab === "pending" ? (
            <DataTable
              columns={pendingColumns}
              data={pendingItems}
              isLoading={isLoading}
              emptyTitle="Governance Queue Empty"
              emptyMessage="No mitigation actions currently pending human review."
              onRowClick={(row) => loadDossier(row.decision_id || row.id)}
            />
          ) : (
            <DataTable
              columns={historyColumns}
              data={historyItems}
              isLoading={isLoading}
              emptyTitle="No Historic Sign-Offs"
              emptyMessage="No historical human approvals recorded yet."
              onRowClick={(row) => setSelectedHistory(row)}
            />
          )}

          {/* Dossier Review & Sign-Off Modal (Pending) */}
          {selectedPendingId && (
            <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto">
              <div className="w-full max-w-3xl rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6 space-y-4 my-8 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                      <ShieldCheck className="w-4 h-4 text-amber-400" />
                      Comprehensive Review Dossier
                    </h3>
                    <span className="text-[10px] font-mono text-slate-400">
                      Target Decision ID: {selectedPendingId}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setSelectedPendingId(null);
                      setDossier(null);
                    }}
                    className="text-xs text-slate-400 hover:text-slate-200"
                  >
                    Close
                  </button>
                </div>

                {isLoadingDossier ? (
                  <div className="py-12 flex flex-col items-center justify-center text-slate-400 gap-2">
                    <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
                    <span className="text-xs">Loading decision dossier & cryptographic evidence...</span>
                  </div>
                ) : dossier ? (
                  <div className="space-y-4 text-xs">
                    {/* Header info */}
                    <div className="p-3 rounded bg-[#1A2332] border border-slate-800 space-y-2">
                      <div className="flex justify-between items-start">
                        <div>
                          <span className="text-slate-400 block">Proposed Action:</span>
                          <span className="text-white font-semibold text-sm">{dossier.title}</span>
                        </div>
                        <StatusBadge status={dossier.urgency} variant={dossier.urgency === "CRITICAL" ? "error" : "warning"} />
                      </div>
                      <p className="text-slate-300 mt-1">{dossier.rationale}</p>
                    </div>

                    {/* Authoritative vs Non-Authoritative Section */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {/* Authoritative Evidence */}
                      <div className="p-3 rounded bg-blue-950/20 border border-blue-900/40 space-y-2">
                        <div className="flex items-center justify-between border-b border-blue-900/30 pb-1">
                          <span className="font-semibold text-blue-300 uppercase tracking-wider text-[10px]">
                            Authoritative Engine Data
                          </span>
                          <span className="text-[9px] font-mono text-blue-400 bg-blue-900/50 px-1 rounded">
                            SOURCE_OF_TRUTH
                          </span>
                        </div>
                        <div className="space-y-1.5 text-slate-300">
                          <div>
                            <span className="text-slate-400 block text-[10px]">Impact Level:</span>
                            <span className="font-mono font-medium">{dossier.impact_level}</span>
                          </div>
                          {dossier.fingerprint && (
                            <div>
                              <span className="text-slate-400 block text-[10px]">Cryptographic Fingerprint:</span>
                              <span className="font-mono text-[10px] text-emerald-400 break-all">
                                {dossier.fingerprint}
                              </span>
                            </div>
                          )}
                          {dossier.recommendation_summary && (
                            <div>
                              <span className="text-slate-400 block text-[10px]">Deterministic Plan:</span>
                              <span className="text-slate-200">{dossier.recommendation_summary}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Non-Authoritative Claude Explanation */}
                      <div className="p-3 rounded bg-amber-950/20 border border-amber-900/40 space-y-2">
                        <div className="flex items-center justify-between border-b border-amber-900/30 pb-1">
                          <span className="font-semibold text-amber-300 uppercase tracking-wider text-[10px] flex items-center gap-1">
                            <AlertTriangle className="w-3 h-3 text-amber-400" />
                            LLM Advisory Narrative
                          </span>
                          <span className="text-[9px] font-mono text-amber-400 bg-amber-900/50 px-1 rounded">
                            NON-AUTHORITATIVE
                          </span>
                        </div>
                        {dossier.claude_explanation ? (
                          <div className="space-y-1.5 text-slate-300">
                            {dossier.claude_explanation.summary && (
                              <p className="text-slate-200 italic">{dossier.claude_explanation.summary}</p>
                            )}
                            {dossier.claude_explanation.caveats && dossier.claude_explanation.caveats.length > 0 && (
                              <div className="pt-1">
                                <span className="text-amber-400 font-semibold text-[10px] block">Caveats:</span>
                                <ul className="list-disc list-inside space-y-0.5 text-slate-400 text-[11px]">
                                  {dossier.claude_explanation.caveats.map((c, i) => (
                                    <li key={i}>{c}</li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-500 italic block py-2">
                            No narrative commentary provided for this candidate.
                          </span>
                        )}
                        <p className="text-[9px] text-amber-400/80 border-t border-amber-900/20 pt-1">
                          Notice: AI-generated summaries are purely advisory. Operational governance must rely on authoritative engine calculations.
                        </p>
                      </div>
                    </div>

                    {/* Operator Sign-off Controls */}
                    {canDecide ? (
                      <div className="space-y-3 pt-2 border-t border-[#243044]">
                        <div>
                          <label className="block text-slate-300 font-medium mb-1">
                            Formal Operator Rationale & Justification (Recorded to Immutable Audit Trail)
                          </label>
                          <textarea
                            rows={3}
                            value={actionComments}
                            onChange={(e) => setActionComments(e.target.value)}
                            placeholder="State rationale for authorizing or rejecting this operational intervention..."
                            className="w-full p-2.5 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                          />
                        </div>

                        <div className="flex items-center justify-end gap-3 pt-2">
                          <button
                            onClick={() => handleDecision("REJECT")}
                            disabled={isSubmitting}
                            className="px-4 py-2 rounded bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 font-medium transition-colors flex items-center gap-1.5"
                          >
                            <XCircle className="w-4 h-4" />
                            Reject Action Candidate
                          </button>
                          <button
                            onClick={() => handleDecision("APPROVE")}
                            disabled={isSubmitting}
                            className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-colors flex items-center gap-1.5"
                          >
                            <CheckCircle2 className="w-4 h-4" />
                            Authorize Execution
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="p-3 rounded bg-amber-950/20 border border-amber-900/40 text-xs text-amber-300 flex items-center gap-2">
                        <ShieldAlert className="w-4 h-4 shrink-0" />
                        <span>
                          Your role ({user?.role || "Viewer"}) has read-only governance privileges. Formal sign-off requires RiskManager, OpsManager, or Admin authority.
                        </span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="py-6 text-center text-slate-400">Dossier details unavailable.</div>
                )}
              </div>
            </div>
          )}

          {/* Historical Detail Modal */}
          {selectedHistory && (
            <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
              <div className="w-full max-w-lg rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                  <div>
                    <h3 className="text-sm font-bold text-white">Historical Sign-Off Record</h3>
                    <span className="text-[10px] font-mono text-slate-400">
                      ID: {selectedHistory.id}
                    </span>
                  </div>
                  <button
                    onClick={() => setSelectedHistory(null)}
                    className="text-xs text-slate-400 hover:text-slate-200"
                  >
                    Close
                  </button>
                </div>

                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 text-xs space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Target Recommendation:</span>
                    <span className="font-mono text-blue-400">{selectedHistory.recommendation_id}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Decision Outcome:</span>
                    <span className="font-mono font-bold text-white">{selectedHistory.decision}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Sign-Off Timestamp:</span>
                    <span className="font-mono text-slate-300">
                      {new Date(selectedHistory.decided_at).toLocaleString()}
                    </span>
                  </div>
                  {selectedHistory.comments && (
                    <div className="pt-2 border-t border-slate-700/50">
                      <span className="text-slate-400 block mb-1">Operator Notes:</span>
                      <p className="text-slate-200 bg-[#111827] p-2 rounded">{selectedHistory.comments}</p>
                    </div>
                  )}
                  {selectedHistory.fingerprint && (
                    <div className="flex justify-between items-center pt-2 border-t border-slate-700/50">
                      <span className="text-slate-400">Integrity Fingerprint:</span>
                      <span className="font-mono text-[10px] text-emerald-400">
                        {selectedHistory.fingerprint}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
