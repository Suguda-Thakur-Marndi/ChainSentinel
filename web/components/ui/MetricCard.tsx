"use client";

import React from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { NumberTicker } from "./MagicComponents";

export function MetricCard({
  title,
  value,
  subtext,
  trend,
  trendDirection,
  icon: Icon,
  variant = "default",
  className = "",
}: {
  title: string;
  value: string | number;
  subtext?: string;
  trend?: string | null;
  trendDirection?: "up" | "down" | "neutral";
  icon?: React.ElementType;
  variant?: "default" | "critical" | "warning" | "success" | "orange";
  className?: string;
}) {
  let borderStyle = "border-arch";
  let valueColor = "text-foreground";
  let accentBar = "";

  if (variant === "critical") {
    borderStyle = "border-rose-900/40 bg-gradient-to-b from-card to-rose-950/20";
    valueColor = "text-[#B71C1C]";
    accentBar = "border-t-2 border-[#B71C1C]";
  } else if (variant === "warning") {
    borderStyle = "border-amber-900/40 bg-gradient-to-b from-card to-amber-950/20";
    valueColor = "text-[#E88D00]";
    accentBar = "border-t-2 border-[#E88D00]";
  } else if (variant === "success") {
    borderStyle = "border-emerald-900/40 bg-gradient-to-b from-card to-emerald-950/20";
    valueColor = "text-[#0A7A75]";
    accentBar = "border-t-2 border-[#0A7A75]";
  } else if (variant === "orange") {
    borderStyle = "border-[#D95E00]/40 bg-gradient-to-b from-card to-[#D95E00]/10";
    valueColor = "text-[#D95E00]";
    accentBar = "border-t-2 border-[#D95E00]";
  }

  // If value is numeric, we can use NumberTicker or display directly
  const numericValue = typeof value === "number" ? value : parseFloat(String(value));
  const isPlainNumber = !isNaN(numericValue) && String(numericValue) === String(value).trim();

  return (
    <div
      className={`p-4 rounded-lg border flex flex-col justify-between transition-all duration-150 hover:border-[#D95E00]/50 shadow-arch-sm ${accentBar} ${borderStyle} ${className}`}
      style={{
        backgroundColor: "var(--bg-card)",
        borderColor: variant === "default" ? "var(--border-arch)" : undefined,
      }}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[11px] font-mono font-bold tracking-wider text-muted-foreground uppercase">
          {title}
        </span>
        {Icon && (
          <div className="p-1.5 rounded bg-surface border border-arch text-muted-foreground">
            <Icon className="w-3.5 h-3.5" />
          </div>
        )}
      </div>

      <div className="flex items-baseline gap-2 mb-1">
        {isPlainNumber ? (
          <NumberTicker
            value={numericValue}
            className={`text-2xl font-bold tracking-tight ${valueColor}`}
          />
        ) : (
          <span className={`text-2xl font-bold font-mono-tnum tracking-tight ${valueColor}`}>
            {value}
          </span>
        )}
      </div>

      <div
        className="flex items-center justify-between text-xs text-muted-foreground pt-2 border-t mt-2 font-mono"
        style={{ borderColor: "var(--border-arch)" }}
      >
        {trend ? (
          <div className="flex items-center gap-1 font-mono-tnum text-[11px]">
            {trendDirection === "up" && <ArrowUpRight className="w-3.5 h-3.5 text-[#B71C1C]" />}
            {trendDirection === "down" && <ArrowDownRight className="w-3.5 h-3.5 text-[#0A7A75]" />}
            {trendDirection === "neutral" && <Minus className="w-3.5 h-3.5 text-muted-foreground" />}
            <span
              className={
                trendDirection === "up"
                  ? "text-[#B71C1C] font-semibold"
                  : trendDirection === "down"
                  ? "text-[#0A7A75] font-semibold"
                  : "text-muted-foreground"
              }
            >
              {trend}
            </span>
          </div>
        ) : (
          <span className="text-[11px] text-muted-foreground/70 italic">Authoritative Telemetry</span>
        )}
        {subtext && <span className="text-[11px] text-muted-foreground truncate">{subtext}</span>}
      </div>
    </div>
  );
}
