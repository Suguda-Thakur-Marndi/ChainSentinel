"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  Building2,
  Check,
  CheckCircle2,
  Copy,
  Lock,
  Mail,
  Send,
  Server,
  Shield,
  UserPlus,
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
import { apiClient, ApiClientError } from "@/lib/api/client";
import { InvitationResponse } from "@/lib/auth/types";

export default function AdminPage() {
  const { user } = useAuth();
  const isAdmin = user?.role?.toUpperCase() === "ADMIN";

  // Invitations state
  const [invitations, setInvitations] = useState<InvitationResponse[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("ANALYST");
  const [isInviting, setIsInviting] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [latestInviteLink, setLatestInviteLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (isAdmin) {
      apiClient.auth
        .listInvitations()
        .then(setInvitations)
        .catch((err) => console.error("Failed to load invitations", err));
    }
  }, [isAdmin]);

  const handleSendInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setInviteError(null);
    setLatestInviteLink(null);
    setIsInviting(true);

    try {
      const inv = await apiClient.auth.inviteEmployee({
        email: inviteEmail.trim(),
        role: inviteRole,
      });
      setInviteEmail("");
      if (inv.invitation_link) {
        setLatestInviteLink(inv.invitation_link);
      }
      // Refresh list
      const updated = await apiClient.auth.listInvitations();
      setInvitations(updated);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setInviteError(err.detail || "Failed to issue invitation");
      } else {
        setInviteError("Unexpected error sending invitation");
      }
    } finally {
      setIsInviting(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6 max-w-5xl">
          <div className="border-b border-arch pb-4">
            <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2 font-mono">
              <Shield className="w-5 h-5 text-[#D95E00]" />
              Administration
            </h1>
            <p className="text-xs text-muted-foreground mt-0.5 font-mono">
              Organization settings, user roles, integrations, and compliance.
            </p>
          </div>

          <ArchTabs defaultValue="org">
            <ArchTabsList>
              <ArchTabsTrigger value="org">Organization</ArchTabsTrigger>
              <ArchTabsTrigger value="users">Users & Roles</ArchTabsTrigger>
              <ArchTabsTrigger value="integrations">Integrations</ArchTabsTrigger>
              <ArchTabsTrigger value="security">Compliance</ArchTabsTrigger>
            </ArchTabsList>

            {/* Tab 1: Organization */}
            <ArchTabsContent value="org">
              <ArchCard elevated>
                <div className="p-5 space-y-4 font-mono">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Building2 className="w-4 h-4 text-[#D95E00]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Organization Details</h3>
                    </div>
                    <ArchBadge variant="teal">
                      ACTIVE
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
                        Multi-Tenant Scoping & Masking Active
                      </span>
                    </ArchFormGroup>
                  </div>
                </div>
              </ArchCard>
            </ArchTabsContent>

            {/* Tab 2: Users & Roles */}
            <ArchTabsContent value="users">
              <div className="space-y-5">
                <ArchCard elevated>
                  <div className="p-5 space-y-4 font-mono">
                    <div className="flex items-center justify-between border-b border-arch pb-3">
                      <div className="flex items-center gap-2">
                        <Users className="w-4 h-4 text-[#D95E00]" />
                        <h3 className="text-sm font-bold text-foreground font-mono">Active Operator</h3>
                      </div>
                      <span className="text-xs text-muted-foreground font-mono">5 Defined Roles</span>
                    </div>

                    <div className="space-y-3 text-xs font-mono">
                      <div className="p-3 rounded border border-arch flex items-center justify-between bg-surface">
                        <div>
                          <span className="font-semibold text-foreground block">{user?.full_name || "Current Operator"}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">{user?.email}</span>
                        </div>
                        <RoleBadge role={user?.role || "Viewer"} />
                      </div>

                      <div
                        className="p-4 rounded border border-arch space-y-2 text-[11px] bg-card"
                        style={{ backgroundColor: "var(--bg-primary)" }}
                      >
                        <h5 className="font-semibold text-foreground uppercase tracking-wider">
                          Role Hierarchy & Permissions:
                        </h5>
                        <ul className="space-y-1 text-muted-foreground font-mono">
                          <li>• <strong className="text-[#D95E00]">ADMIN:</strong> Full tenant governance, employee invitations, role assignments.</li>
                          <li>• <strong className="text-[#B71C1C]">RISKMANAGER:</strong> Authority to approve critical mitigation recommendations.</li>
                          <li>• <strong className="text-[#E88D00]">OPSMANAGER:</strong> Authority to trigger executions and rerouting commands.</li>
                          <li>• <strong className="text-[#0A7A75]">ANALYST:</strong> Run what-if simulations, formulate decisions, inspect ML models.</li>
                          <li>• <strong className="text-muted-foreground">VIEWER:</strong> Read-only observability across Control Tower telemetry.</li>
                        </ul>
                      </div>
                    </div>
                  </div>
                </ArchCard>

                {/* Employee Invitations Management (Admins Only) */}
                {isAdmin && (
                  <ArchCard elevated>
                    <div className="p-5 space-y-4 font-mono">
                      <div className="flex items-center justify-between border-b border-arch pb-3">
                        <div className="flex items-center gap-2">
                          <UserPlus className="w-4 h-4 text-[#0A7A75]" />
                          <h3 className="text-sm font-bold text-foreground font-mono">Invite Employee</h3>
                        </div>
                        <ArchBadge variant="teal">ADMIN PRIVILEGE</ArchBadge>
                      </div>

                      {inviteError && (
                        <div className="p-3 rounded border border-red-500/30 bg-red-500/10 text-red-400 text-xs font-mono flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                          <span>{inviteError}</span>
                        </div>
                      )}

                      {latestInviteLink && (
                        <div className="p-3.5 rounded border border-emerald-500/30 bg-emerald-500/10 text-xs font-mono space-y-2">
                          <div className="flex items-center gap-2 text-emerald-400 font-semibold">
                            <CheckCircle2 className="w-4 h-4" />
                            <span>Invitation Link Generated (Valid for 7 days)</span>
                          </div>
                          <div className="flex items-center gap-2 bg-[#08090A] p-2 rounded border border-white/10 overflow-hidden">
                            <input
                              type="text"
                              readOnly
                              value={latestInviteLink}
                              className="bg-transparent text-slate-300 text-[11px] font-mono w-full focus:outline-none select-all"
                            />
                            <button
                              type="button"
                              onClick={() => copyToClipboard(latestInviteLink)}
                              className="px-2.5 py-1 rounded bg-[#0A7A75] text-white hover:bg-[#0A7A75]/80 text-[11px] font-mono flex items-center gap-1 transition-colors shrink-0 cursor-pointer"
                            >
                              {copied ? <Check className="w-3.5 h-3.5 text-white" /> : <Copy className="w-3.5 h-3.5" />}
                              <span>{copied ? "COPIED" : "COPY LINK"}</span>
                            </button>
                          </div>
                        </div>
                      )}

                      <form onSubmit={handleSendInvite} className="grid grid-cols-1 sm:grid-cols-12 gap-3 text-xs">
                        <div className="sm:col-span-7">
                          <ArchLabel>Employee Corporate Email</ArchLabel>
                          <ArchInput
                            type="email"
                            required
                            placeholder="colleague@company.com"
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            disabled={isInviting}
                          />
                        </div>

                        <div className="sm:col-span-3">
                          <ArchLabel>Granted Role</ArchLabel>
                          <select
                            value={inviteRole}
                            onChange={(e) => setInviteRole(e.target.value)}
                            disabled={isInviting}
                            className="w-full px-3 py-2 text-xs rounded border border-arch bg-card text-foreground focus:outline-none focus:border-[#0A7A75] font-mono"
                          >
                            <option value="VIEWER">Viewer</option>
                            <option value="ANALYST">Analyst</option>
                            <option value="OPSMANAGER">OpsManager</option>
                            <option value="RISKMANAGER">RiskManager</option>
                            <option value="ADMIN">Admin</option>
                          </select>
                        </div>

                        <div className="sm:col-span-2 flex items-end">
                          <button
                            type="submit"
                            disabled={isInviting || !inviteEmail}
                            className="w-full py-2 px-3 rounded bg-[#0A7A75] hover:bg-[#0A7A75]/90 text-white font-mono text-xs font-medium flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                          >
                            <Send className="w-3.5 h-3.5" />
                            <span>{isInviting ? "INVITING…" : "INVITE"}</span>
                          </button>
                        </div>
                      </form>

                      {/* Pending invitations table */}
                      <div className="pt-3 border-t border-arch space-y-2">
                        <h4 className="text-xs font-semibold text-foreground tracking-wide uppercase">
                          Recent Tenant Invitations ({invitations.length})
                        </h4>
                        {invitations.length === 0 ? (
                          <p className="text-xs text-muted-foreground font-mono italic">
                            No team invitations currently active.
                          </p>
                        ) : (
                          <div className="divide-y divide-arch border border-arch rounded overflow-hidden">
                            {invitations.map((inv) => (
                              <div
                                key={inv.id}
                                className="p-2.5 flex items-center justify-between text-xs font-mono bg-surface/50"
                              >
                                <div className="space-y-0.5">
                                  <span className="font-medium text-foreground block">{inv.email}</span>
                                  <span className="text-[11px] text-muted-foreground block">
                                    Expires: {new Date(inv.expires_at).toLocaleDateString()}
                                  </span>
                                </div>
                                <div className="flex items-center gap-2">
                                  <RoleBadge role={inv.role} />
                                  <span
                                    className={`px-2 py-0.5 text-[10px] uppercase font-mono rounded ${
                                      inv.status === "PENDING"
                                        ? "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                                        : inv.status === "ACCEPTED"
                                        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                                        : "bg-slate-500/10 text-slate-400 border border-slate-500/30"
                                    }`}
                                  >
                                    {inv.status}
                                  </span>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </ArchCard>
                )}
              </div>
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
                      SERVER MANAGED
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
                      <span className="text-[#E88D00] font-medium font-mono">Managed via backend environment & AWS KMS</span>
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
                <div className="p-5 space-y-4 font-mono text-xs">
                  <div className="flex items-center justify-between border-b border-arch pb-3">
                    <div className="flex items-center gap-2">
                      <Shield className="w-4 h-4 text-[#0A7A75]" />
                      <h3 className="text-sm font-bold text-foreground font-mono">Multi-Tenant Isolation & Compliance</h3>
                    </div>
                    <ArchBadge variant="teal">ENFORCED</ArchBadge>
                  </div>

                  <div className="space-y-3 font-mono text-[11px]">
                    <div className="p-3 rounded border border-arch bg-surface space-y-1">
                      <span className="font-semibold text-foreground block">Session Security</span>
                      <p className="text-muted-foreground">
                        HttpOnly, SameSite=Lax, Secure session cookies with server-side TTL and instant revocation on logout.
                      </p>
                    </div>

                    <div className="p-3 rounded border border-arch bg-surface space-y-1">
                      <span className="font-semibold text-foreground block">Tenant Scoping Guarantee</span>
                      <p className="text-muted-foreground">
                        Every resource access and modification is strictly bounded to the authenticated organization boundary. Client-supplied organization IDs are explicitly rejected or overwritten.
                      </p>
                    </div>

                    <div className="p-3 rounded border border-arch bg-surface space-y-1">
                      <span className="font-semibold text-foreground block">Cryptographic Assurance</span>
                      <p className="text-muted-foreground">
                        Local passwords hashed with PBKDF2-HMAC-SHA256 (600,000 iterations). Invitation and password reset tokens hashed with SHA-256 for persistent security.
                      </p>
                    </div>
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
