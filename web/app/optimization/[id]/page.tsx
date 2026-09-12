"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  CheckCircle2,
  Clock,
  Cpu,
  Layers,
  RefreshCw,
  Sliders,
  Sparkles,
  Zap,
} from "lucide-react";
import {
  ResponsiveContainer,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { OptimizationStatusBadge } from "@/components/ui/Badges";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { OptimizationCandidate, OptimizationResult } from "@/lib/api/types";

export default function OptimizationDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [result, setResult] = useState<OptimizationResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchResult = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.optimization.get(id);
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load optimization run result");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchResult();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Retrieving mathematical solver solution..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !result) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/optimization")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Optimization
            </button>
            <ErrorState message={error || "Optimization run not found."} onRetry={fetchResult} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  // Check if candidates have Pareto frontier data
  const paretoCandidates = (result.candidates || []).filter((c) => c.pareto_optimal);
  const hasParetoData = paretoCandidates.length > 0;

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <Link
              href="/optimization"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Optimization Runs
            </Link>

            <button
              onClick={fetchResult}
              className="p-1.5 rounded bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044]"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Solver Run Dossier Header */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-mono text-blue-400 block font-bold">
                  Google OR-Tools Mathematical Optimization Result
                </span>
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight">Run ID: {result.optimization_id}</h1>
              <p className="text-xs text-slate-400 font-mono">
                Objective: <span className="text-slate-200">{result.objective}</span> • Solver: Google OR-Tools CP-SAT
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">
                  Authoritative Solver Status
                </span>
                <OptimizationStatusBadge status={result.status} />
              </div>
            </div>
          </div>

          {/* Solver Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <MetricCard
              title="Solver Execution Time"
              value={`${result.runtime_ms} ms`}
              subtext="Sub-second deterministic solve"
              icon={Clock}
              variant="default"
              trend={null}
            />
            <MetricCard
              title="Candidate Solutions"
              value={result.candidates?.length ?? 0}
              subtext="Feasible alternatives explored"
              icon={Layers}
              variant="default"
              trend={null}
            />
            <MetricCard
              title="Objective Feasibility"
              value={result.solver_status || result.status}
              subtext="Mathematically constrained"
              icon={Cpu}
              variant={result.status === "OPTIMAL" ? "success" : "default"}
              trend={null}
            />
          </div>

          {/* Pareto Frontier Section */}
          <div className="p-4 rounded-lg bg-[#111827] border border-[#243044]">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-3 border-b border-[#243044] pb-2 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-blue-400" /> Multi-Objective Pareto Frontier
            </h3>

            {hasParetoData ? (
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <ScatterChart margin={{ top: 20, right: 20, bottom: 20, left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#243044" />
                    <XAxis
                      type="number"
                      dataKey="cost_usd"
                      name="Cost Impact"
                      unit="$"
                      stroke="#64748B"
                      fontSize={11}
                    />
                    <YAxis
                      type="number"
                      dataKey="delay_hours"
                      name="Delay Impact"
                      unit="h"
                      stroke="#64748B"
                      fontSize={11}
                    />
                    <Tooltip
                      cursor={{ strokeDasharray: "3 3" }}
                      contentStyle={{
                        backgroundColor: "#111827",
                        borderColor: "#243044",
                        color: "#F8FAFC",
                        fontSize: "12px",
                      }}
                    />
                    <Scatter
                      name="Pareto Optimal"
                      data={paretoCandidates}
                      fill="#3B82F6"
                    />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <div className="py-12 text-center text-xs text-slate-500 font-mono">
                Pareto frontier unavailable
              </div>
            )}
          </div>

          {/* Candidate Alternatives List */}
          <div className="p-4 rounded-lg bg-[#111827] border border-[#243044]">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-3 border-b border-[#243044] pb-2">
              Candidate Mitigation Alternatives ({result.candidates?.length || 0})
            </h3>

            <div className="space-y-2.5">
              {(result.candidates || []).length === 0 ? (
                <EmptyState
                  title="No Candidates Generated"
                  message="Problem constraints resulted in zero feasible assignments."
                />
              ) : (
                result.candidates.map((c) => (
                  <div
                    key={c.candidate_id}
                    className={`p-3 rounded border text-xs flex flex-wrap items-center justify-between gap-4 transition-colors ${
                      c.candidate_id === result.selected_candidate_id
                        ? "bg-blue-950/40 border-blue-500/80"
                        : "bg-[#1A2332]/60 border-slate-800"
                    }`}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-slate-200">{c.action_type}</span>
                        {c.candidate_id === result.selected_candidate_id && (
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-600 text-white font-bold">
                            RECOMMENDED SOLUTION
                          </span>
                        )}
                        {c.pareto_optimal && (
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                            PARETO
                          </span>
                        )}
                      </div>
                      <span className="font-mono text-[11px] text-slate-400 block mt-0.5">
                        Target ID: {c.target_id} • Utility: {c.utility.toFixed(3)}
                      </span>
                    </div>

                    <div className="flex items-center gap-4 text-xs font-mono">
                      <div>
                        <span className="text-slate-500 block text-[10px]">COST IMPACT</span>
                        <span className="text-slate-200">${c.cost_usd.toLocaleString()}</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">DELAY VARIANCE</span>
                        <span className="text-slate-200">+{c.delay_hours} hrs</span>
                      </div>
                      <div>
                        <span className="text-slate-500 block text-[10px]">RISK REDUCTION</span>
                        <span className="text-emerald-400">{(c.risk_mitigation * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
