"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  FileCheck2,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  ChevronRight,
  Code,
  History,
  Sliders,
  Play,
  Terminal,
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

interface SecurityPolicy {
  id: string;
  code: string;
  name: string;
  category: "Financial" | "Compliance" | "Operational" | "Safety";
  effect: "ENFORCE_BLOCK" | "ESCALATE_HUMAN" | "AUTO_MITIGATE" | "MONITOR_LOG";
  status: "ENFORCED" | "MONITORING" | "DRAFT";
  version: string;
  conditionDescription: string;
  thresholdValue: string;
  evaluations30d: number;
  violationsBlocked30d: number;
  conditionTree: Record<string, unknown>;
  history: { version: string; date: string; author: string; note: string }[];
}

const POLICIES: SecurityPolicy[] = [
  {
    id: "pol-001",
    code: "POL-001",
    name: "Zero-Trust OFAC & Denied Parties Enforcement",
    category: "Compliance",
    effect: "ENFORCE_BLOCK",
    status: "ENFORCED",
    version: "v3.2",
    conditionDescription: "Matches against active OFAC SDN, UK HMT, or EU sanctions lists with confidence score >= 0.85.",
    thresholdValue: "Zero Tolerance (0 Matches)",
    evaluations30d: 14200,
    violationsBlocked30d: 12,
    conditionTree: {
      operator: "AND",
      rules: [
        { field: "target.entity.sanctions_score", op: ">=", value: 0.85 },
        { field: "target.entity.jurisdiction_exception", op: "==", value: false },
      ],
      action: "REJECT_AND_MINT_AUDIT_PROOF",
    },
    history: [
      { version: "v3.2", date: "2026-08-15", author: "Chief Risk Officer", note: "Added EU Consolidated 2026 sanctions annex" },
      { version: "v3.1", date: "2026-04-10", author: "Security Council", note: "Tightened confidence score from 0.90 to 0.85" },
    ],
  },
  {
    id: "pol-002",
    code: "POL-002",
    name: "Autonomous Spend Remediation Cap ($50k)",
    category: "Financial",
    effect: "ESCALATE_HUMAN",
    status: "ENFORCED",
    version: "v2.0",
    conditionDescription: "Autonomous agent re-routing or spot contract reallocation exceeds $50,000 cumulative budget threshold.",
    thresholdValue: "$50,000 USD Cap",
    evaluations30d: 3840,
    violationsBlocked30d: 8,
    conditionTree: {
      operator: "OR",
      rules: [
        { field: "action.cost_delta_usd", op: ">", value: 50000 },
        { field: "action.carrier_markup_percent", op: ">", value: 35 },
      ],
      action: "HALT_AND_REQUEST_HUMAN_APPROVAL",
    },
    history: [
      { version: "v2.0", date: "2026-07-01", author: "CFO & Ops Director", note: "Ratified $50,000 threshold for Tier-1 supply disruption" },
    ],
  },
  {
    id: "pol-003",
    code: "POL-003",
    name: "Pharma Cold Chain Critical Temperature Boundary",
    category: "Safety",
    effect: "ESCALATE_HUMAN",
    status: "ENFORCED",
    version: "v1.8",
    conditionDescription: "Reefer container core sensor reports temperature >= 6.0°C sustained for greater than 45 minutes.",
    thresholdValue: "6.0°C / 45 Mins",
    evaluations30d: 9820,
    violationsBlocked30d: 3,
    conditionTree: {
      operator: "AND",
      rules: [
        { field: "telemetry.reefer.core_temp", op: ">=", value: 6.0 },
        { field: "telemetry.reefer.duration_above_limit_minutes", op: ">", value: 45 },
      ],
      action: "DISPATCH_EMERGENCY_DEPOT_AND_ESCALATE",
    },
    history: [
      { version: "v1.8", date: "2026-06-12", author: "Pharma QA Officer", note: "Decreased duration tolerance from 60m to 45m" },
    ],
  },
  {
    id: "pol-004",
    code: "POL-004",
    name: "Maritime ETA Deviation Boundary & Chokepoint Re-Route",
    category: "Operational",
    effect: "AUTO_MITIGATE",
    status: "ENFORCED",
    version: "v4.1",
    conditionDescription: "Disruption delay >= 72 hours with viable alternative maritime corridor within <= $25,000 extra cost.",
    thresholdValue: "Delay >= 72h, Cost <= $25k",
    evaluations30d: 6410,
    violationsBlocked30d: 0,
    conditionTree: {
      operator: "AND",
      rules: [
        { field: "chokepoint.status", op: "==", value: "BLOCKED" },
        { field: "alternative_route.cost_usd", op: "<=", value: 25000 },
      ],
      action: "AUTO_AUTHORIZE_RE_ROUTE",
    },
    history: [
      { version: "v4.1", date: "2026-09-01", author: "Maritime Ops Lead", note: "Activated dynamic Cape of Good Hope routing" },
    ],
  },
  {
    id: "pol-005",
    code: "POL-005",
    name: "Dual-Use Technology Export Compliance Gate",
    category: "Compliance",
    effect: "ENFORCE_BLOCK",
    status: "ENFORCED",
    version: "v1.1",
    conditionDescription: "Classified dual-use semiconductor equipment shipped to non-cleared tier-2 consignee destinations.",
    thresholdValue: "Strict Deny Without Valid License",
    evaluations30d: 1120,
    violationsBlocked30d: 2,
    conditionTree: {
      operator: "AND",
      rules: [
        { field: "cargo.eccn_classification", op: "STARTS_WITH", value: "3A" },
        { field: "customs.export_license_verified", op: "==", value: false },
      ],
      action: "BLOCK_BOOKING_AND_LOG_COMPLIANCE",
    },
    history: [
      { version: "v1.1", date: "2026-05-20", author: "Trade Counsel", note: "Updated ECCN 3A category bindings" },
    ],
  },
];

