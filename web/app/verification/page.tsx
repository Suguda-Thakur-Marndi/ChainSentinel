"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Clock,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { EvidenceBadge, VerificationBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { VerificationResultResponse, VerificationStatus } from "@/lib/api/types";

export default function VerificationPage() {
  const router = useRouter();
  const [results, setResults] = useState<VerificationResultResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchVerifications = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.verification.list({ limit: 50 });
      setResults(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load verification outcomes");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchVerifications();
  }, []);

  const columns: Column<VerificationResultResponse>[] = [
    {
      key: "id",
      header: "Verification ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-semibold hover:underline">
          {row.id.slice(0, 8)}...
        </span>
      ),
    },
    {
      key: "action_id",
      header: "Action Reference",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          ACT: {row.action_id.slice(0, 10)}...
        </span>
      ),
    },
    {
      key: "status",
      header: "Verification Status",
      sortable: true,
      render: (row) => <VerificationBadge status={row.status} />,
    },
    {
      key: "evidence_precedence",
      header: "Evidence Hierarchy",
      render: (row) => <EvidenceBadge source={row.evidence_precedence} />,
    },
    {
      key: "observation_summary",
      header: "Observed Physical Outcome",
      render: (row) => (
        <span className="text-xs text-slate-300 max-w-sm block truncate">
          {row.observation_summary || "Telemetry confirmed mitigation completed."}
        </span>
      ),
    },
    {
      key: "verified_at",
      header: "Verified Timestamp",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {new Date(row.verified_at).toLocaleString()}
        </span>
      ),
    },
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Deterministic Verification Engine Console
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                  Phase 18
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Strict ground-truth physical telemetry verification. AI does not determine the outcome.
              </p>
            </div>

            <button
              onClick={fetchVerifications}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchVerifications} />}

          {/* Authoritative Deterministic Disclaimer Notice */}
          <div className="p-3.5 rounded-lg bg-[#111827] border border-emerald-900/40 text-xs text-emerald-300 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <span className="font-semibold">
                Verification is deterministic — AI does not determine the outcome.
              </span>
            </div>
            <span className="text-[11px] font-mono text-slate-400">
              Evidence Authority: REAL &gt; ESTIMATED &gt; SIMULATED
            </span>
          </div>

          <DataTable
            columns={columns}
            data={results}
            isLoading={isLoading}
            emptyTitle="No Verification Records"
            emptyMessage="Outcomes are verified automatically as physical transponders deliver post-action telemetry."
            onRowClick={(row) => router.push(`/verification/${row.id}`)}
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
