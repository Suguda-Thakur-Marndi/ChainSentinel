"use client";

import React from "react";
import Link from "next/link";
import { ShieldAlert, ArrowLeft, LayoutDashboard, Globe2, Activity } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { ArchButton, ArchCard, ArchBadge } from "@/components/ui/ArchitecturalComponents";

export default function NotFoundPage() {
  return (
    <AppShell>
      <div className="flex-1 flex items-center justify-center min-h-[70vh] p-4">
        <div
          className="w-full max-w-lg p-8 rounded-xl border shadow-arch-lg text-center space-y-6 relative overflow-hidden bg-grid-architectural"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border-arch)",
          }}
        >
          {/* Subtle Ambient Laser Line */}
          <div className="w-12 h-12 rounded-xl bg-[#D95E00]/10 border border-[#D95E00]/30 text-[#D95E00] flex items-center justify-center mx-auto shadow-sm">
            <ShieldAlert className="w-6 h-6 text-[#D95E00]" />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-center gap-2">
              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-950/40 text-rose-400 border border-rose-800/40">
                ERROR 404
              </span>
              <span className="text-xs font-mono text-muted-foreground">ROUTE NOT FOUND</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-foreground font-mono">
              Unmapped Operational Coordinate
            </h1>
            <p className="text-xs text-muted-foreground font-mono max-w-sm mx-auto">
              The requested supply corridor, node identifier, or security endpoint does not exist within the active network topology.
            </p>
          </div>

          <div className="pt-2 flex flex-wrap items-center justify-center gap-3 font-mono text-xs">
            <Link href="/dashboard">
              <ArchButton variant="default" size="sm" className="gap-2">
                <LayoutDashboard className="w-3.5 h-3.5" />
                Control Tower Overview
              </ArchButton>
            </Link>
            <Link href="/map">
              <ArchButton variant="outline" size="sm" className="gap-2">
                <Globe2 className="w-3.5 h-3.5" />
                Global Live Map
              </ArchButton>
            </Link>
            <Link href="/system-health">
              <ArchButton variant="outline" size="sm" className="gap-2">
                <Activity className="w-3.5 h-3.5" />
                System Health
              </ArchButton>
            </Link>
          </div>

          <div className="pt-4 border-t text-[10px] font-mono text-muted-foreground flex items-center justify-between" style={{ borderColor: "var(--border-arch)" }}>
            <span>CHAINSENTINEL // MCP-SENTINEL</span>
            <span className="text-[#0A7A75]">ZERO-TRUST BOUNDARY ACTIVE</span>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
