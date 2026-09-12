"use client";

import React, { useEffect, useState } from "react";
import {
  Clock,
  Fingerprint,
  RefreshCw,
  ScrollText,
  Shield,
  User,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { AuditLogResponse } from "@/lib/api/types";

export default function AuditLogPage() {
  const [logs, setLogs] = useState<AuditLogResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchLogs = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.audit.list({ limit: 100 });
      setLogs(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load audit trail");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  const filteredLogs = logs.filter((log) => {
    const q = searchQuery.toLowerCase();
    return (
      log.action.toLowerCase().includes(q) ||
      (log.actor_type && log.actor_type.toLowerCase().includes(q)) ||
      (log.entity_type && log.entity_type.toLowerCase().includes(q)) ||
      (log.entity_id && log.entity_id.toLowerCase().includes(q))
    );
  });

  const columns: Column<AuditLogResponse>[] = [
    {
      key: "timestamp",
      header: "Timestamp (UTC)",
      sortable: true,
      width: "180px",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {new Date(row.timestamp).toISOString()}
        </span>
      ),
    },
    {
      key: "actor_type",
      header: "Actor",
      sortable: true,
      render: (row) => (
        <span
          className={`font-mono text-[11px] px-2 py-0.5 rounded uppercase ${
            row.actor_type === "AGENT"
              ? "bg-purple-950 text-purple-300 border border-purple-800"
              : row.actor_type === "USER"
              ? "bg-blue-950 text-blue-300 border border-blue-800"
              : "bg-slate-800 text-slate-300 border border-slate-700"
          }`}
        >
          {row.actor_type}
        </span>
      ),
    },
    {
      key: "action",
      header: "Audit Action",
      sortable: true,
      render: (row) => <span className="font-mono text-xs text-white">{row.action}</span>,
    },
    {
      key: "entity_type",
      header: "Target Resource",
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {row.entity_type || "SYSTEM"}:{row.entity_id ? ` ${row.entity_id.slice(0, 8)}...` : ""}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (row) => (
        <span
          className={`font-mono text-[10px] px-1.5 py-0.5 rounded ${
            row.status === "SUCCESS"
              ? "bg-emerald-950 text-emerald-300"
              : "bg-rose-950 text-rose-300"
          }`}
        >
          {row.status}
        </span>
      ),
    },
    {
      key: "fingerprint",
      header: "SHA-256 Hash",
      render: (row) => (
        <span className="font-mono text-[10px] text-slate-500 truncate max-w-[120px] block">
          {row.fingerprint || "SECURE_HASH"}
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
                Enterprise Immutable Audit Log
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                  Cryptographically Sealed
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Append-only compliance ledger tracking all agent actions, human sign-offs, and solver telemetry.
              </p>
            </div>

            <button
              onClick={fetchLogs}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchLogs} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search audit trail by action, actor, resource ID..."
          />

          <DataTable
            columns={columns}
            data={filteredLogs}
            isLoading={isLoading}
            emptyTitle="Audit Log Empty"
            emptyMessage="No administrative actions or agent executions recorded in current epoch."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
