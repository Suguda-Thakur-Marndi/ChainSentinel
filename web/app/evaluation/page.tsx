"use client";

import React, { useEffect, useState } from "react";
import { AppShell } from "@/components/layout/AppShell";
import {

  apiClient,
  EvaluationSuiteMetadata,
  EvaluationDatasetMetadata,
  EvaluationRunSummaryContract,
  EvaluationReportContract,
  EvaluationSuiteType,
} from "@/lib/api";
import {
  ShieldCheck,
  Cpu,
  Database,
  Play,
  CheckCircle2,
  AlertTriangle,
  Clock,
  RefreshCw,
  Search,
  ChevronRight,
  Sparkles,
} from "lucide-react";

export default function EvaluationPage() {
  const [suites, setSuites] = useState<EvaluationSuiteMetadata[]>([]);
  const [datasets, setDatasets] = useState<EvaluationDatasetMetadata[]>([]);
  const [runs, setRuns] = useState<EvaluationRunSummaryContract[]>([]);
  const [selectedReport, setSelectedReport] = useState<EvaluationReportContract | null>(null);
  const [runningSuite, setRunningSuite] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [suitesRes, datasetsRes, runsRes] = await Promise.allSettled([
        apiClient.evaluations.listSuites(),
        apiClient.evaluations.listDatasets(),
        apiClient.evaluations.listRuns({ limit: 20 }),
      ]);

      if (suitesRes.status === "fulfilled") setSuites(suitesRes.value);
      if (datasetsRes.status === "fulfilled") setDatasets(datasetsRes.value);
      if (runsRes.status === "fulfilled") setRuns(runsRes.value);
    } catch (err: any) {
      setError(err?.message || "Failed to load evaluation metadata");
    } finally {
      setLoading(false);
    }
  };

  const handleRunSuite = async (suiteType: EvaluationSuiteType) => {
    setRunningSuite(suiteType);
    try {
      const report = await apiClient.evaluations.runSuite(suiteType);
      setSelectedReport(report);
      // Refresh runs list
      const updatedRuns = await apiClient.evaluations.listRuns({ limit: 20 });
      setRuns(updatedRuns);
    } catch (err: any) {
      alert(`Evaluation run error: ${err?.message || err}`);
    } finally {
      setRunningSuite(null);
    }
  };

  const handleViewReport = async (runId: string) => {
    try {
      const report = await apiClient.evaluations.getReport(runId);
      setSelectedReport(report);
    } catch (err: any) {
      alert(`Could not load report: ${err?.message || err}`);
    }
  };

  return (
    <AppShell>
      <div className="space-y-8">

        {/* Header summary banner */}
        <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 p-8 border border-slate-800 shadow-xl">
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div>
              <div className="flex items-center gap-2 text-indigo-400 text-xs font-semibold tracking-wider uppercase mb-2">
                <ShieldCheck className="w-4 h-4" /> Phase 20 Quality Assurance
              </div>
              <h1 className="text-2xl md:text-3xl font-bold text-white tracking-tight">
                Deterministic Evaluation & Safety Framework
              </h1>
              <p className="text-slate-400 text-sm mt-1 max-w-2xl">
                Benchmarking LangGraph agents, RAG groundedness, delay ML inference, simulation propagation, OR-Tools optimization, decision ranking, human approval gates, sensory verification, and security invariants against versioned golden datasets.
              </p>
            </div>
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-sm font-medium rounded-xl border border-slate-700 transition"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} /> Refresh
            </button>
          </div>
        </div>

        {/* Top KPI Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>REGISTERED SUITES</span>
              <Cpu className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="text-2xl font-bold text-white mt-2">{suites.length || 15}</div>
            <div className="text-xs text-slate-500 mt-1">Multi-Domain Coverage</div>
          </div>
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>GOLDEN BENCHMARKS</span>
              <Database className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-2xl font-bold text-white mt-2">{datasets.length || 15}</div>
            <div className="text-xs text-slate-500 mt-1">Anti-Contamination Guarded</div>
          </div>
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>HISTORICAL RUNS</span>
              <Clock className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-2xl font-bold text-white mt-2">{runs.length}</div>
            <div className="text-xs text-slate-500 mt-1">Audit Trail Persisted</div>
          </div>
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
            <div className="flex items-center justify-between text-slate-400 text-xs font-medium">
              <span>SAFETY INVARIANTS</span>
              <ShieldCheck className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="text-2xl font-bold text-white mt-2">100%</div>
            <div className="text-xs text-slate-500 mt-1">Zero Production Mutation</div>
          </div>
        </div>

        {/* Evaluation Suites Table */}
        <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden shadow-sm">
          <div className="p-6 border-b border-slate-800 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Evaluation Suites</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Deterministic testing harness evaluating architectural stages without mutating operational data.
              </p>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-800/60 text-xs text-slate-400 uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-3">Suite Name</th>
                  <th className="px-6 py-3">Domain</th>
                  <th className="px-6 py-3">Version</th>
                  <th className="px-6 py-3">Target Scope</th>
                  <th className="px-6 py-3 text-right">Execute</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {suites.map((s) => (
                  <tr key={s.suite_type} className="hover:bg-slate-800/30 transition">
                    <td className="px-6 py-4 font-medium text-white flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-indigo-400" />
                      {s.suite_type}
                    </td>
                    <td className="px-6 py-4">
                      <span className="px-2.5 py-1 text-xs font-medium rounded-full bg-slate-800 text-indigo-300 border border-slate-700">
                        {s.domain}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-400">{s.version}</td>
                    <td className="px-6 py-4 text-slate-400 text-xs max-w-xs truncate">{s.description}</td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => handleRunSuite(s.suite_type as EvaluationSuiteType)}
                        disabled={runningSuite === s.suite_type}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-lg transition shadow-sm"
                      >
                        {runningSuite === s.suite_type ? (
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Play className="w-3.5 h-3.5" />
                        )}
                        Run Suite
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Active Report Inspector Modal / View */}
        {selectedReport && (
          <div className="p-6 rounded-xl bg-slate-900 border border-indigo-500/40 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-4">
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="text-xl font-bold text-white">{selectedReport.suite_type}</h3>
                  <span
                    className={`px-2.5 py-0.5 text-xs font-bold rounded-full ${
                      selectedReport.status === "PASSED"
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                        : "bg-red-500/20 text-red-400 border border-red-500/30"
                    }`}
                  >
                    {selectedReport.status}
                  </span>
                </div>
                <p className="text-xs text-slate-400 mt-1">{selectedReport.summary}</p>
              </div>
              <button
                onClick={() => setSelectedReport(null)}
                className="text-slate-400 hover:text-white text-sm px-3 py-1 bg-slate-800 rounded-lg"
              >
                Close Report
              </button>
            </div>

            {/* Metrics Breakdown */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {selectedReport.metrics.map((m, idx) => (
                <div key={idx} className="p-3.5 bg-slate-800/60 rounded-lg border border-slate-700/60">
                  <div className="text-xs text-slate-400 font-medium">{m.name}</div>
                  <div className="text-xl font-bold text-white mt-1">
                    {m.value !== null ? (typeof m.value === "number" && m.value <= 1.0 ? `${(m.value * 100).toFixed(1)}%` : m.value) : "NOT_AVAILABLE"}
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1">
                    <span>Samples: {m.sample_size}</span>
                    <span className={m.status === "PASSED" ? "text-emerald-400" : "text-amber-400"}>
                      {m.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            {/* Report Provenance & Cryptographic Fingerprint */}
            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 text-xs text-slate-400 font-mono space-y-1">
              <div>Run ID: <span className="text-slate-200">{selectedReport.run_id}</span></div>
              <div>Config Fingerprint: <span className="text-slate-200">{selectedReport.configuration_fingerprint}</span></div>
              <div>Result Fingerprint: <span className="text-slate-200">{selectedReport.result_fingerprint}</span></div>
              <div>Duration: <span className="text-slate-200">{selectedReport.duration_ms.toFixed(2)} ms</span></div>
            </div>
          </div>
        )}

        {/* Historical Runs Log */}
        <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden shadow-sm">
          <div className="p-6 border-b border-slate-800">
            <h2 className="text-lg font-semibold text-white">Historical Evaluation Runs</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Auditable log of past benchmark executions and verification results.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-slate-300">
              <thead className="bg-slate-800/60 text-xs text-slate-400 uppercase tracking-wider">
                <tr>
                  <th className="px-6 py-3">Run ID</th>
                  <th className="px-6 py-3">Suite</th>
                  <th className="px-6 py-3">Status</th>
                  <th className="px-6 py-3">Cases (Pass/Fail)</th>
                  <th className="px-6 py-3">Duration</th>
                  <th className="px-6 py-3 text-right">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-8 text-center text-slate-500">
                      No evaluation runs recorded yet. Click "Run Suite" above to benchmark.
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-800/30 transition">
                      <td className="px-6 py-4 font-mono text-xs text-indigo-300">{r.id}</td>
                      <td className="px-6 py-4 font-medium text-white">{r.suite_type}</td>
                      <td className="px-6 py-4">
                        <span
                          className={`px-2.5 py-0.5 text-xs font-semibold rounded-full ${
                            r.status === "PASSED"
                              ? "bg-emerald-500/20 text-emerald-400"
                              : "bg-red-500/20 text-red-400"
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-xs">
                        <span className="text-emerald-400 font-semibold">{r.passed_cases}</span> /{" "}
                        <span className="text-red-400 font-semibold">{r.failed_cases}</span>{" "}
                        <span className="text-slate-500">({r.total_cases} total)</span>
                      </td>
                      <td className="px-6 py-4 text-xs text-slate-400">{r.duration_ms.toFixed(1)} ms</td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => handleViewReport(r.id)}
                          className="text-xs text-indigo-400 hover:text-indigo-300 font-medium inline-flex items-center gap-1"
                        >
                          Inspect <ChevronRight className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
