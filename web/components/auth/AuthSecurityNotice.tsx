import React from "react";
import { ShieldCheck, Lock } from "lucide-react";

export function AuthSecurityNotice() {
  return (
    <div className="w-full pt-4 border-t border-white/[0.06]">
      <p className="text-center text-[11px] text-slate-500 leading-relaxed">
        Requires an active enterprise Google account. For access delegation or SSO setup, contact your{" "}
        <span className="text-slate-400 font-medium">ChainSentinel Administrator</span>.
      </p>
    </div>
  );
}
