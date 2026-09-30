"use client";

import React, { use } from "react";
import Link from "next/link";
import { ArrowLeft, FileCheck2, Shield, Code, History } from "lucide-react";
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

export default function PolicyDetailPage({
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
              href="/policy-inspector"
              className="inline-flex items-center gap-1.5 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back to Policy Inspector</span>
            </Link>
          </div>

          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#E88D00]/15 text-[#E88D00] border border-[#E88D00]/30">
                  SECURITY POLICY DOSSIER
                </span>
                <span className="text-[11px] font-mono text-muted-foreground">ID: {id}</span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Policy Rule: {id.toUpperCase()}
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Declarative security boundary specification, AST condition trees, and enforcement logs.
              </p>
            </div>

            <ArchBadge variant="orange">ENFORCED</ArchBadge>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 font-mono text-xs">
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">STATUS</span>
              <span className="text-sm font-bold text-emerald-400">ENFORCED</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">EVALUATIONS (30D)</span>
              <span className="text-sm font-bold text-foreground">14,200</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">VIOLATIONS BLOCKED</span>
              <span className="text-sm font-bold text-[#D95E00]">12 Blocked</span>
            </ArchCard>
            <ArchCard className="p-4">
              <span className="text-[10px] text-muted-foreground block">SECURITY HASH</span>
              <span className="text-xs font-bold text-[#0A7A75] truncate block">SHA256://RATIFIED</span>
            </ArchCard>
          </div>

          <ArchCard elevated>
            <ArchCardHeader>
              <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                <Code className="w-4 h-4 text-[#D95E00]" />
                Enforcement AST & Threshold Boundaries
              </ArchCardTitle>
            </ArchCardHeader>
            <ArchCardContent className="space-y-4 font-mono text-xs">
              <p className="text-xs text-muted-foreground">
                All agent execution plans and autonomous commands matching this policy will be intercepted by the Deterministic Policy Engine before reaching physical API gateways.
              </p>
            </ArchCardContent>
          </ArchCard>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
