"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Clock,
  Cpu,
  DollarSign,
  Network,
  Play,
  RefreshCw,
  Sliders,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { MetricCard } from "@/components/ui/MetricCard";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { SimulationResult } from "@/lib/api/types";

export default function SimulationResultPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchResult = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.simulation.getResult(id);
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load simulation results");
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
          <LoadingState message="Aggregating simulation impact vectors..." />
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
              onClick={() => router.push("/simulations")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Simulations
            </button>
            <ErrorState message={error || "Simulation run not found."} onRetry={fetchResult} />
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
              href="/simulations"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Simulations
            </Link>

            <Link
              href={`/optimization?scenario_id=${result.scenario_id}`}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
            >
              <Sliders className="w-3.5 h-3.5" />
              <span>Synthesize OR-Tools Mitigation</span>
            </Link>
          </div>

          {/* Dossier Top Banner */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-mono text-purple-400 font-bold">
                  Simulation Outcome Report
                </span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                  SOURCE_TYPE: SIMULATED
                </span>
              </div>
              <h1 className="text-xl font-bold text-white tracking-tight font-mono">
                Run ID: {result.simulation_id || result.result_id || id}
              </h1>
              <p className="text-xs text-slate-400 font-mono">
                Scenario: {result.scenario_id} • Completed: {new Date(result.created_at).toLocaleString()}
              </p>
            </div>

            <div className="text-right">
              <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">Status</span>
              <span className="px-2.5 py-1 rounded text-xs font-mono font-bold bg-emerald-950 text-emerald-300 border border-emerald-800">
                {result.status}
              </span>
            </div>
          </div>

          {/* Simulated Disclaimer Banner */}
          <div className="p-3 rounded-md bg-purple-950/30 border border-purple-800/60 text-xs text-purple-300 flex items-center gap-2">
            <span className="font-bold uppercase font-mono text-[10px] bg-purple-900 px-1.5 py-0.5 rounded">Notice</span>
            <span>Simulated counterfactual output. Non-authoritative until reviewed and formally approved through Human Governance.</span>
          </div>

          {/* Impact KPI Grid */}
          {(() => {
            const impactScore = result.impact_score ?? (typeof result.metrics?.impact_score === "number" ? result.metrics.impact_score : 0);
            const costImpact = result.cost_impact_usd ?? (typeof result.metrics?.total_cost_usd === "number" ? result.metrics.total_cost_usd : 0);
            const delayHours = result.delay_impact_hours ?? (typeof result.metrics?.total_delay_hours === "number" ? result.metrics.total_delay_hours : 0);
            const affectedNodes = result.affected_nodes ?? (result.entity_impacts ? result.entity_impacts.map((e) => e.entity_id) : []);
            const affectedShipments = result.affected_shipments ?? [];

            return (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <MetricCard
                    title="Impact Severity Score"
                    value={`${Math.round(impactScore)}/100`}
                    subtext="Simulated network shock"
                    icon={AlertTriangle}
                    variant={impactScore > 60 ? "critical" : "warning"}
                    trend={null}
                  />
                  <MetricCard
                    title="Cost Impact (Simulated)"
                    value={`$${costImpact.toLocaleString()}`}
                    subtext="Expedited freight & demurrage"
                    icon={DollarSign}
                    variant="default"
                    trend={null}
                  />
                  <MetricCard
                    title="Delay Variance"
                    value={`+${Math.round(delayHours)} hrs`}
                    subtext="Simulated corridor delay"
                    icon={Clock}
                    variant="default"
                    trend={null}
                  />
                </div>

                {/* Affected Topology Nodes & Shipments */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-3">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2 border-b border-[#243044] pb-2">
                      <Network className="w-4 h-4 text-blue-400" /> Affected Topology Nodes ({affectedNodes.length})
                    </h3>
                    <div className="space-y-1.5 max-h-52 overflow-y-auto">
                      {affectedNodes.length === 0 ? (
                        <p className="text-xs text-slate-500 italic">No nodes suffered capacity degradation.</p>
                      ) : (
                        affectedNodes.map((nodeId) => (
                          <div
                            key={nodeId}
                            className="p-2 rounded bg-[#1A2332] text-xs font-mono text-slate-300 flex items-center justify-between"
                          >
                            <span>{nodeId}</span>
                            <span className="text-[10px] text-amber-400">Degraded (Simulated)</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-3">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2 border-b border-[#243044] pb-2">
                      <Clock className="w-4 h-4 text-amber-400" /> Impacted Shipments ({affectedShipments.length})
                    </h3>
                    <div className="space-y-1.5 max-h-52 overflow-y-auto">
                      {affectedShipments.length === 0 ? (
                        <p className="text-xs text-slate-500 italic">No shipments intersected with disruption zone.</p>
                      ) : (
                        affectedShipments.map((shipId) => (
                          <Link
                            key={shipId}
                            href={`/shipments/${shipId}`}
                            className="p-2 rounded bg-[#1A2332] hover:bg-slate-800 text-xs font-mono text-blue-400 flex items-center justify-between block"
                          >
                            <span>{shipId}</span>
                            <span className="text-[10px] text-slate-500 flex items-center gap-1">
                              Inspect <ArrowRight className="w-3 h-3" />
                            </span>
                          </Link>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </>
            );
          })()}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
