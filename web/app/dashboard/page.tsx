"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Clock,
  Cpu,
  Flame,
  Globe2,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Truck,
  UserCheck,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { MetricCard } from "@/components/ui/MetricCard";
import { MapCard, MapEntity } from "@/components/map/MapCard";
import { OperationalPipeline } from "@/components/ui/OperationalPipeline";
import { RiskBadge, VerificationBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type {
  ApprovalResponse,
  ControlTowerMetrics,
  IncidentResponse,
  RiskResponse,
  ShipmentResponse,
  VerificationResultResponse,
} from "@/lib/api/types";

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<ControlTowerMetrics | null>(null);
  const [incidents, setIncidents] = useState<IncidentResponse[]>([]);
  const [approvals, setApprovals] = useState<ApprovalResponse[]>([]);
  const [verifications, setVerifications] = useState<VerificationResultResponse[]>([]);
  const [shipments, setShipments] = useState<ShipmentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const fetchData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [m, incRes, appRes, verRes, shipRes] = await Promise.all([
        apiClient.getDashboardMetrics(),
        apiClient.incidents.list({ limit: 5 }),
        apiClient.approvals.list({ limit: 5 }),
        apiClient.verification.list({ limit: 5 }),
        apiClient.shipments.list({ limit: 50 }),
      ]);

      setMetrics(m);
      setIncidents(incRes.items || []);
      setApprovals(appRes.items || []);
      setVerifications(verRes.items || []);
      setShipments(shipRes.items || []);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to synchronize operational telemetry");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  // Map entities generated from real backend shipments with valid coordinates
  const mapEntities: MapEntity[] = shipments
    .filter((s) => s.current_lat !== null && s.current_lat !== undefined && s.current_lng !== null && s.current_lng !== undefined)
    .map((s) => ({
      id: s.id,
      name: s.tracking_number,
      type: s.mode.toUpperCase() === "OCEAN" ? "vessel" : "truck",
      lat: s.current_lat!,
      lng: s.current_lng!,
      provenance: s.data_provenance,
      carrier: s.carrier_id || undefined,
      shipment_id: s.id,
      destination: s.destination || undefined,
      last_ping: s.updated_at || s.created_at,
    }));

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          {/* Header Bar */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Operational Control Tower
                <span className="w-2 h-2 rounded-full bg-emerald-400 pulse-dot" />
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Multi-tier supply chain risk intelligence, deterministic optimization & governed mitigation.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-slate-500">
                Last updated: <span className="text-slate-300">{lastUpdated || "Connecting..."}</span>
              </span>
              <button
                onClick={fetchData}
                disabled={isLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-[#111827] hover:bg-[#1A2332] text-xs font-medium text-slate-200 border border-[#243044] transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                <span>Sync Telemetry</span>
              </button>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchData} />}

          {/* Top 4 Authoritative KPIs */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              title="Active Critical Risks"
              value={metrics?.active_critical_risks ?? 0}
              subtext="Unmitigated high impact"
              icon={AlertOctagon}
              variant={metrics?.active_critical_risks ? "critical" : "default"}
              trend={null}
            />
            <MetricCard
              title="Shipments In Transit"
              value={metrics?.shipments_in_transit ?? 0}
              subtext="Active live tracking"
              icon={Truck}
              variant="default"
              trend={null}
            />
            <MetricCard
              title="Pending Approvals"
              value={metrics?.pending_approvals ?? 0}
              subtext="Awaiting Human Governance"
              icon={UserCheck}
              variant={metrics?.pending_approvals ? "warning" : "default"}
              trend={null}
            />
            <MetricCard
              title="Verified Actions — 30D"
              value={metrics?.verified_actions_30d ?? 0}
              subtext="Deterministic verification"
              icon={ShieldCheck}
              variant="success"
              trend={null}
            />
          </div>

          {/* Main Operational Grid: Map & Live Incidents */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Live Map (2 cols) */}
            <div className="lg:col-span-2">
              <MapCard
                entities={mapEntities}
                title="Global Live Logistics & Maritime AIS Telemetry"
                height="h-[480px]"
              />
            </div>

            {/* Top Active Incidents (1 col) */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] flex flex-col justify-between h-[480px]">
              <div>
                <div className="flex items-center justify-between mb-3 border-b border-[#243044] pb-2">
                  <div className="flex items-center gap-2">
                    <Flame className="w-4 h-4 text-rose-400" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                      Active Disruption Incidents
                    </h3>
                  </div>
                  <Link
                    href="/incidents"
                    className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono"
                  >
                    View All <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                <div className="space-y-2.5 overflow-y-auto max-h-[380px] pr-1">
                  {incidents.length === 0 ? (
                    <EmptyState
                      title="Zero Active Incidents"
                      message="No disruption incidents reported across active network."
                    />
                  ) : (
                    incidents.map((inc) => (
                      <Link
                        key={inc.id}
                        href={`/incidents/${inc.id}`}
                        className="block p-3 rounded bg-[#1A2332]/60 hover:bg-[#1A2332] border border-slate-800 transition-colors"
                      >
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <span className="text-xs font-semibold text-slate-200 line-clamp-1">
                            {inc.title}
                          </span>
                          <RiskBadge severity={inc.severity} />
                        </div>
                        <p className="text-[11px] text-slate-400 line-clamp-2 mb-2">
                          {inc.description || "Active operational incident under investigation."}
                        </p>
                        <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
                          <span>Status: {inc.status}</span>
                          <span>{new Date(inc.detected_at).toLocaleDateString()}</span>
                        </div>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div className="pt-2 border-t border-[#243044] flex items-center justify-between text-[11px] font-mono text-slate-500">
                <span>Incident Engine: Active</span>
                <span>Deterministic Severity</span>
              </div>
            </div>
          </div>

          {/* Third Section: Pending Approvals & Verification Outcomes & Agent Activity */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {/* Pending Approvals */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3 border-b border-[#243044] pb-2">
                  <div className="flex items-center gap-2">
                    <UserCheck className="w-4 h-4 text-amber-400" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                      Pending Approvals
                    </h3>
                  </div>
                  <Link
                    href="/approvals"
                    className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono"
                  >
                    Review Queue <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                <div className="space-y-2">
                  {approvals.length === 0 ? (
                    <EmptyState
                      title="Queue Clear"
                      message="No recommendations pending human sign-off."
                    />
                  ) : (
                    approvals.map((app) => (
                      <div
                        key={app.id}
                        className="p-2.5 rounded bg-[#1A2332]/60 border border-slate-800 text-xs"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono text-[11px] text-slate-300">
                            Rec ID: {app.recommendation_id.slice(0, 8)}...
                          </span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-950 text-amber-300 border border-amber-800">
                            {app.decision}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 truncate">
                          {app.comments || "Mitigation candidate formulated for authorization."}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <Link
                href="/approvals"
                className="mt-3 block text-center py-1.5 rounded bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 text-xs font-medium border border-blue-500/30 transition-colors"
              >
                Open Governance Sign-Off Console
              </Link>
            </div>

            {/* Recent Verification Outcomes */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3 border-b border-[#243044] pb-2">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                      Recent Verification Outcomes
                    </h3>
                  </div>
                  <Link
                    href="/verification"
                    className="text-[11px] text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono"
                  >
                    Console <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                <div className="space-y-2">
                  {verifications.length === 0 ? (
                    <EmptyState
                      title="No Verifications"
                      message="No post-mitigation action observations recorded yet."
                    />
                  ) : (
                    verifications.map((v) => (
                      <div
                        key={v.id}
                        className="p-2.5 rounded bg-[#1A2332]/60 border border-slate-800 text-xs"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono text-[11px] text-slate-300">
                            Action: {v.action_id.slice(0, 8)}...
                          </span>
                          <VerificationBadge status={v.status} />
                        </div>
                        <p className="text-[11px] text-slate-400 truncate">
                          {v.observation_summary || "Telemetry outcome verified deterministically."}
                        </p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="pt-2 border-t border-[#243044] text-[10px] font-mono text-slate-500 text-center">
                AI does not determine verification outcomes
              </div>
            </div>

            {/* Agent Operational Activity */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3 border-b border-[#243044] pb-2">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-purple-400" />
                    <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                      Multi-Agent Coordination
                    </h3>
                  </div>
                  <span className="text-[10px] font-mono text-purple-400 bg-purple-950/60 px-1.5 py-0.5 rounded border border-purple-800">
                    Governed
                  </span>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="p-2 rounded bg-[#1A2332]/40 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">Risk Intelligence Agent</span>
                    <span className="font-mono text-[11px] text-emerald-400">Deterministic</span>
                  </div>
                  <div className="p-2 rounded bg-[#1A2332]/40 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">Google OR-Tools Solver</span>
                    <span className="font-mono text-[11px] text-blue-400">Mathematical</span>
                  </div>
                  <div className="p-2 rounded bg-[#1A2332]/40 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">Decision Agent (Claude 3.5)</span>
                    <span className="font-mono text-[11px] text-purple-400">Advisory Only</span>
                  </div>
                  <div className="p-2 rounded bg-[#1A2332]/40 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">Human Governance Gateway</span>
                    <span className="font-mono text-[11px] text-amber-400">Mandatory Gate</span>
                  </div>
                  <div className="p-2 rounded bg-[#1A2332]/40 border border-slate-800 flex items-center justify-between">
                    <span className="text-slate-300">Verification Engine</span>
                    <span className="font-mono text-[11px] text-emerald-400">Deterministic Rule</span>
                  </div>
                </div>
              </div>

              <div className="pt-2 border-t border-[#243044] text-[10px] font-mono text-slate-500 text-center">
                Strict RBAC & Tenant Isolation Enforced
              </div>
            </div>
          </div>

          {/* Operational Execution Pipeline Strip */}
          <OperationalPipeline counts={metrics?.pipeline} />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
