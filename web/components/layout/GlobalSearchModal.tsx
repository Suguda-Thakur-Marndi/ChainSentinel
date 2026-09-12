"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertOctagon,
  Building2,
  Flame,
  Loader2,
  Package,
  Search,
  Truck,
  X,
} from "lucide-react";
import { apiClient } from "@/lib/api/client";

interface SearchResultItem {
  id: string;
  type: "shipment" | "risk" | "incident" | "supplier";
  title: string;
  subtitle: string;
  url: string;
}

export function GlobalSearchModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        if (isOpen) onClose();
        else onClose(); // parent handles toggle
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!query.trim() || !isOpen) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      try {
        const [shipmentsRes, risksRes, suppliersRes] = await Promise.allSettled([
          apiClient.shipments.list({ limit: 10 }),
          apiClient.risks.list({ limit: 10 }),
          apiClient.network.suppliers.list({ limit: 10 }),
        ]);

        const items: SearchResultItem[] = [];
        const q = query.toLowerCase();

        if (shipmentsRes.status === "fulfilled" && shipmentsRes.value.items) {
          shipmentsRes.value.items
            .filter(
              (s) =>
                s.tracking_number.toLowerCase().includes(q) ||
                (s.origin && s.origin.toLowerCase().includes(q)) ||
                (s.destination && s.destination.toLowerCase().includes(q))
            )
            .forEach((s) => {
              items.push({
                id: s.id,
                type: "shipment",
                title: s.tracking_number,
                subtitle: `${s.origin || "Origin"} → ${s.destination || "Dest"} (${s.status})`,
                url: `/shipments/${s.id}`,
              });
            });
        }

        if (risksRes.status === "fulfilled" && risksRes.value.items) {
          risksRes.value.items
            .filter((r) => r.title.toLowerCase().includes(q))
            .forEach((r) => {
              items.push({
                id: r.id,
                type: "risk",
                title: r.title,
                subtitle: `Severity: ${r.severity} | Score: ${r.risk_score || "N/A"}`,
                url: `/risks/${r.id}`,
              });
            });
        }

        if (suppliersRes.status === "fulfilled" && suppliersRes.value.items) {
          suppliersRes.value.items
            .filter((sup) => sup.name.toLowerCase().includes(q))
            .forEach((sup) => {
              items.push({
                id: sup.id,
                type: "supplier",
                title: sup.name,
                subtitle: `${sup.country || "Global"} | Tier: ${sup.tier || "N/A"}`,
                url: `/suppliers`,
              });
            });
        }

        setResults(items);
      } catch {
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [query, isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-start justify-center pt-20 px-4">
      <div className="w-full max-w-xl rounded-lg border border-[#243044] bg-[#111827] shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Search header input */}
        <div className="flex items-center px-4 py-3 border-b border-[#243044] gap-2">
          <Search className="w-4 h-4 text-slate-400" />
          <input
            type="text"
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search across shipments, risks, suppliers, decisions..."
            className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 focus:outline-none"
          />
          {isLoading && <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />}
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results List */}
        <div className="max-h-96 overflow-y-auto p-2 divide-y divide-slate-800/60">
          {query.trim() === "" ? (
            <div className="p-8 text-center text-xs text-slate-500">
              Type keywords to search live operational supply chain telemetry...
            </div>
          ) : results.length === 0 && !isLoading ? (
            <div className="p-8 text-center text-xs text-slate-500">
              No matching records found for &ldquo;{query}&rdquo;
            </div>
          ) : (
            results.map((item) => {
              const Icon =
                item.type === "shipment"
                  ? Truck
                  : item.type === "risk"
                  ? AlertOctagon
                  : item.type === "incident"
                  ? Flame
                  : Building2;

              return (
                <button
                  key={`${item.type}-${item.id}`}
                  onClick={() => {
                    onClose();
                    router.push(item.url);
                  }}
                  className="w-full flex items-center gap-3 p-2.5 rounded-md hover:bg-slate-800/60 transition-colors text-left group"
                >
                  <div className="p-2 rounded bg-slate-800 text-slate-400 group-hover:text-blue-400 group-hover:bg-blue-950/40 transition-colors">
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="flex-1 truncate">
                    <span className="text-xs font-semibold text-slate-200 block truncate group-hover:text-white">
                      {item.title}
                    </span>
                    <span className="text-[11px] text-slate-400 block truncate font-mono">
                      {item.subtitle}
                    </span>
                  </div>
                  <span className="text-[10px] uppercase font-mono text-slate-500 px-1.5 py-0.5 rounded bg-slate-800/80">
                    {item.type}
                  </span>
                </button>
              );
            })
          )}
        </div>

        {/* Footer info */}
        <div className="px-4 py-2 bg-[#0B0F14] border-t border-[#243044] flex items-center justify-between text-[11px] text-slate-500 font-mono">
          <span>Esc to exit</span>
          <span>Authoritative Backend Index</span>
        </div>
      </div>
    </div>
  );
}
