"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ShieldCheck,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/ui/Badges";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import {
  ArchButton,
  ArchBadge,
  ArchCard,
  ArchCardContent,
} from "@/components/ui/ArchitecturalComponents";
import { apiClient } from "@/lib/api/client";
import type { ActionResponse } from "@/lib/api/types";

export default function ActionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [action, setAction] = useState<ActionResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAction = useCallback(async () => {
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
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    apiClient.actions.get(id)
      .then((res) => {
        if (!cancelled) {
          setAction(res);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load action details");
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
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
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground font-mono transition-colors"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Action Monitor
            </Link>

            <Link href={`/verification?action_id=${action.id}`}>
              <ArchButton variant="default" size="sm">
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Verify Observed Outcome</span>
              </ArchButton>
            </Link>
          </div>

          {/* Header Banner */}
          <ArchCard elevated>
            <div className="p-5 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4 font-mono">
                <div className="space-y-1.5">
                  <span className="text-[10px] uppercase font-mono text-[#D95E00] block font-bold tracking-wider">
                    Phase 17 Operational Action Dispatch
                  </span>
                  <h1 className="text-xl font-bold text-foreground tracking-tight font-mono">
                    {action.action_type}
                  </h1>
                  <p className="text-xs text-muted-foreground font-mono">
                    ID: {action.id} • Target: {action.target_entity_type} ({action.target_entity_id || "GLOBAL"})
                  </p>
                </div>

                <div className="text-right">
                  <span className="text-[10px] uppercase font-mono text-muted-foreground block mb-1">Status</span>
                  <StatusBadge status={action.status} />
                </div>
              </div>

              {/* Stepper Bar */}
              <div className="pt-3 border-t border-arch">
                <div className="flex items-center justify-between overflow-x-auto pb-1">
                  {STAGES.map((stg, idx) => (
                    <React.Fragment key={stg}>
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        <div className="w-5 h-5 rounded-full bg-[#D95E00] text-white flex items-center justify-center text-[10px] font-mono font-bold">
                          {idx + 1}
                        </div>
                        <span className="text-[11px] font-mono text-foreground">{stg}</span>
                      </div>
                      {idx < STAGES.length - 1 && (
                        <div className="flex-1 h-0.5 mx-2 bg-[#D95E00]/60 min-w-[16px]" />
                      )}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </div>
          </ArchCard>

          {/* Execution Payload Inspection */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ArchCard>
              <ArchCardContent className="space-y-2">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-foreground">
                  Execution Payload (Command Ingestion)
                </h3>
                <pre
                  className="p-3 rounded border border-arch text-[11px] font-mono text-muted-foreground overflow-x-auto max-h-60"
                  style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border-arch)" }}
                >
                  {JSON.stringify(action.execution_payload || {}, null, 2)}
                </pre>
              </ArchCardContent>
            </ArchCard>

            <ArchCard>
              <ArchCardContent className="space-y-2">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-foreground">
                  Adapter Acknowledgement Result
                </h3>
                <pre
                  className="p-3 rounded border border-arch text-[11px] font-mono text-muted-foreground overflow-x-auto max-h-60"
                  style={{ backgroundColor: "var(--bg-primary)", borderColor: "var(--border-arch)" }}
                >
                  {JSON.stringify(action.result_payload || { status: "Awaiting adapter receipt" }, null, 2)}
                </pre>
              </ArchCardContent>
            </ArchCard>
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
