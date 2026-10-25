"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, ChevronRight, Eye, EyeOff, Loader2, Lock, Mail, Shield, User, Building } from "lucide-react";
import { ChainSentinelLogo } from "@/components/auth/RiskWiseLogo";
import { AuthCard } from "@/components/auth/AuthCard";
import { AuthModeSwitch, AuthMode } from "@/components/auth/AuthModeSwitch";
import { GoogleAuthButton } from "@/components/auth/GoogleAuthButton";
import { AuthErrorBanner } from "@/components/auth/AuthErrorBanner";
import { AuthSecurityNotice } from "@/components/auth/AuthSecurityNotice";

import { useAuth } from "@/lib/auth/AuthContext";
import { apiClient, ApiClientError } from "@/lib/api/client";
import { OrganizationSelector } from "@/components/auth/OrganizationSelector";

type ExtendedAuthMode = "signin" | "signup" | "forgot";

function AuthContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, isLoading, refreshSession, user, logout } = useAuth();

  const [mode, setMode] = useState<ExtendedAuthMode>(
    searchParams.get("mode") === "signup" ? "signup" : "signin"
  );

  const queryError = searchParams.get("error");
  const [clientError, setClientError] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);
  const [isDismissed, setIsDismissed] = useState(false);
  const activeError = isDismissed ? null : (clientError || queryError);
  const [hasChosenOrg, setHasChosenOrg] = useState(false);

  // Sign-in state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Sign-up state
  const [fullName, setFullName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [termsAccepted, setTermsAccepted] = useState(false);

  // Forgot password state
  const [forgotEmail, setForgotEmail] = useState("");

  const rawReturnTo = searchParams.get("return_to") || "/";
  const returnTo =
    rawReturnTo.startsWith("/") && !rawReturnTo.startsWith("//") && !rawReturnTo.startsWith("/api/")
      ? rawReturnTo
      : "/";

  const organizations = user?.organizations || [];

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      if (organizations.length > 1 && !hasChosenOrg) {
        return;
      }
      if (organizations.length === 0 && !user?.org_id) {
        return;
      }
      router.replace(returnTo);
    }
  }, [isAuthenticated, organizations.length, hasChosenOrg, user?.org_id, returnTo, router]);

  if (isAuthenticated && organizations.length > 1 && !hasChosenOrg) {
    return (
      <div className="w-full max-w-md mx-auto">
        <AuthCard>
          <OrganizationSelector
            variant="standalone"
            onSelect={() => {
              setHasChosenOrg(true);
              router.replace(returnTo);
            }}
          />
        </AuthCard>
      </div>
    );
  }

  if (isAuthenticated && organizations.length === 0 && !user?.org_id) {
    return (
      <div className="w-full max-w-md mx-auto">
        <AuthCard>
          <div className="text-center space-y-4 py-2">
            <div className="w-12 h-12 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center mx-auto">
              <Building className="w-6 h-6" />
            </div>
            <div>
              <span className="px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded">
                ONBOARDING REQUIRED
              </span>
              <h2 className="mt-2 text-lg font-bold text-white tracking-tight">
                No Organization Assigned
              </h2>
              <p className="mt-1 text-xs text-slate-400">
                You are signed in as <span className="text-slate-200 font-medium">{user?.email}</span>, but you are not currently associated with an active company workspace.
              </p>
            </div>
            <div className="space-y-2 pt-2">
              <button
                type="button"
                onClick={() => setMode("signup")}
                className="w-full py-2.5 px-4 rounded-xl text-xs font-semibold text-white bg-[#0A7A75] hover:bg-[#0A7A75]/90 transition-colors shadow-lg cursor-pointer"
              >
                Register New Company
              </button>
              <button
                type="button"
                onClick={() => logout()}
                className="w-full py-2 px-4 rounded-xl text-xs font-medium text-slate-400 hover:text-white bg-white/[0.02] hover:bg-white/[0.06] border border-white/[0.08] transition-colors cursor-pointer"
              >
                Sign Out
              </button>
            </div>
          </div>
        </AuthCard>
      </div>
    );
  }

  if (isAuthenticated) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex flex-col items-center justify-center space-y-3 p-8 text-center"
      >
        <Loader2 className="w-6 h-6 text-[#0A7A75] animate-spin" aria-hidden="true" />
        <p className="text-sm text-slate-300 font-medium">
          Session verified. Opening workspace…
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

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsDismissed(false);
    setClientError(null);
    setIsSubmitting(true);

    try {
      const userRes = await apiClient.auth.login({
        email: loginEmail.trim(),
        password: loginPassword,
      });
      await refreshSession();
      if (userRes.organizations && userRes.organizations.length > 1) {
        setHasChosenOrg(false);
      } else {
        router.replace(returnTo);
      }
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setClientError(err.detail || "Authentication failed. Please verify credentials.");
      } else if (err instanceof Error) {
        setClientError(err.message);
      } else {
        setClientError("An unexpected login error occurred");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsDismissed(false);
    setClientError(null);

    if (signupPassword !== confirmPassword) {
      setClientError("Passwords do not match");
      return;
    }
    if (!termsAccepted) {
      setClientError("You must accept the Terms of Service and Privacy Policy");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiClient.auth.registerCompany({
        full_name: fullName.trim(),
        company_name: companyName.trim(),
        email: signupEmail.trim(),
        password: signupPassword,
        confirm_password: confirmPassword,
        terms_accepted: termsAccepted,
      });
      await refreshSession();
      router.replace(returnTo);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setClientError(err.detail || "Company registration failed. Please check your information.");
      } else if (err instanceof Error) {
        setClientError(err.message);
      } else {
        setClientError("Failed to register organization");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleForgotSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsDismissed(false);
    setClientError(null);
    setSuccessNotice(null);
    setIsSubmitting(true);

    try {
      const res = await apiClient.auth.forgotPassword({ email: forgotEmail.trim() });
      setSuccessNotice(res.message);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setClientError(err.detail || "Unable to send recovery instructions");
      } else {
        setClientError("Request failed. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AuthCard>
      {/* Brand Header */}
      <ChainSentinelLogo size="md" />

      {/* Error Alert Display */}
      {activeError && (
        <AuthErrorBanner
          error={activeError}
          onDismiss={handleDismissError}
        />
      )}

      {/* Success Alert Display */}
      {successNotice && (
        <div
          role="status"
          className="w-full flex items-start gap-3 p-3.5 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 text-xs font-mono"
        >
          <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
          <p className="leading-relaxed">{successNotice}</p>
        </div>
      )}

      {/* Mode Switch (Sign In / Sign Up) */}
      {mode !== "forgot" ? (
        <AuthModeSwitch
          mode={mode}
          onChange={(newMode) => {
            setMode(newMode);
            setIsDismissed(false);
            setClientError(null);
            setSuccessNotice(null);
          }}
          disabled={isLoading || isSubmitting}
        />
      ) : (
        <div className="w-full text-center space-y-1">
          <h2 className="text-sm font-semibold text-white tracking-wide">
            Password Recovery
          </h2>
          <p className="text-xs text-slate-400">
            Enter your work email address to receive password reset instructions.
          </p>
        </div>
      )}

      {/* ==================================================================== */}
      {/* 1. SIGN IN FORM */}
      {/* ==================================================================== */}
      {mode === "signin" && (
        <form onSubmit={handleLoginSubmit} className="w-full space-y-3.5">
          <div className="space-y-1.5">
            <label
              htmlFor="signin-email"
              className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
            >
              Work Email
            </label>
            <div className="relative">
              <input
                id="signin-email"
                type="email"
                required
                autoComplete="email"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder="colleague@company.com"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#0A7A75] focus:ring-1 focus:ring-[#0A7A75] transition-all font-mono"
              />
              <Mail className="w-4 h-4 text-slate-500 absolute right-3 top-2.5 pointer-events-none" />
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label
                htmlFor="signin-password"
                className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
              >
                Password
              </label>
              <button
                type="button"
                onClick={() => {
                  setMode("forgot");
                  setClientError(null);
                  setSuccessNotice(null);
                }}
                className="text-[11px] text-[#0A7A75] hover:text-[#0A7A75]/80 font-mono transition-colors cursor-pointer"
              >
                Forgot password?
              </button>
            </div>
            <div className="relative">
              <input
                id="signin-password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="current-password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="••••••••••••"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#0A7A75] focus:ring-1 focus:ring-[#0A7A75] transition-all font-mono pr-9"
              />
              <button
                type="button"
                aria-label={showPassword ? "Hide password" : "Show password"}
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-2.5 text-slate-500 hover:text-slate-300 transition-colors cursor-pointer"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            id="signin-submit-btn"
            disabled={isSubmitting || isLoading}
            className="w-full py-2.5 px-4 rounded-xl bg-[#0A7A75] hover:bg-[#0A7A75]/90 text-white text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm shadow-[#0A7A75]/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>AUTHENTICATING…</span>
              </>
            ) : (
              <>
                <Lock className="w-3.5 h-3.5" />
                <span>SIGN IN TO WORKSPACE</span>
              </>
            )}
          </button>
        </form>
      )}

      {/* ==================================================================== */}
      {/* 2. SIGN UP (COMPANY REGISTRATION) FORM */}
      {/* ==================================================================== */}
      {mode === "signup" && (
        <form onSubmit={handleRegisterSubmit} className="w-full space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div className="space-y-1">
              <label
                htmlFor="signup-name"
                className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
              >
                Full Name
              </label>
              <div className="relative">
                <input
                  id="signup-name"
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Jane Doe"
                  disabled={isSubmitting || isLoading}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#D95E00] focus:ring-1 focus:ring-[#D95E00] transition-all font-mono"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="signup-company"
                className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
              >
                Company Name
              </label>
              <div className="relative">
                <input
                  id="signup-company"
                  type="text"
                  required
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="Acme Global"
                  disabled={isSubmitting || isLoading}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#D95E00] focus:ring-1 focus:ring-[#D95E00] transition-all font-mono"
                />
              </div>
            </div>
          </div>

          <div className="space-y-1">
            <label
              htmlFor="signup-email"
              className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
            >
              Work Email
            </label>
            <div className="relative">
              <input
                id="signup-email"
                type="email"
                required
                autoComplete="email"
                value={signupEmail}
                onChange={(e) => setSignupEmail(e.target.value)}
                placeholder="jane@acmeglobal.com"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#D95E00] focus:ring-1 focus:ring-[#D95E00] transition-all font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div className="space-y-1">
              <label
                htmlFor="signup-password"
                className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
              >
                Password
              </label>
              <input
                id="signup-password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="new-password"
                value={signupPassword}
                onChange={(e) => setSignupPassword(e.target.value)}
                placeholder="Min 8 chars, 1 uppercase"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#D95E00] focus:ring-1 focus:ring-[#D95E00] transition-all font-mono"
              />
            </div>

            <div className="space-y-1">
              <label
                htmlFor="signup-confirm-password"
                className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
              >
                Confirm
              </label>
              <input
                id="signup-confirm-password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Repeat password"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#D95E00] focus:ring-1 focus:ring-[#D95E00] transition-all font-mono"
              />
            </div>
          </div>

          <div className="flex items-start gap-2 pt-1">
            <input
              id="signup-terms"
              type="checkbox"
              required
              checked={termsAccepted}
              onChange={(e) => setTermsAccepted(e.target.checked)}
              disabled={isSubmitting || isLoading}
              className="mt-0.5 rounded border-white/20 bg-[#0A0D14] text-[#D95E00] focus:ring-[#D95E00] cursor-pointer"
            />
            <label htmlFor="signup-terms" className="text-[11px] text-slate-400 leading-tight">
              I agree to the Enterprise{" "}
              <span className="text-slate-200 underline cursor-pointer">Terms of Service</span> and{" "}
              <span className="text-slate-200 underline cursor-pointer">Privacy Policy</span>.
            </label>
          </div>

          <button
            type="submit"
            id="signup-submit-btn"
            disabled={isSubmitting || isLoading}
            className="w-full py-2.5 px-4 rounded-xl bg-[#D95E00] hover:bg-[#D95E00]/90 text-white text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm shadow-[#D95E00]/20 disabled:opacity-50 disabled:cursor-not-allowed mt-1"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>PROVISIONING TENANT…</span>
              </>
            ) : (
              <>
                <Building className="w-3.5 h-3.5" />
                <span>REGISTER COMPANY & WORKSPACE</span>
              </>
            )}
          </button>
        </form>
      )}

      {/* ==================================================================== */}
      {/* 3. FORGOT PASSWORD FORM */}
      {/* ==================================================================== */}
      {mode === "forgot" && (
        <form onSubmit={handleForgotSubmit} className="w-full space-y-3.5">
          <div className="space-y-1.5">
            <label
              htmlFor="forgot-email"
              className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
            >
              Account Email
            </label>
            <div className="relative">
              <input
                id="forgot-email"
                type="email"
                required
                autoComplete="email"
                value={forgotEmail}
                onChange={(e) => setForgotEmail(e.target.value)}
                placeholder="colleague@company.com"
                disabled={isSubmitting || isLoading}
                className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#0A7A75] focus:ring-1 focus:ring-[#0A7A75] transition-all font-mono"
              />
              <Mail className="w-4 h-4 text-slate-500 absolute right-3 top-2.5 pointer-events-none" />
            </div>
          </div>

          <button
            type="submit"
            id="forgot-submit-btn"
            disabled={isSubmitting || isLoading}
            className="w-full py-2.5 px-4 rounded-xl bg-[#0A7A75] hover:bg-[#0A7A75]/90 text-white text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm shadow-[#0A7A75]/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>SENDING INSTRUCTIONS…</span>
              </>
            ) : (
              <span>SEND RECOVERY LINK</span>
            )}
          </button>

          <button
            type="button"
            onClick={() => {
              setMode("signin");
              setClientError(null);
              setSuccessNotice(null);
            }}
            className="w-full py-2 text-center text-xs text-slate-400 hover:text-white font-mono transition-colors cursor-pointer"
          >
            ← Back to Sign In
          </button>
        </form>
      )}

      {/* Alternative SSO & Demo Options (Available in Sign In and Sign Up modes) */}
      {mode !== "forgot" && (
        <div className="w-full pt-1 space-y-3">
          <div className="relative flex items-center justify-center py-1">
            <div className="border-t border-arch w-full" />
            <span
              className="px-2 text-[10px] uppercase font-mono text-muted-foreground tracking-wider"
              style={{ backgroundColor: "var(--bg-card)" }}
            >
              OR CONTINUE WITH
            </span>
            <div className="border-t border-arch w-full" />
          </div>

          <GoogleAuthButton
            mode={mode}
            returnTo={returnTo}
            onError={(err) => {
              setIsDismissed(false);
              setClientError(err);
            }}
            disabled={isLoading || isSubmitting}
          />

          <a
            href={`/api/v1/auth/demo-login?return_to=${encodeURIComponent(returnTo)}`}
            className="w-full py-2.5 px-4 rounded-xl border border-[#D95E00]/40 hover:border-[#D95E00]/80 bg-[#D95E00]/10 hover:bg-[#D95E00]/20 text-[#D95E00] text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all cursor-pointer text-center shadow-sm shadow-[#D95E00]/10 select-none"
          >
            <span className="w-2 h-2 rounded-full bg-[#0A7A75] animate-pulse" />
            Demo Workspace Access
          </a>
        </div>
      )}

      {/* Enterprise Security Notice & Metadata */}
      <AuthSecurityNotice />
    </AuthCard>
  );
}

function AuthLoadingFallback() {
  return (
    <div
      role="status"
      aria-label="Loading CHAINSENTINEL Authentication"
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
          <span className="tracking-widest uppercase font-semibold">CHAINSENTINEL GATEWAY</span>
        </div>
        <div className="hidden sm:block text-slate-500 tracking-wider">
          TLS 1.3 ENCRYPTED • MULTI-TENANT ISOLATED
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
        <p>© {new Date().getFullYear()} CHAINSENTINEL Inc. All rights reserved.</p>
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
            Audit Assurance
          </span>
        </div>
      </footer>
    </main>
  );
}
