import React from "react";

interface AuthCardProps {
  children: React.ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  return (
    <div className="w-full max-w-[420px] relative">
      {/* Restrained Ambient Backlight (Dark blue/slate gradient) */}
      <div
        className="absolute -top-16 -left-16 w-64 h-64 rounded-full bg-blue-600/[0.07] blur-3xl pointer-events-none"
        aria-hidden="true"
      />
      <div
        className="absolute -bottom-16 -right-16 w-64 h-64 rounded-full bg-indigo-600/[0.05] blur-3xl pointer-events-none"
        aria-hidden="true"
      />

      {/* Liquid Metal Panel Outer Container */}
      <div className="liquid-metal-panel shadow-2xl relative">
        {/* Precision Inner Card Surface */}
        <div className="liquid-metal-content p-6 sm:p-8 flex flex-col items-center space-y-6">
          {children}
        </div>
      </div>
    </div>
  );
}
