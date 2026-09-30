"use client";

import React, { useEffect, useState } from "react";

/**
 * Magic UI: BorderBeam
 * Animated border beam of light that tracks along the border of a card.
 */
export function BorderBeam({
  size = 180,
  duration = 8,
  anchor = 90,
  borderWidth = 1.5,
  colorFrom = "#D95E00",
  colorTo = "#0A7A75",
  delay = 0,
  className = "",
}: {
  size?: number;
  duration?: number;
  anchor?: number;
  borderWidth?: number;
  colorFrom?: string;
  colorTo?: string;
  delay?: number;
  className?: string;
}) {
  return (
    <div
      style={
        {
          "--size": size,
          "--duration": duration,
          "--anchor": anchor,
          "--border-width": borderWidth,
          "--color-from": colorFrom,
          "--color-to": colorTo,
          "--delay": `-${delay}s`,
        } as React.CSSProperties
      }
      className={`pointer-events-none absolute inset-0 rounded-[inherit] [border:calc(var(--border-width)*1px)_solid_transparent] ![mask-clip:padding-box,border-box] ![mask-composite:intersect] [mask:linear-gradient(transparent,transparent),linear-gradient(white,white)] after:absolute after:aspect-square after:w-[calc(var(--size)*1px)] after:animate-[borderBeamSweep_var(--duration)s_linear_infinite] after:[animation-delay:var(--delay)] after:[background:linear-gradient(to_left,var(--color-from),var(--color-to),transparent)] after:[offset-anchor:calc(var(--anchor)*1%)_50%] after:[offset-path:rect(0_auto_auto_0_round_calc(var(--size)*1px))] ${className}`}
    />
  );
}

/**
 * Magic UI: NumberTicker
 * Animated count-up component for financial, metric, and telemetry figures.
 */
export function NumberTicker({
  value,
  direction = "up",
  delay = 0,
  decimalPlaces = 0,
  prefix = "",
  suffix = "",
  className = "",
}: {
  value: number;
  direction?: "up" | "down";
  delay?: number;
  decimalPlaces?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
}) {
  const [displayValue, setDisplayValue] = useState(direction === "down" ? value : 0);

  useEffect(() => {
    let startTimestamp: number | null = null;
    const duration = 1200; // ms
    let frameId: number;

    const startValue = direction === "down" ? value * 1.5 : 0;
    const endValue = value;

    const step = (timestamp: number) => {
      if (!startTimestamp) startTimestamp = timestamp;
      const progress = Math.min((timestamp - startTimestamp) / duration, 1);
      // Ease out cubic
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      const current = startValue + (endValue - startValue) * easeProgress;

      setDisplayValue(current);

      if (progress < 1) {
        frameId = requestAnimationFrame(step);
      } else {
        setDisplayValue(endValue);
      }
    };

    const timeout = setTimeout(() => {
      frameId = requestAnimationFrame(step);
    }, delay * 1000);

    return () => {
      clearTimeout(timeout);
      cancelAnimationFrame(frameId);
    };
  }, [value, direction, delay]);

  return (
    <span className={`font-mono-tnum tracking-tight ${className}`}>
      {prefix}
      {displayValue.toLocaleString(undefined, {
        minimumFractionDigits: decimalPlaces,
        maximumFractionDigits: decimalPlaces,
      })}
      {suffix}
    </span>
  );
}

/**
 * Magic UI: GlowBadge
 * Subtle glowing pill badge for live operational status.
 */
export function GlowBadge({
  children,
  color = "#D95E00",
  pulse = true,
}: {
  children: React.ReactNode;
  color?: string;
  pulse?: boolean;
}) {
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-mono font-medium border"
      style={{
        borderColor: `${color}40`,
        backgroundColor: `${color}12`,
        color: color,
      }}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${pulse ? "animate-pulse" : ""}`}
        style={{ backgroundColor: color }}
      />
      {children}
    </span>
  );
}
