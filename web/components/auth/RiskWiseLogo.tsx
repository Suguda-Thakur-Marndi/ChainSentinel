import React from "react";

interface ChainSentinelLogoProps {
  className?: string;
  size?: "sm" | "md" | "lg";
  showSubtitle?: boolean;
}

export function ChainSentinelLogo({
  className = "",
  size = "md",
  showSubtitle = true,
}: ChainSentinelLogoProps) {
  const iconSizes = {
    sm: "w-9 h-9",
    md: "w-12 h-12",
    lg: "w-16 h-16",
  };

  const titleSizes = {
    sm: "text-lg",
    md: "text-2xl",
    lg: "text-3xl",
  };

  return (
    <div className={`flex flex-col items-center gap-3.5 select-none ${className}`}>
      {/* Sentinel Emblem with Cyber Glow & Liquid Metal Sheen */}
      <div className="relative group cursor-pointer">
        <div className="absolute -inset-2 rounded-2xl bg-gradient-to-tr from-cyan-500/25 via-blue-600/20 to-indigo-600/25 blur-lg opacity-80 group-hover:opacity-100 transition-all duration-300 group-hover:scale-105" />
        <div
          className={`relative ${iconSizes[size]} rounded-2xl bg-gradient-to-b from-[#1C2430] via-[#10151E] to-[#0A0D13] p-[1.5px] shadow-2xl ring-1 ring-cyan-500/30 flex items-center justify-center transition-transform duration-300 group-hover:scale-[1.02]`}
        >
          <div className="w-full h-full rounded-[14px] bg-[#070A0F] flex items-center justify-center overflow-hidden relative">
            {/* Subtle background radar grid */}
            <div className="absolute inset-0 bg-[radial-gradient(#38bdf812_1px,transparent_1px)] [background-size:8px_8px] pointer-events-none" />

            <svg
              viewBox="0 0 40 40"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              className="w-3/5 h-3/5 relative z-10 drop-shadow-[0_0_8px_rgba(56,189,248,0.4)]"
              aria-hidden="true"
            >
              <defs>
                <linearGradient id="cs-glow" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#38BDF8" stopOpacity="0.95" />
                  <stop offset="0.5" stopColor="#818CF8" stopOpacity="0.75" />
                  <stop offset="1" stopColor="#06B6D4" stopOpacity="0.3" />
                </linearGradient>
                <linearGradient id="cs-core" x1="12" y1="12" x2="28" y2="28" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#22D3EE" />
                  <stop offset="1" stopColor="#6366F1" />
                </linearGradient>
              </defs>

              {/* Sentinel Hexagonal Defense Shield */}
              <path
                d="M20 3L35 9.5V20C35 28.5 28.6 35.8 20 38C11.4 35.8 5 28.5 5 20V9.5L20 3Z"
                stroke="url(#cs-glow)"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />

              {/* Internal Surveillance Radar Ring */}
              <circle
                cx="20"
                cy="20"
                r="9.5"
                stroke="#38BDF8"
                strokeWidth="1.2"
                strokeDasharray="2.5 2.5"
                opacity="0.5"
              />

              {/* Interconnected Chain Links */}
              <path
                d="M15 16C15 13.8 16.8 12 19 12H21C23.2 12 25 13.8 25 16V24C25 26.2 23.2 28 21 28H19C16.8 28 15 26.2 15 24"
                stroke="url(#cs-core)"
                strokeWidth="2.2"
                strokeLinecap="round"
              />

              {/* Central Pulsing Sentinel Node */}
              <circle cx="20" cy="20" r="2.5" fill="#38BDF8" />
              <circle cx="20" cy="20" r="4" stroke="#38BDF8" strokeWidth="0.8" opacity="0.6" />

              {/* Telemetry Sensor Vertices */}
              <circle cx="20" cy="6.5" r="1.5" fill="#38BDF8" />
              <circle cx="31.5" cy="20" r="1.5" fill="#818CF8" />
              <circle cx="8.5" cy="20" r="1.5" fill="#818CF8" />
            </svg>
          </div>
        </div>
      </div>

      {/* Brand Typography in Full Capital Styling */}
      <div className="text-center space-y-1">
        <div className="flex items-center justify-center gap-1.5 flex-wrap">
          <div className="flex items-center tracking-[0.16em]">
            <span className={`font-black text-white ${titleSizes[size]}`}>
              CHAIN
            </span>
            <span
              className={`font-black text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-sky-400 to-indigo-400 ${titleSizes[size]}`}
            >
              SENTINEL
            </span>
          </div>
          <span className="ml-1 px-1.5 py-0.5 text-[9px] uppercase font-mono font-bold tracking-widest bg-cyan-500/10 text-cyan-300 border border-cyan-500/25 rounded shadow-[0_0_10px_rgba(6,182,212,0.15)]">
            AUTONOMOUS
          </span>
        </div>

        {showSubtitle && (
          <div className="flex flex-col items-center gap-1">
            <p className="text-xs text-slate-400 font-medium tracking-wide">
              Autonomous Supply Chain Risk Intelligence & Defense
            </p>
            <div className="flex items-center gap-1.5 pt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_rgba(52,211,153,0.8)]" />
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400">
                DEFENSE GRID ONLINE
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Backwards-compatibility alias
export const RiskWiseLogo = ChainSentinelLogo;
