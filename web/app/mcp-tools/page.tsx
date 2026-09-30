"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Wrench,
  Search,
  CheckCircle2,
  Code,
  Shield,
  Layers,
  Activity,
  Sliders,
  Play,
  Terminal,
  ChevronRight,
  ExternalLink,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import {
  ArchButton,
  ArchCard,
  ArchCardHeader,
  ArchCardTitle,
  ArchCardContent,
  ArchBadge,
  ArchModal,
} from "@/components/ui/ArchitecturalComponents";

interface McpTool {
  id: string;
  name: string;
  category: "Logistics" | "Compliance" | "Telemetry" | "Financial";
  version: string;
  status: "ACTIVE" | "MAINTENANCE" | "DEPRECATED";
  description: string;
  endpoint: string;
  requiredRole: "Viewer" | "Analyst" | "OpsManager" | "RiskManager" | "Admin";
  avgLatencyMs: number;
  invocations30d: number;
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
}

const MCP_TOOLS: McpTool[] = [
  {
    id: "route_optimizer",
    name: "mcp:route_optimizer",
    category: "Logistics",
    version: "2.4.1",
    status: "ACTIVE",
    description:
      "Deterministic multi-modal routing engine calculating alternative sea, rail, and road corridors under disruption constraints.",
    endpoint: "mcp://core.chainsentinel.internal/tools/route_optimizer",
    requiredRole: "OpsManager",
    avgLatencyMs: 142,
    invocations30d: 4120,
    inputSchema: {
      type: "object",
      properties: {
        origin_port_id: { type: "string", description: "UN/LOCODE origin (e.g. CNSHA)" },
        destination_port_id: { type: "string", description: "UN/LOCODE destination (e.g. NLRTM)" },
        avoid_chokepoints: { type: "array", items: { type: "string" }, default: ["SUEZ", "PANAMA"] },
        max_eta_deviation_days: { type: "number", default: 14 },
      },
      required: ["origin_port_id", "destination_port_id"],
    },
    outputSchema: {
      type: "object",
      properties: {
        optimal_route_id: { type: "string" },
        transit_days: { type: "number" },
        cost_usd: { type: "number" },
        carbon_tonnes: { type: "number" },
        waypoints: { type: "array", items: { type: "string" } },
      },
    },
  },
  {
    id: "maritime_ais",
    name: "mcp:maritime_ais",
    category: "Telemetry",
    version: "1.9.0",
    status: "ACTIVE",
    description:
      "Authoritative satellite AIS vessel tracking and port congestion density telemetry with sub-minute positional updates.",
    endpoint: "mcp://telemetry.chainsentinel.internal/tools/maritime_ais",
    requiredRole: "Analyst",
    avgLatencyMs: 48,
    invocations30d: 18920,
    inputSchema: {
      type: "object",
      properties: {
        vessel_imo: { type: "string", description: "7-digit IMO number" },
        radius_nm: { type: "number", default: 50 },
      },
      required: ["vessel_imo"],
    },
    outputSchema: {
      type: "object",
      properties: {
        latitude: { type: "number" },
        longitude: { type: "number" },
        speed_knots: { type: "number" },
        course_degrees: { type: "number" },
        destination: { type: "string" },
        eta_raw: { type: "string" },
      },
    },
  },
  {
    id: "ofac_sanctions",
    name: "mcp:ofac_sanctions",
    category: "Compliance",
    version: "3.1.2",
    status: "ACTIVE",
    description:
      "Real-time sanctions and denied-parties screening against US OFAC SDN, EU Consolidated, and UK HM Treasury lists.",
    endpoint: "mcp://compliance.chainsentinel.internal/tools/ofac_sanctions",
    requiredRole: "RiskManager",
    avgLatencyMs: 65,
    invocations30d: 8740,
    inputSchema: {
      type: "object",
      properties: {
        entity_name: { type: "string" },
        country_iso: { type: "string" },
        duns_number: { type: "string" },
      },
      required: ["entity_name"],
    },
    outputSchema: {
      type: "object",
      properties: {
        match_found: { type: "boolean" },
        confidence_score: { type: "number" },
        programs: { type: "array", items: { type: "string" } },
        certificate_hash: { type: "string" },
      },
    },
  },
  {
    id: "carrier_contract",
    name: "mcp:carrier_contract",
    category: "Financial",
    version: "2.0.0",
    status: "ACTIVE",
    description:
      "Dynamic bunker rate locking and spot container allocation across pre-negotiated tier-1 carrier contracts.",
    endpoint: "mcp://commercial.chainsentinel.internal/tools/carrier_contract",
    requiredRole: "OpsManager",
    avgLatencyMs: 198,
    invocations30d: 2940,
    inputSchema: {
      type: "object",
      properties: {
        carrier_code: { type: "string" },
        container_type: { type: "string", enum: ["20FT_DRY", "40FT_DRY", "40FT_REEFER"] },
        quantity: { type: "integer" },
      },
      required: ["carrier_code", "quantity"],
    },
    outputSchema: {
      type: "object",
      properties: {
        booking_reference: { type: "string" },
        all_in_rate_usd: { type: "number" },
        validity_hours: { type: "number" },
      },
    },
  },
  {
    id: "reefer_iot",
    name: "mcp:reefer_iot",
    category: "Telemetry",
    version: "1.4.3",
    status: "ACTIVE",
    description:
      "Pharma and perishables telemetry monitor reading container compressor duty cycles, core temperature, and relative humidity.",
    endpoint: "mcp://telemetry.chainsentinel.internal/tools/reefer_iot",
    requiredRole: "Analyst",
    avgLatencyMs: 38,
    invocations30d: 14200,
    inputSchema: {
      type: "object",
      properties: {
        container_serial: { type: "string" },
      },
      required: ["container_serial"],
    },
    outputSchema: {
      type: "object",
      properties: {
        current_temp_celsius: { type: "number" },
        setpoint_celsius: { type: "number" },
        humidity_percent: { type: "number" },
        alarm_codes: { type: "array", items: { type: "string" } },
      },
    },
  },
  {
    id: "customs_validator",
    name: "mcp:customs_validator",
    category: "Compliance",
    version: "1.2.0",
    status: "ACTIVE",
    description:
      "Automated cross-border tariff classification, rules-of-origin certificate verification, and duty calculation.",
    endpoint: "mcp://compliance.chainsentinel.internal/tools/customs_validator",
    requiredRole: "OpsManager",
    avgLatencyMs: 110,
    invocations30d: 3100,
    inputSchema: {
      type: "object",
      properties: {
        hs_code: { type: "string" },
        origin_country: { type: "string" },
        destination_country: { type: "string" },
      },
      required: ["hs_code", "origin_country", "destination_country"],
    },
    outputSchema: {
      type: "object",
      properties: {
        applicable_duty_rate: { type: "number" },
        restricted_goods_flag: { type: "boolean" },
      },
    },
  },
];

