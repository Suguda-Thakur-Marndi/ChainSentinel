"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
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
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { RoleBadge } from "../ui/Badges";

interface NavItem {
  label: string;
  href: string;
  icon: React.ElementType;
}

interface NavGroup {
  group: string;
  items: NavItem[];
}

const NAVIGATION: NavGroup[] = [
  {
    group: "Overview",
    items: [
      { label: "Control Tower", href: "/dashboard", icon: LayoutDashboard },
      { label: "Global Live Map", href: "/map", icon: Globe2 },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { label: "Risks", href: "/risks", icon: AlertOctagon },
      { label: "Incidents", href: "/incidents", icon: Flame },
    ],
  },
  {
    group: "Digital Twin & Simulation",
    items: [
      { label: "Digital Twin", href: "/digital-twin", icon: Network },
      { label: "Simulations", href: "/simulations", icon: Cpu },
      { label: "Optimization", href: "/optimization", icon: Sliders },
    ],
  },
  {
    group: "Decisions & Governance",
    items: [
      { label: "Recommendations", href: "/recommendations", icon: Sparkles },
      { label: "Decisions", href: "/decisions", icon: Scale },
      { label: "Approvals", href: "/approvals", icon: UserCheck },
    ],
  },
  {
    group: "Operations",
    items: [
      { label: "Shipments", href: "/shipments", icon: Truck },
      { label: "Actions", href: "/actions", icon: Zap },
      { label: "Verification", href: "/verification", icon: ShieldCheck },
    ],
  },
  {
    group: "Network Data",
    items: [
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
  {
    group: "System",
    items: [
      { label: "Evaluation & QA", href: "/evaluation", icon: Shield },
      { label: "Notifications", href: "/notifications", icon: Bell },
      { label: "Audit Log", href: "/audit", icon: ScrollText },
      { label: "Admin", href: "/admin", icon: Settings },
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

  return (
    <aside
      className={`fixed left-0 top-0 bottom-0 z-30 bg-[#0F172A] border-r border-[#243044] flex flex-col transition-all duration-200 select-none ${
        isCollapsed ? "w-16" : "w-64"
      }`}
    >
      {/* Brand Header */}
      <div className="h-14 border-b border-[#243044] px-4 flex items-center justify-between">
        <Link href="/dashboard" className="flex items-center gap-2.5 overflow-hidden">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white flex-shrink-0 font-black shadow-md shadow-blue-500/20">
            RW
          </div>
          {!isCollapsed && (
            <div className="flex flex-col truncate">
              <span className="text-sm font-bold tracking-tight text-white flex items-center gap-1">
                RiskWise <span className="text-[10px] px-1 py-0.5 rounded bg-blue-500/20 text-blue-400 font-mono">2.0</span>
              </span>
              <span className="text-[10px] text-slate-400 truncate">Control Tower</span>
            </div>
          )}
        </Link>
        <button
          onClick={onToggleCollapse}
          className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Organization Header */}
      {!isCollapsed && (
        <div className="px-3 py-2 bg-[#111827] border-b border-[#243044] flex items-center justify-between">
          <div className="truncate">
            <span className="text-[10px] uppercase font-semibold tracking-wider text-slate-500 block">Organization</span>
            <span className="text-xs font-medium text-slate-200 truncate block">
              {user?.organization?.name || "Global Enterprise"}
            </span>
          </div>
          {user?.role && <RoleBadge role={user.role} />}
        </div>
      )}

      {/* Navigation Groups */}
      <div className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
        {NAVIGATION.map((grp) => (
          <div key={grp.group}>
            {!isCollapsed && (
              <h5 className="px-2 mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                {grp.group}
              </h5>
            )}
            <ul className="space-y-0.5">
              {grp.items.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`);

                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        isActive
                          ? "bg-blue-600/20 text-blue-400 border border-blue-500/30 font-semibold"
                          : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                      } ${isCollapsed ? "justify-center px-0" : ""}`}
                      title={isCollapsed ? item.label : undefined}
                    >
                      <Icon className={`w-4 h-4 flex-shrink-0 ${isActive ? "text-blue-400" : "text-slate-400"}`} />
                      {!isCollapsed && <span className="truncate">{item.label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      {/* Footer / User Profile summary */}
      <div className="p-3 border-t border-[#243044] bg-[#0B0F14]/50">
        <div className={`flex items-center gap-2.5 ${isCollapsed ? "justify-center" : ""}`}>
          <div className="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-semibold text-slate-300 flex-shrink-0">
            {user?.full_name ? user.full_name[0].toUpperCase() : "U"}
          </div>
          {!isCollapsed && (
            <div className="truncate flex-1">
              <p className="text-xs font-medium text-slate-200 truncate">{user?.full_name || "Operator"}</p>
              <p className="text-[10px] text-slate-500 truncate font-mono">{user?.email || "auth@riskwise.io"}</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
