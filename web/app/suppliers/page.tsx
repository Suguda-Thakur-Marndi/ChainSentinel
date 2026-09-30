"use client";

import React, { useEffect, useState } from "react";
import {
  Plus,
  RefreshCw,
  Building2,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/FeedbackStates";
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
    let cancelled = false;
    apiClient.network.suppliers
      .list({ limit: 100 })
      .then((res) => {
        if (!cancelled) {
          setSuppliers(res.items || []);
          setIsLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load suppliers");
          setIsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
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
          <span className="font-semibold text-foreground block font-mono">{row.name}</span>
          <span className="text-[11px] font-mono text-muted-foreground">{row.code || "NO_CODE"}</span>
        </div>
      ),
    },
    {
      key: "country",
      header: "Country / Jurisdiction",
      sortable: true,
      render: (row) => <span className="text-muted-foreground font-mono">{row.country || "Global"}</span>,
    },
    {
      key: "tier",
      header: "Criticality Tier",
      sortable: true,
      render: (row) => {
        const tierVariant =
          row.tier === "CRITICAL"
            ? "danger"
            : row.tier === "HIGH"
            ? "amber"
            : row.tier === "MEDIUM"
            ? "orange"
            : "teal";
        return (
          <ArchBadge variant={tierVariant}>
            {row.tier || "MEDIUM"}
          </ArchBadge>
        );
      },
    },
    {
      key: "reliability_score",
      header: "Reliability Score",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs font-bold text-foreground">
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
        <span className="font-mono text-xs text-muted-foreground">
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
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-arch pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 font-mono">
                <Building2 className="w-5 h-5 text-[#D95E00]" />
                Suppliers Directory
                <ArchBadge variant="orange">
                  {suppliers.length} Registered
                </ArchBadge>
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Multi-tier supplier profiles, tier criticalities, and financial exposures.
              </p>
            </div>

            <div className="flex items-center gap-2.5">
              <ArchButton
                variant="outline"
                size="sm"
                onClick={fetchSuppliers}
                disabled={isLoading}
                title="Refresh suppliers"
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
                <span>Register Supplier</span>
              </ArchButton>
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

          <ArchModal
            isOpen={showCreateModal}
            onClose={() => setShowCreateModal(false)}
            title="Register Authoritative Supplier"
            subtitle="Deterministic Multi-tier Supplier Profile Creation"
          >
            <form onSubmit={handleCreateSupplier} className="space-y-4">
              <ArchFormGroup>
                <ArchLabel required>Supplier Name</ArchLabel>
                <ArchInput
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Taiwan Semiconductor Corp"
                />
              </ArchFormGroup>

              <div className="grid grid-cols-2 gap-3">
                <ArchFormGroup>
                  <ArchLabel>Supplier Code</ArchLabel>
                  <ArchInput
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="e.g. TSMC-01"
                  />
                </ArchFormGroup>
                <ArchFormGroup>
                  <ArchLabel>Country / Jurisdiction</ArchLabel>
                  <ArchInput
                    type="text"
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    placeholder="e.g. Taiwan"
                  />
                </ArchFormGroup>
              </div>

              <ArchFormGroup>
                <ArchLabel>Criticality Tier</ArchLabel>
                <ArchSelect
                  value={tier}
                  onChange={(e) => setTier(e.target.value as "LOW" | "MEDIUM" | "HIGH" | "CRITICAL")}
                >
                  <option value="CRITICAL">Tier 1 — Critical SPOF</option>
                  <option value="HIGH">Tier 2 — High Criticality</option>
                  <option value="MEDIUM">Tier 3 — Medium</option>
                  <option value="LOW">Tier 4 — Standard Commodity</option>
                </ArchSelect>
              </ArchFormGroup>

              <div className="flex justify-end gap-2.5 pt-3 border-t border-arch">
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
                  Save Supplier
                </ArchButton>
              </div>
            </form>
          </ArchModal>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
