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
  DollarSign,
  FileText,
  RefreshCw,
  Scale,
  ShieldCheck,
  Sparkles,
  UserCheck,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { RecommendationResponse } from "@/lib/api/types";

export default function RecommendationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [recommendation, setRecommendation] = useState<RecommendationResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRec = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.recommendations.get(id);
      setRecommendation(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load recommendation detail");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchRec();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Loading decision recommendation dossier..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !recommendation) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/recommendations")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Recommendations
            </button>
            <ErrorState message={error || "Recommendation not found."} onRetry={fetchRec} />
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
              href="/recommendations"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Recommendations
            </Link>

            <Link
              href={`/approvals?recommendation_id=${recommendation.id}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
            >
              <UserCheck className="w-3.5 h-3.5" />
              <span>Submit to Human Governance Gate</span>
            </Link>
          </div>

          {/* Top Dossier Header */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1 max-w-2xl">
              <span className="text-[10px] uppercase font-mono text-purple-400 block font-bold">
                Synthesized Decision Recommendation
              </span>
              <h1 className="text-xl font-bold text-white tracking-tight">{recommendation.title}</h1>
              <p className="text-xs text-slate-400 font-mono">
                ID: {recommendation.id} • Formulated: {new Date(recommendation.created_at).toLocaleString()}
              </p>
            </div>

            <div className="text-right">
              <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">Status</span>
              <StatusBadge status={recommendation.status} />
            </div>
          </div>

          {/* Rationale & Expected Benefits */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-1.5">
                <Scale className="w-4 h-4 text-blue-400" /> Mathematical Solver Rationale
              </h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                {recommendation.rationale || "Formulated based on Mixed-Integer Linear Programming trade-off frontier."}
              </p>
              {recommendation.estimated_cost !== null && recommendation.estimated_cost !== undefined && (
                <div className="pt-2 border-t border-[#243044] flex justify-between text-xs font-mono">
                  <span className="text-slate-400">Budget Impact:</span>
                  <span className="text-white font-bold">${recommendation.estimated_cost.toLocaleString()}</span>
                </div>
              )}
            </div>

            {/* AI Advisor Advisory Disclaimed Block */}
            <div className="p-4 rounded-lg bg-purple-950/20 border border-purple-900/40 space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-purple-300 flex items-center gap-1.5">
                  <Sparkles className="w-4 h-4 text-purple-400" /> AI Natural Language Explanation
                </h3>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-900/40 text-purple-300 border border-purple-800">
                  Advisory Only
                </span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed italic">
                &ldquo;This action reallocates high-criticality cargo through alternative port capacity, mitigating 85% of projected downstream assembly starvation.&rdquo;
              </p>
              <div className="pt-2 border-t border-purple-900/40 text-[10px] font-mono text-purple-400/80">
                Notice: Claude is NOT authoritative. The deterministic backend result remains authoritative.
              </div>
            </div>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
