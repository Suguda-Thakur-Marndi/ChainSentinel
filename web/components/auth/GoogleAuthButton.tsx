"use client";

import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import { AuthMode } from "./AuthModeSwitch";

interface GoogleAuthButtonProps {
  mode: AuthMode;
  returnTo?: string;
  onError?: (error: string) => void;
  disabled?: boolean;
}

export function GoogleAuthButton({
  mode,
  returnTo = "/",
  onError,
  disabled = false,
}: GoogleAuthButtonProps) {
  const [isInitiating, setIsInitiating] = useState(false);

  const handleGoogleAuth = () => {
    if (isInitiating || disabled) return;

    try {
      setIsInitiating(true);

      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
      const sanitizedReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";
      const targetUrl = new URL("/api/v1/auth/google", apiBase);
      targetUrl.searchParams.set("return_to", sanitizedReturnTo);

      // External navigation to backend OAuth service
      window.location.href = targetUrl.href;
    } catch (err) {
      setIsInitiating(false);
      onError?.(err instanceof Error ? err.message : "network_error");
    }
  };

  const buttonLabel =
    mode === "signup" ? "Sign up with Google Workspace" : "Continue with Google";

  return (
    <div className="w-full space-y-2">
      <button
        type="button"
        id="google-auth-button"
        onClick={handleGoogleAuth}
        disabled={disabled || isInitiating}
        aria-busy={isInitiating}
        aria-label={isInitiating ? "Connecting to Google Single Sign-On" : buttonLabel}
        className={`w-full relative flex items-center justify-center gap-3 py-3 px-4 rounded-xl text-sm font-medium text-white liquid-metal-button cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-[#08090A] select-none ${
          disabled || isInitiating ? "opacity-60 cursor-not-allowed" : ""
        }`}
      >
        {isInitiating ? (
          <>
            <Loader2 className="w-4 h-4 text-blue-400 animate-spin" aria-hidden="true" />
            <span className="text-slate-200 tracking-wide font-normal">
              Connecting to Google…
            </span>
          </>
        ) : (
          <>
            {/* High fidelity Google G vector mark */}
            <svg
              className="w-4 h-4 shrink-0"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                fill="#4285F4"
              />
              <path
                d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                fill="#34A853"
              />
              <path
                d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                fill="#FBBC05"
              />
              <path
                d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                fill="#EA4335"
              />
            </svg>
            <span className="tracking-normal font-medium">{buttonLabel}</span>
          </>
        )}
      </button>

      {/* Trust & Identity Assurance */}
      <div className="flex items-center justify-center gap-1.5 pt-1">
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-400/80 animate-pulse" />
        <span className="text-[11px] text-slate-400 font-mono tracking-wider uppercase">
          Google Cloud OIDC • 256-Bit TLS
        </span>
      </div>
    </div>
  );
}
