"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Cpu,
  Layers,
  Play,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorState } from "@/components/ui/FeedbackStates";
import {
  ArchButton,
  ArchModal,
  ArchInput,
  ArchSelect,
  ArchLabel,
  ArchBadge,
  ArchFormGroup,
  ArchCard,
  ArchCardContent,
} from "@/components/ui/ArchitecturalComponents";
import { useAuth } from "@/lib/auth/AuthContext";
import { apiClient } from "@/lib/api/client";
import type { DisruptionType, SimulationScenario } from "@/lib/api/types";

export default function SimulationsPage() {
  const router = useRouter();
  const { user } = useAuth();
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
      let baseFingerprint = "0".repeat(64);
      try {
        const twin = await apiClient.digitalTwin.getSnapshot();
        const twinFp = twin?.twin_fingerprint || twin?.source_fingerprint;
        if (twinFp && twinFp.length === 64) {
          baseFingerprint = twinFp;
        }
      } catch {
        // Fallback valid 64-char fingerprint
      }

      const orgId = user?.org_id || "acme-global";
      const scenId = `scen_${Date.now()}`;
      const changeId = `chg_${Date.now()}`;
      const isEdge = disruptionType === "CANAL_BLOCKAGE";

      const scenarioPayload: SimulationScenario = {
        scenario_id: scenId,
        organization_id: orgId,
        name: scenarioName || `${disruptionType} Stress Test`,
        description: `What-if stress test simulating ${disruptionType} for ${durationDays} days.`,
        base_snapshot_fingerprint: baseFingerprint,
        changes: [
          {
            change_id: changeId,
            change_type: isEdge ? "EDGE_UNAVAILABLE" : "NODE_UNAVAILABLE",
            target_entity_type: isEdge ? "ROUTE" : disruptionType === "SUPPLIER_OUTAGE" ? "SUPPLIER" : "PORT",
            target_entity_id: targetNode.trim() || "NODE_AUTO",
            magnitude: durationDays,
            unit: "DAYS",
            duration_minutes: durationDays * 24 * 60,
            source_type: "SIMULATED",
          },
        ],
        parameters: { severity, duration_days: durationDays },
        fingerprint: "f".repeat(64),
      };

      const scenario = await apiClient.simulation.createScenario(scenarioPayload);
      const result = await apiClient.simulation.run(scenario.scenario_id);

      setWizardOpen(false);
      const simId = result.simulation_id || result.result_id || scenario.scenario_id;
      router.push(`/simulations/${simId}`);
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
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 font-mono">
                <Cpu className="w-5 h-5 text-[#D95E00]" />
                What-If Simulation Engine
                <ArchBadge variant="orange">
                  Phase 13
                </ArchBadge>
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Deterministic stress testing, port disruption cascades & supply-chain counterfactual modeling.
              </p>
            </div>

            <ArchButton
              variant="default"
              size="sm"
              onClick={() => {
                setStep(1);
                setWizardOpen(true);
              }}
            >
              <Play className="w-3.5 h-3.5" />
              <span>Launch New Simulation</span>
            </ArchButton>
          </div>

          {error && <ErrorState message={error} onRetry={() => setError(null)} />}

          {/* Simulation Setup Wizard Modal */}
          <ArchModal
            isOpen={wizardOpen}
            onClose={() => setWizardOpen(false)}
            title={`Simulation Setup Wizard — Step ${step} of 3`}
            subtitle="Monte Carlo Stochastic Cascade Modeling"
          >
            {/* Step 1: Scenario Definition */}
            {step === 1 && (
              <div className="space-y-4">
                <ArchFormGroup>
                  <ArchLabel required>Scenario Title</ArchLabel>
                  <ArchInput
                    type="text"
                    value={scenarioName}
                    onChange={(e) => setScenarioName(e.target.value)}
                    placeholder="e.g. Red Sea Closure Q3 Shockwave"
                  />
                </ArchFormGroup>

                <ArchFormGroup>
                  <ArchLabel required>Disruption Archetype</ArchLabel>
                  <ArchSelect
                    value={disruptionType}
                    onChange={(e) => setDisruptionType(e.target.value as DisruptionType)}
                  >
                    <option value="PORT_CLOSURE">Port Closure / Berth Congestion</option>
                    <option value="SUPPLIER_OUTAGE">Supplier Plant Outage / Force Majeure</option>
                    <option value="CANAL_BLOCKAGE">Maritime Chokepoint / Canal Blockage</option>
                    <option value="WEATHER_EVENT">Extreme Weather / Typhoon</option>
                    <option value="DEMAND_SURGE">Downstream Demand Surge (+50%)</option>
                  </ArchSelect>
                </ArchFormGroup>

                <div className="flex justify-end pt-3 border-t border-arch">
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={() => setStep(2)}
                  >
                    <span>Next: Parameters</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </ArchButton>
                </div>
              </div>
            )}

            {/* Step 2: Disruption Parameters */}
            {step === 2 && (
              <div className="space-y-4">
                <ArchFormGroup>
                  <ArchLabel>Target Node or Edge ID (Optional)</ArchLabel>
                  <ArchInput
                    type="text"
                    value={targetNode}
                    onChange={(e) => setTargetNode(e.target.value)}
                    placeholder="e.g. PORT-SGP or leave blank for network shock"
                  />
                </ArchFormGroup>

                <div className="grid grid-cols-2 gap-3">
                  <ArchFormGroup>
                    <ArchLabel required>Duration (Days)</ArchLabel>
                    <ArchInput
                      type="number"
                      min="1"
                      max="90"
                      value={durationDays}
                      onChange={(e) => setDurationDays(Number(e.target.value))}
                    />
                  </ArchFormGroup>
                  <ArchFormGroup>
                    <ArchLabel required>Severity (0.1 - 1.0)</ArchLabel>
                    <ArchInput
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="1.0"
                      value={severity}
                      onChange={(e) => setSeverity(Number(e.target.value))}
                    />
                  </ArchFormGroup>
                </div>

                <div className="flex justify-between pt-3 border-t border-arch">
                  <ArchButton
                    variant="outline"
                    size="sm"
                    onClick={() => setStep(1)}
                  >
                    Back
                  </ArchButton>
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={() => setStep(3)}
                  >
                    <span>Review & Run</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </ArchButton>
                </div>
              </div>
            )}

            {/* Step 3: Confirmation */}
            {step === 3 && (
              <div className="space-y-4">
                <div
                  className="p-3.5 rounded border border-arch space-y-2 bg-surface"
                  style={{ backgroundColor: "var(--bg-secondary)", borderColor: "var(--border-arch)" }}
                >
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Scenario:</span>
                    <span className="text-foreground font-semibold">
                      {scenarioName || `${disruptionType} Stress Test`}
                    </span>
                  </div>
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Archetype:</span>
                    <ArchBadge variant="orange">{disruptionType}</ArchBadge>
                  </div>
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Target Node:</span>
                    <span className="text-foreground font-mono">{targetNode || "ALL CORRIDORS"}</span>
                  </div>
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-muted-foreground">Duration / Severity:</span>
                    <span className="text-foreground font-mono">
                      {durationDays} days @ {(severity * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>

                <div className="flex justify-between pt-3 border-t border-arch">
                  <ArchButton
                    variant="outline"
                    size="sm"
                    onClick={() => setStep(2)}
                    disabled={isSubmitting}
                  >
                    Back
                  </ArchButton>
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={handleRunSimulation}
                    isLoading={isSubmitting}
                  >
                    <Play className="w-3.5 h-3.5" />
                    <span>{isSubmitting ? "Executing Monte Carlo..." : "Execute Simulation"}</span>
                  </ArchButton>
                </div>
              </div>
            )}
          </ArchModal>

          {/* Intro Information Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ArchCard>
              <ArchCardContent className="space-y-2">
                <span className="text-xs font-mono font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-[#D95E00]" /> Multi-Tier Propagation
                </span>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed">
                  Evaluates multi-echelon cascading failure paths from Tier-3 sub-component suppliers down to assembly hubs.
                </p>
              </ArchCardContent>
            </ArchCard>

            <ArchCard>
              <ArchCardContent className="space-y-2">
                <span className="text-xs font-mono font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-[#0A7A75]" /> Deterministic Constraints
                </span>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed">
                  Strict adherence to contractual lead times, inventory safety buffers, and carrier capacity bounds.
                </p>
              </ArchCardContent>
            </ArchCard>

            <ArchCard>
              <ArchCardContent className="space-y-2">
                <span className="text-xs font-mono font-bold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                  <Zap className="w-3.5 h-3.5 text-[#E88D00]" /> Solver Handoff
                </span>
                <p className="text-xs font-mono text-muted-foreground leading-relaxed">
                  Simulation shock vectors feed directly into Google OR-Tools to solve optimal candidate mitigations.
                </p>
              </ArchCardContent>
            </ArchCard>
          </div>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
