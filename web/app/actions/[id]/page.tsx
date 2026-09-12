"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  Layers,
  RefreshCw,
  ShieldCheck,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { ActionResponse } from "@/lib/api/types";

export default function ActionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [action, setAction] = useState<ActionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAction = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.actions.get(id);
      setAction(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load action details");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAction();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Loading action execution dossier..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !action) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/actions")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Actions
            </button>
            <ErrorState message={error || "Action not found."} onRetry={fetchAction} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  const STAGES = [
    "QUEUED",
    "VALIDATION",
    "APPROVAL_BINDING",
    "IDEMPOTENCY",
    "EXECUTION",
    "ADAPTER_ACK",
    "RESULT",
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <Link
              href="/actions"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Action Monitor
            </Link>

            <Link
              href={`/verification?action_id=${action.id}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Verify Observed Outcome</span>
            </Link>
          </div>

          {/* Header Banner */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1">
                <span className="text-[10px] uppercase font-mono text-blue-400 block font-bold">
                  Phase 17 Operational Action Dispatch
                </span>
                <h1 className="text-xl font-bold text-white tracking-tight font-mono">
                  {action.action_type}
                </h1>
                <p className="text-xs text-slate-400 font-mono">
                  ID: {action.id} • Target: {action.target_entity_type} ({action.target_entity_id || "GLOBAL"})
                </p>
              </div>

              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">Status</span>
                <StatusBadge status={action.status} />
              </div>
            </div>

            {/* Stepper Bar */}
            <div className="pt-3 border-t border-[#243044]">
              <div className="flex items-center justify-between overflow-x-auto pb-1">
                {STAGES.map((stg, idx) => (
                  <React.Fragment key={stg}>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      <div className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px] font-mono font-bold">
                        {idx + 1}
                      </div>
                      <span className="text-[11px] font-mono text-slate-300">{stg}</span>
                    </div>
                    {idx < STAGES.length - 1 && (
                      <div className="flex-1 h-0.5 mx-2 bg-blue-600 min-w-[16px]" />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>
          </div>

          {/* Execution Payload Inspection */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                Execution Payload (Command Ingestion)
              </h3>
              <pre className="p-3 rounded bg-[#070A0E] text-[11px] font-mono text-slate-300 overflow-x-auto max-h-60">
                {JSON.stringify(action.execution_payload || {}, null, 2)}
              </pre>
            </div>

            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                Adapter Acknowledgement Result
              </h3>
              <pre className="p-3 rounded bg-[#070A0E] text-[11px] font-mono text-slate-300 overflow-x-auto max-h-60">
                {JSON.stringify(action.result_payload || { status: "Awaiting adapter receipt" }, null, 2)}
              </pre>
            </div>
          </div>

          {/* Explicit Notice: SUBMITTED != VERIFIED */}
          <div className="p-3.5 rounded-lg bg-amber-950/20 border border-amber-900/40 text-xs text-amber-300 font-mono flex items-center justify-between">
            <span>IMPORTANT INVARIANT: SUBMITTED != VERIFIED</span>
            <span className="text-slate-400 text-[11px]">
              Adapter execution acknowledgement is not equivalent to verified business mitigation.
            </span>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