export default function McpToolsPage() {
  const [tools] = useState<McpTool[]>(MCP_TOOLS);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [activeTool, setActiveTool] = useState<McpTool | null>(null);

  const filteredTools = tools.filter((tool) => {
    const matchesCategory =
      selectedCategory === "ALL" || tool.category === selectedCategory;
    const matchesSearch =
      tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.endpoint.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          {/* Header */}
          <div
            className="flex flex-wrap items-center justify-between gap-4 border-b pb-4"
            style={{ borderColor: "var(--border-arch)" }}
          >
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-[#0A7A75]/15 text-[#0A7A75] border border-[#0A7A75]/30">
                  PROTOCOL REGISTRY
                </span>
                <span className="w-1.5 h-1.5 rounded-full bg-[#D95E00] animate-pulse" />
                <span className="text-[11px] font-mono text-muted-foreground uppercase">
                  SANDBOXED AGENT TOOLS
                </span>
              </div>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 mt-1">
                Agent Tool Registry & Schemas
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono">
                Model Context Protocol (MCP) tool registrations, input/output contracts, and access control governance.
              </p>
            </div>

            <ArchBadge variant="teal">18 REGISTERED TOOLS</ArchBadge>
          </div>

          {/* Search & Categories Deck */}
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative w-full">
                <Search className="w-4 h-4 text-muted-foreground absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  placeholder="Filter agent tools by name, description, or endpoint..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 rounded border text-xs font-mono bg-card text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-[#D95E00]"
                  style={{
                    backgroundColor: "var(--bg-card)",
                    borderColor: "var(--border-arch)",
                  }}
                />
              </div>
            </div>

            <div className="flex items-center gap-1.5 font-mono text-xs">
              {["ALL", "Logistics", "Telemetry", "Compliance", "Financial"].map((cat) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-2.5 py-1 rounded text-xs transition-colors ${
                    selectedCategory === cat
                      ? "bg-[#D95E00] text-white font-bold"
                      : "bg-card border border-arch text-muted-foreground hover:text-foreground"
                  }`}
                  style={{
                    backgroundColor: selectedCategory === cat ? "#D95E00" : "var(--bg-card)",
                    borderColor: "var(--border-arch)",
                  }}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>

          {/* Tools Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredTools.map((tool) => (
              <ArchCard
                key={tool.id}
                className="flex flex-col justify-between hover:border-[#D95E00]/60 transition-all cursor-pointer group"
              >
                <div>
                  <ArchCardHeader className="flex-row items-start justify-between space-y-0 pb-2">
                    <div className="truncate pr-2">
                      <div className="flex items-center gap-2">
                        <Wrench className="w-3.5 h-3.5 text-[#D95E00]" />
                        <span className="text-xs font-bold font-mono text-foreground truncate">
                          {tool.name}
                        </span>
                      </div>
                      <span className="text-[10px] text-muted-foreground font-mono">
                        v{tool.version} • {tool.category}
                      </span>
                    </div>
                    <ArchBadge variant="teal">{tool.status}</ArchBadge>
                  </ArchCardHeader>

                  <ArchCardContent className="space-y-3 pt-3">
                    <p className="text-xs text-muted-foreground line-clamp-3 font-mono">
                      {tool.description}
                    </p>

                    <div className="p-2 rounded bg-surface border border-arch text-[11px] font-mono space-y-1">
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>REQUIRED ROLE:</span>
                        <span className="text-foreground font-semibold">{tool.requiredRole}</span>
                      </div>
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>AVG LATENCY:</span>
                        <span className="text-[#0A7A75] font-semibold">{tool.avgLatencyMs}ms</span>
                      </div>
                      <div className="flex items-center justify-between text-muted-foreground">
                        <span>INVOCATIONS (30D):</span>
                        <span className="text-[#D95E00] font-semibold">
                          {tool.invocations30d.toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </ArchCardContent>
                </div>

                <div
                  className="px-4 py-2.5 border-t flex items-center justify-between bg-surface/40"
                  style={{ borderColor: "var(--border-arch)" }}
                >
                  <Link
                    href={`/mcp-tools/${tool.id}`}
                    className="text-xs font-mono text-[#D95E00] hover:underline flex items-center gap-1"
                  >
                    View Detail <ExternalLink className="w-3 h-3" />
                  </Link>

                  <ArchButton
                    variant="outline"
                    size="sm"
                    onClick={() => setActiveTool(tool)}
                    className="text-[11px]"
                  >
                    Schema Inspector
                  </ArchButton>
                </div>
              </ArchCard>
            ))}
          </div>

          {/* Schema Inspector Modal */}
          {activeTool && (
            <ArchModal
              isOpen={Boolean(activeTool)}
              onClose={() => setActiveTool(null)}
              title={`MCP SCHEMA // ${activeTool.name}`}
              subtitle={`Version ${activeTool.version} • Required RBAC: ${activeTool.requiredRole}`}
            >
              <div className="space-y-4">
                <div className="p-2.5 rounded bg-surface border border-arch text-xs font-mono">
                  <span className="text-muted-foreground block text-[10px]">MCP ENDPOINT URI</span>
                  <span className="text-[#0A7A75] font-bold">{activeTool.endpoint}</span>
                </div>

                {/* Input Schema */}
                <div>
                  <span className="text-xs font-bold text-foreground uppercase mb-1.5 flex items-center gap-1.5">
                    <Code className="w-3.5 h-3.5 text-[#D95E00]" />
                    Input Parameters (JSON Schema)
                  </span>
                  <pre className="p-3 rounded bg-black/40 border border-arch text-[11px] text-slate-200 overflow-x-auto max-h-[160px]">
                    {JSON.stringify(activeTool.inputSchema, null, 2)}
                  </pre>
                </div>

                {/* Output Schema */}
                <div>
                  <span className="text-xs font-bold text-foreground uppercase mb-1.5 flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-[#0A7A75]" />
                    Output Response Contract
                  </span>
                  <pre className="p-3 rounded bg-black/40 border border-arch text-[11px] text-slate-200 overflow-x-auto max-h-[160px]">
                    {JSON.stringify(activeTool.outputSchema, null, 2)}
                  </pre>
                </div>

                <div className="pt-2 border-t flex justify-end gap-2" style={{ borderColor: "var(--border-arch)" }}>
                  <ArchButton variant="outline" size="sm" onClick={() => setActiveTool(null)}>
                    Dismiss
                  </ArchButton>
                  <ArchButton
                    variant="default"
                    size="sm"
                    onClick={() => {
                      alert(`Dispatched test sandbox ping for ${activeTool.name}`);
                    }}
                  >
                    Test Sandbox Invocation
                  </ArchButton>
                </div>
              </div>
            </ArchModal>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
