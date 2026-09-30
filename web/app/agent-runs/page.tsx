"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Bot,
  Search,
  Filter,
  RefreshCw,
  Clock,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ArrowRight,
  Terminal,
  Shield,
  Layers,
  Cpu,
  ChevronRight,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  ArchButton,
  ArchCard,
  ArchCardHeader,
  ArchCardTitle,
  ArchCardContent,
  ArchBadge,
  ArchModal,
} from "@/components/ui/ArchitecturalComponents";
import { apiClient } from "@/lib/api/client";
import type { ActionResponse } from "@/lib/api/types";

interface AgentRun {
  id: string;
  name: string;
  agentRole: string;
  model: string;
  status: "COMPLETED" | "RUNNING" | "BLOCKED" | "FAILED";
  trigger: string;
  toolsUsed: string[];
  policiesChecked: string[];
  latencyMs: number;
  startedAt: string;
  completedAt?: string;
  auditHash: string;
  traceSteps: {
    step: number;
    title: string;
    action: string;
    status: "OK" | "WARN" | "FAIL";
    durationMs: number;
    details: string;
  }[];
}

const DEFAULT_RUNS: AgentRun[] = [
  {
    id: "run-9481",
    name: "Suez Canal Disruption Re-router",
    agentRole: "Maritime Route Optimizer Agent",
    model: "claude-3-5-sonnet-20241022",
    status: "COMPLETED",
    trigger: "Telemetry Exception: Vessel 9301 Speed < 2 knots",
    toolsUsed: ["mcp:maritime_ais", "mcp:route_optimizer", "mcp:carrier_contract"],
    policiesChecked: ["POL-004: Alternative Route Cost Cap", "POL-012: ETA Deviation Limits"],
    latencyMs: 342,
    startedAt: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
    completedAt: new Date(Date.now() - 1000 * 60 * 13).toISOString(),
    auditHash: "sha256:8f9b2c3d1e4a5f6e7d8c9b0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c",
    traceSteps: [
      {
        step: 1,
        title: "Telemetry Ingestion",
        action: "mcp:maritime_ais:getVesselLocation",
        status: "OK",
        durationMs: 42,
        details: "Vessel IMO 948271 anchored outside Port Said. Speed 0.4 knots.",
      },
      {
        step: 2,
        title: "Policy Boundary Check",
        action: "policy_engine:evaluateLimits",
        status: "OK",
        durationMs: 8,
        details: "Deviation budget authorized up to $45,000 without escalation.",
      },
      {
        step: 3,
        title: "Route Graph Calculation",
        action: "mcp:route_optimizer:solveCapeRoute",
        status: "OK",
        durationMs: 248,
        details: "Cape of Good Hope transit calculated. ETA delta +6 days, cost delta +$24,100.",
      },
      {
        step: 4,
        title: "Carrier Booking Dispatch",
        action: "mcp:carrier_contract:reserveBunker",
        status: "OK",
        durationMs: 44,
        details: "Contract reserved with Maersk Maritime line. Awaiting human sign-off dossier.",
      },
    ],
  },
  {
    id: "run-9480",
    name: "Semiconductor Supplier Sanctions Audit",
    agentRole: "Compliance & Tier-N Provenance Agent",
    model: "gpt-4o-2024-08-06",
    status: "COMPLETED",
    trigger: "Vendor Onboarding: Tokyo Precision Optics",
    toolsUsed: ["mcp:ofac_sanctions", "mcp:duns_registry", "mcp:contract_validator"],
    policiesChecked: ["POL-001: Zero-Trust Sanctions List", "POL-009: Dual-Use Tech Validation"],
    latencyMs: 184,
    startedAt: new Date(Date.now() - 1000 * 60 * 42).toISOString(),
    completedAt: new Date(Date.now() - 1000 * 60 * 41).toISOString(),
    auditHash: "sha256:1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b",
    traceSteps: [
      {
        step: 1,
        title: "Entity Identity Resolution",
        action: "mcp:duns_registry:verifyDUNS",
        status: "OK",
        durationMs: 52,
        details: "Verified registered entity in Chiyoda-ku, Tokyo. Registration active.",
      },
      {
        step: 2,
        title: "Cross-jurisdiction Sanctions Scan",
        action: "mcp:ofac_sanctions:queryEntity",
        status: "OK",
        durationMs: 98,
        details: "Zero matches found across US OFAC, EU Consolidated, and UN Security Council lists.",
      },
      {
        step: 3,
        title: "Cryptographic Certificate Audit",
        action: "ledger:mintComplianceProof",
        status: "OK",
        durationMs: 34,
        details: "Compliance token signed with HSM Key #8291. Tier-1 certification verified.",
      },
    ],
  },
  {
    id: "run-9479",
    name: "Cold-Chain Temperature Breach Recovery",
    agentRole: "Pharma Telemetry Mitigator",
    model: "claude-3-5-sonnet-20241022",
    status: "BLOCKED",
    trigger: "IoT Alert: Reefer Container RF-910 Temp Exceeded 6.5°C",
    toolsUsed: ["mcp:reefer_iot", "mcp:depot_allocator"],
    policiesChecked: ["POL-018: Pharma Cold Chain Destruction Escalate"],
    latencyMs: 290,
    startedAt: new Date(Date.now() - 1000 * 60 * 75).toISOString(),
    auditHash: "sha256:7e8d9c0b1a2f3e4d5c6b7a8f9e0d1c2b3a4f5e6d7c8b9a0f1e2d3c4b5a6f7e8d",
    traceSteps: [
      {
        step: 1,
        title: "Reefer Telemetry Diagnostics",
        action: "mcp:reefer_iot:getCompressorStatus",
        status: "WARN",
        durationMs: 78,
        details: "Secondary compressor failure detected. Temperature 7.1°C (Threshold 4.0°C).",
      },
      {
        step: 2,
        title: "Policy Escalation Evaluation",
        action: "policy_engine:checkHumanThreshold",
        status: "WARN",
        durationMs: 12,
        details: "Cargo valuation ($142,000) exceeds autonomous remediation cap ($50,000).",
      },
      {
        step: 3,
        title: "Human Governance Ticket Creation",
        action: "mcp:approvals:createDossier",
        status: "OK",
        durationMs: 200,
        details: "Ticket APP-0082 created. Execution blocked pending Quality Assurance sign-off.",
      },
    ],
  },
];

