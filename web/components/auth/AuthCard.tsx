import React from "react";
import { BorderBeam } from "@/components/ui/MagicComponents";

interface AuthCardProps {
  children: React.ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  return (
    <div className="w-full max-w-[420px] relative">
      {/* Restrained Ambient Backlight (Architectural Burnt Orange / Teal glow) */}
      <div
        className="absolute -top-16 -left-16 w-64 h-64 rounded-full bg-[#D95E00]/[0.08] blur-3xl pointer-events-none"
        aria-hidden="true"
      />
      <div
        className="absolute -bottom-16 -right-16 w-64 h-64 rounded-full bg-[#0A7A75]/[0.08] blur-3xl pointer-events-none"
        aria-hidden="true"
      />

      {/* Liquid Metal Panel Outer Container */}
      <div className="liquid-metal-panel shadow-2xl relative rounded-2xl overflow-hidden">
        <BorderBeam size={220} duration={10} colorFrom="#D95E00" colorTo="#0A7A75" />
        {/* Precision Inner Card Surface */}
        <div className="liquid-metal-content p-6 sm:p-8 flex flex-col items-center space-y-6">
          {children}
        </div>
      </div>
    </div>
  );
}
