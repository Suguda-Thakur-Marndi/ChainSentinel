"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Shield,
  ShieldCheck,
  Cpu,
  Layers,
  RotateCw,
  Eye,
  Sliders,
  Sparkles,
  Zap,
  Activity,
  AlertCircle,
  Terminal,
} from "lucide-react";

interface SecurityNode {
  id: string;
  name: string;
  role: string;
  status: "OPTIMAL" | "ACTIVE" | "VERIFIED" | "GUARDED";
  metric: string;
  metricLabel: string;
  x: number;
  y: number;
  z: number;
  accent: string;
}

const SECURITY_NODES: SecurityNode[] = [
  {
    id: "mcp-gateway",
    name: "MCP TOOL GATEWAY",
    role: "Sandboxed MCP Protocol Interconnect",
    status: "VERIFIED",
    metric: "18 Tools",
    metricLabel: "Active Schemas",
    x: -120,
    y: -80,
    z: 40,
    accent: "#0A7A75", // Teal
  },
  {
    id: "identity-sentinel",
    name: "AUTH SENTINEL",
    role: "Zero-Trust RBAC & Session Boundary",
    status: "GUARDED",
    metric: "0 Leaks",
    metricLabel: "HttpOnly Boundary",
    x: 120,
    y: -80,
    z: 50,
    accent: "#D95E00", // Burnt Orange
  },
  {
    id: "risk-engine",
    name: "DETERMINISTIC ENGINE",
    role: "Graph Path Optimization & Verification",
    status: "OPTIMAL",
    metric: "14ms",
    metricLabel: "P99 Compute Latency",
    x: -110,
    y: 90,
    z: 35,
    accent: "#0A7A75", // Teal
  },
  {
    id: "mitigation-dispatcher",
    name: "AUTONOMOUS DISPATCH",
    role: "Human-in-the-Loop Threshold Gate",
    status: "ACTIVE",
    metric: "$50k Cap",
    metricLabel: "Escalation Policy",
    x: 110,
    y: 90,
    z: 45,
    accent: "#E88D00", // Amber
  },
];

