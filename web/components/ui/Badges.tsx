"use client";

import React from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Clock,
  HelpCircle,
  Info,
  Shield,
  ShieldAlert,
  ShieldCheck,
  XCircle,
  Zap,
  Activity,
} from "lucide-react";
import type {
  EvidenceSourcePrecedence,
  OptimizationStatus,
  RiskSeverity,
  Role,
  VerificationStatus,
} from "@/lib/api/types";

// =========================================================================
// RISK BADGE (icon + text + color)
// =========================================================================
export function RiskBadge({
  severity,
  score,
  className = "",
}: {
  severity?: RiskSeverity | string;
  score?: number | null;
  className?: string;
}) {
  const norm = (severity || "INFORMATIONAL").toUpperCase();

  let colors = "bg-slate-800/80 text-slate-300 border-slate-700";
  let Icon = Info;

  if (norm === "CRITICAL") {
    colors = "bg-rose-950/50 text-rose-300 border-rose-800/60";
    Icon = AlertCircle;
  } else if (norm === "HIGH") {
    colors = "bg-orange-950/50 text-orange-300 border-orange-800/60";
    Icon = AlertTriangle;
  } else if (norm === "MEDIUM") {
    colors = "bg-amber-950/50 text-amber-300 border-amber-800/60";
    Icon = Activity;
  } else if (norm === "LOW") {
    colors = "bg-emerald-950/50 text-emerald-300 border-emerald-800/60";
    Icon = CheckCircle2;
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border font-mono-tnum ${colors} ${className}`}
      title={score !== undefined && score !== null ? `Score: ${score}/100` : norm}
    >
      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
      <span>{norm}</span>
      {score !== undefined && score !== null && (
        <span className="opacity-75 font-mono text-[11px]">({Math.round(score)})</span>
      )}
    </span>
  );
}

// =========================================================================
// EVIDENCE BADGE (REAL > ESTIMATED > SIMULATED)
// =========================================================================
export function EvidenceBadge({
  source,
  className = "",
}: {
  source?: EvidenceSourcePrecedence | string;
  className?: string;
}) {
  const norm = (source || "REAL").toUpperCase();

  if (norm === "REAL") {
    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/40 text-emerald-300 border border-emerald-700/60 ${className}`}
        title="Authoritative physical ground-truth observation"
      >
        <ShieldCheck className="w-3.5 h-3.5" />
        <span>REAL</span>
      </span>
    );
  }

  if (norm === "ESTIMATED") {
    return (
      <span
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium bg-amber-950/40 text-amber-300 border border-dashed border-amber-600/70 ${className}`}
        title="Derived or interpolated approximation"
      >
        <Activity className="w-3.5 h-3.5" />
        <span>ESTIMATED</span>
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium bg-purple-950/40 text-purple-300 border border-dotted border-purple-600/70 ${className}`}
      title="Synthesized counterfactual model simulation"
    >
      <Zap className="w-3.5 h-3.5" />
      <span>SIMULATED</span>
    </span>
  );
}

