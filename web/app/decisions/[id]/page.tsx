"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Scale,
  Sparkles,
  UserCheck,
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
import type { DecisionResult } from "@/lib/api/types";

export default function DecisionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [decision, setDecision] = useState<DecisionResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDecision = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.decisions.get(id);
      setDecision(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load decision detail");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    if (!id) return;
    apiClient.decisions
      .get(id)
      .then((res) => {
        if (!cancelled) {
          setDecision(res);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load decision detail");
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
          <LoadingState message="Loading decision strategy..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !decision) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/decisions")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Decisions
            </button>
            <ErrorState message={error || "Decision not found."} onRetry={fetchDecision} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <Link
              href="/decisions"
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground font-mono transition-colors"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Decisions
            </Link>

            <Link href={`/approvals?decision_id=${decision.decision_id}`}>
              <ArchButton variant="default" size="sm">
                <UserCheck className="w-3.5 h-3.5" />
                <span>Submit to Human Gate</span>
              </ArchButton>
            </Link>
          </div>

          <ArchCard elevated>
            <div className="p-5 flex flex-wrap items-center justify-between gap-4 font-mono">
              <div className="space-y-1.5 max-w-2xl">
                <span className="text-[10px] uppercase font-mono text-[#D95E00] block font-bold tracking-wider">
                  Phase 15 Decision Synthesis
                </span>
                <h1 className="text-xl font-bold text-foreground tracking-tight">{decision.title}</h1>
                <p className="text-xs text-muted-foreground font-mono">
                  ID: {decision.decision_id} • Score: {decision.deterministic_score !== undefined && decision.deterministic_score !== null ? decision.deterministic_score.toFixed(3) : "N/A"}
                </p>
              </div>

              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-muted-foreground block mb-1">Status</span>
                <StatusBadge status={decision.decision_status || (decision as unknown as { status?: string }).status || "PENDING"} />
              </div>
            </div>
          </ArchCard>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ArchCard>
              <ArchCardContent className="space-y-2.5">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                  <Scale className="w-4 h-4 text-[#D95E00]" /> Deterministic Synthesis Rationale
                </h3>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed">{decision.rationale}</p>
              </ArchCardContent>
            </ArchCard>

            {decision.ai_explanation && (
              <ArchCard className="border-[#0A7A75]/30">
                <ArchCardContent className="space-y-2.5">
                  <div className="flex items-center justify-between font-mono">
                    <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-[#0A7A75] flex items-center gap-1.5">
                      <Sparkles className="w-4 h-4 text-[#0A7A75]" /> Advisory AI Reasoning
                    </h3>
                    <ArchBadge variant="teal">Advisory</ArchBadge>
                  </div>
                  <p className="text-xs font-mono text-muted-foreground leading-relaxed italic">
                    &ldquo;{decision.ai_explanation}&rdquo;
                  </p>
                  <div className="pt-2 border-t border-arch text-[10px] font-mono text-muted-foreground">
                    Notice: Claude / Gemini is advisory only. Backend mathematical optimization remains authoritative.
                  </div>
                </ArchCardContent>
              </ArchCard>
            )}
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
