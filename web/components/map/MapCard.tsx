"use client";

import React, { useState } from "react";
import {
  Anchor,
  Globe2,
  Layers,
  MapPin,
  Navigation,
  Ship,
  Truck,
  Wind,
  X,
  Zap,
} from "lucide-react";
import { EvidenceBadge } from "../ui/Badges";
import type { DataProvenance } from "@/lib/api/types";

export interface MapEntity {
  id: string;
  name: string;
  type: "vessel" | "aircraft" | "truck" | "port" | "facility";
  lat: number;
  lng: number;
  provenance: DataProvenance;
  speed_knots?: number;
  heading_degrees?: number;
  carrier?: string;
  shipment_id?: string;
  destination?: string;
  eta?: string;
  risk_level?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  last_ping?: string;
}

export function MapCard({
  entities = [],
  title = "Global Supply Chain AIS & Telemetry Map",
  className = "",
  height = "h-[450px]",
}: {
  entities?: MapEntity[];
  title?: string;
  className?: string;
  height?: string;
}) {
  const [selectedEntity, setSelectedEntity] = useState<MapEntity | null>(null);
  const [activeLayers, setActiveLayers] = useState({
    maritime: true,
    aviation: true,
    road: true,
    ports: true,
    weather: true,
  });

  const toggleLayer = (layer: keyof typeof activeLayers) => {
    setActiveLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  };

  return (
    <div
      className={`relative rounded-lg border border-[#243044] bg-[#0B0F14] overflow-hidden flex flex-col ${height} ${className}`}
    >
      {/* Top Header & Layer Filter Controls */}
      <div className="absolute top-3 left-3 right-3 z-10 flex flex-wrap items-center justify-between gap-2 pointer-events-none">
        <div className="bg-[#111827]/90 backdrop-blur border border-[#243044] px-3 py-1.5 rounded-md flex items-center gap-2 pointer-events-auto shadow-lg">
          <Globe2 className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-semibold text-slate-200">{title}</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
            {entities.length} Telemetry Nodes
          </span>
        </div>

        {/* Layer toggles */}
        <div className="bg-[#111827]/90 backdrop-blur border border-[#243044] p-1 rounded-md flex items-center gap-1 pointer-events-auto shadow-lg text-[11px]">
          <button
            onClick={() => toggleLayer("maritime")}
            className={`px-2 py-1 rounded flex items-center gap-1 transition-colors ${
              activeLayers.maritime
                ? "bg-blue-600/30 text-blue-300 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Ship className="w-3 h-3" /> Maritime
          </button>
          <button
            onClick={() => toggleLayer("road")}
            className={`px-2 py-1 rounded flex items-center gap-1 transition-colors ${
              activeLayers.road
                ? "bg-blue-600/30 text-blue-300 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Truck className="w-3 h-3" /> Road/Rail
          </button>
          <button
            onClick={() => toggleLayer("ports")}
            className={`px-2 py-1 rounded flex items-center gap-1 transition-colors ${
              activeLayers.ports
                ? "bg-blue-600/30 text-blue-300 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Anchor className="w-3 h-3" /> Hubs
          </button>
          <button
            onClick={() => toggleLayer("weather")}
            className={`px-2 py-1 rounded flex items-center gap-1 transition-colors ${
              activeLayers.weather
                ? "bg-blue-600/30 text-blue-300 font-medium"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Wind className="w-3 h-3" /> Weather
          </button>
        </div>
      </div>

      {/* Dark Tactical Map Canvas */}
      <div className="flex-1 w-full h-full relative bg-[#070A0E] flex items-center justify-center overflow-hidden">
        {/* World Grid & Tactical Radar Overlay */}
        <svg
          className="absolute inset-0 w-full h-full opacity-30 pointer-events-none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1E293B" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
          {/* Latitude lines */}
          <line x1="0" y1="25%" x2="100%" y2="25%" stroke="#1E293B" strokeDasharray="4 4" />
          <line x1="0" y1="50%" x2="100%" y2="50%" stroke="#334155" strokeWidth="1" />
          <line x1="0" y1="75%" x2="100%" y2="75%" stroke="#1E293B" strokeDasharray="4 4" />
        </svg>

        {/* Global Continental Outline Watermark */}
        <div className="absolute inset-0 flex items-center justify-center opacity-15 pointer-events-none">
          <Globe2 className="w-[450px] h-[450px] text-blue-400/30" />
        </div>

        {/* Render entities */}
        {entities.length === 0 ? (
          <div className="z-10 text-center p-6 bg-[#111827]/80 backdrop-blur rounded-lg border border-[#243044]">
            <MapPin className="w-8 h-8 text-slate-500 mx-auto mb-2" />
            <p className="text-xs font-semibold text-slate-300">No Active Physical Telemetry Ping</p>
            <p className="text-[11px] text-slate-500 mt-1 font-mono">
              Live AIS / GPS tracking awaits telemetry ingestion
            </p>
          </div>
        ) : (
          <div className="relative w-full h-full">
            {entities.map((ent) => {
              // Convert lat/lng to roughly normalized container percentage coordinates
              const top = `${Math.min(Math.max((90 - ent.lat) / 1.8, 5), 90)}%`;
              const left = `${Math.min(Math.max((ent.lng + 180) / 3.6, 5), 95)}%`;

              const isSelected = selectedEntity?.id === ent.id;

              return (
                <button
                  key={ent.id}
                  onClick={() => setSelectedEntity(ent)}
                  style={{ top, left }}
                  className={`absolute -translate-x-1/2 -translate-y-1/2 group p-1.5 rounded-full transition-all cursor-pointer ${
                    isSelected
                      ? "ring-2 ring-blue-400 bg-blue-600 text-white z-20 scale-125"
                      : "bg-[#111827] border border-blue-500/60 text-blue-400 hover:scale-110 hover:border-blue-400 z-10"
                  }`}
                  title={`${ent.name} (${ent.type})`}
                >
                  {ent.type === "vessel" ? (
                    <Ship className="w-3.5 h-3.5" />
                  ) : ent.type === "port" ? (
                    <Anchor className="w-3.5 h-3.5" />
                  ) : (
                    <Truck className="w-3.5 h-3.5" />
                  )}
                  {/* Radar pulse ring */}
                  <span className="pulse-dot bg-blue-400 absolute top-0 right-0" />
                </button>
              );
            })}
          </div>
        )}

        {/* Selected Entity Drawer */}
        {selectedEntity && (
          <div className="absolute right-3 top-14 bottom-3 w-80 bg-[#111827]/95 backdrop-blur border border-[#243044] rounded-lg shadow-2xl z-30 p-4 flex flex-col justify-between animate-in slide-in-from-right duration-200">
            <div>
              <div className="flex items-start justify-between gap-2 border-b border-[#243044] pb-3 mb-3">
                <div>
                  <h4 className="text-sm font-bold text-slate-100">{selectedEntity.name}</h4>
                  <span className="text-[10px] font-mono text-slate-400 uppercase">
                    {selectedEntity.type} • ID: {selectedEntity.id}
                  </span>
                </div>
                <button
                  onClick={() => setSelectedEntity(null)}
                  className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div className="space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Provenance</span>
                  <EvidenceBadge source={selectedEntity.provenance} />
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Coordinates</span>
                  <span className="font-mono text-slate-200">
                    {selectedEntity.lat.toFixed(4)}°, {selectedEntity.lng.toFixed(4)}°
                  </span>
                </div>

                {selectedEntity.carrier && (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Carrier</span>
                    <span className="font-semibold text-slate-200">{selectedEntity.carrier}</span>
                  </div>
                )}

                {selectedEntity.speed_knots !== undefined && (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Speed</span>
                    <span className="font-mono text-slate-200">
                      {selectedEntity.speed_knots} knots
                    </span>
                  </div>
                )}

                {selectedEntity.destination && (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Destination</span>
                    <span className="text-slate-200">{selectedEntity.destination}</span>
                  </div>
                )}

                {selectedEntity.shipment_id && (
                  <div className="p-2.5 rounded bg-[#1A2332] border border-slate-800">
                    <span className="text-[10px] uppercase font-mono text-slate-400 block mb-1">
                      Linked Active Shipment
                    </span>
                    <a
                      href={`/shipments/${selectedEntity.shipment_id}`}
                      className="text-xs font-mono text-blue-400 hover:underline block truncate"
                    >
                      {selectedEntity.shipment_id}
                    </a>
                  </div>
                )}
              </div>
            </div>

            <div className="pt-3 border-t border-[#243044] text-[10px] font-mono text-slate-500">
              Telemetry Status: Active Ping
            </div>
          </div>
        )}
      </div>

      {/* Legend & Watermark */}
      <div className="px-3 py-2 bg-[#0F172A] border-t border-[#243044] flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400" /> REAL (Physical)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400" /> ESTIMATED
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-purple-400" /> SIMULATED
          </span>
        </div>
        <span className="text-slate-500">WGS-84 Coordinate Grid</span>
      </div>
    </div>
  );
}
