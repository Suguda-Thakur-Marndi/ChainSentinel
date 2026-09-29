"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Anchor,
  Globe2,
  MapPin,
  Ship,
  Truck,
  Wind,
  X,
  AlertTriangle,
  ExternalLink,
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

// Tactical Dark Theme for Google Maps
const TACTICAL_DARK_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#0B0F14" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0B0F14" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#64748B" }] },
  {
    featureType: "administrative.locality",
    elementType: "labels.text.fill",
    stylers: [{ color: "#94A3B8" }],
  },
  {
    featureType: "poi",
    elementType: "labels.text.fill",
    stylers: [{ color: "#475569" }],
  },
  {
    featureType: "poi.park",
    elementType: "geometry",
    stylers: [{ color: "#111827" }],
  },
  {
    featureType: "road",
    elementType: "geometry",
    stylers: [{ color: "#1E293B" }],
  },
  {
    featureType: "road",
    elementType: "geometry.stroke",
    stylers: [{ color: "#0F172A" }],
  },
  {
    featureType: "road",
    elementType: "labels.text.fill",
    stylers: [{ color: "#64748B" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry",
    stylers: [{ color: "#334155" }],
  },
  {
    featureType: "transit",
    elementType: "geometry",
    stylers: [{ color: "#1E293B" }],
  },
  {
    featureType: "water",
    elementType: "geometry",
    stylers: [{ color: "#060A10" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.fill",
    stylers: [{ color: "#3B82F6" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.stroke",
    stylers: [{ color: "#070A0E" }],
  },
];

declare global {
  interface Window {
    google?: any;
    gm_authFailure?: () => void;
  }
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
  const [mapViewType, setMapViewType] = useState<"google-dark" | "google-satellite" | "tactical-radar">("google-dark");
  const [googleMapsReady, setGoogleMapsReady] = useState(false);
  const [googleMapsAuthError, setGoogleMapsAuthError] = useState<string | null>(null);

  const [activeLayers, setActiveLayers] = useState({
    maritime: true,
    aviation: true,
    road: true,
    ports: true,
    weather: true,
  });

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const googleMapInstanceRef = useRef<any>(null);
  const markersRef = useRef<any[]>([]);

  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";

  // 1. Google Maps JS SDK Loader & Auth Error Interceptor
  useEffect(() => {
    if (!apiKey) {
      setMapViewType("tactical-radar");
      return;
    }

    // Intercept Google Maps authentication/billing failures
    window.gm_authFailure = () => {
      console.warn("[RiskWise Maps] Google Maps authentication or billing failure detected.");
      setGoogleMapsAuthError(
        "Billing is not enabled on this Google Cloud Project. Please enable billing at console.cloud.google.com/project/_/billing/enable."
      );
    };

    if (window.google?.maps) {
      setGoogleMapsReady(true);
      return;
    }

    const scriptId = "google-maps-api-script";
    let script = document.getElementById(scriptId) as HTMLScriptElement | null;

    if (!script) {
      script = document.createElement("script");
      script.id = scriptId;
      script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=geometry`;
      script.async = true;
      script.defer = true;
      script.onload = () => {
        if (window.google?.maps) {
          setGoogleMapsReady(true);
        }
      };
      script.onerror = () => {
        setGoogleMapsAuthError("Failed to connect to Google Maps servers.");
      };
      document.head.appendChild(script);
    } else {
      script.addEventListener("load", () => {
        if (window.google?.maps) {
          setGoogleMapsReady(true);
        }
      });
    }
  }, [apiKey]);

  // 2. Initialize Google Map Instance
  useEffect(() => {
    if (!googleMapsReady || !mapContainerRef.current || !window.google?.maps) return;

    let isCancelled = false;

    async function setupMap() {
      try {
        let MapClass = window.google?.maps?.Map;
        if (!MapClass && window.google?.maps?.importLibrary) {
          const mapsLib = await window.google.maps.importLibrary("maps");
          MapClass = mapsLib.Map;
        }

        if (!MapClass || !mapContainerRef.current || isCancelled) return;

        if (!googleMapInstanceRef.current) {
          const isSatellite = mapViewType === "google-satellite";
          const initialMap = new MapClass(mapContainerRef.current, {
            center: { lat: 20, lng: 100 },
            zoom: 3,
            mapTypeId: isSatellite ? "hybrid" : "roadmap",
            styles: isSatellite ? [] : TACTICAL_DARK_STYLE,
            disableDefaultUI: false,
            zoomControl: true,
            mapTypeControl: false,
            streetViewControl: false,
            fullscreenControl: true,
            backgroundColor: "#070A0E",
          });

          googleMapInstanceRef.current = initialMap;
        } else {
          const isSatellite = mapViewType === "google-satellite";
          googleMapInstanceRef.current.setMapTypeId(isSatellite ? "hybrid" : "roadmap");
          googleMapInstanceRef.current.setOptions({
            styles: isSatellite ? [] : TACTICAL_DARK_STYLE,
          });
        }
      } catch (err) {
        console.warn("[RiskWise Maps] Error initializing Google Map:", err);
      }
    }

    setupMap();

    return () => {
      isCancelled = true;
    };
  }, [googleMapsReady, mapViewType]);

  // 3. Sync Markers on Google Map with Entities & Layer Visibility
  useEffect(() => {
    if (!googleMapInstanceRef.current || !window.google?.maps) return;

    const MarkerClass = window.google?.maps?.Marker;
    const LatLngBoundsClass = window.google?.maps?.LatLngBounds;
    const SymbolPathObj = window.google?.maps?.SymbolPath;

    if (!MarkerClass || !LatLngBoundsClass) return;

    // Clear existing markers
    markersRef.current.forEach((m) => m.setMap(null));
    markersRef.current = [];

    const bounds = new LatLngBoundsClass();
    let hasCoords = false;

    entities.forEach((ent) => {
      // Check layer filtering
      if (ent.type === "vessel" && !activeLayers.maritime) return;
      if (ent.type === "truck" && !activeLayers.road) return;
      if (ent.type === "port" && !activeLayers.ports) return;

      const position = { lat: ent.lat, lng: ent.lng };
      bounds.extend(position);
      hasCoords = true;

      // Pin Color according to risk or type
      const pinColor =
        ent.risk_level === "CRITICAL"
          ? "#F43F5E"
          : ent.risk_level === "HIGH"
          ? "#FB923C"
          : ent.type === "vessel"
          ? "#38BDF8"
          : ent.type === "port"
          ? "#34D399"
          : "#60A5FA";

      const marker = new MarkerClass({
        position,
        map: googleMapInstanceRef.current,
        title: `${ent.name} (${ent.type})`,
        icon: {
          path: SymbolPathObj.CIRCLE,
          scale: 7,
          fillColor: pinColor,
          fillOpacity: 0.9,
          strokeColor: "#FFFFFF",
          strokeWeight: 1.5,
        },
      });

      marker.addListener("click", () => {
        setSelectedEntity(ent);
      });

      markersRef.current.push(marker);
    });

    if (hasCoords && entities.length > 0) {
      if (entities.length === 1) {
        googleMapInstanceRef.current.setCenter({ lat: entities[0].lat, lng: entities[0].lng });
        googleMapInstanceRef.current.setZoom(7);
      } else {
        googleMapInstanceRef.current.fitBounds(bounds, 50);
      }
    }
  }, [entities, googleMapsReady, activeLayers]);

  const toggleLayer = (layer: keyof typeof activeLayers) => {
    setActiveLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  };

  const filteredEntities = entities.filter((ent) => {
    if (ent.type === "vessel" && !activeLayers.maritime) return false;
    if (ent.type === "truck" && !activeLayers.road) return false;
    if (ent.type === "port" && !activeLayers.ports) return false;
    return true;
  });

  return (
    <div
      className={`relative rounded-lg border border-[#243044] bg-[#0B0F14] overflow-hidden flex flex-col ${height} ${className}`}
    >
      {/* Top Header & Layer Filter Controls */}
      <div className="absolute top-3 left-3 right-3 z-10 flex flex-wrap items-center justify-between gap-2 pointer-events-none">
        <div className="bg-[#111827]/95 backdrop-blur border border-[#243044] px-3 py-1.5 rounded-md flex items-center gap-2 pointer-events-auto shadow-lg">
          <Globe2 className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-semibold text-slate-200">{title}</span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-950 text-blue-300 border border-blue-800">
            {entities.length} Telemetry Nodes
          </span>
        </div>

        {/* Layer & Map View Mode Controls */}
        <div className="flex items-center gap-2 pointer-events-auto">
          {/* Map Type Switcher */}
          <div className="bg-[#111827]/95 backdrop-blur border border-[#243044] p-1 rounded-md flex items-center gap-1 shadow-lg text-[11px]">
            <button
              onClick={() => setMapViewType("google-dark")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                mapViewType === "google-dark"
                  ? "bg-blue-600 text-white font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              title="Google Maps Dark Mode"
            >
              Google Dark
            </button>
            <button
              onClick={() => setMapViewType("google-satellite")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                mapViewType === "google-satellite"
                  ? "bg-blue-600 text-white font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              title="Google Maps Satellite Hybrid"
            >
              Satellite
            </button>
            <button
              onClick={() => setMapViewType("tactical-radar")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                mapViewType === "tactical-radar"
                  ? "bg-blue-600 text-white font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
              title="Tactical Radar Grid"
            >
              Tactical SVG
            </button>
          </div>

          {/* Layer toggles */}
          <div className="bg-[#111827]/95 backdrop-blur border border-[#243044] p-1 rounded-md flex items-center gap-1 shadow-lg text-[11px]">
            <button
              onClick={() => toggleLayer("maritime")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                activeLayers.maritime
                  ? "bg-blue-600/30 text-blue-300 font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Ship className="w-3 h-3" /> Maritime
            </button>
            <button
              onClick={() => toggleLayer("road")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                activeLayers.road
                  ? "bg-blue-600/30 text-blue-300 font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Truck className="w-3 h-3" /> Road/Rail
            </button>
            <button
              onClick={() => toggleLayer("ports")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                activeLayers.ports
                  ? "bg-blue-600/30 text-blue-300 font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Anchor className="w-3 h-3" /> Hubs
            </button>
            <button
              onClick={() => toggleLayer("weather")}
              className={`px-2 py-1 rounded flex items-center gap-1 transition-colors cursor-pointer ${
                activeLayers.weather
                  ? "bg-blue-600/30 text-blue-300 font-medium"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <Wind className="w-3 h-3" /> Weather
            </button>
          </div>
        </div>
      </div>

      {/* Billing or Auth Error Notice Banner */}
      {googleMapsAuthError && (
        <div className="absolute top-14 left-3 right-3 z-20 bg-amber-950/90 border border-amber-600/60 rounded-md p-2.5 backdrop-blur flex items-start justify-between gap-3 shadow-xl text-xs text-amber-200">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-amber-100">Google Maps Billing Notice</p>
              <p className="text-[11px] text-amber-300/90 mt-0.5 leading-relaxed">
                {googleMapsAuthError}
              </p>
              <div className="flex items-center gap-2 mt-1.5">
                <a
                  href="https://console.cloud.google.com/project/_/billing/enable"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-300 underline hover:text-white"
                >
                  Enable Billing on Google Cloud <ExternalLink className="w-3 h-3" />
                </a>
                <span className="text-amber-500">•</span>
                <span className="text-[11px] text-amber-300/80">
                  Tactical SVG Radar remains 100% operational
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={() => setGoogleMapsAuthError(null)}
            className="text-amber-400 hover:text-amber-200 p-1"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Main Map Rendering Area */}
      <div className="flex-1 w-full h-full relative bg-[#070A0E] overflow-hidden">
        {/* GOOGLE MAP CANVAS */}
        <div
          ref={mapContainerRef}
          className={`absolute inset-0 w-full h-full transition-opacity duration-300 ${
            mapViewType !== "tactical-radar" ? "opacity-100 z-0 pointer-events-auto" : "opacity-0 -z-10 pointer-events-none"
          }`}
        />

        {/* TACTICAL SVG RADAR FALLBACK / VIEW */}
        {mapViewType === "tactical-radar" && (
          <div className="absolute inset-0 w-full h-full flex items-center justify-center overflow-hidden">
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

            {/* Render entities on Tactical Radar */}
            {filteredEntities.length === 0 ? (
              <div className="z-10 text-center p-6 bg-[#111827]/80 backdrop-blur rounded-lg border border-[#243044]">
                <MapPin className="w-8 h-8 text-slate-500 mx-auto mb-2" />
                <p className="text-xs font-semibold text-slate-300">No Active Physical Telemetry Ping</p>
                <p className="text-[11px] text-slate-500 mt-1 font-mono">
                  Live AIS / GPS tracking awaits telemetry ingestion
                </p>
              </div>
            ) : (
              <div className="relative w-full h-full">
                {filteredEntities.map((ent) => {
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
                      <span className="pulse-dot bg-blue-400 absolute top-0 right-0" />
                    </button>
                  );
                })}
              </div>
            )}
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
                  className="p-1 rounded text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
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

            <div className="pt-3 border-t border-[#243044] flex items-center justify-between text-[10px] font-mono text-slate-500">
              <span>Telemetry: Active Ping</span>
              <button
                onClick={() => {
                  if (googleMapInstanceRef.current) {
                    googleMapInstanceRef.current.panTo({
                      lat: selectedEntity.lat,
                      lng: selectedEntity.lng,
                    });
                    googleMapInstanceRef.current.setZoom(10);
                  }
                }}
                className="text-blue-400 hover:underline cursor-pointer"
              >
                Center on Map
              </button>
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
        <div className="flex items-center gap-2">
          {mapViewType.startsWith("google") && (
            <span className="text-blue-400/80">Google Maps Platform</span>
          )}
          <span className="text-slate-500">• WGS-84 Coordinate Grid</span>
        </div>
      </div>
    </div>
  );
}