// =========================================================================
// VERIFICATION BADGE
// =========================================================================
export function VerificationBadge({
  status,
  className = "",
}: {
  status?: VerificationStatus | string;
  className?: string;
}) {
  const norm = (status || "PENDING").toUpperCase();

  let colors = "bg-slate-800 text-slate-300 border-slate-700";
  let Icon = Clock;

  switch (norm) {
    case "VERIFIED":
      colors = "bg-emerald-950/50 text-emerald-300 border-emerald-700/60";
      Icon = CheckCircle2;
      break;
    case "PARTIALLY_VERIFIED":
      colors = "bg-amber-950/50 text-amber-300 border-amber-700/60";
      Icon = AlertTriangle;
      break;
    case "FAILED":
      colors = "bg-rose-950/50 text-rose-300 border-rose-800/60";
      Icon = XCircle;
      break;
    case "CONFLICT":
      colors = "bg-orange-950/50 text-orange-300 border-orange-800/60";
      Icon = AlertCircle;
      break;
    case "EXPIRED":
    case "INSUFFICIENT_EVIDENCE":
    case "NOT_APPLICABLE":
      colors = "bg-slate-900 text-slate-400 border-slate-700";
      Icon = HelpCircle;
      break;
    case "PENDING":
    default:
      colors = "bg-blue-950/50 text-blue-300 border-blue-800/60";
      Icon = Clock;
      break;
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border font-mono-tnum ${colors} ${className}`}
    >
      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
      <span>{norm.replace(/_/g, " ")}</span>
    </span>
  );
}

// =========================================================================
// OPTIMIZATION STATUS BADGE (Never render FEASIBLE as OPTIMAL)
// =========================================================================
export function OptimizationStatusBadge({
  status,
  className = "",
}: {
  status?: OptimizationStatus | string;
  className?: string;
}) {
  const norm = (status || "NOT_AVAILABLE").toUpperCase();

  let colors = "bg-slate-800 text-slate-300 border-slate-700";
  let Icon = Clock;

  if (norm === "OPTIMAL") {
    colors = "bg-emerald-950/50 text-emerald-300 border-emerald-700/60";
    Icon = CheckCircle2;
  } else if (norm === "FEASIBLE") {
    colors = "bg-blue-950/50 text-blue-300 border-blue-700/60";
    Icon = Activity;
  } else if (norm === "INFEASIBLE") {
    colors = "bg-rose-950/50 text-rose-300 border-rose-800/60";
    Icon = XCircle;
  } else if (norm === "TIME_LIMIT") {
    colors = "bg-amber-950/50 text-amber-300 border-amber-700/60";
    Icon = Clock;
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border font-mono-tnum ${colors} ${className}`}
    >
      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
      <span>{norm.replace(/_/g, " ")}</span>
    </span>
  );
}

// =========================================================================
// ROLE BADGE
// =========================================================================
export function RoleBadge({ role, className = "" }: { role?: Role | string; className?: string }) {
  const r = role || "Viewer";
  let badgeColor = "bg-slate-800 text-slate-300 border-slate-700";

  if (r === "Admin") badgeColor = "bg-purple-950/60 text-purple-300 border-purple-700/60";
  else if (r === "RiskManager") badgeColor = "bg-rose-950/60 text-rose-300 border-rose-700/60";
  else if (r === "OpsManager") badgeColor = "bg-amber-950/60 text-amber-300 border-amber-700/60";
  else if (r === "Analyst") badgeColor = "bg-blue-950/60 text-blue-300 border-blue-700/60";

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold border ${badgeColor} ${className}`}
    >
      <Shield className="w-3 h-3" />
      <span>{r}</span>
    </span>
  );
}

// =========================================================================
// GENERAL STATUS BADGE
// =========================================================================
export function StatusBadge({
  status,
  variant = "neutral",
  className = "",
}: {
  status: string;
  variant?: "success" | "warning" | "error" | "info" | "neutral";
  className?: string;
}) {
  let colors = "bg-slate-800 text-slate-300 border-slate-700";
  let Icon = Info;

  switch (variant) {
    case "success":
      colors = "bg-emerald-950/50 text-emerald-300 border-emerald-700/60";
      Icon = CheckCircle2;
      break;
    case "warning":
      colors = "bg-amber-950/50 text-amber-300 border-amber-700/60";
      Icon = AlertTriangle;
      break;
    case "error":
      colors = "bg-rose-950/50 text-rose-300 border-rose-800/60";
      Icon = XCircle;
      break;
    case "info":
      colors = "bg-blue-950/50 text-blue-300 border-blue-800/60";
      Icon = Info;
      break;
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium border font-mono-tnum ${colors} ${className}`}
    >
      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
      <span>{status.replace(/_/g, " ")}</span>
    </span>
  );
}
