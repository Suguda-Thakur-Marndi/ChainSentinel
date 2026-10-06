"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Boxes,
  Plus,
  RefreshCw,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { EvidenceBadge, StatusBadge } from "@/components/ui/Badges";
import { ErrorState } from "@/components/ui/FeedbackStates";
import {
  TransportModeBadge,
  normalizeTransportMode,
} from "@/components/ui/TransportModeIcon";
import {
  ArchButton,
  ArchModal,
  ArchInput,
  ArchSelect,
  ArchLabel,
  ArchBadge,
  ArchFormGroup,
} from "@/components/ui/ArchitecturalComponents";
import { apiClient } from "@/lib/api/client";
import type { ShipmentCreate, ShipmentResponse } from "@/lib/api/types";

export default function ShipmentsPage() {
  const router = useRouter();
  const [shipments, setShipments] = useState<ShipmentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [modeFilter, setModeFilter] = useState<string>("ALL");
  const [showCreateModal, setShowCreateModal] = useState(false);

  // New Shipment Form State
  const [newTracking, setNewTracking] = useState("");
  const [newOrigin, setNewOrigin] = useState("");
  const [newDestination, setNewDestination] = useState("");
  const [newMode, setNewMode] = useState("OCEAN");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const fetchShipments = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.shipments.list({ limit: 100 });
      setShipments(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load shipments");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    apiClient.shipments
      .list({ limit: 100 })
      .then((res) => {
        if (!cancelled) {
          setShipments(res.items || []);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load shipments");
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleCreateShipment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTracking.trim()) return;
    setIsSubmitting(true);
    setCreateError(null);
    try {
      const payload: ShipmentCreate = {
        tracking_number: newTracking.trim(),
        origin: newOrigin.trim() || undefined,
        destination: newDestination.trim() || undefined,
        mode: newMode,
        status: "IN_TRANSIT",
        data_provenance: "REAL",
      };
      await apiClient.shipments.create(payload);
      setShowCreateModal(false);
      setNewTracking("");
      setNewOrigin("");
      setNewDestination("");
      await fetchShipments();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create shipment");
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredShipments = shipments.filter((s) => {
    const matchesSearch =
      s.tracking_number.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (s.origin && s.origin.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (s.destination && s.destination.toLowerCase().includes(searchQuery.toLowerCase())) ||
      (s.carrier_id && s.carrier_id.toLowerCase().includes(searchQuery.toLowerCase()));

    const matchesStatus = statusFilter === "ALL" || s.status === statusFilter;
    const matchesMode =
      modeFilter === "ALL" ||
      normalizeTransportMode(s.mode) === normalizeTransportMode(modeFilter);

    return matchesSearch && matchesStatus && matchesMode;
  });

  const columns: Column<ShipmentResponse>[] = [
    {
      key: "tracking_number",
      header: "Shipment ID",
      sortable: true,
      render: (row) => (
        <span className="font-mono font-semibold text-blue-400 hover:underline">
          {row.tracking_number}
        </span>
      ),
    },
    {
      key: "origin",
      header: "Origin",
      sortable: true,
      render: (row) => <span className="text-slate-300">{row.origin || "—"}</span>,
    },
    {
      key: "destination",
      header: "Destination",
      sortable: true,
      render: (row) => <span className="text-slate-300">{row.destination || "—"}</span>,
    },
    {
      key: "mode",
      header: "Mode",
      sortable: true,
      render: (row) => <TransportModeBadge mode={row.mode} />,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (row) => {
        let variant: "success" | "warning" | "error" | "info" | "neutral" = "info";
        if (row.status === "DELIVERED") variant = "success";
        else if (row.status === "DELAYED") variant = "warning";
        else if (row.status === "EXCEPTION" || row.status === "CANCELLED") variant = "error";
        return <StatusBadge status={row.status} variant={variant} />;
      },
    },
    {
      key: "data_provenance",
      header: "Evidence",
      render: (row) => <EvidenceBadge source={row.data_provenance} />,
    },
    {
      key: "delay_minutes",
      header: "Pred. Delay",
      sortable: true,
      align: "right",
      render: (row) =>
        row.delay_minutes !== null && row.delay_minutes !== undefined ? (
          <span
            className={`font-mono-tnum font-medium ${
              row.delay_minutes > 0 ? "text-amber-400" : "text-emerald-400"
            }`}
          >
            {row.delay_minutes > 0 ? `+${Math.round(row.delay_minutes)}m` : "On Time"}
          </span>
        ) : (
          <span className="text-slate-500 font-mono">—</span>
        ),
    },
    {
      key: "eta",
      header: "ETA",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {row.eta ? new Date(row.eta).toLocaleDateString() : "—"}
        </span>
      ),
    },
  ];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4">
          {/* Top Page Header */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-arch pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 font-mono">
                <Boxes className="w-5 h-5 text-[#D95E00]" />
                Shipments Monitor
                <ArchBadge variant="orange">
                  {shipments.length} Total
                </ArchBadge>
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Real-time multi-tier logistics tracking, carrier telemetry & predicted delays.
              </p>
            </div>

            <div className="flex items-center gap-2.5">
              <ArchButton
                variant="outline"
                size="sm"
                onClick={fetchShipments}
                disabled={isLoading}
                title="Refresh shipments"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                <span>Refresh</span>
              </ArchButton>
              <ArchButton
                variant="default"
                size="sm"
                onClick={() => setShowCreateModal(true)}
              >
                <Plus className="w-4 h-4" />
                <span>Register Shipment</span>
              </ArchButton>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchShipments} />}

          {/* Filter Bar & Search */}
          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search by tracking #, origin, destination, carrier..."
          >
            {/* Status filter */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-card border border-arch text-xs font-mono text-muted-foreground rounded px-2.5 py-1.5 focus:outline-none focus:border-[#D95E00]"
              style={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-arch)" }}
            >
              <option value="ALL">All Statuses</option>
              <option value="IN_TRANSIT">In Transit</option>
              <option value="DELAYED">Delayed</option>
              <option value="DELIVERED">Delivered</option>
              <option value="PLANNED">Planned</option>
              <option value="EXCEPTION">Exception</option>
            </select>

            {/* Mode filter */}
            <select
              value={modeFilter}
              onChange={(e) => setModeFilter(e.target.value)}
              className="bg-card border border-arch text-xs font-mono text-muted-foreground rounded px-2.5 py-1.5 focus:outline-none focus:border-[#D95E00]"
              style={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-arch)" }}
              aria-label="Filter by transport mode"
            >
              <option value="ALL">All Modes</option>
              <option value="OCEAN">Ocean Freight</option>
              <option value="AIR">Air Freight</option>
              <option value="ROAD">Road Freight</option>
              <option value="RAIL">Rail Freight</option>
            </select>
          </TableToolbar>

          {/* High-density Enterprise Table */}
          <DataTable
            columns={columns}
            data={filteredShipments}
            isLoading={isLoading}
            emptyTitle="No shipments match filters"
            emptyMessage="Clear filters or register a new shipment to begin tracking."
            onRowClick={(row) => router.push(`/shipments/${row.id}`)}
          />

          {/* Register Shipment Modal */}
          <ArchModal
            isOpen={showCreateModal}
            onClose={() => setShowCreateModal(false)}
            title="Register Authoritative Shipment"
            subtitle="Deterministic Multi-tier Logistics Tracking"
          >
            {createError && (
              <div className="mb-4 p-3 rounded bg-rose-950/40 border border-rose-800 text-xs text-rose-300 font-mono">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateShipment} className="space-y-4">
              <ArchFormGroup>
                <ArchLabel required>Tracking / Container Number</ArchLabel>
                <ArchInput
                  type="text"
                  required
                  value={newTracking}
                  onChange={(e) => setNewTracking(e.target.value)}
                  placeholder="e.g. MAEU98234123"
                />
              </ArchFormGroup>

              <div className="grid grid-cols-2 gap-3">
                <ArchFormGroup>
                  <ArchLabel>Origin Hub</ArchLabel>
                  <ArchInput
                    type="text"
                    value={newOrigin}
                    onChange={(e) => setNewOrigin(e.target.value)}
                    placeholder="e.g. Port of Shanghai"
                  />
                </ArchFormGroup>
                <ArchFormGroup>
                  <ArchLabel>Destination Hub</ArchLabel>
                  <ArchInput
                    type="text"
                    value={newDestination}
                    onChange={(e) => setNewDestination(e.target.value)}
                    placeholder="e.g. Port of Rotterdam"
                  />
                </ArchFormGroup>
              </div>

              <ArchFormGroup>
                <ArchLabel>Transport Mode</ArchLabel>
                <ArchSelect
                  value={newMode}
                  onChange={(e) => setNewMode(e.target.value)}
                >
                  <option value="OCEAN">Ocean (Maritime AIS)</option>
                  <option value="AIR">Air Freight</option>
                  <option value="ROAD">Road Logistics</option>
                  <option value="RAIL">Intermodal Rail</option>
                </ArchSelect>
              </ArchFormGroup>

              <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-arch">
                <ArchButton
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreateModal(false)}
                >
                  Cancel
                </ArchButton>
                <ArchButton
                  type="submit"
                  variant="default"
                  size="sm"
                  isLoading={isSubmitting}
                >
                  Save Shipment
                </ArchButton>
              </div>
            </form>
          </ArchModal>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
