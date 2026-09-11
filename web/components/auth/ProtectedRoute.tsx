"use client";

import React, { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Loader2, ShieldAlert, Clock, Building2, LogOut, ArrowLeft } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: string | string[];
  requiredPermission?: string;
  fallback?: React.ReactNode;
}

export function ProtectedRoute({
  children,
  requiredRole,
  requiredPermission,
  fallback,
}: ProtectedRouteProps) {
  const {
    status,
    user,
    organization,
    role,
    permissions,
    logout,
    hasRole,
    hasPermission,
    isLoading,
  } = useAuth();

  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "unauthenticated") {
      const returnTo = pathname && pathname !== "/auth" ? `?return_to=${encodeURIComponent(pathname)}` : "";
      router.replace(`/auth${returnTo}`);
    }
  }, [status, pathname, router]);

  // Loading State
  if (isLoading || status === "loading") {
    return (
      fallback || (
        <div
          role="status"
          aria-label="Verifying authentication session"
          className="min-h-screen w-full flex flex-col items-center justify-center bg-[#08090A] text-slate-100 p-6"
        >
          <div className="w-full max-w-sm rounded-2xl liquid-metal-panel p-8 text-center space-y-4 shadow-2xl">
            <Loader2 className="w-8 h-8 text-blue-400 animate-spin mx-auto" aria-hidden="true" />
            <div>
              <h2 className="text-sm font-semibold tracking-wide uppercase text-slate-200">
                Verifying Credentials
              </h2>
              <p className="mt-1 text-xs text-slate-400 font-mono tracking-wider">
                CHECKING SESSION & TENANT ISOLATION…
              </p>
            </div>
          </div>
        </div>
      )
    );
  }

  // Unauthenticated State (redirecting in useEffect)
  if (status === "unauthenticated") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="min-h-screen w-full flex flex-col items-center justify-center bg-[#08090A] text-slate-100 p-6"
      >
        <Loader2 className="w-6 h-6 text-blue-400 animate-spin" aria-hidden="true" />
        <p className="mt-3 text-xs text-slate-400 font-mono">
          REDIRECTING TO RISKWISE GATEWAY…
        </p>
      </div>
    );
  }

  // Onboarding Required: Authenticated with Google, but organization not yet assigned
  if (status === "onboarding-required") {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-[#08090A] text-slate-100 p-4 sm:p-6">
        <div className="w-full max-w-md liquid-metal-panel shadow-2xl">
          <div className="liquid-metal-content p-6 sm:p-8 space-y-6 text-center">
            <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400 flex items-center justify-center mx-auto">
              <Building2 className="w-6 h-6" aria-hidden="true" />
            </div>

            <div>
              <span className="px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded">
                IDENTITY VERIFIED
              </span>
              <h2 className="mt-2 text-xl font-bold tracking-tight text-white">
                Organization Setup Required
              </h2>
              <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                Signed in as <span className="text-slate-200 font-medium">{user?.email}</span>. Your Google identity is authenticated, but you are not yet associated with an active RiskWise organization workspace.
              </p>
            </div>

            <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] text-left text-xs text-slate-400 space-y-1.5">
              <p className="font-semibold text-slate-300">Next Steps:</p>
              <ul className="list-disc list-inside space-y-1 text-slate-400 text-[11px]">
                <li>Ask your organization administrator to invite your email.</li>
                <li>Ensure you are signing in with your corporate Google Workspace account.</li>
              </ul>
            </div>

            <div className="flex flex-col sm:flex-row gap-2 pt-2">
              <button
                type="button"
                onClick={() => logout()}
                className="w-full py-2.5 px-4 rounded-xl text-xs font-medium text-slate-300 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] transition-colors flex items-center justify-center gap-2 cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Sign Out</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Access Pending: Organization exists but is inactive / awaiting administrator review
  if (status === "access-pending") {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-[#08090A] text-slate-100 p-4 sm:p-6">
        <div className="w-full max-w-md liquid-metal-panel shadow-2xl">
          <div className="liquid-metal-content p-6 sm:p-8 space-y-6 text-center">
            <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center mx-auto">
              <Clock className="w-6 h-6" aria-hidden="true" />
            </div>

            <div>
              <span className="px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded">
                ACCESS PENDING
              </span>
              <h2 className="mt-2 text-xl font-bold tracking-tight text-white">
                Workspace Approval In Progress
              </h2>
              <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                Organization <span className="text-slate-200 font-medium">{organization?.name || user?.org_id}</span> is currently inactive or pending administrator verification.
              </p>
            </div>

            <div className="p-3 rounded-lg bg-amber-950/20 border border-amber-500/20 text-xs text-amber-200/90 text-left">
              Contact your RiskWise platform administrator to activate your organization subscription.
            </div>

            <button
              type="button"
              onClick={() => logout()}
              className="w-full py-2.5 px-4 rounded-xl text-xs font-medium text-slate-300 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] transition-colors flex items-center justify-center gap-2 cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Sign Out</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Access Denied: 403 Forbidden or Role / Permission check failure
  const roleDenied = requiredRole
    ? Array.isArray(requiredRole)
      ? !hasRole(...requiredRole)
      : !hasRole(requiredRole)
    : false;

  const permissionDenied = requiredPermission ? !hasPermission(requiredPermission) : false;

  if (status === "access-denied" || roleDenied || permissionDenied) {
    return (
      <div className="min-h-screen w-full flex flex-col items-center justify-center bg-[#08090A] text-slate-100 p-4 sm:p-6">
        <div className="w-full max-w-md liquid-metal-panel shadow-2xl">
          <div className="liquid-metal-content p-6 sm:p-8 space-y-6 text-center">
            <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 flex items-center justify-center mx-auto">
              <ShieldAlert className="w-6 h-6" aria-hidden="true" />
            </div>

            <div>
              <span className="px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest bg-red-500/10 text-red-400 border border-red-500/20 rounded">
                HTTP 403 FORBIDDEN
              </span>
              <h2 className="mt-2 text-xl font-bold tracking-tight text-white">
                Insufficient Permissions
              </h2>
              <p className="mt-2 text-xs text-slate-400 leading-relaxed">
                Your authenticated role (<span className="text-slate-200 font-mono font-medium">{role || "VIEWER"}</span>) does not possess authorization to access this view.
              </p>
            </div>

            <div className="p-3 rounded-lg bg-white/[0.02] border border-white/[0.06] text-left text-xs text-slate-400 space-y-1 font-mono text-[11px]">
              {requiredRole && (
                <div>
                  <span className="text-slate-500">Required Role: </span>
                  <span className="text-blue-300">{Array.isArray(requiredRole) ? requiredRole.join(" or ") : requiredRole}</span>
                </div>
              )}
              {requiredPermission && (
                <div>
                  <span className="text-slate-500">Required Capability: </span>
                  <span className="text-blue-300">{requiredPermission}</span>
                </div>
              )}
              <div>
                <span className="text-slate-500">Granted Capabilities: </span>
                <span className="text-slate-300">{permissions.length > 0 ? permissions.join(", ") : "none"}</span>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2 pt-2">
              <button
                type="button"
                onClick={() => router.push("/")}
                className="flex-1 py-2.5 px-4 rounded-xl text-xs font-medium text-white bg-blue-600/20 hover:bg-blue-600/30 border border-blue-500/30 transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <ArrowLeft className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Return to Home</span>
              </button>

              <button
                type="button"
                onClick={() => logout()}
                className="py-2.5 px-4 rounded-xl text-xs font-medium text-slate-400 hover:text-slate-200 bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.08] transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
                <span>Sign Out</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Authenticated and Authorized
  return <>{children}</>;
}
