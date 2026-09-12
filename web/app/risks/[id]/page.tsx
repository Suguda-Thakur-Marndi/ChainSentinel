"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  ArrowLeft,
  Calendar,
  ChevronRight,
  Cpu,
  Layers,
  MapPin,
  RefreshCw,
  TrendingUp,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { RiskBadge, StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type {
  RiskAssessmentResponse,
  RiskFactorResponse,
  RiskResponse,
} from "@/lib/api/types";

export default function RiskDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [risk, setRisk] = useState<RiskResponse | null>(null);
  const [factors, setFactors] = useState<RiskFactorResponse[]>([]);
  const [assessments, setAssessments] = useState<RiskAssessmentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const r = await apiClient.risks.get(id);
      setRisk(r);

      const [fRes, aRes] = await Promise.allSettled([
        apiClient.risks.getFactors(id),
        apiClient.risks.getAssessments(id),
      ]);

      if (fRes.status === "fulfilled") setFactors(fRes.value || []);
      if (aRes.status === "fulfilled") setAssessments(aRes.value || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load risk detail");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Calculating deterministic risk parameters..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !risk) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/risks")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Risk Register
            </button>
            <ErrorState message={error || "Risk record not found."} onRetry={fetchData} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  const score = risk.risk_score !== null && risk.risk_score !== undefined ? Math.round(risk.risk_score) : 0;

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <Link
              href="/risks"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Risk Register
            </Link>

            <button
              onClick={fetchData}
              className="p-1.5 rounded bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044]"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Top Dossier Card */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-6">
            <div className="space-y-1 max-w-2xl">
              <div className="flex items-center gap-2">
                <span className="text-xs uppercase font-mono text-slate-500">Risk Assessment Dossier</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                  {risk.source || "SYSTEM"}
                </span>
              </div>
              <h1 className="text-2xl font-bold text-white tracking-tight">{risk.title}</h1>
              <p className="text-xs text-slate-400 flex items-center gap-2">
                <MapPin className="w-3.5 h-3.5 text-slate-500" />
                <span>{risk.location || "Global Supply Corridor"}</span>
                <span>•</span>
                <span className="font-mono">ID: {risk.id}</span>
              </p>
            </div>

            {/* Authoritative Score Meter (0-100) */}
            <div className="flex items-center gap-4 bg-[#1A2332] p-4 rounded-lg border border-slate-800">
              <div className="text-center">
                <span className="text-[10px] uppercase font-mono text-slate-400 block mb-1">
                  Authoritative Score
                </span>
                <span className="text-4xl font-extrabold font-mono-tnum text-white tracking-tight">
                  {score}
                  <span className="text-base text-slate-500 font-normal">/100</span>
                </span>
              </div>
              <div className="pl-4 border-l border-slate-700 space-y-1.5">
                <RiskBadge severity={risk.severity} />
                <span className="block text-[11px] font-mono text-slate-400">
                  Trend: <strong>{risk.trend}</strong>
                </span>
              </div>
            </div>
          </div>

          {/* Factor Breakdown & Contributing Assessments */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Contributing Risk Factors */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044]">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-3 border-b border-[#243044] pb-2 flex items-center gap-2">
                <Layers className="w-4 h-4 text-blue-400" /> Multi-Factor Breakdown
              </h3>

              <div className="space-y-3">
                {factors.length === 0 ? (
                  <EmptyState
                    title="No Factors Disaggregated"
                    message="Authoritative backend risk engine computed a composite unified score."
                  />
                ) : (
                  factors.map((factor) => (
                    <div
                      key={factor.id}
                      className="p-3 rounded bg-[#1A2332]/60 border border-slate-800 space-y-1.5"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-slate-200">{factor.factor_name}</span>
                        <span className="font-mono font-bold text-slate-300">
                          Weight: {(factor.weight * 100).toFixed(0)}%
                        </span>
                      </div>
                      {/* Bar indicator */}
                      <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                        <div
                          className="bg-blue-500 h-full rounded-full"
                          style={{ width: `${Math.min(factor.score, 100)}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-[10px] font-mono text-slate-500">
                        <span>Factor Score: {Math.round(factor.score)}/100</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Assessment History / Agents */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044]">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-3 border-b border-[#243044] pb-2 flex items-center gap-2">
                <Cpu className="w-4 h-4 text-purple-400" /> Assessor Lineage & Rationale
              </h3>

              <div className="space-y-3">
                {assessments.length === 0 ? (
                  <EmptyState
                    title="Unified Assessment"
                    message="Evaluated directly by deterministic risk scoring kernel."
                  />
                ) : (
                  assessments.map((a) => (
                    <div
                      key={a.id}
                      className="p-3 rounded bg-[#1A2332]/60 border border-slate-800 space-y-2 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[11px] px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                          {a.assessor_type}
                        </span>
                        <span className="font-mono text-[10px] text-slate-500">
                          {new Date(a.created_at).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-300 italic">
                        &ldquo;{a.rationale || "Evaluated against multi-tier empirical historical failure rates."}&rdquo;
                      </p>
                      <div className="flex items-center justify-between text-[10px] font-mono text-slate-400 pt-1 border-t border-slate-800">
                        <span>Assessor ID: {a.assessor_id || "KERNEL-01"}</span>
                        <span>Confidence: {(a.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