export function SecurityMachine3D({
  activePostureScore = 99.4,
  mitigationsCount = 12,
  threatsBlocked = 4,
}: {
  activePostureScore?: number;
  mitigationsCount?: number;
  threatsBlocked?: number;
}) {
  const [isRotating, setIsRotating] = useState(true);
  const [isExploded, setIsExploded] = useState(false);
  const [force2D, setForce2D] = useState(false);
  const [activeNode, setActiveNode] = useState<SecurityNode>(SECURITY_NODES[0]);
  const [rotationAngle, setRotationAngle] = useState(0);
  const [tiltAngle, setTiltAngle] = useState(55);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
  const animationFrameRef = useRef<number | null>(null);

  // Check system prefers-reduced-motion
  useEffect(() => {
    if (typeof window !== "undefined") {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      setPrefersReducedMotion(mq.matches);
      if (mq.matches) {
        setIsRotating(false);
      }
      const listener = (e: MediaQueryListEvent) => {
        setPrefersReducedMotion(e.matches);
        if (e.matches) setIsRotating(false);
      };
      mq.addEventListener("change", listener);
      return () => mq.removeEventListener("change", listener);
    }
  }, []);

  // Continuous subtle 3D turntable rotation
  useEffect(() => {
    if (!isRotating || force2D || prefersReducedMotion) return;

    let lastTime = performance.now();
    const animate = (time: number) => {
      const delta = time - lastTime;
      lastTime = time;
      setRotationAngle((prev) => (prev + delta * 0.015) % 360);
      animationFrameRef.current = requestAnimationFrame(animate);
    };

    animationFrameRef.current = requestAnimationFrame(animate);
    return () => {
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    };
  }, [isRotating, force2D, prefersReducedMotion]);

  const layerZMultiplier = isExploded ? 2.2 : 1.0;

  return (
    <div
      role="region"
      aria-label="3D Security Machine Architecture Visualization"
      className="relative w-full rounded-xl border border-arch bg-card/60 backdrop-blur-md overflow-hidden flex flex-col transition-all duration-300 shadow-arch-md group"
      style={{
        backgroundColor: "var(--bg-card)",
        borderColor: "var(--border-arch)",
      }}
    >
      {/* Header Bar with Status & Controls */}
      <div
        className="px-4 py-3 border-b flex items-center justify-between z-20"
        style={{ borderColor: "var(--border-arch)", backgroundColor: "var(--bg-card-elevated)" }}
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded bg-arch-orange/10 border border-arch-orange/30 text-[#D95E00]">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold tracking-wider font-mono text-foreground uppercase">
                SECURITY MACHINE // ARCHITECTURAL CORE
              </span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-[#0A7A75]/15 text-[#0A7A75] border border-[#0A7A75]/30 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-[#0A7A75] animate-pulse" />
                DETERMINISTIC
              </span>
            </div>
            <span className="text-[11px] text-muted-foreground font-mono">
              Autonomous Policy Enforcer & Telemetry Pipeline
            </span>
          </div>
        </div>

        {/* Tactical Interaction Controls */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setIsRotating(!isRotating)}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 border transition-all ${
              isRotating
                ? "bg-[#D95E00]/15 text-[#D95E00] border-[#D95E00]/40 shadow-sm"
                : "bg-surface text-muted-foreground border-arch hover:text-foreground"
            }`}
            title="Toggle Continuous 3D Orbit"
          >
            <RotateCw className={`w-3 h-3 ${isRotating ? "animate-spin" : ""}`} style={{ animationDuration: "8s" }} />
            <span className="hidden sm:inline">{isRotating ? "ORBIT ON" : "ORBIT OFF"}</span>
          </button>

          <button
            onClick={() => setIsExploded(!isExploded)}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 border transition-all ${
              isExploded
                ? "bg-[#0A7A75]/15 text-[#0A7A75] border-[#0A7A75]/40"
                : "bg-surface text-muted-foreground border-arch hover:text-foreground"
            }`}
            title="Explode 3D Structural Layers"
          >
            <Layers className="w-3 h-3" />
            <span className="hidden sm:inline">{isExploded ? "COLLAPSE" : "EXPLODE"}</span>
          </button>

          <button
            onClick={() => setForce2D(!force2D)}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 border transition-all ${
              force2D
                ? "bg-slate-700 text-white border-slate-500"
                : "bg-surface text-muted-foreground border-arch hover:text-foreground"
            }`}
            title="Switch between 3D Spatial and 2D Architectural Schematic"
          >
            <Sliders className="w-3 h-3" />
            <span className="hidden sm:inline">{force2D ? "3D MODE" : "2D FLAT"}</span>
          </button>
        </div>
      </div>

      {/* Main 3D Canvas / Viewport */}
      <div className="relative h-[340px] sm:h-[400px] w-full flex items-center justify-center overflow-hidden bg-grid-architectural select-none">
        {/* Subtle Ambient Radial Lighting */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "radial-gradient(circle at 50% 50%, rgba(217, 94, 0, 0.08) 0%, rgba(10, 122, 117, 0.04) 45%, transparent 75%)",
          }}
        />

        {/* 2D Fallback View when requested or under reduced motion */}
        {force2D || prefersReducedMotion ? (
          <div className="relative w-full h-full p-6 flex flex-col justify-between z-10">
            <div className="flex items-center justify-between text-xs font-mono text-muted-foreground border-b border-arch pb-2">
              <span className="flex items-center gap-1.5">
                <Terminal className="w-3.5 h-3.5 text-[#D95E00]" />
                2D ARCHITECTURAL SECURITY SCHEMATIC
              </span>
              <span className="text-[#0A7A75]">ALL SYSTEMS VERIFIED</span>
            </div>

            {/* Schematic Node Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 my-auto">
              {SECURITY_NODES.map((node) => (
                <div
                  key={node.id}
                  onClick={() => setActiveNode(node)}
                  className={`p-3 rounded border transition-all cursor-pointer ${
                    activeNode.id === node.id
                      ? "bg-arch-elevated border-[#D95E00] shadow-md"
                      : "bg-surface/80 border-arch hover:border-slate-500"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-mono text-muted-foreground uppercase">{node.status}</span>
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: node.accent }}
                    />
                  </div>
                  <div className="text-xs font-bold text-foreground truncate">{node.name}</div>
                  <div className="text-[11px] font-mono text-[#D95E00] mt-1">{node.metric}</div>
                  <div className="text-[10px] text-muted-foreground truncate">{node.metricLabel}</div>
                </div>
              ))}
            </div>

            <div className="p-3 rounded bg-surface border border-arch text-xs font-mono flex items-center justify-between">
              <span className="text-muted-foreground">Active Security Machine Core:</span>
              <span className="text-[#D95E00] font-bold">{activePostureScore}% Posture Verified</span>
            </div>
          </div>
        ) : (
          /* True 3D CSS Transform Isometric Machine */
          <div
            className="relative w-full h-full flex items-center justify-center perspective-1000"
            style={{ perspective: "1100px" }}
          >
            {/* The 3D World Stage */}
            <div
              className="relative transform-style-3d transition-transform duration-150"
              style={{
                transform: `rotateX(${tiltAngle}deg) rotateZ(${rotationAngle}deg)`,
                width: "280px",
                height: "280px",
              }}
            >
              {/* Foundation Tier 0: Ground Radar Ring */}
              <div
                className="absolute inset-0 rounded-full border border-dashed border-[#243044] transform-style-3d pointer-events-none"
                style={{
                  transform: `translateZ(${-30 * layerZMultiplier}px)`,
                  boxShadow: "inset 0 0 40px rgba(10, 122, 117, 0.08)",
                }}
              >
                {/* Rotating Laser Sweep */}
                <div
                  className="w-full h-full rounded-full animate-spin"
                  style={{
                    animationDuration: "12s",
                    background:
                      "conic-gradient(from 0deg, rgba(217, 94, 0, 0.15) 0deg, rgba(10, 122, 117, 0.05) 60deg, transparent 120deg)",
                  }}
                />
              </div>

              {/* Foundation Tier 1: Substrate Chassis Layer */}
              <div
                className="absolute inset-4 rounded-xl border border-arch bg-[#0F172A]/70 backdrop-blur-sm transform-style-3d transition-all duration-300"
                style={{
                  transform: `translateZ(${-10 * layerZMultiplier}px)`,
                  boxShadow: "0 10px 30px rgba(0, 0, 0, 0.5)",
                }}
              >
                {/* Coordinate Grid on Substrate */}
                <div className="absolute inset-0 bg-grid-architectural opacity-40 rounded-xl" />
                <div className="absolute top-2 left-2 text-[8px] font-mono text-muted-foreground/60 tracking-widest">
                  SYS://SENTINEL-CORE-V4
                </div>
                <div className="absolute bottom-2 right-2 text-[8px] font-mono text-[#0A7A75]/80">
                  LATENCY 14MS
                </div>
              </div>

              {/* Central Core: The Security Reactor Prism */}
              <div
                className="absolute top-1/2 left-1/2 -mt-10 -ml-10 w-20 h-20 transform-style-3d transition-all duration-300"
                style={{
                  transform: `translateZ(${25 * layerZMultiplier}px)`,
                }}
              >
                {/* Glowing Core Reactor Face */}
                <div className="w-full h-full rounded-lg bg-gradient-to-br from-[#D95E00]/40 via-[#0A7A75]/30 to-[#0B0F14] border-2 border-[#D95E00] shadow-[0_0_25px_rgba(217,94,0,0.4)] flex flex-col items-center justify-center p-1">
                  <div className="w-7 h-7 rounded-full bg-[#D95E00]/20 border border-[#D95E00] flex items-center justify-center animate-pulse">
                    <ShieldCheck className="w-4 h-4 text-[#D95E00]" />
                  </div>
                  <span className="text-[9px] font-bold font-mono text-white mt-1">CORE 99.4%</span>
                </div>

                {/* Floating Core Holographic Shield Ring */}
                <div
                  className="absolute -inset-4 rounded-full border border-dashed border-[#D95E00]/60 pointer-events-none animate-spin"
                  style={{ animationDuration: "16s" }}
                />
              </div>

              {/* Tier 2: Floating Satellite Nodes */}
              {SECURITY_NODES.map((node) => {
                const isSelected = activeNode.id === node.id;
                return (
                  <div
                    key={node.id}
                    onClick={() => setActiveNode(node)}
                    className="absolute cursor-pointer transform-style-3d group/node"
                    style={{
                      left: `calc(50% + ${node.x}px - 45px)`,
                      top: `calc(50% + ${node.y}px - 25px)`,
                      transform: `translateZ(${node.z * layerZMultiplier}px)`,
                    }}
                  >
                    {/* Laser Connector to Core */}
                    <div
                      className="absolute top-1/2 left-1/2 h-[1px] pointer-events-none origin-left opacity-40 transition-opacity group-hover/node:opacity-90"
                      style={{
                        width: Math.hypot(node.x, node.y),
                        transform: `rotate(${Math.atan2(-node.y, -node.x)}rad)`,
                        backgroundColor: node.accent,
                        boxShadow: `0 0 6px ${node.accent}`,
                      }}
                    />

                    {/* Node Chip Card */}
                    <div
                      className={`w-[96px] p-2 rounded-lg border backdrop-blur-md transition-all duration-200 transform hover:scale-110 ${
                        isSelected
                          ? "bg-slate-900/95 border-[#D95E00] shadow-[0_0_15px_rgba(217,94,0,0.5)]"
                          : "bg-[#0F172A]/85 border-slate-700/80 hover:border-slate-400"
                      }`}
                      style={{
                        // Counter-rotate text so it stays readable when orbiting
                        transform: `rotateZ(${-rotationAngle}deg) rotateX(${-tiltAngle}deg)`,
                      }}
                    >
                      <div className="flex items-center justify-between gap-1 mb-1">
                        <span
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ backgroundColor: node.accent }}
                        />
                        <span className="text-[8px] font-mono text-slate-400 uppercase tracking-tighter truncate">
                          {node.status}
                        </span>
                      </div>
                      <div className="text-[9px] font-bold text-slate-100 truncate tracking-tight">
                        {node.name}
                      </div>
                      <div className="text-[10px] font-mono font-bold text-[#D95E00] mt-0.5">
                        {node.metric}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* HUD Telemetry Overlay: Bottom Left */}
        <div className="absolute bottom-3 left-3 z-20 pointer-events-none sm:pointer-events-auto">
          <div className="p-2.5 rounded-lg bg-[#0F172A]/90 border border-arch backdrop-blur-md text-xs font-mono space-y-1 shadow-lg max-w-[210px]">
            <div className="flex items-center justify-between gap-3 text-[10px] text-muted-foreground">
              <span>ACTIVE NODE:</span>
              <span className="font-bold text-foreground truncate">{activeNode.name}</span>
            </div>
            <div className="text-[11px] text-[#D95E00] font-semibold">{activeNode.role}</div>
            <div className="flex items-center justify-between text-[10px] text-slate-400 pt-1 border-t border-slate-800">
              <span>{activeNode.metricLabel}:</span>
              <span className="text-emerald-400 font-bold">{activeNode.metric}</span>
            </div>
          </div>
        </div>

        {/* HUD Status Badges: Top Right Overlay */}
        <div className="absolute top-3 right-3 z-20 flex flex-col items-end gap-1.5 pointer-events-none">
          <div className="px-2 py-1 rounded bg-[#0F172A]/90 border border-arch backdrop-blur-md text-[11px] font-mono flex items-center gap-2">
            <span className="text-muted-foreground">POSTURE SCORE:</span>
            <span className="text-emerald-400 font-bold">{activePostureScore}%</span>
          </div>
          <div className="px-2 py-1 rounded bg-[#0F172A]/90 border border-arch backdrop-blur-md text-[11px] font-mono flex items-center gap-2">
            <span className="text-muted-foreground">MITIGATIONS:</span>
            <span className="text-[#D95E00] font-bold">{mitigationsCount} DISPATCHED</span>
          </div>
          <div className="px-2 py-1 rounded bg-[#0F172A]/90 border border-arch backdrop-blur-md text-[11px] font-mono flex items-center gap-2">
            <span className="text-muted-foreground">ZERO-TRUST:</span>
            <span className="text-[#0A7A75] font-bold">100% ENFORCED</span>
          </div>
        </div>
      </div>

      {/* Footer Audit Bar */}
      <div
        className="px-4 py-2 border-t flex flex-wrap items-center justify-between text-xs font-mono text-muted-foreground"
        style={{ borderColor: "var(--border-arch)", backgroundColor: "var(--bg-card)" }}
      >
        <div className="flex items-center gap-2">
          <Activity className="w-3.5 h-3.5 text-[#0A7A75]" />
          <span>Real-time Hardware & Policy Consensus: NOMINAL</span>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span>Rotate: {Math.round(rotationAngle)}°</span>
          <span>Tilt: {tiltAngle}°</span>
          <span className="text-[#D95E00]">SHA256://EVIDENCE-VERIFIED</span>
        </div>
      </div>
    </div>
  );
}
