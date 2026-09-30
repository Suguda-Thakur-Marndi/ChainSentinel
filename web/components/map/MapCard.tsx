"use client";

import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  Anchor,
  Compass,
  ExternalLink,
  Eye,
  Globe2,
  Layers,
  MapPin,
  Navigation,
  RefreshCw,
  RotateCcw,
  Search,
  Ship,
  Truck,
  Wind,
  X,
  AlertTriangle,
  Plane,
  Box,
  Flame,
  Clock,
  Radio,
  SlidersHorizontal,
} from "lucide-react";
import type { LiveMapObject, LiveMapObjectType, ProviderHealth } from "@/lib/api/types";

// Backward-compatible interface for legacy callers
export interface MapEntity {
  id: string;
  name: string;
  type: string;
  lat: number;
  lng: number;
  provenance?: string;
  speed_knots?: number;
  heading_degrees?: number;
  carrier?: string;
  shipment_id?: string;
  destination?: string;
  eta?: string;
  risk_level?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  last_ping?: string;
  metadata?: Record<string, any>;
}

// Convert MapEntity to LiveMapObject if passed
function toLiveMapObject(ent: MapEntity | LiveMapObject): LiveMapObject {
  if ("latitude" in ent && "longitude" in ent) {
    return ent as LiveMapObject;
  }
  const legacy = ent as MapEntity;
  return {
    id: legacy.id,
    name: legacy.name,
    type: (legacy.type as LiveMapObjectType) || "shipment",
    source: "internal_riskwise",
    latitude: legacy.lat,
    longitude: legacy.lng,
    heading: legacy.heading_degrees ?? null,
    speed: legacy.speed_knots ?? null,
    status: legacy.risk_level || "ACTIVE",
    identifier: legacy.shipment_id || legacy.id,
    timestamp: legacy.last_ping || new Date().toISOString(),
    last_seen: legacy.last_ping || new Date().toISOString(),
    metadata: legacy.metadata || {},
  };
}

