"use client";

import React, { useEffect, useRef } from "react";
import { AlertTriangle, X } from "lucide-react";

interface AuthErrorBannerProps {
  error: string | null;
  onDismiss: () => void;
}

const ERROR_MESSAGES: Record<string, { title: string; detail: string }> = {
  invalid_state: {
    title: "Security Verification Expired",
    detail: "Your authentication session timed out or security verification failed. Please try again.",
  },
  oauth_exchange_failed: {
    title: "Authentication Failed",
    detail: "Google authentication could not be completed. Please try again or contact support.",
  },
  account_deactivated: {
    title: "Account Deactivated",
    detail: "Your RiskWise account has been deactivated. Please contact your organization administrator.",
  },
  unverified_email: {
    title: "Unverified Google Account",
    detail: "Your Google email address is not verified. Please verify your email with Google before signing in.",
  },
  google_not_configured: {
    title: "SSO Service Unavailable",
    detail: "Google Single Sign-On is not currently enabled on this environment.",
  },
  access_denied: {
    title: "Sign In Cancelled",
    detail: "Google sign-in request was cancelled. You may retry whenever you are ready.",
  },
  session_expired: {
    title: "Session Expired",
    detail: "Your previous session has expired. Please sign in to resume your workspace.",
  },
  network_error: {
    title: "Connection Error",
    detail: "Unable to connect to the authentication server. Please check your connection and retry.",
  },
};

export function AuthErrorBanner({ error, onDismiss }: AuthErrorBannerProps) {
  const alertRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (error && alertRef.current) {
      alertRef.current.focus();
    }
  }, [error]);

  if (!error) return null;

  const errorInfo = ERROR_MESSAGES[error] || {
    title: "Authentication Error",
    detail: error.length > 80 ? "An unexpected error occurred during authentication. Please retry." : error,
  };

  return (
    <div
      ref={alertRef}
      role="alert"
      aria-live="assertive"
      tabIndex={-1}
      className="relative w-full rounded-xl bg-red-950/40 border border-red-500/30 p-4 text-red-200 shadow-lg backdrop-blur-sm focus:outline-none focus:ring-2 focus:ring-red-500/50"
    >
      <div className="flex items-start gap-3">
        <div className="p-1 rounded-md bg-red-500/10 text-red-400 mt-0.5 shrink-0" aria-hidden="true">
          <AlertTriangle className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0 pr-2">
          <h2 className="text-xs font-semibold tracking-wide uppercase text-red-300">
            {errorInfo.title}
          </h2>
          <p className="mt-1 text-xs text-red-200/90 leading-relaxed font-normal">
            {errorInfo.detail}
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="p-1 rounded-md text-red-400 hover:text-red-200 hover:bg-red-500/10 transition-colors focus:outline-none focus:ring-2 focus:ring-red-400"
          aria-label="Dismiss error alert"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
