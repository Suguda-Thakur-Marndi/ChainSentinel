import React from "react";

interface RiskWiseLogoProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function RiskWiseLogo({ className = "", size = "md" }: RiskWiseLogoProps) {
  const iconSizes = {
    sm: "w-8 h-8",
    md: "w-11 h-11",
    lg: "w-14 h-14",
  };

  const titleSizes = {
    sm: "text-lg",
    md: "text-2xl",
    lg: "text-3xl",
  };

  return (
    <div className={`flex flex-col items-center gap-3 ${className}`}>
      {/* Brand Icon with Liquid Metal Sheen */}
      <div className="relative group">
        <div className="absolute -inset-1.5 rounded-2xl bg-gradient-to-b from-blue-500/20 via-blue-600/10 to-transparent blur-md opacity-75 group-hover:opacity-100 transition-opacity" />
        <div
          className={`relative ${iconSizes[size]} rounded-xl bg-gradient-to-b from-[#1E232B] to-[#0E1116] p-[1px] shadow-2xl ring-1 ring-white/10 flex items-center justify-center`}
        >
          <div className="w-full h-full rounded-[11px] bg-[#0A0D11] flex items-center justify-center overflow-hidden">
            <svg
              viewBox="0 0 32 32"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="w-3/5 h-3/5 text-blue-400"
              aria-hidden="true"
            >
              <defs>
                <linearGradient id="rw-gradient" x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#60A5FA" />
                  <stop offset="0.5" stopColor="#3B82F6" />
                  <stop offset="1" stopColor="#1D4ED8" />
                </linearGradient>
                <linearGradient id="rw-sheen" x1="0" y1="0" x2="32" y2="32" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#93C5FD" stopOpacity="0.8" />
                  <stop offset="1" stopColor="#3B82F6" stopOpacity="0.2" />
                </linearGradient>
              </defs>
              {/* Outer Risk Shield Geometry */}
              <path
                d="M16 3L27 7.5V15.5C27 22.2 22.3 28.3 16 30C9.7 28.3 5 22.2 5 15.5V7.5L16 3Z"
                stroke="url(#rw-sheen)"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {/* Network Graph Risk Nodes */}
              <circle cx="16" cy="11" r="2" fill="#60A5FA" />
              <circle cx="11" cy="19" r="2" fill="#3B82F6" />
              <circle cx="21" cy="19" r="2" fill="#3B82F6" />
              {/* Intelligent Vector Links */}
              <path
                d="M16 11L11 19M16 11L21 19M11 19H21"
                stroke="url(#rw-gradient)"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>
      </div>

      {/* Brand Typography */}
      <div className="text-center">
        <div className="flex items-center justify-center gap-1.5">
          <span className={`font-semibold tracking-tight text-white ${titleSizes[size]}`}>
            Risk
          </span>
          <span
            className={`font-serif italic font-normal tracking-wide text-blue-400 ${titleSizes[size]}`}
            style={{ fontFamily: "var(--font-serif)" }}
          >
            Wise
          </span>
          <span className="ml-1.5 px-1.5 py-0.5 text-[10px] uppercase font-mono tracking-widest bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded">
            2.0
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-400 font-medium tracking-wide">
          Supply Chain Risk Intelligence Platform
        </p>
      </div>
    </div>
  );
}
