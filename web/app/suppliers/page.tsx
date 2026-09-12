"use client";

import React, { useEffect, useState } from "react";
import {
  Building2,
  DollarSign,
  Plus,
  RefreshCw,
  Search,
  Shield,
  X,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { SupplierCreate, SupplierResponse } from "@/lib/api/types";

export default function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<SupplierResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Form State
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [country, setCountry] = useState("");
  const [tier, setTier] = useState<"LOW" | "MEDIUM" | "HIGH" | "CRITICAL">("MEDIUM");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchSuppliers = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.suppliers.list({ limit: 100 });
      setSuppliers(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load suppliers");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSuppliers();
  }, []);

  const handleCreateSupplier = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    try {
      const payload: SupplierCreate = {
        name: name.trim(),
        code: code.trim() || undefined,
        country: country.trim() || undefined,
        tier,
      };
      await apiClient.network.suppliers.create(payload);
      setShowCreateModal(false);
      setName("");
      setCode("");
      setCountry("");
      await fetchSuppliers();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create supplier");
    } finally {
      setIsSubmitting(false);
    }
  };

  const filteredSuppliers = suppliers.filter((s) => {
    const q = searchQuery.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      (s.code && s.code.toLowerCase().includes(q)) ||
      (s.country && s.country.toLowerCase().includes(q))
    );
  });

  const columns: Column<SupplierResponse>[] = [
    {
      key: "name",
      header: "Supplier Name",
      sortable: true,
      render: (row) => (
        <div>
          <span className="font-semibold text-slate-200 block">{row.name}</span>
          <span className="text-[11px] font-mono text-slate-500">{row.code || "NO_CODE"}</span>
        </div>
      ),
    },
    {
      key: "country",
      header: "Country / Jurisdiction",
      sortable: true,
      render: (row) => <span className="text-slate-300">{row.country || "Global"}</span>,
    },
    {
      key: "tier",
      header: "Criticality Tier",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-amber-400 px-2 py-0.5 rounded bg-amber-950/40 border border-amber-800">
          {row.tier || "MEDIUM"}
        </span>
      ),
    },
    {
      key: "reliability_score",
      header: "Reliability Score",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs font-bold text-slate-200">
          {row.reliability_score !== null && row.reliability_score !== undefined
            ? `${Math.round(row.reliability_score)}/100`
            : "—"}
        </span>
      ),
    },
    {
      key: "financial_exposure",
      header: "Exposure (USD)",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.financial_exposure !== null && row.financial_exposure !== undefined
            ? `$${row.financial_exposure.toLocaleString()}`
            : "—"}
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
                Suppliers Directory
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {suppliers.length} Registered
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Multi-tier supplier profiles, tier criticalities, and financial exposures.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={fetchSuppliers}
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
                <span>Register Supplier</span>
              </button>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchSuppliers} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search suppliers by name, code, country..."
          />

          <DataTable
            columns={columns}
            data={filteredSuppliers}
            isLoading={isLoading}
            emptyTitle="No Suppliers Registered"
            emptyMessage="Register your first tier-1 or tier-2 supplier."
          />

          {showCreateModal && (
            <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
              <div className="w-full max-w-md rounded-lg border border-[#243044] bg-[#111827] shadow-2xl p-6 space-y-4">
                <div className="flex items-center justify-between border-b border-[#243044] pb-3">
                  <h3 className="text-sm font-bold text-white">Register Authoritative Supplier</h3>
                  <button
                    onClick={() => setShowCreateModal(false)}
                    className="text-slate-400 hover:text-slate-200"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                <form onSubmit={handleCreateSupplier} className="space-y-4 text-xs">
                  <div>
                    <label className="block text-slate-300 font-medium mb-1">Supplier Name *</label>
                    <input
                      type="text"
                      required
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Taiwan Semiconductor Corp"
                      className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Supplier Code</label>
                      <input
                        type="text"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        placeholder="e.g. TSMC-01"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none font-mono"
                      />
                    </div>
                    <div>
                      <label className="block text-slate-300 font-medium mb-1">Country</label>
                      <input
                        type="text"
                        value={country}
                        onChange={(e) => setCountry(e.target.value)}
                        placeholder="e.g. Taiwan"
                        className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-slate-300 font-medium mb-1">Criticality Tier</label>
                    <select
                      value={tier}
                      onChange={(e) => setTier(e.target.value as "LOW" | "MEDIUM" | "HIGH" | "CRITICAL")}
                      className="w-full px-3 py-2 rounded bg-[#1A2332] border border-slate-700 text-slate-100 focus:outline-none"
                    >
                      <option value="CRITICAL">Tier 1 — Critical SPOF</option>
                      <option value="HIGH">Tier 2 — High Criticality</option>
                      <option value="MEDIUM">Tier 3 — Medium</option>
                      <option value="LOW">Tier 4 — Standard Commodity</option>
                    </select>
                  </div>

                  <div className="flex justify-end gap-3 pt-3 border-t border-[#243044]">
                    <button
                      type="button"
                      onClick={() => setShowCreateModal(false)}
                      className="px-3 py-1.5 rounded bg-slate-800 text-slate-300"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmitting}
                      className="px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-semibold disabled:opacity-50"
                    >
                      {isSubmitting ? "Registering..." : "Save Supplier"}
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
