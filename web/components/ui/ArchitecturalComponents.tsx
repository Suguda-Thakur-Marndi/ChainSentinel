"use client";

import React, { createContext, useContext, useState } from "react";
import { X } from "lucide-react";

// ==========================================
// 1. BUTTON (shadcn-inspired with Architectural Tokens)
// ==========================================
export interface ArchButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "outline" | "destructive" | "teal" | "ghost";
  size?: "sm" | "md" | "lg" | "icon";
  isLoading?: boolean;
}

export function ArchButton({
  children,
  variant = "default",
  size = "md",
  isLoading = false,
  className = "",
  disabled,
  ...props
}: ArchButtonProps) {
  const baseStyles =
    "inline-flex items-center justify-center font-medium font-mono text-xs transition-all duration-150 rounded cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed select-none active:scale-[0.98]";

  let sizeStyles = "px-3.5 py-2 gap-2";
  if (size === "sm") sizeStyles = "px-2.5 py-1 text-[11px] gap-1.5";
  if (size === "lg") sizeStyles = "px-5 py-2.5 text-sm gap-2.5";
  if (size === "icon") sizeStyles = "p-2 w-8 h-8";

  let variantStyles = "";
  if (variant === "default") {
    // Burnt Orange Architectural Primary
    variantStyles =
      "bg-[#D95E00] text-white hover:bg-[#BF5300] shadow-sm shadow-[#D95E00]/20 border border-[#D95E00]";
  } else if (variant === "teal") {
    // Teal Secondary Accent
    variantStyles =
      "bg-[#0A7A75] text-white hover:bg-[#08635F] shadow-sm shadow-[#0A7A75]/20 border border-[#0A7A75]";
  } else if (variant === "secondary") {
    variantStyles =
      "bg-surface text-foreground hover:bg-surface-high border border-arch";
  } else if (variant === "outline") {
    variantStyles =
      "bg-transparent text-foreground hover:bg-surface border border-arch hover:border-[#D95E00]/60";
  } else if (variant === "destructive") {
    variantStyles =
      "bg-[#B71C1C] text-white hover:bg-[#991B1B] border border-[#B71C1C]";
  } else if (variant === "ghost") {
    variantStyles =
      "bg-transparent text-muted-foreground hover:text-foreground hover:bg-surface";
  }

  return (
    <button
      disabled={disabled || isLoading}
      className={`${baseStyles} ${sizeStyles} ${variantStyles} ${className}`}
      {...props}
    >
      {isLoading ? (
        <span className="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : null}
      {children}
    </button>
  );
}

export interface ArchCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  elevated?: boolean;
}

export function ArchCard({
  children,
  className = "",
  elevated = false,
  onClick,
  ...props
}: ArchCardProps) {
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border border-arch ${
        elevated ? "bg-arch-elevated shadow-arch-md" : "bg-card shadow-arch-sm"
      } transition-colors ${className}`}
      style={{
        backgroundColor: elevated ? "var(--bg-card-elevated)" : "var(--bg-card)",
        borderColor: "var(--border-arch)",
      }}
      {...props}
    >
      {children}
    </div>
  );
}

export function ArchCardHeader({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`px-5 py-4 border-b border-arch flex flex-col space-y-1.5 ${className}`}
      style={{ borderColor: "var(--border-arch)" }}
    >
      {children}
    </div>
  );
}

export function ArchCardTitle({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <h3 className={`text-sm font-bold tracking-tight text-foreground ${className}`}>
      {children}
    </h3>
  );
}

export function ArchCardDescription({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p className={`text-xs text-muted-foreground ${className}`}>
      {children}
    </p>
  );
}

export function ArchCardContent({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={`p-5 ${className}`}>{children}</div>;
}

export function ArchCardFooter({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`px-5 py-3 border-t border-arch flex items-center justify-between bg-surface/40 ${className}`}
      style={{ borderColor: "var(--border-arch)" }}
    >
      {children}
    </div>
  );
}

// ==========================================
// 3. BADGE (Architectural Status Indicator)
// ==========================================
export function ArchBadge({
  children,
  variant = "default",
  className = "",
}: {
  children: React.ReactNode;
  variant?: "default" | "orange" | "teal" | "amber" | "danger" | "outline";
  className?: string;
}) {
  let style = "bg-surface text-foreground border-arch";
  if (variant === "orange") {
    style = "bg-[#D95E00]/15 text-[#D95E00] border-[#D95E00]/40";
  } else if (variant === "teal") {
    style = "bg-[#0A7A75]/15 text-[#0A7A75] border-[#0A7A75]/40";
  } else if (variant === "amber") {
    style = "bg-[#E88D00]/15 text-[#E88D00] border-[#E88D00]/40";
  } else if (variant === "danger") {
    style = "bg-[#B71C1C]/15 text-rose-400 border-[#B71C1C]/40";
  } else if (variant === "outline") {
    style = "bg-transparent text-muted-foreground border-arch";
  }

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-semibold tracking-wider uppercase border ${style} ${className}`}
    >
      {children}
    </span>
  );
}

