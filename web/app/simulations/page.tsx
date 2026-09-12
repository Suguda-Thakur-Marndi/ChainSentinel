"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Cpu,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { DisruptionType, SimulationResult, SimulationScenario } from "@/lib/api/types";

export default function SimulationsPage() {
  const router = useRouter();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wizard form state
  const [scenarioName, setScenarioName] = useState("");
  const [disruptionType, setDisruptionType] = useState<DisruptionType>("PORT_CLOSURE");
  const [targetNode, setTargetNode] = useState("");
  const [durationDays, setDurationDays] = useState(7);
  const [severity, setSeverity] = useState(0.8);

  const handleRunSimulation = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      // 1. Create scenario
      const scenario = await apiClient.simulation.createScenario({
        name: scenarioName || `${disruptionType} Stress Test`,
        disruptions: [
          {
            disruption_type: disruptionType,
            target_node_id: targetNode || undefined,
            duration_days: durationDays,
            severity,
          },
        ],
      });

      // 2. Execute simulation
      const result = await apiClient.simulation.run({
        scenario_id: scenario.scenario_id,
      });

      setWizardOpen(false);
      router.push(`/simulations/${result.result_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to run simulation");
      setIsSubmitting(false);
    }
  };

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                What-If Simulation Engine
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-purple-950 text-purple-300 border border-purple-800">
                  Phase 13
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic stress testing, port disruption cascades & supply-chain counterfactual modeling.
              </p>
            </div>

            <button
              onClick={() => {
                setStep(1);
                setWizardOpen(true);
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
            >
              <Play className="w-3.5 h-3.5" />
              <span>Launch New Simulation</span>
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={() => setError(null)} />}

          {/* Simulation Setup Wizard Modal */}
          {wizardOpen && (
            <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
              <div className="w-full max-w-lg rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3 mb-4">
                  <h3 className="text-sm font-bold text-white">Simulation Setup Wizard — Step {step} of 3</h3>
                  <button
                    onClick={() => setWizardOpen(false)}
                    className="text-slate-400 hover:text-slate-200 text-xs"
                  >
                    Close
                  </button>
                </div>

                {/* Step 1: Scenario Definition */}
                {step === 1 && (
                  <div className="space-y-4 text-xs">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Scenario Title</label>
                      <input
                        type="text"
                        value={scenarioName}
                        onChange={(e) => setScenarioName(e.target.value)}
                        placeholder="e.g. Red Sea Closure Q3 Shockwave"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      />
                    </div>

                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Disruption Archetype</label>
                      <select
                        value={disruptionType}
                        onChange={(e) => setDisruptionType(e.target.value as DisruptionType)}
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
                      >
                        <option value="PORT_CLOSURE">Port Closure / Berth Congestion</option>
                        <option value="SUPPLIER_OUTAGE">Supplier Plant Outage / Force Majeure</option>
                        <option value="CANAL_BLOCKAGE">Maritime Chokepoint / Canal Blockage</option>
                        <option value="WEATHER_EVENT">Extreme Weather / Typhoon</option>
                        <option value="DEMAND_SURGE">Downstream Demand Surge (+50%)</option>
                      </select>
                    </div>

                    <div className="flex justify-end pt-3 border-t border-[#243044]">
                      <button
                        onClick={() => setStep(2)}
                        className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold flex items-center gap-1"
                      >
                        Next: Parameters <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                )}

                {/* Step 2: Disruption Parameters */}
                {step === 2 && (
                  <div className="space-y-4 text-xs">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">
                        Target Node or Edge ID (Optional)
                      </label>
                      <input
                        type="text"
                        value={targetNode}
                        onChange={(e) => setTargetNode(e.target.value)}
                        placeholder="e.g. PORT-SGP or leave blank for network shock"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-slate-300 font-medium mb-1">Duration (Days)</label>
                        <input
                          type="number"
                          min="1"
                          max="90"
                          value={durationDays}
                          onChange={(e) => setDurationDays(Number(e.target.value))}
                          className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 focus:outline-none font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-slate-300 font-medium mb-1">
                          Severity (0.1 - 1.0)
                        </label>
                        <input
                          type="number"
                          step="0.1"
                          min="0.1"
                          max="1.0"
                          value={severity}
                          onChange={(e) => setSeverity(Number(e.target.value))}
                          className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 focus:outline-none font-mono"
                        />
                      </div>
                    </div>

                    <div className="flex justify-between pt-3 border-t border-[#243044]">
                      <button
                        onClick={() => setStep(1)}
                        className="px-3 py-1.5 rounded bg-slate-800 text-slate-300"
                      >
                        Back
                      </button>
                      <button
                        onClick={() => setStep(3)}
                        className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold flex items-center gap-1"
                      >
                        Review & Run <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                )}

                {/* Step 3: Confirmation */}
                {step === 3 && (
                  <div className="space-y-4 text-xs">
                    <div className="p-3 rounded bg-[#1A2332] border border-slate-800 space-y-2">
                      <div className="flex justify-between">
                        <span className="text-slate-400">Scenario:</span>
                        <span className="text-white font-semibold">
                          {scenarioName || `${disruptionType} Stress Test`}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-400">Archetype:</span>
                        <span className="text-purple-400 font-mono">{disruptionType}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-400">Target Node:</span>
                        <span className="text-slate-200 font-mono">{targetNode || "ALL CORRIDORS"}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-400">Duration / Severity:</span>
                        <span className="text-slate-200 font-mono">
                          {durationDays} days @ {(severity * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>

                    <div className="flex justify-between pt-3 border-t border-[#243044]">
                      <button
                        onClick={() => setStep(2)}
                        disabled={isSubmitting}
                        className="px-3 py-1.5 rounded bg-slate-800 text-slate-300"
                      >
                        Back
                      </button>
                      <button
                        onClick={handleRunSimulation}
                        disabled={isSubmitting}
                        className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold flex items-center gap-1.5 disabled:opacity-50"
                      >
                        <Play className="w-3.5 h-3.5" />
                        {isSubmitting ? "Executing Monte Carlo..." : "Execute Simulation"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Intro Information Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Cpu className="w-3.5 h-3.5 text-blue-400" /> Multi-Tier Propagation
              </span>
              <p className="text-xs text-slate-400 leading-relaxed">
                Evaluates multi-echelon cascading failure paths from Tier-3 sub-component suppliers down to assembly hubs.
              </p>
            </div>

            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-purple-400" /> Deterministic Constraints
              </span>
              <p className="text-xs text-slate-400 leading-relaxed">
                Strict adherence to contractual lead times, inventory safety buffers, and carrier capacity bounds.
              </p>
            </div>

            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-1.5">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-amber-400" /> Solver Handoff
              </span>
              <p className="text-xs text-slate-400 leading-relaxed">
                Simulation shock vectors feed directly into Google OR-Tools to solve optimal candidate mitigations.
              </p>
            </div>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
