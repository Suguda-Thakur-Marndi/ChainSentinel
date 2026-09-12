"use client";

import React from "react";
import { AlertCircle, AlertTriangle, Inbox, Loader2, Lock, RefreshCw } from "lucide-react";

export function LoadingState({
  message = "Loading operational telemetry...",
  className = "",
}: {
  message?: string;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-16 px-4 text-center ${className}`}
      role="status"
      aria-live="polite"
    >
      <Loader2 className="w-8 h-8 text-blue-500 animate-spin mb-3" />
      <p className="text-sm font-medium text-slate-300">{message}</p>
      <span className="text-xs text-slate-500 mt-1">Connecting to authoritative backend...</span>
    </div>
  );
}

export function EmptyState({
  title = "No records found",
  message = "No operational data matches your current filters or query.",
  icon: Icon = Inbox,
  action,
  className = "",
}: {
  title?: string;
  message?: string;
  icon?: React.ElementType;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-16 px-4 text-center rounded-lg border border-dashed border-slate-800 bg-slate-900/30 ${className}`}
    >
      <div className="w-12 h-12 rounded-full bg-slate-800/80 border border-slate-700/60 flex items-center justify-center text-slate-400 mb-3">
        <Icon className="w-6 h-6" />
      </div>
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <p className="text-xs text-slate-400 max-w-sm mt-1 mb-4">{message}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  title = "Telemetry Synchronization Error",
  message = "Unable to load data from backend services. Please retry.",
  onRetry,
  className = "",
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-14 px-4 text-center rounded-lg border border-rose-900/40 bg-rose-950/20 ${className}`}
      role="alert"
    >
      <div className="w-12 h-12 rounded-full bg-rose-900/30 border border-rose-800/60 flex items-center justify-center text-rose-400 mb-3">
        <AlertTriangle className="w-6 h-6" />
      </div>
      <h3 className="text-sm font-semibold text-rose-200">{title}</h3>
      <p className="text-xs text-slate-300 max-w-md mt-1 mb-4">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Retry Request</span>
        </button>
      )}
    </div>
  );
}

export function ForbiddenState({
  requiredRole = "RiskManager or Admin",
  message = "Your current account role does not have authorization to access this operational subsystem.",
  className = "",
}: {
  requiredRole?: string;
  message?: string;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center py-16 px-4 text-center rounded-lg border border-amber-900/40 bg-amber-950/20 ${className}`}
      role="alert"
    >
      <div className="w-12 h-12 rounded-full bg-amber-900/30 border border-amber-800/60 flex items-center justify-center text-amber-400 mb-3">
        <Lock className="w-6 h-6" />
      </div>
      <h3 className="text-sm font-semibold text-amber-200">Access Restricted</h3>
      <p className="text-xs text-slate-300 max-w-sm mt-1">{message}</p>
      <p className="text-xs font-mono text-amber-400 mt-2">Required Role: {requiredRole}</p>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse bg-slate-800/60 rounded ${className}`} />;
}
