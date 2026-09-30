"use client";

import React, { use } from "react";
import Link from "next/link";
import { ArrowLeft, Wrench, Shield, Code, CheckCircle2 } from "lucide-react";
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

export default function McpToolDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-5xl">
          <div className="flex items-center gap-2">
            <Link
              href="/mcp-tools"
              className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to MCP Tool Registry</span>
            </Link>
          </div>

          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#0A7A75]/15 text-[#0A7A75] border border-[#0A7A75]/30">
                  PROTOCOL TOOL SCHEMA
                </span>
                <span className="text-[11px] font-mono text-muted-foreground">ID: {id}</span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                MCP Tool Contract: mcp:{id}
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Authoritative schema definition, RBAC gating policy, and sandboxed test execution parameters.
              </p>
            </div>

            <ArchBadge variant="teal">ACTIVE REGISTRATION</ArchBadge>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 font-mono text-xs">
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">STATUS</span>
              <span className="text-sm font-bold text-emerald-400">ACTIVE</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">REQUIRED ROLE</span>
              <span className="text-sm font-bold text-[#D95E00]">OpsManager</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">BENCHMARK LATENCY</span>
              <span className="text-sm font-bold text-foreground">48ms P99</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">SECURITY BOUNDARY</span>
              <span className="text-sm font-bold text-[#0A7A75]">Zero-Trust Sandbox</span>
            </ArchCard>
          </div>

          <ArchCard elevated>
            <ArchCardHeader>
              <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                <Code className="w-4 h-4 text-[#D95E00]" />
                Tool Contract & Permissions Specification
              </ArchCardTitle>
            </ArchCardHeader>
            <ArchCardContent className="space-y-4 font-mono text-xs">
              <div className="p-3 rounded bg-surface border border-arch">
                <span className="text-[10px] text-muted-foreground block mb-1">MCP PROTOCOL URI</span>
                <code className="text-[#0A7A75]">mcp://core.chainsentinel.internal/tools/{id}</code>
              </div>

              <div>
                <span className="text-xs font-bold text-foreground uppercase block mb-1">
                  Enforced Access Control
                </span>
                <p className="text-xs text-muted-foreground">
                  Tool execution requires cryptographic JWT assertion with tenant claims and minimum role level OpsManager.
                  Invocations without valid credentials will trigger immediate 401/403 audit alerts.
                </p>
              </div>
            </ArchCardContent>
          </ArchCard>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