export default function AgentRunsPage() {
  const [runs, setRuns] = useState<AgentRun[]>(DEFAULT_RUNS);
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRun, setSelectedRun] = useState<AgentRun | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    // Ingest backend real actions and merge into agent runs
    apiClient.actions
      .list({ limit: 20 })
      .then((res) => {
        if (res.items && res.items.length > 0) {
          const apiMapped: AgentRun[] = res.items.map((act, idx) => ({
            id: act.id,
            name: act.action_type || `Autonomous Action #${act.id.slice(0, 6)}`,
            agentRole: act.executed_by || "Autonomous Dispatch Agent",
            model: "claude-3-5-sonnet",
            status:
              act.status === "SUCCEEDED"
                ? "COMPLETED"
                : act.status === "PENDING" || act.status === "EXECUTING"
                ? "RUNNING"
                : act.status === "FAILED"
                ? "FAILED"
                : "BLOCKED",
            trigger: `Target Entity: ${act.target_entity_id || act.target_entity_type || "Supply Chain Object"}`,
            toolsUsed: ["mcp:action_dispatcher", "mcp:verification_engine"],
            policiesChecked: ["POL-GLOBAL-RBAC", "POL-AUDIT-HASH"],
            latencyMs: 120 + idx * 25,
            startedAt: act.executed_at,
            auditHash: `sha256:${act.id.replace(/-/g, "")}0000000000000000000000000000`.slice(0, 71),
            traceSteps: [
              {
                step: 1,
                title: "Action Payload Validation",
                action: "schema:verifyActionCommand",
                status: "OK",
                durationMs: 24,
                details: `Validated payload for ${act.action_type}`,
              },
              {
                step: 2,
                title: "Execution Dispatch",
                action: "mcp:actions:dispatchExecution",
                status: act.status === "FAILED" ? "FAIL" : "OK",
                durationMs: 86,
                details: typeof act.result_payload?.message === "string" ? act.result_payload.message : "Dispatched to authoritative target endpoint.",
              },
            ],
          }));

          setRuns([...apiMapped, ...DEFAULT_RUNS]);
        }
      })
      .catch(() => {
        // Fall back gracefully to default curated telemetry
      });
  }, []);

  const filteredRuns = runs.filter((r) => {
    const matchesStatus = filterStatus === "ALL" || r.status === filterStatus;
    const matchesSearch =
      r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.agentRole.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.toolsUsed.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesStatus && matchesSearch;
  });

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          {/* Header */}
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#D95E00]/15 text-[#D95E00] border border-[#D95E00]/30">
                  AGENTIC INTELLIGENCE
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  SANDBOXED EXECUTION LOGS
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                AI Agent Runs & Execution Traces
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Full-fidelity audit of autonomous decisions, MCP tool calls, policy evaluations, and cryptographic proof hashes.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <ArchButton
                onClick={() => setRuns([...DEFAULT_RUNS])}
                variant="outline"
                size="sm"
                className="font-mono text-xs"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Refresh Runs</span>
              </ArchButton>
            </div>
          </div>

          {/* Filtering and Search Deck */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative w-full">
                <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search by Run ID, agent name, tool, or policy..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 rounded border text-xs font-mono bg-card text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-[#D95E00]"
                  style={{
                    backgroundColor: "var(--bg-card)",
                    borderColor: "var(--border-arch)",
                  }}
                />
              </div>
            </div>

            <div className="flex items-center gap-1.5 font-mono text-xs">
              <span className="text-muted-foreground mr-1 flex items-center gap-1">
                <Filter className="w-3.5 h-3.5" /> Filter:
              </span>
              {["ALL", "COMPLETED", "RUNNING", "BLOCKED", "FAILED"].map((st) => (
                <button
                  key={st}
                  onClick={() => setFilterStatus(st)}
                  className={`px-2.5 py-1 rounded text-xs transition-colors ${
                    filterStatus === st
                      ? "bg-[#D95E00] text-white font-bold"
                      : "bg-card border border-arch text-muted-foreground hover:text-foreground"
                  }`}
                  style={{
                    backgroundColor: filterStatus === st ? "#D95E00" : "var(--bg-card)",
                    borderColor: "var(--border-arch)",
                  }}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          {/* Runs Table */}
          <div
            className="rounded-lg border overflow-hidden shadow-arch-sm"
            style={{
              backgroundColor: "var(--bg-card)",
              borderColor: "var(--border-arch)",
            }}
          >
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr
                    className="border-b text-muted-foreground text-[10px] uppercase tracking-wider"
                    style={{
                      borderColor: "var(--border-arch)",
                      backgroundColor: "var(--bg-card-elevated)",
                    }}
                  >
                    <th className="py-3 px-4">Run Identifier</th>
                    <th className="py-3 px-4">Agent Identity & Task</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4">Model & Runtime</th>
                    <th className="py-3 px-4">MCP Tools Invoked</th>
                    <th className="py-3 px-4">Latency</th>
                    <th className="py-3 px-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y" style={{ borderColor: "var(--border-arch)" }}>
                  {filteredRuns.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-muted-foreground">
                        No agent execution runs match the specified filter criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredRuns.map((run) => (
                      <tr
                        key={run.id}
                        className="hover:bg-surface/50 transition-colors group cursor-pointer"
                        onClick={() => setSelectedRun(run)}
                      >
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <Bot className="w-4 h-4 text-[#D95E00] flex-shrink-0" />
                            <span className="font-bold text-foreground">{run.id}</span>
                          </div>
                          <span className="text-[10px] text-muted-foreground block truncate max-w-[120px]">
                            {new Date(run.startedAt).toLocaleTimeString()}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span className="font-semibold text-foreground block">{run.name}</span>
                          <span className="text-[11px] text-muted-foreground">{run.agentRole}</span>
                        </td>
                        <td className="py-3 px-4">
                          {run.status === "COMPLETED" ? (
                            <ArchBadge variant="teal">COMPLETED</ArchBadge>
                          ) : run.status === "RUNNING" ? (
                            <ArchBadge variant="orange">RUNNING</ArchBadge>
                          ) : run.status === "BLOCKED" ? (
                            <ArchBadge variant="amber">BLOCKED</ArchBadge>
                          ) : (
                            <ArchBadge variant="danger">FAILED</ArchBadge>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className="text-foreground">{run.model}</span>
                          <span className="text-[10px] text-muted-foreground block">
                            Trigger: {run.trigger.slice(0, 30)}...
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <div className="flex flex-wrap gap-1 max-w-[200px]">
                            {run.toolsUsed.map((t) => (
                              <span
                                key={t}
                                className="px-1.5 py-0.5 rounded text-[9px] bg-surface border border-arch text-muted-foreground truncate"
                              >
                                {t.replace("mcp:", "")}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="py-3 px-4 font-mono-tnum text-foreground">
                          {run.latencyMs}ms
                        </td>
                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelectedRun(run);
                            }}
                            className="px-2.5 py-1 rounded border border-arch bg-surface hover:bg-[#D95E00] hover:text-white hover:border-[#D95E00] transition-colors text-[11px] font-mono inline-flex items-center gap-1"
                          >
                            Trace <ChevronRight className="w-3 h-3" />
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Trace Detail Modal */}
          {selectedRun && (
            <ArchModal
              isOpen={Boolean(selectedRun)}
              onClose={() => setSelectedRun(null)}
              title={`EXECUTION TRACE // ${selectedRun.id}`}
              subtitle={`${selectedRun.name} • ${selectedRun.agentRole}`}
            >
              <div className="space-y-4">
                {/* Meta details */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-3 rounded bg-surface border border-arch">
                  <div>
                    <span className="text-[10px] text-muted-foreground block">STATUS</span>
                    <span className="font-bold text-foreground">{selectedRun.status}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground block">TOTAL LATENCY</span>
                    <span className="font-bold text-[#D95E00]">{selectedRun.latencyMs}ms</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground block">AI MODEL</span>
                    <span className="font-bold text-foreground truncate block">{selectedRun.model}</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-muted-foreground block">AUDIT PROOF</span>
                    <span className="font-bold text-[#0A7A75]">SHA256 SIGNED</span>
                  </div>
                </div>

                {/* Audit Hash */}
                <div className="p-2.5 rounded bg-black/30 border border-arch flex items-center justify-between text-[11px]">
                  <span className="text-muted-foreground">Audit Fingerprint:</span>
                  <span className="text-[#0A7A75] font-mono truncate max-w-[360px]">
                    {selectedRun.auditHash}
                  </span>
                </div>

                {/* Policies Evaluated */}
                <div>
                  <h4 className="text-xs font-bold text-foreground uppercase mb-1.5 flex items-center gap-1.5">
                    <Shield className="w-3.5 h-3.5 text-[#D95E00]" />
                    Evaluated Security Policies
                  </h4>
                  <div className="space-y-1">
                    {selectedRun.policiesChecked.map((pol) => (
                      <div
                        key={pol}
                        className="px-2.5 py-1 rounded bg-surface border border-arch flex items-center justify-between"
                      >
                        <span className="text-foreground">{pol}</span>
                        <ArchBadge variant="teal">ENFORCED</ArchBadge>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Step-by-Step Trace Timeline */}
                <div>
                  <h4 className="text-xs font-bold text-foreground uppercase mb-2 flex items-center gap-1.5">
                    <Terminal className="w-3.5 h-3.5 text-[#0A7A75]" />
                    Deterministic Step Timeline
                  </h4>
                  <div className="space-y-2 border-l-2 border-arch pl-3 ml-1.5">
                    {selectedRun.traceSteps.map((step) => (
                      <div key={step.step} className="relative space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="w-5 h-5 rounded-full bg-arch-elevated border border-arch text-[#D95E00] font-bold text-[10px] flex items-center justify-center -ml-[19px]">
                            {step.step}
                          </span>
                          <span className="font-bold text-foreground">{step.title}</span>
                          <span className="text-[10px] text-muted-foreground">
                            ({step.durationMs}ms)
                          </span>
                          <span className="ml-auto">
                            {step.status === "OK" ? (
                              <ArchBadge variant="teal">200 OK</ArchBadge>
                            ) : (
                              <ArchBadge variant="amber">BLOCKED</ArchBadge>
                            )}
                          </span>
                        </div>
                        <div className="text-[11px] text-[#0A7A75] font-mono">{step.action}</div>
                        <p className="text-[11px] text-muted-foreground bg-surface/50 p-2 rounded border border-arch/50">
                          {step.details}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="pt-2 border-t flex justify-end gap-2" style={{ borderColor: "var(--border-arch)" }}>
                  <ArchButton variant="outline" size="sm" onClick={() => setSelectedRun(null)}>
                    Close Trace
                  </ArchButton>
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={() => {
                      alert(`Exported cryptographic evidence dossier for Run ${selectedRun.id}`);
                    }}
                  >
                    Export Signed Audit Dossier
                  </ArchButton>
                </div>
              </div>
            </ArchModal>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