// Tactical Dark Theme for Google Maps
const TACTICAL_DARK_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#0B0F14" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0B0F14" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#64748B" }] },
  { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#94A3B8" }] },
  { featureType: "poi", elementType: "labels.text.fill", stylers: [{ color: "#475569" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#111827" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#1E293B" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#0F172A" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#64748B" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#334155" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#1E293B" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#060A10" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#3B82F6" }] },
  { featureType: "water", elementType: "labels.text.stroke", stylers: [{ color: "#070A0E" }] },
];

// Heading directional arrow SVG path for vessel/aircraft orientation
const DIRECTIONAL_ARROW_PATH = "M 0,-8 L 5,8 L 0,4 L -5,8 Z";
const CIRCLE_DOT_PATH = "M 0,0 m -5,0 a 5,5 0 1,0 10,0 a 5,5 0 1,0 -10,0";

function getTypeColor(type: string): string {
  switch (type) {
    case "vessel":
      return "#38BDF8"; // Sky blue
    case "aircraft":
      return "#F59E0B"; // Amber
    case "shipment":
      return "#60A5FA"; // Blue
    case "truck":
      return "#10B981"; // Emerald
    case "train":
    case "transit":
      return "#A855F7"; // Purple
    case "port":
      return "#34D399"; // Green
    case "weather":
      return "#F43F5E"; // Rose
    case "incident":
    case "risk":
      return "#EF4444"; // Red
    default:
      return "#94A3B8"; // Slate
  }
}

function getFreshnessStatus(lastSeenIso: string): "fresh" | "aging" | "stale" {
  try {
    const seenMs = new Date(lastSeenIso).getTime();
    const diffSec = (Date.now() - seenMs) / 1000;
    if (diffSec < 30) return "fresh";
    if (diffSec < 120) return "aging";
    return "stale";
  } catch {
    return "fresh";
  }
}

declare global {
  interface Window {
    google?: any;
    gm_authFailure?: () => void;
  }
}

export function MapCard({
  entities = [],
  objects = [],
  title = "Live Geospatial Telemetry Map",
  className = "",
  height = "h-[600px]",
  providers = [],
  wsConnected = false,
  onRefresh,
}: {
  entities?: MapEntity[];
  objects?: LiveMapObject[];
  title?: string;
  className?: string;
  height?: string;
  providers?: ProviderHealth[];
  wsConnected?: boolean;
  onRefresh?: () => void;
}) {
  // Normalize incoming objects
  const allObjects: LiveMapObject[] = useMemo(() => {
    if (objects && objects.length > 0) return objects;
    return entities.map(toLiveMapObject);
  }, [objects, entities]);

  const [selectedObject, setSelectedObject] = useState<LiveMapObject | null>(null);
  const [mapViewType, setMapViewType] = useState<"google-dark" | "google-satellite" | "tactical-radar">("google-dark");
  const [googleMapsReady, setGoogleMapsReady] = useState(false);
  const [googleMapsAuthError, setGoogleMapsAuthError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [showControlsDrawer, setShowControlsDrawer] = useState(false);

  // Active layer visibility toggles
  const [layers, setLayers] = useState({
    vessel: true,
    aircraft: true,
    shipment: true,
    truck: true,
    port: true,
    weather: true,
    incident: true,
    transit: true,
  });

  const mapContainerRef = useRef<HTMLDivElement>(null);
  const googleMapInstanceRef = useRef<any>(null);
  // Map of active markers: obj.id -> google.maps.Marker
  const markersMapRef = useRef<Map<string, any>>(new Map());

  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "";

  // 1. Google Maps JS SDK Loader
  useEffect(() => {
    if (!apiKey) {
      setMapViewType("tactical-radar");
      return;
    }

    window.gm_authFailure = () => {
      console.warn("[RiskWise Maps] Google Maps authentication or billing failure detected.");
      setGoogleMapsAuthError("Google Maps API requires billing enabled on Google Cloud. Switching to Tactical SVG mode.");
      setMapViewType("tactical-radar");
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
        setGoogleMapsAuthError("Could not reach Google Maps CDN. Falling back to Tactical SVG Radar.");
        setMapViewType("tactical-radar");
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

  // 2. Initialize Google Maps
  useEffect(() => {
    if (!googleMapsReady || !mapContainerRef.current || !window.google?.maps) return;
    if (mapViewType === "tactical-radar") return;

    try {
      const isSatellite = mapViewType === "google-satellite";
      if (!googleMapInstanceRef.current) {
        const initialMap = new window.google.maps.Map(mapContainerRef.current, {
          center: { lat: 25.0, lng: 55.0 },
          zoom: 3,
          minZoom: 2,
          maxZoom: 18,
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
        googleMapInstanceRef.current.setMapTypeId(isSatellite ? "hybrid" : "roadmap");
        googleMapInstanceRef.current.setOptions({
          styles: isSatellite ? [] : TACTICAL_DARK_STYLE,
        });
      }
    } catch (err) {
      console.warn("[RiskWise Maps] Error initializing Google Map:", err);
    }
  }, [googleMapsReady, mapViewType]);

  // 3. Filtered Objects
  const filteredObjects = useMemo(() => {
    return allObjects.filter((obj) => {
      const typeKey = obj.type as keyof typeof layers;
      if (layers[typeKey] === false) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const matchesName = obj.name.toLowerCase().includes(q);
        const matchesId = obj.identifier?.toLowerCase().includes(q);
        const matchesSource = obj.source.toLowerCase().includes(q);
        if (!matchesName && !matchesId && !matchesSource) return false;
      }
      return true;
    });
  }, [allObjects, layers, searchQuery]);

  // Layer toggler
  const toggleLayer = (layerKey: keyof typeof layers) => {
    setLayers((prev) => ({ ...prev, [layerKey]: !prev[layerKey] }));
  };

  // 4. Incremental Marker Sync on Google Map
  useEffect(() => {
    if (!googleMapInstanceRef.current || !window.google?.maps || mapViewType === "tactical-radar") return;

    const map = googleMapInstanceRef.current;
    const markersMap = markersMapRef.current;
    const currentIds = new Set<string>();

    filteredObjects.forEach((obj) => {
      currentIds.add(obj.id);
      const position = { lat: obj.latitude, lng: obj.longitude };
      const color = getTypeColor(obj.type);
      const hasHeading = typeof obj.heading === "number" && !isNaN(obj.heading);

      const iconConfig = {
        path: hasHeading ? DIRECTIONAL_ARROW_PATH : CIRCLE_DOT_PATH,
        fillColor: color,
        fillOpacity: 0.95,
        strokeColor: "#FFFFFF",
        strokeWeight: 1.2,
        scale: hasHeading ? 1.6 : 1.2,
        rotation: hasHeading ? obj.heading : 0,
      };

      let marker = markersMap.get(obj.id);
      if (marker) {
        // Update existing marker position & rotation
        marker.setPosition(position);
        marker.setIcon(iconConfig);
      } else {
        // Create new marker
        marker = new window.google.maps.Marker({
          position,
          map,
          title: `${obj.name} (${obj.type})`,
          icon: iconConfig,
        });

        marker.addListener("click", () => {
          setSelectedObject(obj);
        });

        markersMap.set(obj.id, marker);
      }
    });

    // Remove markers that are no longer in filtered set
    for (const [id, marker] of markersMap.entries()) {
      if (!currentIds.has(id)) {
        marker.setMap(null);
        markersMap.delete(id);
      }
    }
  }, [filteredObjects, googleMapsReady, mapViewType]);

  // Center on object
  const centerOnObject = (obj: LiveMapObject) => {
    if (googleMapInstanceRef.current && window.google?.maps) {
      googleMapInstanceRef.current.setCenter({ lat: obj.latitude, lng: obj.longitude });
      googleMapInstanceRef.current.setZoom(10);
    }
    setSelectedObject(obj);
  };

  // Counts by type
  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    allObjects.forEach((obj) => {
      counts[obj.type] = (counts[obj.type] || 0) + 1;
    });
    return counts;
  }, [allObjects]);

  return (
    <div
      className={`relative rounded-xl border border-[#243044] bg-[#070A0E] overflow-hidden flex flex-col min-h-[550px] w-full ${height} ${className} shadow-2xl`}
    >
      {/* Top Overlay Control Bar */}
      <div className="absolute top-3 left-3 right-3 z-10 flex flex-wrap items-center justify-between gap-2 pointer-events-none">
        {/* Title & Live Pulse Badge */}
        <div className="bg-[#0B0F14]/90 backdrop-blur-md border border-[#243044] px-3.5 py-1.5 rounded-lg flex items-center gap-2.5 pointer-events-auto shadow-xl">
          <Globe2 className="w-4 h-4 text-sky-400" />
          <span className="text-xs font-semibold text-slate-100 tracking-tight">{title}</span>
          <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium border bg-emerald-950/80 text-emerald-300 border-emerald-800/80">
            <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? "bg-emerald-400 animate-ping" : "bg-amber-400"}`} />
            {wsConnected ? "LIVE STREAM" : "POLLING"}
          </span>
          <span className="text-[11px] font-mono text-slate-400 border-l border-[#243044] pl-2">
            <strong className="text-sky-300">{filteredObjects.length}</strong> / {allObjects.length} nodes
          </span>
        </div>

        {/* View Switcher, Layer Filter, Search Bar */}
        <div className="flex items-center gap-2 pointer-events-auto">
          {/* Quick Search */}
          <div className="relative hidden md:block">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2 text-slate-500" />
            <input
              type="text"
              placeholder="Search vessel, MMSI..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-[#0B0F14]/90 backdrop-blur border border-[#243044] rounded-lg pl-8 pr-3 py-1 text-[11px] text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 w-44"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2 top-2 text-slate-400 hover:text-slate-200"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* Map Style Selector */}
          <div className="bg-[#0B0F14]/90 backdrop-blur border border-[#243044] p-1 rounded-lg flex items-center gap-1 shadow-lg text-[11px]">
            <button
              id="btn-view-google-dark"
              onClick={() => setMapViewType("google-dark")}
              className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                mapViewType === "google-dark"
                  ? "bg-sky-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Google Dark
            </button>
            <button
              id="btn-view-satellite"
              onClick={() => setMapViewType("google-satellite")}
              className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                mapViewType === "google-satellite"
                  ? "bg-sky-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Satellite
            </button>
            <button
              id="btn-view-tactical-svg"
              onClick={() => setMapViewType("tactical-radar")}
              className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                mapViewType === "tactical-radar"
                  ? "bg-sky-600 text-white font-medium shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Tactical SVG
            </button>
          </div>

          {/* Toggle Controls Drawer Button */}
          <button
            id="btn-toggle-telemetry-layers"
            onClick={() => setShowControlsDrawer(!showControlsDrawer)}
            className={`px-2.5 py-1.5 rounded-lg border text-[11px] font-medium flex items-center gap-1.5 transition-colors cursor-pointer ${
              showControlsDrawer
                ? "bg-sky-600 border-sky-500 text-white"
                : "bg-[#0B0F14]/90 border-[#243044] text-slate-300 hover:text-white"
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Telemetry Layers</span>
          </button>

          {onRefresh && (
            <button
              id="btn-refresh-telemetry"
              onClick={onRefresh}
              className="p-1.5 rounded-lg border border-[#243044] bg-[#0B0F14]/90 text-slate-300 hover:text-white transition-colors cursor-pointer"
              title="Refresh Telemetry"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Layer Toggles & Source Status Float-in Panel */}
      {showControlsDrawer && (
        <div className="absolute top-14 right-3 z-30 w-80 bg-[#0B0F14]/95 backdrop-blur-xl border border-[#243044] rounded-xl p-4 shadow-2xl space-y-4 max-h-[calc(100%-70px)] overflow-y-auto">
          <div className="flex items-center justify-between border-b border-[#1E293B] pb-2">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-sky-400" />
              <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">Telemetry Layers</span>
            </div>
            <button
              onClick={() => setShowControlsDrawer(false)}
              className="text-slate-400 hover:text-slate-200 p-0.5"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Layer Checkboxes */}
          <div className="space-y-1.5 text-xs">
            {[
              { key: "vessel", label: "Maritime Vessels (AIS)", count: typeCounts["vessel"] || 0, color: "#38BDF8", icon: Ship },
              { key: "aircraft", label: "Aviation Flights", count: typeCounts["aircraft"] || 0, color: "#F59E0B", icon: Plane },
              { key: "shipment", label: "Verified Shipments", count: typeCounts["shipment"] || 0, color: "#60A5FA", icon: Box },
              { key: "truck", label: "Road Freight & Trucks", count: typeCounts["truck"] || 0, color: "#10B981", icon: Truck },
              { key: "port", label: "Ports & Hub Terminals", count: typeCounts["port"] || 0, color: "#34D399", icon: Anchor },
              { key: "weather", label: "Meteorological Hazards", count: typeCounts["weather"] || 0, color: "#F43F5E", icon: Wind },
              { key: "incident", label: "Port Gate / Corridor Delays", count: typeCounts["incident"] || 0, color: "#EF4444", icon: Flame },
            ].map(({ key, label, count, color, icon: Icon }) => (
              <label
                key={key}
                className="flex items-center justify-between p-1.5 rounded-md hover:bg-[#111827] cursor-pointer transition-colors"
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={layers[key as keyof typeof layers]}
                    onChange={() => toggleLayer(key as keyof typeof layers)}
                    className="rounded border-[#334155] bg-[#070A0E] text-sky-500 focus:ring-0 cursor-pointer"
                  />
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                  <Icon className="w-3.5 h-3.5 text-slate-400" />
                  <span className="text-slate-300 text-[11px]">{label}</span>
                </div>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#1E293B] text-slate-400 font-semibold">
                  {count}
                </span>
              </label>
            ))}
          </div>

          {/* Telemetry Sources Health Section */}
          {providers && providers.length > 0 && (
            <div className="border-t border-[#1E293B] pt-3 space-y-2">
              <div className="flex items-center gap-2">
                <Radio className="w-3.5 h-3.5 text-emerald-400" />
                <span className="text-[11px] font-bold text-slate-200 uppercase tracking-wider">
                  Telemetry Providers
                </span>
              </div>
              <div className="space-y-1.5 text-[11px]">
                {providers.map((p) => {
                  const isConn = p.status === "connected";
                  const isUnavail = p.status === "unavailable" || p.status === "unconfigured";
                  return (
                    <div
                      key={p.name}
                      className="p-2 rounded-lg bg-[#070A0E] border border-[#1E293B] flex flex-col gap-1"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5 font-medium text-slate-300">
                          <span
                            className={`w-2 h-2 rounded-full ${
                              isConn ? "bg-emerald-400" : isUnavail ? "bg-slate-500" : "bg-rose-500"
                            }`}
                          />
                          <span className="capitalize">{p.name}</span>
                        </div>
                        <span
                          className={`text-[10px] font-mono uppercase px-1 rounded ${
                            isConn
                              ? "bg-emerald-950 text-emerald-300"
                              : isUnavail
                              ? "bg-slate-900 text-slate-400"
                              : "bg-rose-950 text-rose-300"
                          }`}
                        >
                          {p.status}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-[10px] text-slate-400">
                        <span>{p.purpose}</span>
                        <span className="font-mono text-slate-300">{p.objects} objects</span>
                      </div>
                      {p.reason && (
                        <p className="text-[10px] text-slate-500 italic mt-0.5 leading-tight">{p.reason}</p>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Selected Object Detail Side Card / Drawer */}
      {selectedObject && (
        <div className="absolute bottom-4 left-4 z-30 w-84 bg-[#0B0F14]/95 backdrop-blur-xl border border-[#243044] rounded-xl p-4 shadow-2xl space-y-3 max-h-[80%] overflow-y-auto">
          <div className="flex items-start justify-between border-b border-[#1E293B] pb-2">
            <div>
              <div className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: getTypeColor(selectedObject.type) }}
                />
                <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 font-semibold">
                  {selectedObject.type} • {selectedObject.source}
                </span>
              </div>
              <h3 className="text-sm font-bold text-slate-100 mt-0.5 leading-snug">{selectedObject.name}</h3>
            </div>
            <button
              onClick={() => setSelectedObject(null)}
              className="text-slate-400 hover:text-slate-200 p-0.5"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Core Telemetry Grid */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="p-2 rounded bg-[#070A0E] border border-[#1E293B]">
              <span className="text-[10px] text-slate-500 uppercase block">Coordinates</span>
              <span className="font-mono text-slate-200 font-medium">
                {selectedObject.latitude.toFixed(4)}, {selectedObject.longitude.toFixed(4)}
              </span>
            </div>
            <div className="p-2 rounded bg-[#070A0E] border border-[#1E293B]">
              <span className="text-[10px] text-slate-500 uppercase block">Status</span>
              <span className="text-slate-200 font-medium truncate block" title={selectedObject.status || "Normal"}>
                {selectedObject.status || "Operational"}
              </span>
            </div>
            {selectedObject.speed !== null && selectedObject.speed !== undefined && (
              <div className="p-2 rounded bg-[#070A0E] border border-[#1E293B]">
                <span className="text-[10px] text-slate-500 uppercase block">Speed Over Ground</span>
                <span className="font-mono text-emerald-400 font-bold">{selectedObject.speed} kts</span>
              </div>
            )}
            {selectedObject.heading !== null && selectedObject.heading !== undefined && (
              <div className="p-2 rounded bg-[#070A0E] border border-[#1E293B] flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-slate-500 uppercase block">Heading</span>
                  <span className="font-mono text-sky-400 font-bold">{selectedObject.heading}°</span>
                </div>
                <Navigation
                  className="w-4 h-4 text-sky-400"
                  style={{ transform: `rotate(${selectedObject.heading}deg)` }}
                />
              </div>
            )}
          </div>

          {/* Freshness & Metadata */}
          <div className="p-2 rounded bg-[#070A0E] border border-[#1E293B] space-y-1 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Observation Time:</span>
              <span className="font-mono text-slate-300">
                {new Date(selectedObject.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Freshness:</span>
              <span className="font-mono text-emerald-400 uppercase font-semibold">
                {getFreshnessStatus(selectedObject.last_seen)}
              </span>
            </div>
            {selectedObject.identifier && (
              <div className="flex items-center justify-between">
                <span className="text-slate-500">Identifier (MMSI/Ref):</span>
                <span className="font-mono text-slate-300">{selectedObject.identifier}</span>
              </div>
            )}
          </div>

          {/* Deep Metadata attributes */}
          {selectedObject.metadata && Object.keys(selectedObject.metadata).length > 0 && (
            <div className="space-y-1 text-[10px] border-t border-[#1E293B] pt-2">
              <span className="text-slate-500 uppercase font-bold block">Telemetry Attributes</span>
              <div className="max-h-24 overflow-y-auto font-mono text-slate-400 space-y-0.5">
                {Object.entries(selectedObject.metadata).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <span className="text-slate-500">{k}:</span>
                    <span className="text-slate-300 truncate max-w-[150px]">{String(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main Map Rendering Area */}
      <div className="flex-1 w-full h-full relative bg-[#070A0E] overflow-hidden">
        {/* GOOGLE MAP CANVAS */}
        <div
          ref={mapContainerRef}
          className={`absolute inset-0 w-full h-full transition-opacity duration-300 ${
            mapViewType !== "tactical-radar"
              ? "opacity-100 z-0 pointer-events-auto"
              : "opacity-0 -z-10 pointer-events-none"
          }`}
        />

        {/* TACTICAL SVG RADAR FALLBACK / VIEW */}
        {mapViewType === "tactical-radar" && (
          <div className="absolute inset-0 w-full h-full flex items-center justify-center overflow-hidden">
            {/* World Grid */}
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
              <line x1="0" y1="25%" x2="100%" y2="25%" stroke="#1E293B" strokeDasharray="4 4" />
              <line x1="0" y1="50%" x2="100%" y2="50%" stroke="#334155" strokeWidth="1" />
              <line x1="0" y1="75%" x2="100%" y2="75%" stroke="#1E293B" strokeDasharray="4 4" />
            </svg>

            {/* Global Continental Watermark */}
            <div className="absolute inset-0 flex items-center justify-center opacity-15 pointer-events-none">
              <Globe2 className="w-[500px] h-[500px] text-sky-400/30" />
            </div>

            {/* Render entities on Tactical SVG Grid */}
            {filteredObjects.length === 0 ? (
              <div className="z-10 text-center p-6 bg-[#0B0F14]/90 backdrop-blur rounded-xl border border-[#243044]">
                <MapPin className="w-8 h-8 text-slate-500 mx-auto mb-2" />
                <p className="text-xs font-semibold text-slate-300">No Active Physical Telemetry Ping</p>
                <p className="text-[11px] text-slate-500 mt-1 font-mono">
                  Live AIS / GPS tracking awaits telemetry ingestion
                </p>
              </div>
            ) : (
              <div className="relative w-full h-full">
                {filteredObjects.slice(0, 300).map((obj) => {
                  const top = `${Math.min(Math.max((90 - obj.latitude) / 1.8, 4), 96)}%`;
                  const left = `${Math.min(Math.max((obj.longitude + 180) / 3.6, 2), 98)}%`;
                  const isSelected = selectedObject?.id === obj.id;
                  const color = getTypeColor(obj.type);

                  return (
                    <button
                      key={obj.id}
                      onClick={() => setSelectedObject(obj)}
                      style={{ top, left }}
                      title={`${obj.name} (${obj.type}) - Lat: ${obj.latitude.toFixed(2)}, Lon: ${obj.longitude.toFixed(2)}`}
                      className={`absolute -translate-x-1/2 -translate-y-1/2 p-1 rounded-full transition-transform hover:scale-150 focus:outline-none cursor-pointer group ${
                        isSelected ? "scale-150 z-30" : "z-10"
                      }`}
                    >
                      <span
                        className="w-2.5 h-2.5 rounded-full block border border-white/80 shadow-md group-hover:animate-ping"
                        style={{ backgroundColor: color }}
                      />
                    </button>
                  );
                })}
                {filteredObjects.length > 300 && (
                  <div className="absolute bottom-2 right-2 text-[10px] text-slate-400 font-mono bg-[#0B0F14]/90 border border-[#243044] px-2 py-0.5 rounded shadow">
                    Displaying primary 300 of {filteredObjects.length} radar targets
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
