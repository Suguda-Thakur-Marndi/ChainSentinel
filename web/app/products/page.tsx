"use client";

import React, { useEffect, useState } from "react";
import { Package, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { ProductResponse } from "@/lib/api/types";

export default function ProductsPage() {
  const [products, setProducts] = useState<ProductResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchProducts = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.products.list({ limit: 100 });
      setProducts(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load products");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchProducts();
  }, []);

  const filtered = products.filter((p) => {
    const q = searchQuery.toLowerCase();
    return (
      p.name.toLowerCase().includes(q) ||
      p.sku.toLowerCase().includes(q) ||
      (p.category && p.category.toLowerCase().includes(q))
    );
  });

  const columns: Column<ProductResponse>[] = [
    {
      key: "sku",
      header: "SKU / Part Number",
      sortable: true,
      width: "160px",
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-bold">{row.sku}</span>
      ),
    },
    {
      key: "name",
      header: "Product / Component Description",
      sortable: true,
      render: (row) => <span className="font-semibold text-slate-200">{row.name}</span>,
    },
    {
      key: "category",
      header: "Category",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">{row.category || "General"}</span>
      ),
    },
    {
      key: "criticality",
      header: "BOM Criticality",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-amber-400 px-2 py-0.5 rounded bg-amber-950/40 border border-amber-800">
          {row.criticality || "MEDIUM"}
        </span>
      ),
    },
    {
      key: "unit_cost",
      header: "Unit Cost (USD)",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-300">
          {row.unit_cost !== null && row.unit_cost !== undefined ? `$${row.unit_cost.toFixed(2)}` : "—"}
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
                Bill of Materials & SKU Catalog
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {products.length} SKUs
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Critical sub-components, raw materials, and finished assembly SKUs.
              </p>
            </div>

            <button
              onClick={fetchProducts}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchProducts} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search SKUs by description, part number, category..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Products Registered"
            emptyMessage="No bill of material parts or SKUs configured in catalog."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
