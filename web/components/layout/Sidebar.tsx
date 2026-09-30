"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Bot,
  Wrench,
  AlertOctagon,
  Flame,
  Globe2,
  Network,
  Cpu,
  Sliders,
  Sparkles,
  Scale,
  UserCheck,
  Truck,
  Zap,
  ShieldCheck,
  Building2,
  Anchor,
  Ship,
  Factory,
  Warehouse,
  GitFork,
  Package,
  Boxes,
  Bell,
  ScrollText,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Activity,
  FileCheck2,
  Sun,
  Moon,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { useTheme } from "@/lib/theme/ThemeContext";
import { RoleBadge } from "../ui/Badges";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
  badge?: string;
}

interface NavGroup {
  group: string;
  items: NavItem[];
}

const NAVIGATION: NavGroup[] = [
  {
    group: "Command Center",
    items: [
      { label: "Overview & Machine", href: "/dashboard", icon: LayoutDashboard },
      { label: "Global Live Map", href: "/map", icon: Globe2 },
    ],
  },
  {
    group: "Agentic Execution",
    items: [
      { label: "Agent Runs", href: "/agent-runs", icon: Bot, badge: "AI" },
      { label: "Agent Tools", href: "/mcp-tools", icon: Wrench, badge: "TOOLS" },
      { label: "Action Dispatch", href: "/actions", icon: Zap },
    ],
  },
  {
    group: "Governance & Policies",
    items: [
      { label: "Approvals Queue", href: "/approvals", icon: UserCheck },
      { label: "Policy Inspector", href: "/policy-inspector", icon: FileCheck2 },
      { label: "Audit Ledger", href: "/audit", icon: ScrollText },
      { label: "Decisions Log", href: "/decisions", icon: Scale },
    ],
  },
  {
    group: "Security & Intelligence",
    items: [
      { label: "Evaluation & QA", href: "/evaluation", icon: Shield },
      { label: "Threat Incidents", href: "/incidents", icon: Flame },
      { label: "Risk Matrix", href: "/risks", icon: AlertOctagon },
      { label: "Digital Twin", href: "/digital-twin", icon: Network },
      { label: "Simulations", href: "/simulations", icon: Cpu },
      { label: "Optimization", href: "/optimization", icon: Sliders },
      { label: "Recommendations", href: "/recommendations", icon: Sparkles },
    ],
  },
  {
    group: "Infrastructure & Platform",
    items: [
      { label: "System Health", href: "/system-health", icon: Activity, badge: "P99" },
      { label: "Verification", href: "/verification", icon: ShieldCheck },
      { label: "Notifications", href: "/notifications", icon: Bell },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
  {
    group: "Supply Network Assets",
    items: [
      { label: "Shipments", href: "/shipments", icon: Truck },
      { label: "Suppliers", href: "/suppliers", icon: Building2 },
      { label: "Ports", href: "/ports", icon: Anchor },
      { label: "Carriers", href: "/carriers", icon: Ship },
      { label: "Factories", href: "/factories", icon: Factory },
      { label: "Warehouses", href: "/warehouses", icon: Warehouse },
      { label: "Routes", href: "/routes", icon: GitFork },
      { label: "Products", href: "/products", icon: Package },
      { label: "Inventory", href: "/inventory", icon: Boxes },
    ],
  },
];

export function Sidebar({
  isCollapsed,
  onToggleCollapse,
}: {
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const pathname = usePathname();
  const { user } = useAuth();
  const { theme, toggleTheme } = useTheme();

  return (
    <aside
      className={`fixed left-0 top-0 bottom-0 z-30 border-r flex flex-col transition-all duration-200 select-none ${
        isCollapsed ? "w-16" : "w-64"
      }`}
      style={{
        backgroundColor: "var(--bg-secondary)",
        borderColor: "var(--border-arch)",
      }}
    >
      {/* Brand Header */}
      <div
        className="h-14 border-b px-4 flex items-center justify-between"
        style={{ borderColor: "var(--border-arch)" }}
      >
        <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden group">
          {/* Architectural Hex/Prism Logo */}
          <div className="w-8 h-8 rounded bg-[#151D2A] border border-[#D95E00]/60 p-1 flex items-center justify-center shadow-sm shadow-[#D95E00]/30 group-hover:border-[#D95E00] transition-colors flex-shrink-0">
            <span className="font-mono font-black text-xs text-[#D95E00] tracking-wider">
              MS
            </span>
          </div>
          {!isCollapsed && (
            <div className="flex flex-col truncate">
              <span className="text-xs font-black tracking-[0.16em] text-foreground flex items-center">
                CHAIN<span className="text-[#D95E00]">SENTINEL</span>
              </span>
              <span className="text-[9px] text-muted-foreground font-mono tracking-wider flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse inline-block" />
                ARCHITECTURAL INTEL
              </span>
            </div>
          )}
        </Link>
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-surface transition-colors"
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Organization / Tenant Bar */}
      {!isCollapsed && (
        <div
          className="px-3 py-2 border-b flex items-center justify-between"
          style={{
            backgroundColor: "var(--bg-card)",
            borderColor: "var(--border-arch)",
          }}
        >
          <div className="truncate">
            <span className="text-[9px] uppercase font-mono tracking-wider text-muted-foreground block">
              ENTERPRISE TENANT
            </span>
            <span className="text-xs font-medium text-foreground truncate block font-mono">
              {user?.organization?.name || "Global Defense Logistics"}
            </span>
          </div>
          {user?.role && <RoleBadge role={user.role} />}
        </div>
      )}

      {/* Navigation List */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-5">
        {NAVIGATION.map((group) => (
          <div key={group.group}>
            {!isCollapsed && (
              <div className="px-2 mb-1.5 text-[9px] font-mono font-bold tracking-wider text-muted-foreground uppercase flex items-center justify-between">
                <span>{group.group}</span>
                <span className="text-[8px] opacity-40 font-mono">■</span>
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = pathname === item.href || pathname?.startsWith(`${item.href}/`);
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded text-xs font-mono transition-all ${
                      isActive
                        ? "bg-[#D95E00]/15 text-[#D95E00] font-bold border-l-2 border-[#D95E00] shadow-sm"
                        : "text-muted-foreground hover:text-foreground hover:bg-surface"
                    }`}
                    title={isCollapsed ? item.label : undefined}
                  >
                    <Icon
                      className={`w-4 h-4 flex-shrink-0 ${
                        isActive ? "text-[#D95E00]" : "text-muted-foreground"
                      }`}
                    />
                    {!isCollapsed && (
                      <div className="flex-1 flex items-center justify-between truncate">
                        <span className="truncate">{item.label}</span>
                        {item.badge && (
                          <span className="ml-1.5 px-1 py-0.2 rounded text-[9px] font-mono bg-arch-elevated border border-arch text-[#0A7A75]">
                            {item.badge}
                          </span>
                        )}
                      </div>
                    )}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Footer Controls: Theme Toggle & Posture Indicator */}
      <div
        className="p-3 border-t flex items-center justify-between"
        style={{
          borderColor: "var(--border-arch)",
          backgroundColor: "var(--bg-card)",
        }}
      >
        <button
          onClick={toggleTheme}
          className="w-full flex items-center justify-center gap-2 px-2.5 py-1.5 rounded border border-arch text-xs font-mono text-muted-foreground hover:text-foreground hover:bg-surface transition-colors"
          title="Toggle Architectural Theme (Obsidian vs Warm Ivory)"
        >
          {theme === "ivory" ? (
            <>
              <Moon className="w-3.5 h-3.5 text-[#D95E00]" />
              {!isCollapsed && <span>OBSIDIAN DARK</span>}
            </>
          ) : (
            <>
              <Sun className="w-3.5 h-3.5 text-[#E88D00]" />
              {!isCollapsed && <span>WARM IVORY</span>}
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
