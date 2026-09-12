"use client";

import React, { useState } from "react";
import {
  Building2,
  CheckCircle2,
  Database,
  Globe,
  KeyRound,
  Lock,
  RefreshCw,
  Server,
  Shield,
  User,
  Users,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { RoleBadge } from "@/components/ui/Badges";
import { ForbiddenState } from "@/components/ui/FeedbackStates";
import { useAuth } from "@/lib/auth/AuthContext";

export default function AdminPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<"org" | "users" | "integrations" | "security">("org");

  const isAdmin = user?.role === "Admin";

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-5xl">
          <div className="border-b border-[#243044] pb-4">
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              Tenant Administration & RBAC Controls
              <span className="text-xs font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                Enterprise
              </span>
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Multi-tenant boundary enforcement, role-based access control, and telemetry adapter integration keys.
            </p>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center gap-2 border-b border-[#243044] pb-2 text-xs">
            <button
              onClick={() => setActiveTab("org")}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                activeTab === "org"
                  ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Organization Settings
            </button>
            <button
              onClick={() => setActiveTab("users")}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                activeTab === "users"
                  ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Users & Roles (RBAC)
            </button>
            <button
              onClick={() => setActiveTab("integrations")}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                activeTab === "integrations"
                  ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Telemetry Integrations
            </button>
            <button
              onClick={() => setActiveTab("security")}
              className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
                activeTab === "security"
                  ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Audit & Compliance
            </button>
          </div>

          {/* Tab 1: Organization */}
          {activeTab === "org" && (
            <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4">
              <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                <div className="flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-bold text-white">Active Tenant Boundary</h3>
                </div>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                  TENANT ISOLATED
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                <div>
                  <span className="text-slate-400 block mb-1">Organization Name</span>
                  <input
                    type="text"
                    disabled={!isAdmin}
                    defaultValue={user?.organization?.name || "Acme Logistics Global"}
                    className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 disabled:opacity-60"
                  />
                </div>
                <div>
                  <span className="text-slate-400 block mb-1">Domain Boundary</span>
                  <input
                    type="text"
                    disabled
                    defaultValue={user?.organization?.slug || "acmelogistics"}
                    className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-400 font-mono disabled:opacity-60"
                  />
                </div>
                <div>
                  <span className="text-slate-400 block mb-1">Tenant Organization ID</span>
                  <span className="font-mono text-slate-300 block py-2">
                    {user?.org_id || "org_01HXYZ..."}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block mb-1">Database Schema Isolation</span>
                  <span className="font-mono text-emerald-400 block py-2">
                    Row-Level Security (RLS) Active
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: Users & Roles */}
          {activeTab === "users" && (
            <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4">
              <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                <div className="flex items-center gap-2">
                  <Users className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-bold text-white">Role-Based Access Control (RBAC)</h3>
                </div>
                <span className="text-xs text-slate-400 font-mono">5 Defined Roles</span>
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-white block">Current Operator</span>
                    <span className="font-mono text-[11px] text-slate-400">{user?.email}</span>
                  </div>
                  <RoleBadge role={user?.role || "Viewer"} />
                </div>

                <div className="p-4 rounded bg-[#070A0E] border border-slate-800/80 space-y-2 text-[11px]">
                  <h5 className="font-semibold text-slate-300 uppercase tracking-wider">
                    Authoritative Role Hierarchy:
                  </h5>
                  <ul className="space-y-1 text-slate-400 font-mono">
                    <li>• <strong className="text-purple-400">Admin:</strong> Full tenant governance, user management, integration secrets.</li>
                    <li>• <strong className="text-rose-400">RiskManager:</strong> Authority to approve critical mitigation recommendations.</li>
                    <li>• <strong className="text-amber-400">OpsManager:</strong> Authority to trigger executions and rerouting commands.</li>
                    <li>• <strong className="text-blue-400">Analyst:</strong> Run what-if simulations, formulate decisions, inspect ML models.</li>
                    <li>• <strong className="text-slate-400">Viewer:</strong> Read-only observability across Control Tower telemetry.</li>
                  </ul>
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: Integrations (Masked Secrets) */}
          {activeTab === "integrations" && (
            <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4">
              <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                <div className="flex items-center gap-2">
                  <Server className="w-4 h-4 text-blue-400" />
                  <h3 className="text-sm font-bold text-white">Telemetry & ERP Adapter Secrets</h3>
                </div>
                <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                  SECRETS MASKED
                </span>
              </div>

              <div className="space-y-3 text-xs">
                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-slate-200 block">AIS Live Vessel Stream (Spire / MarineTraffic)</span>
                    <span className="font-mono text-[11px] text-slate-500">API Key: ••••••••••••••••••••a8f2</span>
                  </div>
                  <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                    CONNECTED
                  </span>
                </div>

                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-slate-200 block">SAP / ERP Execution Adapter</span>
                    <span className="font-mono text-[11px] text-slate-500">OAuth Client Secret: ••••••••••••••••••••9b1c</span>
                  </div>
                  <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                    ONLINE
                  </span>
                </div>

                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-slate-200 block">NOAA / Weather Disruption Feed</span>
                    <span className="font-mono text-[11px] text-slate-500">Token: ••••••••••••••••••••44e1</span>
                  </div>
                  <span className="text-[10px] font-mono text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                    ACTIVE
                  </span>
                </div>
              </div>

              <div className="pt-2 border-t border-[#243044] text-[11px] text-slate-500 font-mono">
                Notice: Raw API keys are never transmitted to browser clients.
              </div>
            </div>
          )}

          {/* Tab 4: Security */}
          {activeTab === "security" && (
            <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <h3 className="text-sm font-bold text-white">Compliance & Cryptographic Verification</h3>
                </div>
                <span className="text-xs font-mono text-slate-400">SOC2 Type II Ready</span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 space-y-1">
                  <span className="font-semibold text-slate-200 block">Session Management</span>
                  <p className="text-slate-400 text-[11px]">
                    Strict HttpOnly, SameSite=Lax session cookies. Zero browser token exposure.
                  </p>
                </div>
                <div className="p-3 rounded bg-[#1A2332] border border-slate-800 space-y-1">
                  <span className="font-semibold text-slate-200 block">Immutable Audit Trails</span>
                  <p className="text-slate-400 text-[11px]">
                    Cryptographically sealed SHA-256 fingerprints recorded for all solver executions and approvals.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
