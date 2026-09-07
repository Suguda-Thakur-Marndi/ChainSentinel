"use client";

import React from "react";
import { LogOut, RefreshCw, Shield, User, Building, KeyRound, CheckCircle2 } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { useAuth } from "@/lib/auth/AuthContext";
import { RiskWiseLogo } from "@/components/auth/RiskWiseLogo";

function AuthenticatedWorkspace() {
  const { user, organization, role, permissions, logout, refreshSession, isLoading } = useAuth();
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await refreshSession();
    } finally {
      setIsRefreshing(false);
    }
  };

  return (
    <main className="min-h-screen w-full flex flex-col bg-[#08090A] text-slate-100 selection:bg-blue-500/30 selection:text-blue-200">
      {/* Top Enterprise Navigation Bar */}
      <header className="w-full border-b border-white/[0.08] bg-[#0D0F11]/80 backdrop-blur-md px-4 sm:px-8 py-3.5 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <RiskWiseLogo size="sm" className="!gap-1 !flex-row items-center" />
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading || isRefreshing}
            className="p-2 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.04] border border-white/[0.06] transition-colors cursor-pointer disabled:opacity-50"
            title="Refresh Session Context"
            aria-label="Refresh Session Context"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-blue-400" : ""}`} />
          </button>

          <div className="hidden sm:flex flex-col text-right">
            <span className="text-xs font-medium text-slate-200">
              {user?.full_name || user?.email}
            </span>
            <span className="text-[10px] font-mono text-slate-500 tracking-wider">
              {role || "VIEWER"}
            </span>
          </div>

          <button
            type="button"
            onClick={() => logout()}
            className="flex items-center gap-2 py-1.5 px-3 rounded-lg text-xs font-medium text-slate-300 hover:text-white bg-white/[0.04] hover:bg-red-500/10 hover:text-red-300 hover:border-red-500/30 border border-white/[0.08] transition-all cursor-pointer"
          >
            <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Sign Out</span>
          </button>
        </div>
      </header>

      {/* Main Workspace Body */}
      <div className="flex-1 w-full max-w-5xl mx-auto p-4 sm:p-8 space-y-6">
        {/* Verification Banner */}
        <div className="rounded-xl bg-emerald-950/20 border border-emerald-500/20 p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">
              <CheckCircle2 className="w-5 h-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-emerald-300">
                Authenticated Session Active
              </h2>
              <p className="text-xs text-emerald-200/70">
                Connected via HttpOnly session cookie to FastAPI backend (/api/v1/auth/me).
              </p>
            </div>
          </div>
          <span className="hidden md:inline-block px-2.5 py-1 text-[11px] font-mono uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded">
            ZERO TOKEN EXPOSURE
          </span>
        </div>

        {/* Identity & Tenancy Context Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* User Profile Card */}
          <div className="liquid-metal-panel shadow-xl">
            <div className="liquid-metal-content p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                <div className="flex items-center gap-2 text-blue-400">
                  <User className="w-4 h-4" />
                  <h3 className="text-xs font-semibold tracking-wider uppercase text-slate-300">
                    User Identity
                  </h3>
                </div>
                <span className="px-2 py-0.5 text-[10px] font-mono uppercase bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded">
                  {role || "ANALYST"}
                </span>
              </div>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-500">Email:</span>
                  <span className="text-slate-200 font-mono font-medium">{user?.email}</span>
                </div>
                {user?.full_name && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Name:</span>
                    <span className="text-slate-200">{user.full_name}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-slate-500">User ID:</span>
                  <span className="text-slate-400 font-mono text-[11px]">{user?.id}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Assigned Role:</span>
                  <span className="text-slate-200 font-medium">{role}</span>
                </div>
              </div>
            </div>
          </div>

          {/* Organization Boundary Card */}
          <div className="liquid-metal-panel shadow-xl">
            <div className="liquid-metal-content p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
                <div className="flex items-center gap-2 text-indigo-400">
                  <Building className="w-4 h-4" />
                  <h3 className="text-xs font-semibold tracking-wider uppercase text-slate-300">
                    Organization Tenant
                  </h3>
                </div>
                <span className="px-2 py-0.5 text-[10px] font-mono uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded">
                  {organization?.plan || "ENTERPRISE"}
                </span>
              </div>

              <div className="space-y-2.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-500">Organization:</span>
                  <span className="text-slate-200 font-medium">
                    {organization?.name || "Personal Workspace"}
                  </span>
                </div>
                {organization?.slug && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Slug:</span>
                    <span className="text-slate-400 font-mono">{organization.slug}</span>
                  </div>
                )}
                <div className="flex justify-between">
                  <span className="text-slate-500">Tenant ID:</span>
                  <span className="text-slate-400 font-mono text-[11px]">
                    {organization?.id || user?.org_id || "Unassigned"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Status:</span>
                  <span className="text-emerald-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    Active Boundary
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Granted Capabilities / Permissions */}
        <div className="liquid-metal-panel shadow-xl">
          <div className="liquid-metal-content p-6 space-y-3">
            <div className="flex items-center gap-2 text-slate-300 border-b border-white/[0.06] pb-3">
              <KeyRound className="w-4 h-4 text-blue-400" />
              <h3 className="text-xs font-semibold tracking-wider uppercase text-slate-300">
                Granted RBAC Capabilities
              </h3>
            </div>

            {permissions && permissions.length > 0 ? (
              <div className="flex flex-wrap gap-2 pt-1">
                {permissions.map((perm) => (
                  <span
                    key={perm}
                    className="px-2.5 py-1 text-xs font-mono rounded-lg bg-white/[0.03] text-blue-300 border border-white/[0.08]"
                  >
                    {perm}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 italic">
                Standard read capabilities assigned.
              </p>
            )}
          </div>
        </div>

        {/* Security & Infrastructure Telemetry */}
        <div className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.04] text-[11px] text-slate-500 font-mono flex flex-col sm:flex-row items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Shield className="w-3.5 h-3.5 text-blue-400" />
            <span>SESSION BOUNDARY: STRICT HTTPONLY • SAMESITE=LAX</span>
          </div>
          <div>FASTAPI 0.115 • POSTGRESQL 16 • MULTI-TENANT</div>
        </div>
      </div>
    </main>
  );
}

export default function Home() {
  return (
    <ProtectedRoute>
      <AuthenticatedWorkspace />
    </ProtectedRoute>
  );
}