// ==========================================
// 4. TABS (shadcn-inspired Tab Switcher)
// ==========================================
interface TabsContextType {
  activeTab: string;
  setActiveTab: (val: string) => void;
}
const TabsContext = createContext<TabsContextType>({ activeTab: "", setActiveTab: () => {} });

export function ArchTabs({
  defaultValue,
  children,
  className = "",
}: {
  defaultValue: string;
  children: React.ReactNode;
  className?: string;
}) {
  const [activeTab, setActiveTab] = useState(defaultValue);
  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab }}>
      <div className={`space-y-4 ${className}`}>{children}</div>
    </TabsContext.Provider>
  );
}

export function ArchTabsList({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`inline-flex items-center p-1 rounded-lg border border-arch bg-surface ${className}`}
      style={{ borderColor: "var(--border-arch)", backgroundColor: "var(--bg-secondary)" }}
    >
      {children}
    </div>
  );
}

export function ArchTabsTrigger({
  value,
  children,
  className = "",
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const { activeTab, setActiveTab } = useContext(TabsContext);
  const isActive = activeTab === value;

  return (
    <button
      onClick={() => setActiveTab(value)}
      className={`px-3 py-1.5 rounded text-xs font-mono font-medium transition-all ${
        isActive
          ? "bg-arch-card text-[#D95E00] border border-arch shadow-sm"
          : "text-muted-foreground hover:text-foreground"
      } ${className}`}
      style={
        isActive
          ? {
              backgroundColor: "var(--bg-card)",
              color: "#D95E00",
              borderColor: "var(--border-arch)",
            }
          : {}
      }
    >
      {children}
    </button>
  );
}

export function ArchTabsContent({
  value,
  children,
  className = "",
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const { activeTab } = useContext(TabsContext);
  if (activeTab !== value) return null;
  return <div className={`animate-in fade-in-50 duration-150 ${className}`}>{children}</div>;
}

// ==========================================
// 5. MODAL / DIALOG (Accessible Inspection Overlay)
// ==========================================
export function ArchModal({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl rounded-xl border border-arch bg-card shadow-arch-lg overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-200"
        style={{
          backgroundColor: "var(--bg-card)",
          borderColor: "var(--border-arch)",
        }}
      >
        {/* Modal Header */}
        <div
          className="px-5 py-4 border-b border-arch flex items-center justify-between"
          style={{
            borderColor: "var(--border-arch)",
            backgroundColor: "var(--bg-card-elevated)",
          }}
        >
          <div>
            <h2 className="text-sm font-bold text-foreground tracking-tight font-mono uppercase">
              {title}
            </h2>
            {subtitle && (
              <p className="text-xs text-muted-foreground font-mono mt-0.5">{subtitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-surface transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-5 overflow-y-auto space-y-4 text-xs font-mono">{children}</div>
      </div>
    </div>
  );
}
