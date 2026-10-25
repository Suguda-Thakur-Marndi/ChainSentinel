"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Check, ChevronDown, Loader2, ArrowRight } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthContext";
import { OrganizationMembershipSummary } from "@/lib/auth/types";
import { RoleBadge } from "@/components/ui/Badges";

interface OrganizationSelectorProps {
  variant?: "dropdown" | "standalone";
  onSelect?: (orgId: string) => void;
}

export function OrganizationSelector({
  variant = "dropdown",
  onSelect,
}: OrganizationSelectorProps) {
  const { user, organization, switchOrg } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [isSwitching, setIsSwitching] = useState<string | null>(null);
  const router = useRouter();

  const organizations: OrganizationMembershipSummary[] = user?.organizations || [];

  const handleSelectOrg = async (orgId: string) => {
    if (orgId === organization?.id && variant === "dropdown") {
      setIsOpen(false);
      return;
    }

    setIsSwitching(orgId);
    try {
      await switchOrg(orgId);
      if (onSelect) {
        onSelect(orgId);
      } else {
        router.refresh();
      }
    } catch (err) {
      console.error("Failed to switch organization:", err);
    } finally {
      setIsSwitching(null);
      setIsOpen(false);
    }
  };

  if (variant === "standalone") {
    return (
      <div className="w-full space-y-4">
        <div className="text-center space-y-1">
          <div className="w-10 h-10 rounded-xl bg-[#0A7A75]/15 border border-[#0A7A75]/30 text-[#0A7A75] flex items-center justify-center mx-auto mb-2">
            <Building2 className="w-5 h-5" aria-hidden="true" />
          </div>
          <h2 className="text-base font-semibold text-slate-100 tracking-tight">
            Select Organization Workspace
          </h2>
          <p className="text-xs text-slate-400">
            You have authorized access to multiple organizations. Choose a workspace to launch:
          </p>
        </div>

        <div className="space-y-2 mt-4 max-h-72 overflow-y-auto pr-1">
          {organizations.map((org) => {
            const isCurrent = org.org_id === organization?.id;
            const switching = isSwitching === org.org_id;

            return (
              <button
                key={org.org_id}
                type="button"
                disabled={switching}
                onClick={() => handleSelectOrg(org.org_id)}
                className={`w-full text-left p-3.5 rounded-xl border transition-all flex items-center justify-between group cursor-pointer ${
                  isCurrent
                    ? "bg-[#0A7A75]/10 border-[#0A7A75]/40 shadow-sm shadow-[#0A7A75]/10"
                    : "bg-white/[0.02] border-white/[0.08] hover:bg-white/[0.05] hover:border-white/[0.15]"
                }`}
              >
                <div className="flex items-center gap-3 truncate">
                  <div className="w-8 h-8 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center flex-shrink-0">
                    <Building2 className="w-4 h-4 text-slate-300" />
                  </div>
                  <div className="truncate">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-white truncate font-mono">
                        {org.organization_name}
                      </span>
                      {isCurrent && (
                        <span className="px-1.5 py-0.2 rounded text-[9px] font-mono bg-[#0A7A75]/20 text-[#0A7A75] border border-[#0A7A75]/30">
                          ACTIVE
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-slate-400 font-mono block">
                      Role: {org.role}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  <RoleBadge role={org.role} />
                  {switching ? (
                    <Loader2 className="w-4 h-4 animate-spin text-[#0A7A75]" />
                  ) : (
                    <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-white group-hover:translate-x-0.5 transition-all" />
                  )}
                </div>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  // Dropdown variant for TopBar & Sidebar
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-2 py-1 rounded border border-arch hover:border-[#D95E00]/60 transition-colors text-xs font-mono max-w-[180px] truncate"
        style={{ backgroundColor: "var(--bg-card)" }}
        title="Switch Organization Tenant"
      >
        <Building2 className="w-3.5 h-3.5 text-[#D95E00] flex-shrink-0" />
        <span className="truncate text-foreground text-[11px] font-medium">
          {organization?.name || user?.org_id || "Organization"}
        </span>
        {organizations.length > 1 && (
          <ChevronDown className="w-3 h-3 text-muted-foreground flex-shrink-0 ml-0.5" />
        )}
      </button>

      {isOpen && organizations.length > 1 && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
            aria-hidden="true"
          />
          <div
            className="absolute left-0 mt-1 w-64 rounded-xl border border-arch shadow-2xl p-1.5 z-50 backdrop-blur-xl"
            style={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-arch)" }}
          >
            <div className="px-2 py-1 text-[9px] font-mono uppercase tracking-wider text-muted-foreground border-b border-arch mb-1">
              Switch Organization
            </div>

            <div className="max-h-56 overflow-y-auto space-y-1">
              {organizations.map((org) => {
                const isCurrent = org.org_id === organization?.id;
                const switching = isSwitching === org.org_id;

                return (
                  <button
                    key={org.org_id}
                    type="button"
                    disabled={switching}
                    onClick={() => handleSelectOrg(org.org_id)}
                    className={`w-full text-left px-2 py-1.5 rounded-lg text-xs font-mono flex items-center justify-between transition-colors ${
                      isCurrent
                        ? "bg-[#D95E00]/15 text-[#D95E00] font-bold"
                        : "text-foreground hover:bg-surface"
                    }`}
                  >
                    <div className="truncate flex items-center gap-1.5">
                      <span className="truncate text-[11px]">{org.organization_name}</span>
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      <RoleBadge role={org.role} />
                      {switching ? (
                        <Loader2 className="w-3 h-3 animate-spin text-[#D95E00]" />
                      ) : (
                        isCurrent && <Check className="w-3.5 h-3.5 text-[#0A7A75]" />
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
