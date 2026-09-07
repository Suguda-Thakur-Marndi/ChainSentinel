import React from "react";
import { ShieldCheck, Lock } from "lucide-react";

export function AuthSecurityNotice() {
  return (
    <div className="w-full pt-4 border-t border-white/[0.06] space-y-3">
      {/* Enterprise Security Features */}
      <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
        <div className="flex items-center gap-1.5 justify-center py-1.5 px-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <ShieldCheck className="w-3.5 h-3.5 text-blue-400 shrink-0" aria-hidden="true" />
          <span>Tenant Isolated</span>
        </div>
        <div className="flex items-center gap-1.5 justify-center py-1.5 px-2 rounded-lg bg-white/[0.02] border border-white/[0.04]">
          <Lock className="w-3.5 h-3.5 text-emerald-400 shrink-0" aria-hidden="true" />
          <span>HttpOnly Cookie</span>
        </div>
      </div>

      {/* Support & Organization Notice */}
      <p className="text-center text-[11px] text-slate-500 leading-relaxed">
        Requires an active enterprise Google Workspace account. For access delegation or SSO setup, contact your{" "}
        <span className="text-slate-400 font-medium">RiskWise Systems Administrator</span>.
      </p>
    </div>
  );
}
