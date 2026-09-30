"use client";

import React, { useState } from "react";
import {
  Settings as SettingsIcon,
  Shield,
  User,
  Sliders,
  Sun,
  Moon,
  Bell,
  Lock,
  CheckCircle2,
  Save,
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
} from "@/components/ui/ArchitecturalComponents";
import { useAuth } from "@/lib/auth/AuthContext";
import { useTheme } from "@/lib/theme/ThemeContext";
import { RoleBadge } from "@/components/ui/Badges";

export default function SettingsPage() {
  const { user } = useAuth();
  const { theme, toggleTheme, setTheme } = useTheme();

  const [thresholdCap, setThresholdCap] = useState("50000");
  const [aisRefreshSeconds, setAisRefreshSeconds] = useState("30");
  const [strictOfacMode, setStrictOfacMode] = useState(true);
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [isSaved, setIsSaved] = useState(false);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 3000);
  };

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-4xl">
          {/* Header */}
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#D95E00]/15 text-[#D95E00] border border-[#D95E00]/30">
                  CONFIGURATION
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  ENTERPRISE PLATFORM SETTINGS
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Security Posture & Control Tower Settings
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Operator identity, zero-trust token boundaries, human escalation thresholds, and visual design themes.
              </p>
            </div>

            {isSaved && (
              <ArchBadge variant="teal" className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5" />
                SETTINGS COMMITTED
              </ArchBadge>
            )}
          </div>

          <form onSubmit={handleSave} className="space-y-6">
            {/* Operator Profile Card */}
            <ArchCard elevated>
              <ArchCardHeader>
                <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                  <User className="w-4 h-4 text-[#D95E00]" />
                  Authorized Operator Profile & RBAC
                </ArchCardTitle>
              </ArchCardHeader>
              <ArchCardContent className="space-y-4 font-mono text-xs">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      Full Name
                    </label>
                    <input
                      type="text"
                      disabled
                      value={user?.full_name || "Security Operator"}
                      className="w-full px-3 py-1.5 rounded border border-arch bg-surface text-foreground font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      Email Address
                    </label>
                    <input
                      type="text"
                      disabled
                      value={user?.email || "operator@defense-chainsentinel.internal"}
                      className="w-full px-3 py-1.5 rounded border border-arch bg-surface text-foreground font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      Enterprise Tenant
                    </label>
                    <input
                      type="text"
                      disabled
                      value={user?.organization?.name || "Global Enterprise Logistics"}
                      className="w-full px-3 py-1.5 rounded border border-arch bg-surface text-foreground font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      Assigned RBAC Role
                    </label>
                    <div className="pt-1">
                      {user?.role ? <RoleBadge role={user.role} /> : <ArchBadge variant="teal">Admin</ArchBadge>}
                    </div>
                  </div>
                </div>
              </ArchCardContent>
            </ArchCard>

            {/* Zero-Trust Security Boundary Card */}
            <ArchCard elevated>
              <ArchCardHeader>
                <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                  <Lock className="w-4 h-4 text-[#0A7A75]" />
                  Zero-Trust Token & Autonomous Policy Gates
                </ArchCardTitle>
              </ArchCardHeader>
              <ArchCardContent className="space-y-4 font-mono text-xs">
                <div className="p-3 rounded bg-surface border border-arch flex items-center justify-between">
                  <div>
                    <span className="font-bold text-foreground block">
                      HttpOnly Secure Cookie Boundary
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      Client-side localStorage contains zero auth tokens. All session assertions are passed via encrypted HTTP cookies.
                    </span>
                  </div>
                  <ArchBadge variant="teal">ENFORCED</ArchBadge>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      Autonomous Spend Escalation Cap (USD)
                    </label>
                    <input
                      type="number"
                      value={thresholdCap}
                      onChange={(e) => setThresholdCap(e.target.value)}
                      className="w-full px-3 py-1.5 rounded border border-arch bg-card text-foreground font-mono focus:border-[#D95E00] focus:outline-none"
                    />
                    <span className="text-[10px] text-muted-foreground mt-1 block">
                      Actions exceeding this amount require human approval sign-off.
                    </span>
                  </div>

                  <div>
                    <label className="text-[10px] text-muted-foreground uppercase block mb-1">
                      AIS Satellite Poll Interval (Seconds)
                    </label>
                    <input
                      type="number"
                      value={aisRefreshSeconds}
                      onChange={(e) => setAisRefreshSeconds(e.target.value)}
                      className="w-full px-3 py-1.5 rounded border border-arch bg-card text-foreground font-mono focus:border-[#D95E00] focus:outline-none"
                    />
                    <span className="text-[10px] text-muted-foreground mt-1 block">
                      Cadence for real-time maritime AIS satellite positional updates.
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2 border-t" style={{ borderColor: "var(--border-arch)" }}>
                  <div>
                    <span className="font-bold text-foreground block">
                      Strict Sanctions & Entity Screening
                    </span>
                    <span className="text-[11px] text-muted-foreground">
                      Block any dispatch involving entities with confidence score at or above 0.85 on OFAC/EU lists.
                    </span>
                  </div>
                  <input
                    type="checkbox"
                    checked={strictOfacMode}
                    onChange={(e) => setStrictOfacMode(e.target.checked)}
                    className="w-4 h-4 accent-[#D95E00] rounded"
                  />
                </div>
              </ArchCardContent>
            </ArchCard>

            {/* Design System & Appearance Card */}
            <ArchCard elevated>
              <ArchCardHeader>
                <ArchCardTitle className="font-mono text-xs uppercase flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-[#D95E00]" />
                  Visual System & Architectural Palette
                </ArchCardTitle>
              </ArchCardHeader>
              <ArchCardContent className="space-y-4 font-mono text-xs">
                <div>
                  <span className="text-muted-foreground block mb-2">
                    Select Active Theme Mode (Derived from deep-research-report.md)
                  </span>
                  <div className="grid grid-cols-2 gap-3 max-w-md">
                    <button
                      type="button"
                      onClick={() => setTheme("dark")}
                      className={`p-3 rounded border text-left flex items-center justify-between transition-all ${
                        theme === "dark"
                          ? "bg-arch-card border-[#D95E00] shadow-sm shadow-[#D95E00]/20"
                          : "bg-surface border-arch hover:border-slate-500"
                      }`}
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <Moon className="w-3.5 h-3.5 text-[#D95E00]" />
                          <span className="font-bold text-foreground">Obsidian Dark</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground block mt-0.5">
                          High-contrast control tower
                        </span>
                      </div>
                      {theme === "dark" && <span className="text-[#D95E00]">✓</span>}
                    </button>

                    <button
                      type="button"
                      onClick={() => setTheme("ivory")}
                      className={`p-3 rounded border text-left flex items-center justify-between transition-all ${
                        theme === "ivory"
                          ? "bg-arch-card border-[#D95E00] shadow-sm shadow-[#D95E00]/20"
                          : "bg-surface border-arch hover:border-slate-500"
                      }`}
                    >
                      <div>
                        <div className="flex items-center gap-1.5">
                          <Sun className="w-3.5 h-3.5 text-[#E88D00]" />
                          <span className="font-bold text-foreground">Warm Ivory</span>
                        </div>
                        <span className="text-[10px] text-muted-foreground block mt-0.5">
                          Architectural soft ivory #F5F4F0
                        </span>
                      </div>
                      {theme === "ivory" && <span className="text-[#D95E00]">✓</span>}
                    </button>
                  </div>
                </div>
              </ArchCardContent>
            </ArchCard>

            <div className="flex justify-end gap-3">
              <ArchButton type="submit" variant="default" size="md" className="gap-2">
                <Save className="w-4 h-4" />
                Commit Security Configuration
              </ArchButton>
            </div>
          </form>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