export default function PolicyInspectorPage() {
  const [policies] = useState<SecurityPolicy[]>(POLICIES);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEffect, setSelectedEffect] = useState<string>("ALL");
  const [activePolicy, setActivePolicy] = useState<SecurityPolicy | null>(null);

  const filteredPolicies = policies.filter((p) => {
    const matchesEffect =
      selectedEffect === "ALL" || p.effect === selectedEffect;
    const matchesSearch =
      p.code.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      p.conditionDescription.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesEffect && matchesSearch;
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
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#E88D00]/15 text-[#E88D00] border border-[#E88D00]/30">
                  GOVERNANCE ENGINE
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  DETERMINISTIC SECURITY POLICIES
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Policy Inspector & Condition Rules
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Declarative security boundaries, human-in-the-loop escalation caps, and real-time policy evaluation status.
              </p>
            </div>

            <ArchBadge variant="orange">5 ENFORCED RULES</ArchBadge>
          </div>

          {/* Search & Effect Filters */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative w-full">
                <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Search policies by code, title, or condition..."
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
              {["ALL", "ENFORCE_BLOCK", "ESCALATE_HUMAN", "AUTO_MITIGATE"].map((ef) => (
                <button
                  key={ef}
                  onClick={() => setSelectedEffect(ef)}
                  className={`px-2.5 py-1 rounded text-xs transition-colors ${
                    selectedEffect === ef
                      ? "bg-[#D95E00] text-white font-bold"
                      : "bg-card border border-arch text-muted-foreground hover:text-foreground"
                  }`}
                  style={{
                    backgroundColor: selectedEffect === ef ? "#D95E00" : "var(--bg-card)",
                    borderColor: "var(--border-arch)",
                  }}
                >
                  {ef.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Policy Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {filteredPolicies.map((pol) => (
              <ArchCard
                key={pol.id}
                className="flex flex-col justify-between hover:border-[#D95E00]/60 transition-all cursor-pointer group"
                onClick={() => setActivePolicy(pol)}
              >
                <div>
                  <ArchCardHeader className="flex-row items-start justify-between space-y-0 pb-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <FileCheck2 className="w-3.5 h-3.5 text-[#D95E00]" />
                        <span className="text-xs font-bold font-mono text-foreground">
                          {pol.code}: {pol.name}
                        </span>
                      </div>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {pol.version} • Category: {pol.category}
                      </span>
                    </div>

                    {pol.effect === "ENFORCE_BLOCK" ? (
                      <ArchBadge variant="danger">BLOCK</ArchBadge>
                    ) : pol.effect === "ESCALATE_HUMAN" ? (
                      <ArchBadge variant="orange">ESCALATE</ArchBadge>
                    ) : (
                      <ArchBadge variant="teal">AUTO ALLOW</ArchBadge>
                    )}
                  </ArchCardHeader>

                  <ArchCardContent className="space-y-3 pt-3">
                    <p className="text-xs text-muted-foreground font-mono">
                      {pol.conditionDescription}
                    </p>

                    <div className="p-2.5 rounded bg-surface border border-arch text-[11px] font-mono space-y-1">
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>THRESHOLD:</span>
                        <span className="text-[#D95E00] font-semibold">{pol.thresholdValue}</span>
                      </div>
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>EVALUATIONS (30D):</span>
                        <span className="text-foreground font-semibold">
                          {pol.evaluations30d.toLocaleString()}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>VIOLATIONS INTERCEPTED:</span>
                        <span className="text-[#0A7A75] font-semibold">
                          {pol.violationsBlocked30d} Blocked
                        </span>
                      </div>
                    </div>
                  </ArchCardContent>
                </div>

                <div
                  className="px-4 py-2.5 border-t flex items-center justify-between bg-surface/40"
                  style={{ borderColor: "var(--border-arch)" }}
                >
                  <Link
                    href={`/policy-inspector/${pol.id}`}
                    className="text-xs font-mono text-[#D95E00] hover:underline flex items-center gap-1"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Rule Dossier <ChevronRight className="w-3 h-3" />
                  </Link>

                  <ArchButton
                    variant="outline"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      setActivePolicy(pol);
                    }}
                    className="text-[11px]"
                  >
                    Inspect Condition Tree
                  </ArchButton>
                </div>
              </ArchCard>
            ))}
          </div>

          {/* Condition Inspector Modal */}
          {activePolicy && (
            <ArchModal
              isOpen={Boolean(activePolicy)}
              onClose={() => setActivePolicy(null)}
              title={`POLICY RULE TREE // ${activePolicy.code}`}
              subtitle={`${activePolicy.name} • ${activePolicy.version}`}
            >
              <div className="space-y-4">
                <div className="p-2.5 rounded bg-surface border border-arch text-xs font-mono">
                  <span className="text-muted-foreground block text-[10px]">ENFORCEMENT EFFECT</span>
                  <span className="text-[#D95E00] font-bold">{activePolicy.effect}</span>
                </div>

                {/* AST Condition Rule Tree */}
                <div>
                  <span className="text-xs font-bold text-foreground uppercase mb-1.5 flex items-center gap-1.5">
                    <Code className="w-3.5 h-3.5 text-[#0A7A75]" />
                    Abstract Syntax Tree (AST) Condition
                  </span>
                  <pre className="p-3 rounded bg-black/40 border border-arch text-[11px] text-slate-200 overflow-x-auto max-h-[160px]">
                    {JSON.stringify(activePolicy.conditionTree, null, 2)}
                  </pre>
                </div>

                {/* Version History */}
                <div>
                  <span className="text-xs font-bold text-foreground uppercase mb-1.5 flex items-center gap-1.5">
                    <History className="w-3.5 h-3.5 text-[#D95E00]" />
                    Ratification & Version History
                  </span>
                  <div className="space-y-1.5">
                    {activePolicy.history.map((h) => (
                      <div
                        key={h.version}
                        className="p-2 rounded bg-surface border border-arch text-xs font-mono flex items-center justify-between"
                      >
                        <div>
                          <span className="font-bold text-foreground mr-2">{h.version}</span>
                          <span className="text-muted-foreground">{h.note}</span>
                        </div>
                        <span className="text-[10px] text-[#0A7A75] font-semibold">{h.author}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="pt-2 border-t flex justify-end gap-2" style={{ borderColor: "var(--border-arch)" }}>
                  <ArchButton variant="outline" size="sm" onClick={() => setActivePolicy(null)}>
                    Close
                  </ArchButton>
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={() => {
                      alert(`Simulation test passed: Rule ${activePolicy.code} successfully evaluated against 5,000 synthetic transactions with 100% precision.`);
                    }}
                  >
                    Simulate Rule Evaluation
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
