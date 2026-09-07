"use client";

import React, { useRef } from "react";

export type AuthMode = "signin" | "signup";

interface AuthModeSwitchProps {
  mode: AuthMode;
  onChange: (mode: AuthMode) => void;
  disabled?: boolean;
}

export function AuthModeSwitch({ mode, onChange, disabled = false }: AuthModeSwitchProps) {
  const signinRef = useRef<HTMLButtonElement>(null);
  const signupRef = useRef<HTMLButtonElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const nextMode: AuthMode = mode === "signin" ? "signup" : "signin";
      onChange(nextMode);
      if (nextMode === "signin") {
        signinRef.current?.focus();
      } else {
        signupRef.current?.focus();
      }
    }
  };

  return (
    <div className="w-full space-y-3">
      {/* Tab Switcher */}
      <div
        role="tablist"
        aria-label="Authentication Mode"
        className="grid grid-cols-2 p-1 rounded-xl bg-[#090C10] border border-white/[0.08] relative"
      >
        <button
          ref={signinRef}
          role="tab"
          type="button"
          id="tab-signin"
          aria-selected={mode === "signin"}
          aria-controls="panel-signin"
          tabIndex={mode === "signin" ? 0 : -1}
          disabled={disabled}
          onClick={() => onChange("signin")}
          onKeyDown={handleKeyDown}
          className={`py-2 px-3 text-xs font-medium rounded-lg transition-all duration-150 relative cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 focus-visible:ring-offset-[#08090A] ${
            mode === "signin"
              ? "text-white bg-[#1A1E26] shadow-sm border border-white/10 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          Sign In
        </button>

        <button
          ref={signupRef}
          role="tab"
          type="button"
          id="tab-signup"
          aria-selected={mode === "signup"}
          aria-controls="panel-signup"
          tabIndex={mode === "signup" ? 0 : -1}
          disabled={disabled}
          onClick={() => onChange("signup")}
          onKeyDown={handleKeyDown}
          className={`py-2 px-3 text-xs font-medium rounded-lg transition-all duration-150 relative cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 focus-visible:ring-offset-[#08090A] ${
            mode === "signup"
              ? "text-white bg-[#1A1E26] shadow-sm border border-white/10 font-semibold"
              : "text-slate-400 hover:text-slate-200"
          } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
        >
          Sign Up
        </button>
      </div>

      {/* Mode Context Description */}
      <div className="text-center px-1">
        <p className="text-xs text-slate-400 leading-relaxed font-normal">
          {mode === "signin" ? (
            <span>
              Sign in with your enterprise Google account to access your RiskWise intelligence workspace.
            </span>
          ) : (
            <span>
              Provision a new organization tenant or join your team using Google Workspace SSO.
            </span>
          )}
        </p>
      </div>
    </div>
  );
}
