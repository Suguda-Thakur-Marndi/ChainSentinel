"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  ExternalLink,
  Layers,
  RefreshCw,
  Scale,
  ShieldCheck,
  XCircle,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { EvidenceBadge, VerificationBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { VerificationResultResponse } from "@/lib/api/types";

export default function VerificationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [verification, setVerification] = useState<VerificationResultResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchVerification = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.verification.get(id);
      setVerification(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load verification outcome");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchVerification();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Loading deterministic outcome verification report..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !verification) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/verification")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Verification
            </button>
            <ErrorState message={error || "Verification record not found."} onRetry={fetchVerification} />
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
              href="/verification"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Verification Console
            </Link>

            <button
              onClick={fetchVerification}
              className="p-1.5 rounded bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044]"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Top Dossier Header */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-mono text-emerald-400 block font-bold">
                  Phase 18 Ground-Truth Physical Verification Report
                </span>
                <EvidenceBadge source={verification.evidence_precedence} />
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight font-mono">
                Action Ref: {verification.action_id}
              </h1>
              <p className="text-xs text-slate-400 font-mono">
                Report ID: {verification.id} • Verified: {new Date(verification.verified_at).toLocaleString()}
              </p>
            </div>

            <div className="text-right">
              <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">
                Deterministic Status
              </span>
              <VerificationBadge status={verification.status} />
            </div>
          </div>

          {/* Intended vs Observed Comparison Matrix */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Scale className="w-4 h-4 text-blue-400" /> Intended Mitigation Target
              </h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                {verification.intended_outcome || "Reroute cargo through alternate port to reduce arrival delay by 48 hours."}
              </p>
              <div className="pt-2 border-t border-[#243044] flex justify-between text-xs font-mono">
                <span className="text-slate-400">Baseline Risk Score:</span>
                <span className="text-rose-400 font-bold">
                  {verification.risk_score_before !== null && verification.risk_score_before !== undefined
                    ? Math.round(verification.risk_score_before)
                    : "N/A"}
                </span>
              </div>
            </div>

            <div className="p-4 rounded-lg bg-[#111827] border border-emerald-900/40 space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-emerald-300 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4 text-emerald-400" /> Observed Physical Ground-Truth
              </h3>
              <p className="text-xs text-slate-300 leading-relaxed">
                {verification.observed_outcome || verification.observation_summary || "Physical vessel AIS confirmed berth arrival within tolerance window."}
              </p>
              <div className="pt-2 border-t border-emerald-900/40 flex justify-between text-xs font-mono">
                <span className="text-slate-400">Post-Action Risk Score:</span>
                <span className="text-emerald-400 font-bold">
                  {verification.risk_score_after !== null && verification.risk_score_after !== undefined
                    ? Math.round(verification.risk_score_after)
                    : "N/A"}
                </span>
              </div>
            </div>
          </div>

          {/* Disclaimer */}
          <div className="p-3.5 rounded-lg bg-[#111827] border border-[#243044] text-[11px] font-mono text-slate-400 text-center">
            Verification is deterministic — AI does not determine the outcome.
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
