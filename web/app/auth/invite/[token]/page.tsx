"use client";

import React, { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { AlertCircle, Building, CheckCircle2, Eye, EyeOff, Loader2, ShieldCheck, UserCheck } from "lucide-react";
import { AuthCard } from "@/components/auth/AuthCard";
import { ChainSentinelLogo } from "@/components/auth/RiskWiseLogo";
import { apiClient, ApiClientError } from "@/lib/api/client";
import { InvitationDetailsResponse } from "@/lib/auth/types";
import { useAuth } from "@/lib/auth/AuthContext";

export default function AcceptInvitationPage() {
  const params = useParams();
  const token = typeof params?.token === "string" ? params.token : "";
  const router = useRouter();
  const { refreshSession } = useAuth();

  const [isLoadingDetails, setIsLoadingDetails] = useState(true);
  const [invitation, setInvitation] = useState<InvitationDetailsResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setLoadError("Missing invitation token");
      setIsLoadingDetails(false);
      return;
    }

    let isMounted = true;
    apiClient.auth
      .getInvitation(token)
      .then((data) => {
        if (isMounted) {
          setInvitation(data);
          setIsLoadingDetails(false);
        }
      })
      .catch((err) => {
        if (!isMounted) return;
        setIsLoadingDetails(false);
        if (err instanceof ApiClientError) {
          setLoadError(err.detail || "Invitation is invalid or has expired");
        } else {
          setLoadError("Failed to validate invitation token");
        }
      });

    return () => {
      isMounted = false;
    };
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);

    if (password !== confirmPassword) {
      setSubmitError("Passwords do not match");
      return;
    }

    setIsSubmitting(true);
    try {
      await apiClient.auth.acceptInvitation(token, {
        full_name: fullName.trim(),
        password,
        confirm_password: confirmPassword,
      });
      await refreshSession();
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiClientError) {
        setSubmitError(err.detail || "Failed to accept invitation");
      } else if (err instanceof Error) {
        setSubmitError(err.message);
      } else {
        setSubmitError("An unexpected error occurred");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen w-full flex flex-col justify-between items-center p-4 sm:p-6 bg-[#08090A] text-slate-100 relative overflow-hidden select-text">
      {/* Background pattern */}
      <div
        className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff05_1px,transparent_1px),linear-gradient(to_bottom,#ffffff05_1px,transparent_1px)] bg-[size:32px_32px] pointer-events-none"
        aria-hidden="true"
      />

      {/* Top Header */}
      <header className="w-full max-w-5xl flex items-center justify-between text-[11px] text-slate-500 font-mono z-10 py-1">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
          <span className="tracking-widest uppercase font-semibold">CHAINSENTINEL INVITATION</span>
        </div>
        <div className="text-slate-500 tracking-wider">
          SECURE TENANT ONBOARDING
        </div>
      </header>

      {/* Center Viewport */}
      <div className="w-full flex items-center justify-center my-auto py-6 z-10">
        <AuthCard>
          <ChainSentinelLogo size="md" />

          {/* Loading state */}
          {isLoadingDetails && (
            <div className="flex flex-col items-center justify-center space-y-3 py-10 text-center">
              <Loader2 className="w-6 h-6 text-[#0A7A75] animate-spin" />
              <p className="text-xs font-mono text-slate-400">VALIDATING INVITATION CREDENTIALS…</p>
            </div>
          )}

          {/* Invalid / Expired State */}
          {!isLoadingDetails && loadError && (
            <div className="w-full space-y-4 text-center py-4">
              <div className="mx-auto w-12 h-12 rounded-full bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h2 className="text-sm font-semibold text-white">Invitation Unavailable</h2>
                <p className="text-xs text-slate-400 leading-relaxed max-w-xs mx-auto">
                  {loadError}
                </p>
              </div>
              <Link
                href="/auth"
                className="inline-block py-2 px-4 rounded-xl border border-white/10 hover:border-white/20 bg-white/5 hover:bg-white/10 text-xs font-mono text-slate-200 transition-colors"
              >
                Return to Sign In
              </Link>
            </div>
          )}

          {/* Valid Invitation Form */}
          {!isLoadingDetails && invitation && (
            <div className="w-full space-y-4">
              {/* Tenant context banner */}
              <div className="p-3.5 rounded-xl border border-[#0A7A75]/30 bg-[#0A7A75]/10 space-y-1.5 text-xs font-mono">
                <div className="flex items-center gap-2 text-[#0A7A75]">
                  <Building className="w-4 h-4 shrink-0" />
                  <span className="font-semibold text-white tracking-wide">
                    {invitation.organization_name}
                  </span>
                </div>
                <div className="text-slate-300 flex items-center justify-between text-[11px] pt-1 border-t border-[#0A7A75]/20">
                  <span>Assigned Role:</span>
                  <span className="px-2 py-0.5 rounded bg-[#0A7A75]/20 text-[#0A7A75] font-semibold">
                    {invitation.role}
                  </span>
                </div>
                <div className="text-slate-400 text-[11px]">
                  <span>Invited email: </span>
                  <span className="text-slate-200 font-medium">{invitation.email}</span>
                </div>
              </div>

              {submitError && (
                <div className="p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 text-xs font-mono flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{submitError}</span>
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-3">
                <div className="space-y-1">
                  <label
                    htmlFor="invite-fullname"
                    className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
                  >
                    Your Full Name
                  </label>
                  <input
                    id="invite-fullname"
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Jane Doe"
                    disabled={isSubmitting}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#0A7A75] focus:ring-1 focus:ring-[#0A7A75] transition-all font-mono"
                  />
                </div>

                <div className="space-y-1">
                  <label
                    htmlFor="invite-password"
                    className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
                  >
                    Create Password
                  </label>
                  <div className="relative">
                    <input
                      id="invite-password"
                      type={showPassword ? "text" : "password"}
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Min 8 chars, 1 uppercase"
                      disabled={isSubmitting}
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

                <div className="space-y-1">
                  <label
                    htmlFor="invite-confirm"
                    className="block text-[11px] font-mono text-slate-300 uppercase tracking-wider"
                  >
                    Confirm Password
                  </label>
                  <input
                    id="invite-confirm"
                    type={showPassword ? "text" : "password"}
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Repeat password"
                    disabled={isSubmitting}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-white/10 bg-[#0A0D14] text-slate-100 placeholder-slate-500 focus:outline-none focus:border-[#0A7A75] focus:ring-1 focus:ring-[#0A7A75] transition-all font-mono"
                  />
                </div>

                <button
                  type="submit"
                  id="accept-invitation-submit-btn"
                  disabled={isSubmitting}
                  className="w-full py-2.5 px-4 rounded-xl bg-[#0A7A75] hover:bg-[#0A7A75]/90 text-white text-xs font-mono font-medium flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm shadow-[#0A7A75]/20 disabled:opacity-50 disabled:cursor-not-allowed mt-2"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>ACTIVATING ACCOUNT…</span>
                    </>
                  ) : (
                    <>
                      <UserCheck className="w-4 h-4" />
                      <span>JOIN {invitation.organization_name.toUpperCase()}</span>
                    </>
                  )}
                </button>
              </form>
            </div>
          )}
        </AuthCard>
      </div>

      {/* Footer */}
      <footer className="w-full max-w-5xl flex items-center justify-between text-[11px] text-slate-500 z-10 py-1 border-t border-white/[0.04]">
        <p>© {new Date().getFullYear()} CHAINSENTINEL Inc. All rights reserved.</p>
        <div className="flex items-center gap-4 text-slate-400">
          <Link href="/auth" className="hover:text-slate-200 transition-colors">
            Sign In with Existing Account
          </Link>
        </div>
      </footer>
    </main>
  );
}
