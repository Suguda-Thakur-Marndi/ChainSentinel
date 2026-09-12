"use client";

import React, { useEffect, useState } from "react";
import { Boxes, RefreshCw } from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { Column, DataTable, TableToolbar } from "@/components/ui/DataTable";
import { ErrorState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { InventoryResponse } from "@/lib/api/types";

export default function InventoryPage() {
  const [inventory, setInventory] = useState<InventoryResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchInventory = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.network.inventory.list({ limit: 100 });
      setInventory(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load inventory");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchInventory();
  }, []);

  const filtered = inventory.filter((inv) => {
    const q = searchQuery.toLowerCase();
    return (
      inv.product_id.toLowerCase().includes(q) || inv.warehouse_id.toLowerCase().includes(q)
    );
  });

  const columns: Column<InventoryResponse>[] = [
    {
      key: "product_id",
      header: "Product SKU Reference",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-blue-400 font-bold">{row.product_id}</span>
      ),
    },
    {
      key: "warehouse_id",
      header: "Storage Node / DC",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-xs text-slate-200">{row.warehouse_id}</span>
      ),
    },
    {
      key: "quantity_on_hand",
      header: "Quantity on Hand",
      sortable: true,
      align: "right",
      render: (row) => (
        <span
          className={`font-mono text-xs font-bold ${
            row.quantity_on_hand < row.safety_stock ? "text-rose-400" : "text-slate-200"
          }`}
        >
          {row.quantity_on_hand.toLocaleString()} units
        </span>
      ),
    },
    {
      key: "safety_stock",
      header: "Safety Buffer Threshold",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-slate-400">
          {row.safety_stock.toLocaleString()}
        </span>
      ),
    },
    {
      key: "reorder_point",
      header: "Reorder Trigger",
      sortable: true,
      align: "right",
      render: (row) => (
        <span className="font-mono text-xs text-amber-400">
          {row.reorder_point.toLocaleString()}
        </span>
      ),
    },
    {
      key: "last_updated",
      header: "Stock Audit Timestamp",
      sortable: true,
      render: (row) => (
        <span className="font-mono text-[11px] text-slate-400">
          {new Date(row.last_updated).toLocaleString()}
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
                Inventory & Buffer Stock Monitor
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
                  {inventory.length} Stock Records
                </span>
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time stock on hand, buffer thresholds, and starvation reorder triggers.
              </p>
            </div>

            <button
              onClick={fetchInventory}
              disabled={isLoading}
              className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
              title="Refresh"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            </button>
          </div>

          {error && <ErrorState message={error} onRetry={fetchInventory} />}

          <TableToolbar
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            placeholder="Search stock records by SKU or warehouse ID..."
          />

          <DataTable
            columns={columns}
            data={filtered}
            isLoading={isLoading}
            emptyTitle="No Inventory Records"
            emptyMessage="No stock counts recorded for active supply chain nodes."
          />
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
