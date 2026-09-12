"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { RiskWiseLogo } from "@/components/auth/RiskWiseLogo";
import { AuthCard } from "@/components/auth/AuthCard";
import { AuthModeSwitch, AuthMode } from "@/components/auth/AuthModeSwitch";
import { GoogleAuthButton } from "@/components/auth/GoogleAuthButton";
import { AuthErrorBanner } from "@/components/auth/AuthErrorBanner";
import { AuthSecurityNotice } from "@/components/auth/AuthSecurityNotice";

import { useAuth } from "@/lib/auth/AuthContext";

function AuthContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, isLoading } = useAuth();

  const [mode, setMode] = useState<AuthMode>(
    searchParams.get("mode") === "signup" ? "signup" : "signin"
  );
  const queryError = searchParams.get("error");
  const [clientError, setClientError] = useState<string | null>(null);
  const [isDismissed, setIsDismissed] = useState(false);
  const activeError = isDismissed ? null : (clientError || queryError);

  const rawReturnTo = searchParams.get("return_to") || "/";
  // Safe relative path validation to prevent open-redirect vulnerabilities and internal API paths
  const returnTo =
    rawReturnTo.startsWith("/") && !rawReturnTo.startsWith("//") && !rawReturnTo.startsWith("/api/")
      ? rawReturnTo
      : "/";

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      router.replace(returnTo);
    }
  }, [isAuthenticated, returnTo, router]);

  if (isAuthenticated) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center justify-center space-y-3 p-8 text-center"
      >
        <Loader2 className="w-6 h-6 text-blue-400 animate-spin" aria-hidden="true" />
        <p className="text-sm text-slate-300 font-medium">
          Session verified. Redirecting to RiskWise workspace…
        </p>
      </div>
    );
  }

  const handleDismissError = () => {
    setIsDismissed(true);
    setClientError(null);
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.delete("error");
    window.history.replaceState({}, "", nextUrl.pathname + nextUrl.search);
  };

  return (
    <AuthCard>
      {/* Brand Header */}
      <RiskWiseLogo size="md" />

      {/* Error Alert Display */}
      {activeError && (
        <AuthErrorBanner
          error={activeError}
          onDismiss={handleDismissError}
        />
      )}

      {/* Mode Switch (Sign In / Sign Up) */}
      <AuthModeSwitch
        mode={mode}
        onChange={(newMode) => {
          setMode(newMode);
          setIsDismissed(false);
        }}
        disabled={isLoading}
      />

      {/* Primary Google SSO Action & Demo Access */}
      <div className="w-full pt-1 space-y-3">
        <GoogleAuthButton
          mode={mode}
          returnTo={returnTo}
          onError={(err) => {
            setIsDismissed(false);
            setClientError(err);
          }}
          disabled={isLoading}
        />

        <div className="relative flex items-center justify-center py-1">
          <div className="border-t border-slate-800 w-full" />
          <span className="bg-[#111827] px-2 text-[10px] uppercase font-mono text-slate-500 tracking-wider">
            OR
          </span>
          <div className="border-t border-slate-800 w-full" />
        </div>

        <a
          href={`http://localhost:8000/api/v1/auth/demo-login?return_to=${encodeURIComponent(returnTo)}`}
          className="w-full py-2.5 px-4 rounded-xl border border-blue-500/30 hover:border-blue-500/60 bg-blue-500/10 hover:bg-blue-500/20 text-blue-300 text-xs font-medium flex items-center justify-center gap-2 transition-colors cursor-pointer text-center"
        >
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          Enter Mission Control (Demo Access)
        </a>
      </div>

      {/* Enterprise Security Notice & Metadata */}
      <AuthSecurityNotice />
    </AuthCard>
  );
}

function AuthLoadingFallback() {
  return (
    <div
      role="status"
      aria-label="Loading RiskWise Authentication"
      className="w-full max-w-[420px] h-[520px] rounded-2xl liquid-metal-panel flex items-center justify-center"
    >
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 text-blue-400 animate-spin" aria-hidden="true" />
        <span className="text-xs text-slate-400 font-mono tracking-wider">
          INITIALIZING SECURE SESSION…
        </span>
      </div>
    </div>
  );
}

export default function AuthPage() {
  return (
    <main className="min-h-screen w-full flex flex-col justify-between items-center p-4 sm:p-6 bg-[#08090A] text-slate-100 relative overflow-hidden select-text">
      {/* Subtle enterprise background grid pattern */}
      <div
        className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:32px_32px] pointer-events-none"
        aria-hidden="true"
      />

      {/* Top Bar / Security Status */}
      <header className="w-full max-w-5xl flex items-center justify-between text-[11px] text-slate-500 font-mono z-10 py-1">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          <span className="tracking-widest uppercase">RISKWISE GATEWAY SECURE</span>
        </div>
        <div className="hidden sm:block text-slate-500 tracking-wider">
          TLS 1.3 • STRICT MULTI-TENANT
        </div>
      </header>

      {/* Centered Auth Viewport */}
      <div className="w-full flex items-center justify-center my-auto py-4 z-10">
        <Suspense fallback={<AuthLoadingFallback />}>
          <AuthContent />
        </Suspense>
      </div>

      {/* Footer / Governance */}
      <footer className="w-full max-w-5xl flex flex-col sm:flex-row items-center justify-between gap-2 text-[11px] text-slate-500 z-10 py-1 border-t border-white/[0.04]">
        <p>© {new Date().getFullYear()} RiskWise Systems Inc. Enterprise Edition.</p>
        <div className="flex items-center gap-4 text-slate-400">
          <span className="hover:text-slate-200 transition-colors cursor-default">
            Security Architecture
          </span>
          <span>•</span>
          <span className="hover:text-slate-200 transition-colors cursor-default">
            Privacy Policy
          </span>
          <span>•</span>
          <span className="hover:text-slate-200 transition-colors cursor-default">
            Status
          </span>
        </div>
      </footer>
    </main>
  );
}
