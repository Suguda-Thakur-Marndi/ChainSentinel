"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  Layers,
  RefreshCw,
  Scale,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
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
    fetchDecision();
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
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Decisions
            </Link>

            <Link
              href={`/approvals?decision_id=${decision.decision_id}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
            >
              <UserCheck className="w-3.5 h-3.5" />
              <span>Submit to Human Gate</span>
            </Link>
          </div>

          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1 max-w-2xl">
              <span className="text-[10px] uppercase font-mono text-purple-400 block font-bold">
                Phase 15 Decision Synthesis
              </span>
              <h1 className="text-xl font-bold text-white tracking-tight">{decision.title}</h1>
              <p className="text-xs text-slate-400 font-mono">
                ID: {decision.decision_id} • Score: {decision.deterministic_score.toFixed(3)}
              </p>
            </div>

            <div className="text-right">
              <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">Status</span>
              <StatusBadge status={decision.decision_status} />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-1.5">
                <Scale className="w-4 h-4 text-blue-400" /> Deterministic Synthesis Rationale
              </h3>
              <p className="text-xs text-slate-300 leading-relaxed">{decision.rationale}</p>
            </div>

            {decision.ai_explanation && (
              <div className="p-4 rounded-lg bg-purple-950/20 border border-purple-900/40 space-y-2">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-purple-300 flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-purple-400" /> Advisory AI Reasoning
                  </h3>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-800">
                    Advisory
                  </span>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed italic">
                  &ldquo;{decision.ai_explanation}&rdquo;
                </p>
                <div className="pt-2 border-t border-purple-900/40 text-[10px] font-mono text-purple-400/80">
                  Notice: Claude is advisory only. Backend mathematical optimization remains authoritative.
                </div>
              </div>
            )}
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
