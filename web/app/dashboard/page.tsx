"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  Cpu,
  Flame,
  RefreshCw,
  ShieldCheck,
  Truck,
  UserCheck,
  Bot,
  Wrench,
  Activity,
  FileCheck2,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { MetricCard } from "@/components/ui/MetricCard";
import { MapCard, MapEntity } from "@/components/map/MapCard";
import { SecurityMachine3D } from "@/components/visualization/SecurityMachine3D";
import { OperationalPipeline } from "@/components/ui/OperationalPipeline";
import { RiskBadge, VerificationBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState } from "@/components/ui/FeedbackStates";
import { ArchCard, ArchCardHeader, ArchCardTitle, ArchCardContent, ArchButton, ArchBadge } from "@/components/ui/ArchitecturalComponents";
import { apiClient } from "@/lib/api/client";
import type {
  ApprovalResponse,
  ControlTowerMetrics,
  IncidentResponse,
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
    let cancelled = false;
    Promise.all([
      apiClient.getDashboardMetrics(),
      apiClient.incidents.list({ limit: 5 }),
      apiClient.approvals.list({ limit: 5 }),
      apiClient.verification.list({ limit: 5 }),
      apiClient.shipments.list({ limit: 50 }),
    ])
      .then(([m, incRes, appRes, verRes, shipRes]) => {
        if (!cancelled) {
          setMetrics(m);
          setIncidents(incRes.items || []);
          setApprovals(appRes.items || []);
          setVerifications(verRes.items || []);
          setShipments(shipRes.items || []);
          setLastUpdated(new Date().toLocaleTimeString());
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to synchronize operational telemetry");
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Map entities generated from real backend shipments with valid coordinates
  const mapEntities: MapEntity[] = shipments
    .filter(
      (s) =>
        s.current_lat !== null &&
        s.current_lat !== undefined &&
        s.current_lng !== null &&
        s.current_lng !== undefined
    )
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
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2.5">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#D95E00]/15 text-[#D95E00] border border-[#D95E00]/30">
                  DEFENSE GRADE
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  ACTIVE AIRSPACE & SUPPLY CORRIDORS
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                CHAINSENTINEL // Control Tower Overview
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Architectural intelligence, multi-agent sandboxing, deterministic optimization & human-governed mitigation.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <span className="text-xs font-mono text-muted-foreground">
                Telemetry Sync:{" "}
                <span className="text-foreground font-semibold">
                  {lastUpdated || "Connecting..."}
                </span>
              </span>
              <ArchButton
                onClick={fetchData}
                disabled={isLoading}
                variant="outline"
                size="sm"
                className="font-mono text-xs"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                <span>Sync Node</span>
              </ArchButton>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchData} />}

          {/* EDITORIAL HERO SECTION: 3D Security Machine Centerpiece + Authoritative Telemetry Deck */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            {/* Left 7 Columns: 3D Security Machine Visual Centerpiece */}
            <div className="lg:col-span-7">
              <SecurityMachine3D
                activePostureScore={99.4}
                mitigationsCount={metrics?.verified_actions_30d ?? 14}
                threatsBlocked={metrics?.active_critical_risks ?? 2}
              />
            </div>

            {/* Right 5 Columns: Architectural Telemetry & Quick Dispatch Controls */}
            <div className="lg:col-span-5 space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  title="Critical Threats"
                  value={metrics?.active_critical_risks ?? 0}
                  subtext="Unmitigated High Risk"
                  icon={AlertOctagon}
                  variant={metrics?.active_critical_risks ? "critical" : "default"}
                />
                <MetricCard
                  title="Human Approvals"
                  value={metrics?.pending_approvals ?? 0}
                  subtext="Awaiting Operator Sign-Off"
                  icon={UserCheck}
                  variant={metrics?.pending_approvals ? "warning" : "orange"}
                />
                <MetricCard
                  title="Tracked Assets"
                  value={metrics?.shipments_in_transit ?? 0}
                  subtext="Active In Transit"
                  icon={Truck}
                  variant="default"
                />
                <MetricCard
                  title="Verified 30D"
                  value={metrics?.verified_actions_30d ?? 0}
                  subtext="Zero Hallucination Actions"
                  icon={ShieldCheck}
                  variant="success"
                />
              </div>

              {/* Quick Security Actions Card */}
              <ArchCard elevated className="p-4 space-y-3">
                <div className="flex items-center justify-between border-b pb-2" style={{ borderColor: "var(--border-arch)" }}>
                  <div className="flex items-center gap-2">
                    <Zap className="w-4 h-4 text-[#D95E00]" />
                    <span className="text-xs font-bold font-mono text-foreground uppercase">
                      Tactical Dispatch Quick Actions
                    </span>
                  </div>
                  <ArchBadge variant="orange">READY</ArchBadge>
                </div>

                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <Link
                    href="/agent-runs"
                    className="p-2.5 rounded border border-arch bg-surface hover:bg-surface-high hover:border-[#D95E00]/60 transition-all flex flex-col justify-between"
                  >
                    <div className="flex items-center justify-between text-muted-foreground mb-1">
                      <Bot className="w-3.5 h-3.5 text-[#D95E00]" />
                      <span className="text-[10px]">AI AGENTS</span>
                    </div>
                    <span className="font-semibold text-foreground truncate">Inspect Agent Runs</span>
                  </Link>

                  <Link
                    href="/mcp-tools"
                    className="p-2.5 rounded border border-arch bg-surface hover:bg-surface-high hover:border-[#0A7A75]/60 transition-all flex flex-col justify-between"
                  >
                    <div className="flex items-center justify-between text-muted-foreground mb-1">
                      <Wrench className="w-3.5 h-3.5 text-[#0A7A75]" />
                      <span className="text-[10px]">TOOLS</span>
                    </div>
                    <span className="font-semibold text-foreground truncate">MCP Tool Schemas</span>
                  </Link>

                  <Link
                    href="/policy-inspector"
                    className="p-2.5 rounded border border-arch bg-surface hover:bg-surface-high hover:border-[#E88D00]/60 transition-all flex flex-col justify-between"
                  >
                    <div className="flex items-center justify-between text-muted-foreground mb-1">
                      <FileCheck2 className="w-3.5 h-3.5 text-[#E88D00]" />
                      <span className="text-[10px]">RULES</span>
                    </div>
                    <span className="font-semibold text-foreground truncate">Policy Enforcer</span>
                  </Link>

                  <Link
                    href="/system-health"
                    className="p-2.5 rounded border border-arch bg-surface hover:bg-surface-high hover:border-slate-500 transition-all flex flex-col justify-between"
                  >
                    <div className="flex items-center justify-between text-muted-foreground mb-1">
                      <Activity className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-[10px]">P99 14MS</span>
                    </div>
                    <span className="font-semibold text-foreground truncate">System Health</span>
                  </Link>
                </div>
              </ArchCard>
            </div>
          </div>

          {/* Main Operational Grid: Map & Live Incidents */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Live Map (2 cols) */}
            <div className="lg:col-span-2">
              <MapCard
                entities={mapEntities}
                title="Global Live Logistics & Maritime AIS Telemetry"
                height="h-[460px]"
              />
            </div>

            {/* Top Active Incidents (1 col) */}
            <div
              className="p-4 rounded-lg border flex flex-col justify-between h-[460px]"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border-arch)",
              }}
            >
              <div>
                <div
                  className="flex items-center justify-between mb-3 border-b pb-2"
                  style={{ borderColor: "var(--border-arch)" }}
                >
                  <div className="flex items-center gap-2">
                    <Flame className="w-4 h-4 text-rose-500" />
                    <h3 className="text-xs font-bold font-mono uppercase tracking-wider text-foreground">
                      Active Threat Incidents
                    </h3>
                  </div>
                  <Link
                    href="/incidents"
                    className="text-[11px] text-[#D95E00] hover:underline flex items-center gap-1 font-mono"
                  >
                    View All <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>

                <div className="space-y-2.5 overflow-y-auto max-h-[360px] pr-1">
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
                        className="block p-3 rounded border border-arch bg-surface/80 hover:bg-surface transition-colors"
                      >
                        <div className="flex items-start justify-between gap-2 mb-1">
                          <span className="text-xs font-semibold text-foreground line-clamp-1">
                            {inc.title}
                          </span>
                          <RiskBadge severity={inc.severity} />
                        </div>
                        <p className="text-[11px] text-muted-foreground line-clamp-2 mb-2 font-mono">
                          {inc.description || "Active operational incident under automated investigation."}
                        </p>
                        <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground pt-1 border-t border-arch/50">
                          <span>Status: {inc.status}</span>
                          <span>{new Date(inc.detected_at).toLocaleDateString()}</span>
                        </div>
                      </Link>
                    ))
                  )}
                </div>
              </div>

              <div
                className="pt-2 border-t flex items-center justify-between text-[11px] font-mono text-muted-foreground"
                style={{ borderColor: "var(--border-arch)" }}
              >
                <span>Deterministic Threat Detection</span>
                <span className="text-[#0A7A75]">Continuous Ping</span>
              </div>
            </div>
          </div>

          {/* Third Section: Pending Approvals & Verification Outcomes */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Approvals Review Dossier */}
            <div
              className="p-4 rounded-lg border"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border-arch)",
              }}
            >
              <div
                className="flex items-center justify-between mb-3 border-b pb-2"
                style={{ borderColor: "var(--border-arch)" }}
              >
                <div className="flex items-center gap-2">
                  <UserCheck className="w-4 h-4 text-[#D95E00]" />
                  <h3 className="text-xs font-bold font-mono uppercase tracking-wider text-foreground">
                    Pending Governance Approvals ({approvals.length})
                  </h3>
                </div>
                <Link
                  href="/approvals"
                  className="text-[11px] text-[#D95E00] hover:underline flex items-center gap-1 font-mono"
                >
                  Review Dossiers <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              <div className="space-y-2.5">
                {approvals.length === 0 ? (
                  <EmptyState
                    title="Governance Queue Clear"
                    message="All automated escalations have been reviewed or resolved."
                  />
                ) : (
                  approvals.slice(0, 3).map((app) => (
                    <div
                      key={app.id}
                      className="p-3 rounded border border-arch bg-surface/80 flex items-center justify-between gap-3"
                    >
                      <div className="truncate">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-bold text-foreground truncate font-mono">
                            DECISION://{app.decision}
                          </span>
                          <ArchBadge variant="orange">{app.decision}</ArchBadge>
                        </div>
                        <div className="text-[11px] text-muted-foreground font-mono truncate">
                          Recommendation: {app.recommendation_id}
                        </div>
                      </div>
                      <Link
                        href={`/approvals`}
                        className="px-2.5 py-1 rounded bg-[#D95E00] text-white hover:bg-[#BF5300] text-xs font-mono font-medium flex-shrink-0"
                      >
                        Inspect
                      </Link>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Ground-Truth Verification Feed */}
            <div
              className="p-4 rounded-lg border"
              style={{
                backgroundColor: "var(--bg-card)",
                borderColor: "var(--border-arch)",
              }}
            >
              <div
                className="flex items-center justify-between mb-3 border-b pb-2"
                style={{ borderColor: "var(--border-arch)" }}
              >
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#0A7A75]" />
                  <h3 className="text-xs font-bold font-mono uppercase tracking-wider text-foreground">
                    Deterministic Verification Ledger
                  </h3>
                </div>
                <Link
                  href="/verification"
                  className="text-[11px] text-[#0A7A75] hover:underline flex items-center gap-1 font-mono"
                >
                  Audit Ledger <ArrowRight className="w-3 h-3" />
                </Link>
              </div>

              <div className="space-y-2.5">
                {verifications.length === 0 ? (
                  <EmptyState
                    title="Ledger Awaiting Telemetry"
                    message="Verification runs will populate here as mitigations complete."
                  />
                ) : (
                  verifications.slice(0, 3).map((v) => (
                    <div
                      key={v.id}
                      className="p-3 rounded border border-arch bg-surface/80 flex items-center justify-between gap-3"
                    >
                      <div className="truncate">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-xs font-bold text-foreground truncate font-mono">
                            VERIF://{v.id.substring(0, 8)}
                          </span>
                          <VerificationBadge status={v.status} />
                        </div>
                        <div className="text-[11px] text-muted-foreground font-mono truncate">
                          Precedence: {v.evidence_precedence} • Evidence items: {v.evidence_items?.length ?? 1}
                        </div>
                      </div>
                      <div className="text-[10px] font-mono text-muted-foreground">
                        {new Date(v.verified_at).toLocaleDateString()}
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
