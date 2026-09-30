"use client";

import React from "react";
import {
  Building2,
  Lock,
  Server,
  Shield,
  Users,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { RoleBadge } from "@/components/ui/Badges";
import {
  ArchBadge,
  ArchCard,
  ArchCardContent,
  ArchTabs,
  ArchTabsList,
  ArchTabsTrigger,
  ArchTabsContent,
  ArchInput,
  ArchLabel,
  ArchFormGroup,
} from "@/components/ui/ArchitecturalComponents";
import { useAuth } from "@/lib/auth/AuthContext";

export default function AdminPage() {
  const { user } = useAuth();

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-5xl">
          <div className="border-b border-arch pb-4">
            <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 font-mono">
              <Shield className="w-5 h-5 text-[#D95E00]" />
              Tenant Administration & RBAC Controls
              <ArchBadge variant="orange">
                Enterprise
              </ArchBadge>
            </h1>
            <p className="text-xs text-muted-foreground mt-0.5 font-mono">
              Multi-tenant boundary enforcement, role-based access control, and backend system configuration.
            </p>
          </div>

          <ArchTabs defaultValue="org">
            <ArchTabsList>
              <ArchTabsTrigger value="org">Organization Settings</ArchTabsTrigger>
              <ArchTabsTrigger value="users">Users & Roles (RBAC)</ArchTabsTrigger>
              <ArchTabsTrigger value="integrations">Telemetry Integrations</ArchTabsTrigger>
              <ArchTabsTrigger value="security">Audit & Compliance</ArchTabsTrigger>
            </ArchTabsList>

            {/* Tab 1: Organization */}
            <ArchTabsContent value="org">
              <ArchCard elevated>
                <div className="p-5 space-y-4 font-mono">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Building2 className="w-4 h-4 text-[#D95E00]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Active Tenant Boundary</h3>
                    </div>
                    <ArchBadge variant="teal">
                      TENANT ISOLATED
                    </ArchBadge>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                    <ArchFormGroup>
                      <ArchLabel>Organization Name</ArchLabel>
                      <ArchInput
                        type="text"
                        disabled
                        value={user?.organization?.name || "Active Organization"}
                        className="disabled:opacity-80"
                      />
                    </ArchFormGroup>
                    <ArchFormGroup>
                      <ArchLabel>Domain Boundary / Slug</ArchLabel>
                      <ArchInput
                        type="text"
                        disabled
                        value={user?.organization?.slug || user?.org_id || "default"}
                        className="disabled:opacity-80"
                      />
                    </ArchFormGroup>
                    <ArchFormGroup>
                      <ArchLabel>Tenant Organization ID</ArchLabel>
                      <span className="font-mono text-foreground block py-2">
                        {user?.org_id || "—"}
                      </span>
                    </ArchFormGroup>
                    <ArchFormGroup>
                      <ArchLabel>Database Schema Isolation</ArchLabel>
                      <span className="font-mono text-[#0A7A75] font-semibold block py-2">
                        Row-Level Security (RLS) Active
                      </span>
                    </ArchFormGroup>
                  </div>
                </div>
              </ArchCard>
            </ArchTabsContent>

            {/* Tab 2: Users & Roles */}
            <ArchTabsContent value="users">
              <ArchCard elevated>
                <div className="p-5 space-y-4 font-mono">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Users className="w-4 h-4 text-[#D95E00]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Role-Based Access Control (RBAC)</h3>
                    </div>
                    <span className="text-xs text-muted-foreground font-mono">5 Defined Roles</span>
                  </div>

                  <div className="space-y-3 text-xs font-mono">
                    <div className="p-3 rounded border border-arch flex items-center justify-between bg-surface">
                      <div>
                        <span className="font-semibold text-foreground block">Current Operator</span>
                        <span className="font-mono text-[11px] text-muted-foreground">{user?.email}</span>
                      </div>
                      <RoleBadge role={user?.role || "Viewer"} />
                    </div>

                    <div
                      className="p-4 rounded border border-arch space-y-2 text-[11px] bg-card"
                      style={{ backgroundColor: "var(--bg-primary)" }}
                    >
                      <h5 className="font-semibold text-foreground uppercase tracking-wider">
                        Authoritative Role Hierarchy:
                      </h5>
                      <ul className="space-y-1 text-muted-foreground font-mono">
                        <li>• <strong className="text-[#D95E00]">ADMIN:</strong> Full tenant governance, user management, integration secrets.</li>
                        <li>• <strong className="text-[#B71C1C]">RISKMANAGER:</strong> Authority to approve critical mitigation recommendations.</li>
                        <li>• <strong className="text-[#E88D00]">OPSMANAGER:</strong> Authority to trigger executions and rerouting commands.</li>
                        <li>• <strong className="text-[#0A7A75]">ANALYST:</strong> Run what-if simulations, formulate decisions, inspect ML models.</li>
                        <li>• <strong className="text-muted-foreground">VIEWER:</strong> Read-only observability across Control Tower telemetry.</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </ArchCard>
            </ArchTabsContent>

            {/* Tab 3: Integrations */}
            <ArchTabsContent value="integrations">
              <ArchCard elevated>
                <div className="p-5 space-y-4 font-mono">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Server className="w-4 h-4 text-[#D95E00]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Telemetry & Adapter Integrations</h3>
                    </div>
                    <ArchBadge variant="default">
                      BACKEND SECRETS VAULT
                    </ArchBadge>
                  </div>

                  <div className="p-4 rounded border border-arch text-xs space-y-3 bg-surface">
                    <div className="flex items-center gap-2 text-foreground font-mono">
                      <Lock className="w-4 h-4 text-[#E88D00]" />
                      <span className="font-semibold">Credentials Managed Server-Side</span>
                    </div>
                    <p className="text-muted-foreground leading-relaxed text-[11px] font-mono">
                      Telemetry adapter credentials (such as AIS transponders, weather feeds, and ERP execution connectors) are securely configured and managed directly in backend environment configurations and secret stores.
                    </p>
                    <div className="pt-2 border-t border-arch flex items-center justify-between text-[11px] font-mono text-muted-foreground">
                      <span>UI Credential Management:</span>
                      <span className="text-[#E88D00] font-medium font-mono">Not available / Configuration managed via backend environment</span>
                    </div>
                  </div>

                  <div className="pt-2 border-t border-arch text-[11px] text-muted-foreground font-mono">
                    Security Policy: Secrets, API keys, and connection credentials are never transmitted to browser clients.
                  </div>
                </div>
              </ArchCard>
            </ArchTabsContent>

            {/* Tab 4: Security */}
            <ArchTabsContent value="security">
              <ArchCard elevated>
                <div className="p-5 space-y-4 text-xs font-mono">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Shield className="w-4 h-4 text-[#0A7A75]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Compliance & Cryptographic Verification</h3>
                    </div>
                    <ArchBadge variant="teal">SOC2 Type II Ready</ArchBadge>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <ArchCard>
                      <ArchCardContent className="space-y-1">
                        <span className="font-semibold text-foreground block font-mono">Session Management</span>
                        <p className="text-muted-foreground text-[11px] font-mono">
                          Strict HttpOnly, SameSite=Lax session cookies. Zero browser token exposure.
                        </p>
                      </ArchCardContent>
                    </ArchCard>
                    <ArchCard>
                      <ArchCardContent className="space-y-1">
                        <span className="font-semibold text-foreground block font-mono">Immutable Audit Trails</span>
                        <p className="text-muted-foreground text-[11px] font-mono">
                          Cryptographically sealed SHA-256 fingerprints recorded for all solver executions and approvals.
                        </p>
                      </ArchCardContent>
                    </ArchCard>
                  </div>
                </div>
              </ArchCard>
            </ArchTabsContent>
          </ArchTabs>
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
