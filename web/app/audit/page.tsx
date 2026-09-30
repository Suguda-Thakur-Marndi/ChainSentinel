"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  RefreshCw,
  ScrollText,
  Shield,
  FileCheck2,
  Terminal,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { ArchBadge, ArchButton } from "@/components/ui/ArchitecturalComponents";
import { apiClient } from "@/lib/api/client";
import type { AuditLogResponse } from "@/lib/api/types";

export default function AuditLogPage() {
  const [logs, setLogs] = useState<AuditLogResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchLogs = useCallback(async () => {
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
  }, []);

  useEffect(() => {
    let cancelled = false;
    apiClient.audit
      .list({ limit: 100 })
      .then((res) => {
        if (!cancelled) {
          setLogs(res.items || []);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load audit trail");
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
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
        <span className="font-mono text-xs text-foreground font-mono-tnum">
          {new Date(row.timestamp).toISOString()}
        </span>
      ),
    },
    {
      key: "actor_type",
      header: "Actor",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px]">
          {row.actor_type === "AGENT" ? (
            <ArchBadge variant="orange">AGENT</ArchBadge>
          ) : row.actor_type === "USER" ? (
            <ArchBadge variant="teal">USER</ArchBadge>
          ) : (
            <ArchBadge variant="outline">{row.actor_type || "SYSTEM"}</ArchBadge>
          )}
        </span>
      ),
    },
    {
      key: "action",
      header: "Audit Action",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-foreground font-bold">{row.action}</span>
      ),
    },
    {
      key: "entity_type",
      header: "Target Resource",
      render: (row) => (
        <span className="font-mono text-[11px] text-muted-foreground">
          {row.entity_type || "SYSTEM"}:{row.entity_id ? ` ${row.entity_id.slice(0, 8)}...` : ""}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[10px]">
          {row.status === "SUCCESS" ? (
            <ArchBadge variant="teal">SUCCESS</ArchBadge>
          ) : (
            <ArchBadge variant="danger">FAILURE</ArchBadge>
          )}
        </span>
      ),
    },
    {
      key: "fingerprint",
      header: "SHA-256 Hash",
      render: (row) => (
        <span className="font-mono text-[10px] text-[#0A7A75] truncate max-w-[130px] block">
          {row.fingerprint || "SHA256://SEALED"}
        </span>
      ),
    },
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4">
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#0A7A75]/15 text-[#0A7A75] border border-[#0A7A75]/30">
                  COMPLIANCE LEDGER
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  CRYPTOGRAPHICALLY SEALED
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Enterprise Immutable Audit Ledger
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Append-only compliance ledger tracking all agent actions, human sign-offs, and solver telemetry.
              </p>
            </div>

            <ArchButton
              onClick={fetchLogs}
              disabled={isLoading}
              variant="outline"
              size="sm"
              className="font-mono text-xs"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              <span>Refresh Ledger</span>
            </ArchButton>
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
