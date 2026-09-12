"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Clock,
  ExternalLink,
  Flame,
  Layers,
  RefreshCw,
  Scale,
  ShieldCheck,
  Truck,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { RiskBadge, StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { IncidentResponse, RecommendationResponse } from "@/lib/api/types";

export default function IncidentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [incident, setIncident] = useState<IncidentResponse | null>(null);
  const [recommendations, setRecommendations] = useState<RecommendationResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const inc = await apiClient.incidents.get(id);
      setIncident(inc);

      // Fetch linked recommendations
      try {
        const recRes = await apiClient.recommendations.list({ limit: 10 });
        const linked = (recRes.items || []).filter((r) => r.incident_id === id);
        setRecommendations(linked);
      } catch {
        setRecommendations([]);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load incident war room");
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
          <LoadingState message="Initializing Incident War Room context..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !incident) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/incidents")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Incidents
            </button>
            <ErrorState message={error || "Incident record not found."} onRetry={fetchData} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  const STAGES = ["DETECTED", "INVESTIGATING", "MITIGATING", "RESOLVED"];
  const currentStageIndex = STAGES.indexOf(incident.status.toUpperCase());

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <Link
              href="/incidents"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Incident Register
            </Link>

            <button
              onClick={fetchData}
              className="p-1.5 rounded bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044]"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* War Room Header */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="space-y-1 max-w-2xl">
                <div className="flex items-center gap-2">
                  <span className="text-xs uppercase font-mono text-rose-400 font-bold flex items-center gap-1">
                    <Flame className="w-3.5 h-3.5" /> Incident War Room
                  </span>
                  <RiskBadge severity={incident.severity} />
                </div>
                <h1 className="text-2xl font-bold text-white tracking-tight">{incident.title}</h1>
                <p className="text-xs text-slate-400">
                  Detected: {new Date(incident.detected_at).toLocaleString()} • UUID: {incident.id}
                </p>
              </div>

              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">
                  Active Status
                </span>
                <span className="px-3 py-1 rounded-md text-xs font-mono font-bold uppercase bg-slate-800 text-slate-200 border border-slate-700">
                  {incident.status}
                </span>
              </div>
            </div>

            {/* War Room Progress Stepper */}
            <div className="pt-3 border-t border-[#243044]">
              <div className="flex items-center justify-between overflow-x-auto pb-1">
                {STAGES.map((stage, idx) => {
                  const isCompleted = currentStageIndex >= idx;
                  const isCurrent = currentStageIndex === idx;

                  return (
                    <React.Fragment key={stage}>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <div
                          className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-mono font-bold ${
                            isCompleted
                              ? "bg-blue-600 text-white"
                              : "bg-slate-800 text-slate-500 border border-slate-700"
                          }`}
                        >
                          {idx + 1}
                        </div>
                        <span
                          className={`text-xs font-mono ${
                            isCurrent
                              ? "text-blue-400 font-bold"
                              : isCompleted
                              ? "text-slate-300"
                              : "text-slate-500"
                          }`}
                        >
                          {stage}
                        </span>
                      </div>
                      {idx < STAGES.length - 1 && (
                        <div
                          className={`flex-1 h-0.5 mx-3 min-w-[24px] ${
                            currentStageIndex > idx ? "bg-blue-600" : "bg-slate-800"
                          }`}
                        />
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Description & Impact Summary */}
          <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
              Disruption Narrative
            </h3>
            <p className="text-xs text-slate-300 leading-relaxed">
              {incident.description || "Operational disruption reported across primary logistics corridors. Active automated root-cause research dispatched."}
            </p>
          </div>

          {/* Linked Formulated Recommendations */}
          <div className="p-4 rounded-lg bg-[#111827] border border-[#243044]">
            <div className="flex items-center justify-between border-b border-[#243044] pb-2 mb-3">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
                <Scale className="w-4 h-4 text-purple-400" /> Synthesized Mitigation Candidates
              </h3>
              <Link
                href="/recommendations"
                className="text-xs text-blue-400 hover:underline flex items-center gap-1"
              >
                Recommendations Queue <ExternalLink className="w-3 h-3" />
              </Link>
            </div>

            <div className="space-y-3">
              {recommendations.length === 0 ? (
                <EmptyState
                  title="No Mitigation Actions Formulated"
                  message="Run simulation or optimization to synthesize algorithmic mitigation candidates."
                />
              ) : (
                recommendations.map((rec) => (
                  <div
                    key={rec.id}
                    className="p-3 rounded bg-[#1A2332]/60 border border-slate-800 text-xs flex items-center justify-between gap-4"
                  >
                    <div>
                      <span className="font-semibold text-slate-200 block text-sm">{rec.title}</span>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        {rec.rationale || "Mathematical mitigation proposed by solver."}
                      </p>
                    </div>
                    <Link
                      href={`/recommendations/${rec.id}`}
                      className="px-3 py-1.5 rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 flex-shrink-0 transition-colors"
                    >
                      Review Decision Candidate
                    </Link>
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
