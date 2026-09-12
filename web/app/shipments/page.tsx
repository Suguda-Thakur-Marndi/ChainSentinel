"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Calendar,
  Filter,
  Plus,
  RefreshCw,
  Search,
  Ship,
  Truck,
  X,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { EvidenceBadge, RiskBadge, StatusBadge } from "@/components/ui/Badges";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { ShipmentCreate, ShipmentResponse, ShipmentStatus } from "@/lib/api/types";

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
    fetchShipments();
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
    const matchesMode = modeFilter === "ALL" || s.mode.toUpperCase() === modeFilter.toUpperCase();

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
      render: (row) => (
        <span className="font-mono text-[11px] uppercase text-slate-400 px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700">
          {row.mode}
        </span>
      ),
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
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Shipments Monitor
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-400 border border-blue-800">
                  {shipments.length} Total
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time multi-tier logistics tracking, carrier telemetry & predicted delays.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={fetchShipments}
                disabled={isLoading}
                className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
                title="Refresh"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              </button>
              <button
                onClick={() => setShowCreateModal(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-xs font-semibold text-white shadow-md transition-colors"
              >
                <Plus className="w-4 h-4" />
                <span>Register Shipment</span>
              </button>
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
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
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
              className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
            >
              <option value="ALL">All Modes</option>
              <option value="OCEAN">Ocean</option>
              <option value="AIR">Air</option>
              <option value="ROAD">Road</option>
              <option value="RAIL">Rail</option>
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
          {showCreateModal && (
            <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
              <div className="w-full max-w-md rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3 mb-4">
                  <h3 className="text-sm font-bold text-white">Register Authoritative Shipment</h3>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="p-1 rounded text-slate-400 hover:text-slate-200"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {createError && (
                  <div className="mb-4 p-3 rounded bg-rose-950/40 border border-rose-800 text-xs text-rose-300">
                    {createError}
                  </div>
                )}

                <form onSubmit={handleCreateShipment} className="space-y-4 text-xs">
                  <div>
                    <label className="block text-slate-300 font-medium mb-1">
                      Tracking / Container Number *
                    </label>
                    <input
                      type="text"
                      required
                      value={newTracking}
                      onChange={(e) => setNewTracking(e.target.value)}
                      placeholder="e.g. MAEU98234123"
                      className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Origin Hub</label>
                      <input
                        type="text"
                        value={newOrigin}
                        onChange={(e) => setNewOrigin(e.target.value)}
                        placeholder="e.g. Port of Shanghai"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Destination Hub</label>
                      <input
                        type="text"
                        value={newDestination}
                        onChange={(e) => setNewDestination(e.target.value)}
                        placeholder="e.g. Port of Rotterdam"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-slate-300 font-medium mb-1">Transport Mode</label>
                    <select
                      value={newMode}
                      onChange={(e) => setNewMode(e.target.value)}
                      className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
                    >
                      <option value="OCEAN">Ocean (Maritime AIS)</option>
                      <option value="AIR">Air Freight</option>
                      <option value="ROAD">Road Logistics</option>
                      <option value="RAIL">Intermodal Rail</option>
                    </select>
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#243044]">
                    <button
                      type="button"
                      onClick={() => setShowCreateModal(false)}
                      className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold transition-colors disabled:opacity-50"
                    >
                      {isSubmitting ? "Creating..." : "Save Shipment"}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
