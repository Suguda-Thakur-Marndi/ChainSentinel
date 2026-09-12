"use client";

import React from "react";
import {
  ChevronRight,
  Database,
  AlertOctagon,
  Network,
  Cpu,
  Sliders,
  Scale,
  UserCheck,
  Zap,
  ShieldCheck,
} from "lucide-react";

export interface PipelineStageCounts {
  ingestion: number;
  risk: number;
  twin: number;
  simulation: number;
  optimization: number;
  decision: number;
  approval: number;
  action: number;
  verification: number;
}

export function OperationalPipeline({
  counts,
  className = "",
}: {
  counts?: PipelineStageCounts;
  className?: string;
}) {
  const stages = [
    { key: "ingestion", label: "Ingestion", icon: Database, count: counts?.ingestion ?? 0 },
    { key: "risk", label: "Risk Engine", icon: AlertOctagon, count: counts?.risk ?? 0 },
    { key: "twin", label: "Digital Twin", icon: Network, count: counts?.twin ?? 0 },
    { key: "simulation", label: "Simulation", icon: Cpu, count: counts?.simulation ?? 0 },
    { key: "optimization", label: "Optimization", icon: Sliders, count: counts?.optimization ?? 0 },
    { key: "decision", label: "Decision", icon: Scale, count: counts?.decision ?? 0 },
    { key: "approval", label: "Approval", icon: UserCheck, count: counts?.approval ?? 0 },
    { key: "action", label: "Action Dispatch", icon: Zap, count: counts?.action ?? 0 },
    { key: "verification", label: "Verification", icon: ShieldCheck, count: counts?.verification ?? 0 },
  ];

  return (
    <div className={`p-4 rounded-lg bg-[#111827] border border-[#243044] ${className}`}>
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
          Autonomous Operational Execution Pipeline
        </h4>
        <span className="text-[11px] font-mono text-slate-500">Live Stage Telemetry</span>
      </div>

      <div className="flex items-center gap-1.5 overflow-x-auto pb-2 scrollbar-none">
        {stages.map((stage, idx) => {
          const Icon = stage.icon;
          const isLast = idx === stages.length - 1;

          return (
            <React.Fragment key={stage.key}>
              <div className="flex-1 min-w-[100px] p-2.5 rounded bg-[#1A2332]/80 border border-slate-800 flex flex-col items-center justify-center text-center transition-all hover:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-400 mb-1">
                  <Icon className="w-3.5 h-3.5" />
                  <span className="text-[11px] font-medium truncate">{stage.label}</span>
                </div>
                <span className="text-base font-bold font-mono-tnum text-slate-100">
                  {stage.count}
                </span>
              </div>
              {!isLast && (
                <ChevronRight className="w-3.5 h-3.5 text-slate-600 flex-shrink-0" />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}
