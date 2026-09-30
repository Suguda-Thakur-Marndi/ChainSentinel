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
    let cancelled = false;
    if (!id) return;
    apiClient.recommendations
      .get(id)
      .then((res) => {
        if (!cancelled) {
          setRecommendation(res);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load recommendation detail");
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
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground font-mono transition-colors"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Recommendations
            </Link>

            <Link href={`/approvals?recommendation_id=${recommendation.id}`}>
              <ArchButton variant="default" size="sm">
                <UserCheck className="w-3.5 h-3.5" />
                <span>Submit to Human Governance Gate</span>
              </ArchButton>
            </Link>
          </div>

          {/* Top Dossier Header */}
          <ArchCard elevated>
            <div className="p-5 flex flex-wrap items-center justify-between gap-4 font-mono">
              <div className="space-y-1.5 max-w-2xl">
                <span className="text-[10px] uppercase font-mono text-[#D95E00] block font-bold tracking-wider">
                  Synthesized Decision Recommendation
                </span>
                <h1 className="text-xl font-bold text-foreground tracking-tight">{recommendation.title}</h1>
                <p className="text-xs text-muted-foreground font-mono">
                  ID: {recommendation.id} • Formulated: {new Date(recommendation.created_at).toLocaleString()}
                </p>
              </div>

              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-muted-foreground block mb-1">Status</span>
                <StatusBadge status={recommendation.status} />
              </div>
            </div>
          </ArchCard>

          {/* Rationale & Expected Benefits */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ArchCard>
              <ArchCardContent className="space-y-2.5">
                <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                  <Scale className="w-4 h-4 text-[#D95E00]" /> Mathematical Solver Rationale
                </h3>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed">
                  {recommendation.rationale || "Formulated based on Mixed-Integer Linear Programming trade-off frontier."}
                </p>
                {recommendation.estimated_cost !== null && recommendation.estimated_cost !== undefined && (
                  <div className="pt-2 border-t border-arch flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Budget Impact:</span>
                    <span className="text-foreground font-bold font-mono">${recommendation.estimated_cost.toLocaleString()}</span>
                  </div>
                )}
              </ArchCardContent>
            </ArchCard>

            {/* AI Advisor Advisory Disclaimed Block */}
            <ArchCard className="border-[#0A7A75]/30">
              <ArchCardContent className="space-y-2.5">
                <div className="flex items-center justify-between font-mono">
                  <h3 className="text-xs font-mono font-bold uppercase tracking-wider text-[#0A7A75] flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-[#0A7A75]" /> AI Natural Language Explanation
                  </h3>
                  <ArchBadge variant="teal">Advisory Only</ArchBadge>
                </div>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed italic">
                  &ldquo;This action reallocates high-criticality cargo through alternative port capacity, mitigating 85% of projected downstream assembly starvation.&rdquo;
                </p>
                <div className="pt-2 border-t border-arch text-[10px] font-mono text-muted-foreground">
                  Notice: Gemini / Claude is NOT authoritative. The deterministic backend result remains authoritative.
                </div>
              </ArchCardContent>
            </ArchCard>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
