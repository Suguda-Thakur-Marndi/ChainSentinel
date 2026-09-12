"use client";

import React, { useEffect, useState } from "react";
import {
  Anchor,
  Building2,
  Factory,
  Filter,
  GitFork,
  Layers,
  Network,
  RefreshCw,
  Search,
  Ship,
  Warehouse,
  X,
  Zap,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type {
  DigitalTwinSnapshot,
  DigitalTwinSummaryResponse,
  TwinEdgeContract,
  TwinNodeContract,
} from "@/lib/api/types";

export default function DigitalTwinPage() {
  const [snapshot, setSnapshot] = useState<DigitalTwinSnapshot | null>(null);
  const [summary, setSummary] = useState<DigitalTwinSummaryResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<TwinNodeContract | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<TwinEdgeContract | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTwin = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [sum, snap] = await Promise.all([
        apiClient.digitalTwin.getCurrent(),
        apiClient.digitalTwin.getSnapshot(),
      ]);
      setSummary(sum);
      setSnapshot(snap);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load Digital Twin topology");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTwin();
  }, []);

  const rawNodes = snapshot?.nodes;
  const nodes: TwinNodeContract[] = Array.isArray(rawNodes)
    ? rawNodes
    : rawNodes && typeof rawNodes === "object"
    ? Object.values(rawNodes)
    : [];

  const rawEdges = snapshot?.edges;
  const edges: TwinEdgeContract[] = Array.isArray(rawEdges)
    ? rawEdges
    : rawEdges && typeof rawEdges === "object"
    ? Object.values(rawEdges)
    : [];

  const filteredNodes = nodes.filter((n) => {
    const label = n.label || "";
    const id = n.id || n.node_id || "";
    const matchesSearch =
      label.toLowerCase().includes(searchQuery.toLowerCase()) ||
      id.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesType = typeFilter === "ALL" || n.node_type === typeFilter;
    return matchesSearch && matchesType;
  });

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4 flex-1 flex flex-col">
          {/* Header */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#243044] pb-3">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Digital Twin Network Topology
                <span className="w-2 h-2 rounded-full bg-emerald-400 pulse-dot" />
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Authoritative multi-echelon network graph with strictly verified supply edges and dependency paths.
              </p>
            </div>

            <div className="flex items-center gap-3">
              {summary && (
                <div className="hidden sm:flex items-center gap-2 text-[11px] font-mono text-slate-400 px-2.5 py-1 rounded bg-[#111827] border border-[#243044]">
                  <span>Nodes: <strong className="text-white">{summary.node_count}</strong></span>
                  <span>•</span>
                  <span>Edges: <strong className="text-white">{summary.edge_count}</strong></span>
                  <span>•</span>
                  <span>v{summary.version}</span>
                </div>
              )}
              <button
                onClick={fetchTwin}
                disabled={isLoading}
                className="p-2 rounded-md bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044] transition-colors"
                title="Sync Digital Twin"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {error && <ErrorState message={error} onRetry={fetchTwin} />}

          {/* Controls Bar */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search topology nodes by label or ID..."
                className="w-full pl-9 pr-3 py-1.5 rounded-md bg-[#111827] border border-[#243044] text-xs text-slate-100 placeholder-slate-500 focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="bg-[#111827] border border-[#243044] text-xs text-slate-300 rounded-md px-2.5 py-1.5 focus:outline-none"
              >
                <option value="ALL">All Node Types</option>
                <option value="SUPPLIER">Suppliers</option>
                <option value="PORT">Ports & Hubs</option>
                <option value="FACTORY">Factories</option>
                <option value="WAREHOUSE">Warehouses</option>
                <option value="CARRIER">Carriers</option>
              </select>
            </div>
          </div>

          {/* Interactive Topology Graph Canvas */}
          <div className="flex-1 min-h-[500px] rounded-lg border border-[#243044] bg-[#070A0E] relative overflow-hidden flex">
            {/* Background Grid */}
            <div className="absolute inset-0 bg-[linear-gradient(to_right,#ffffff03_1px,transparent_1px),linear-gradient(to_bottom,#ffffff03_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />

            {isLoading ? (
              <div className="m-auto">
                <LoadingState message="Reconstructing graph topology from authoritative database..." />
              </div>
            ) : nodes.length === 0 ? (
              <div className="m-auto">
                <EmptyState
                  title="Empty Network Topology"
                  message="No supplier sites, factories, or logistics edges exist for this tenant."
                />
              </div>
            ) : (
              <div className="flex-1 p-6 relative overflow-auto">
                {/* Node Grid Layout */}
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {filteredNodes.map((node, idx) => {
                    const nodeId = node.id || node.node_id || `node-${idx}`;
                    const selectedId = selectedNode?.id || selectedNode?.node_id;
                    const isSelected = selectedId === nodeId;
                    const Icon =
                      node.node_type === "SUPPLIER"
                        ? Building2
                        : node.node_type === "PORT"
                        ? Anchor
                        : node.node_type === "FACTORY"
                        ? Factory
                        : node.node_type === "WAREHOUSE"
                        ? Warehouse
                        : node.node_type === "CARRIER"
                        ? Ship
                        : Network;

                    return (
                      <div
                        key={nodeId}
                        onClick={() => setSelectedNode(node)}
                        className={`p-3 rounded-lg border transition-all cursor-pointer select-none ${
                          isSelected
                            ? "bg-blue-950/40 border-blue-500 shadow-lg shadow-blue-500/10 scale-102"
                            : "bg-[#111827]/90 hover:bg-[#1A2332] border-[#243044]"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="p-1.5 rounded bg-slate-800 text-blue-400">
                            <Icon className="w-4 h-4" />
                          </div>
                          <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400">
                            {node.node_type}
                          </span>
                        </div>
                        <h4 className="text-xs font-semibold text-slate-200 line-clamp-1">
                          {node.label}
                        </h4>
                        <span className="text-[10px] font-mono text-slate-500 block mt-0.5 truncate">
                          ID: {nodeId}
                        </span>

                        {node.is_spof && (
                          <span className="mt-2 inline-flex items-center gap-1 text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                            Single Point of Failure (SPOF)
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Selected Node Details Drawer */}
            {selectedNode && (
              <div className="w-80 border-l border-[#243044] bg-[#111827] p-5 flex flex-col justify-between z-20 animate-in slide-in-from-right duration-200">
                <div>
                  <div className="flex items-start justify-between border-b border-[#243044] pb-3 mb-4">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-blue-400 block">
                        {selectedNode.node_type}
                      </span>
                      <h3 className="text-sm font-bold text-white mt-0.5">{selectedNode.label}</h3>
                    </div>
                    <button
                      onClick={() => setSelectedNode(null)}
                      className="p-1 rounded text-slate-400 hover:text-slate-200"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <span className="text-[10px] uppercase font-mono text-slate-500 block">Node ID</span>
                      <span className="font-mono text-slate-200">{selectedNode.id || selectedNode.node_id}</span>
                    </div>

                    {selectedNode.criticality && (
                      <div>
                        <span className="text-[10px] uppercase font-mono text-slate-500 block">Criticality Tier</span>
                        <span className="font-mono text-amber-400">{selectedNode.criticality}</span>
                      </div>
                    )}

                    {selectedNode.latitude !== undefined && selectedNode.latitude !== null && (
                      <div>
                        <span className="text-[10px] uppercase font-mono text-slate-500 block">Spatial Coordinates</span>
                        <span className="font-mono text-slate-300">
                          {selectedNode.latitude.toFixed(4)}°, {selectedNode.longitude?.toFixed(4)}°
                        </span>
                      </div>
                    )}

                    {/* Connected Edges */}
                    <div className="pt-2 border-t border-[#243044]">
                      <span className="text-[10px] uppercase font-mono text-slate-500 block mb-1">
                        Topology Connections
                      </span>
                      <div className="space-y-1 max-h-40 overflow-y-auto">
                        {edges
                          .filter((e) => {
                            const curId = selectedNode.id || selectedNode.node_id;
                            const src = e.source || e.from_node_id;
                            const tgt = e.target || e.to_node_id;
                            return src === curId || tgt === curId;
                          })
                          .map((e, idx) => {
                            const curId = selectedNode.id || selectedNode.node_id;
                            const src = e.source || e.from_node_id;
                            const tgt = e.target || e.to_node_id;
                            const edgeKey = e.id || e.edge_id || `edge-${idx}`;
                            return (
                              <div
                                key={edgeKey}
                                className="p-1.5 rounded bg-[#1A2332] text-[11px] font-mono text-slate-300 flex items-center justify-between"
                              >
                                <span className="truncate">
                                  {src === curId ? `→ ${tgt}` : `← ${src}`}
                                </span>
                                <span className="text-[10px] text-slate-500">{e.edge_type}</span>
                              </div>
                            );
                          })}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="pt-3 border-t border-[#243044] text-[10px] font-mono text-slate-500">
                  Deterministic Graph Snapshot
                </div>
              </div>
            )}
          </div>

          {/* Cryptographic Footprint Bar */}
          {summary && (
            <div className="p-2.5 rounded-md bg-[#111827] border border-[#243044] text-[11px] font-mono text-slate-400 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Twin Hash:</span>
                <span className="text-slate-200">{summary.twin_fingerprint.slice(0, 16)}...</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Source Fingerprint:</span>
                <span className="text-slate-200">{summary.source_fingerprint.slice(0, 16)}...</span>
              </div>
              <div>Generated: {new Date(summary.generated_at).toLocaleString()}</div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
