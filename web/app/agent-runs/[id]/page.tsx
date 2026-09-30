"use client";

import React, { use } from "react";
import Link from "next/link";
import { ArrowLeft, Bot, Shield, Terminal, Clock, CheckCircle2 } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  ArchButton,
  ArchCard,
  ArchCardHeader,
  ArchCardTitle,
  ArchCardContent,
  ArchBadge,
} from "@/components/ui/ArchitecturalComponents";

export default function AgentRunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-5xl">
          {/* Back Navigation */}
          <div className="flex items-center gap-2">
            <Link
              href="/agent-runs"
              className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Agent Runs</span>
            </Link>
          </div>

          {/* Header */}
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#D95E00]/15 text-[#D95E00] border border-[#D95E00]/30">
                  RUN DOSSIER
                </span>
                <span className="text-[11px] font-mono text-muted-foreground">ID: {id}</span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Autonomous Execution Trace Dossier
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Full-fidelity verifiable trace of model prompts, tool invocations, and cryptographic signatures.
              </p>
            </div>

            <ArchBadge variant="teal">AUTHORITATIVE LEDGER</ArchBadge>
          </div>

          {/* Metadata Card */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <ArchCard className="p-4">
              <span className="text-[10px] font-mono text-muted-foreground block">STATUS</span>
              <span className="text-sm font-bold font-mono text-emerald-400">COMPLETED (200 OK)</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] font-mono text-muted-foreground block">EXECUTION TIME</span>
              <span className="text-sm font-bold font-mono text-[#D95E00]">342ms Total</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] font-mono text-muted-foreground block">POLICY COMPLIANCE</span>
              <span className="text-sm font-bold font-mono text-[#0A7A75]">100% PASS</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] font-mono text-muted-foreground block">PROOF HASH</span>
              <span className="text-xs font-bold font-mono text-foreground truncate block">SHA256://VERIFIED</span>
            </ArchCard>
          </div>

          {/* Trace Execution Deck */}
          <ArchCard elevated>
            <ArchCardHeader>
              <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                <Terminal className="w-4 h-4 text-[#D95E00]" />
                Deterministic Step-by-Step Invocation Log
              </ArchCardTitle>
            </ArchCardHeader>
            <ArchCardContent className="space-y-4 font-mono text-xs">
              <div className="p-3 rounded bg-surface border border-arch space-y-1">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="font-bold text-foreground">Step 1: Ingestion & Spatial Corridors</span>
                  <span className="text-[#0A7A75]">42ms</span>
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Invoked: <code className="text-[#D95E00]">mcp:maritime_ais:getVesselLocation</code>
                </div>
                <p className="text-[11px] text-foreground bg-black/20 p-2 rounded border border-arch">
                  Target vessel IMO 948271 anchored outside Port Said. Speed 0.4 knots.
                </p>
              </div>

              <div className="p-3 rounded bg-surface border border-arch space-y-1">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="font-bold text-foreground">Step 2: Policy Engine Boundary Gate</span>
                  <span className="text-[#0A7A75]">8ms</span>
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Invoked: <code className="text-[#D95E00]">policy_engine:evaluateLimits</code>
                </div>
                <p className="text-[11px] text-foreground bg-black/20 p-2 rounded border border-arch">
                  Rule POL-004 evaluated. Alternative budget allocation permitted up to $45,000 without escalation.
                </p>
              </div>

              <div className="p-3 rounded bg-surface border border-arch space-y-1">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="font-bold text-foreground">Step 3: Graph Path Optimization</span>
                  <span className="text-[#0A7A75]">248ms</span>
                </div>
                <div className="text-[11px] text-muted-foreground">
                  Invoked: <code className="text-[#D95E00]">mcp:route_optimizer:solveCapeRoute</code>
                </div>
                <p className="text-[11px] text-foreground bg-black/20 p-2 rounded border border-arch">
                  Cape of Good Hope transit calculated. ETA delta +6 days, cost delta +$24,100. Optimal path selected.
                </p>
              </div>
            </ArchCardContent>
          </ArchCard>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
