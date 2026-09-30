"use client";

import React, { useEffect, useState, useRef, useCallback } from "react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { MapCard } from "@/components/map/MapCard";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { LiveMapObject, ProviderHealth } from "@/lib/api/types";
import {
  Globe2,
  Radio,
  RefreshCw,
  Ship,
  Plane,
  Truck,
  Wind,
  Flame,
  Activity,
  Layers,
} from "lucide-react";

export default function GlobalLiveMapPage() {
  const [objects, setObjects] = useState<LiveMapObject[]>([]);
  const [providers, setProviders] = useState<ProviderHealth[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date>(new Date());

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // 1. Initial REST fetch for immediate loading
  const fetchInitialData = useCallback(async () => {
    try {
      setError(null);
      const [objsRes, healthRes] = await Promise.allSettled([
        apiClient.map.getObjects(),
        apiClient.map.getProvidersHealth(),
      ]);

      if (objsRes.status === "fulfilled") {
        setObjects(objsRes.value.items || []);
        setLastUpdate(new Date());
      } else {
        console.warn("[MapPage] Error fetching map objects:", objsRes.reason);
      }

      if (healthRes.status === "fulfilled") {
        setProviders(healthRes.value.providers || []);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load live telemetry data");
    } finally {
      setIsLoading(false);
    }
  }, []);

  // 2. Persistent WebSocket connection for live streaming
  useEffect(() => {
    let isCancelled = false;

    function connectWs() {
      if (isCancelled) return;
      const wsUrl = apiClient.map.getLiveWsUrl();

      try {
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          if (isCancelled) return;
          setWsConnected(true);
          console.log("[MapPage] Connected to live map WebSocket stream.");
        };

        ws.onmessage = (event) => {
          if (isCancelled) return;
          try {
            const data = JSON.parse(event.data);
            if (data.event === "initial_snapshot") {
              if (Array.isArray(data.objects)) {
                setObjects(data.objects);
                setLastUpdate(new Date());
              }
            } else if (data.event === "position_update") {
              const incoming: LiveMapObject[] = data.objects || [];
              if (incoming.length > 0) {
                setObjects((prev) => {
                  const map = new Map(prev.map((o) => [o.id, o]));
                  for (const obj of incoming) {
                    map.set(obj.id, obj);
                  }
                  return Array.from(map.values());
                });
                setLastUpdate(new Date());
              }
            } else if (data.event === "remove") {
              const deadIds: string[] = data.ids || [];
              if (deadIds.length > 0) {
                const deadSet = new Set(deadIds);
                setObjects((prev) => prev.filter((o) => !deadSet.has(o.id)));
              }
            }
          } catch (parseErr) {
            console.debug("[MapPage] WS frame error:", parseErr);
          }
        };

        ws.onclose = () => {
          if (isCancelled) return;
          setWsConnected(false);
          // Auto-reconnect after 3s
          reconnectTimeoutRef.current = setTimeout(connectWs, 3000);
        };

        ws.onerror = () => {
          if (isCancelled) return;
          setWsConnected(false);
        };
      } catch (err) {
        console.warn("[MapPage] WebSocket init failure:", err);
        setWsConnected(false);
        reconnectTimeoutRef.current = setTimeout(connectWs, 5000);
      }
    }

    fetchInitialData().then(() => {
      connectWs();
    });

    // Periodic provider health poll every 20 seconds
    const healthInterval = setInterval(() => {
      apiClient.map
        .getProvidersHealth()
        .then((res) => {
          if (!isCancelled) setProviders(res.providers || []);
        })
        .catch(() => {});
    }, 20000);

    return () => {
      isCancelled = true;
      clearInterval(healthInterval);
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [fetchInitialData]);

  // Telemetry breakdown metrics
  const maritimeCount = objects.filter((o) => o.type === "vessel").length;
  const shipmentCount = objects.filter((o) => o.type === "shipment").length;
  const weatherCount = objects.filter((o) => o.type === "weather").length;
  const incidentCount = objects.filter((o) => o.type === "incident").length;

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-3 flex-1 flex flex-col h-[calc(100vh-100px)]">
          {/* Top Operational Status Header */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#243044] pb-2.5">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                  Global Live Telemetry Control Tower
                </h1>
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider border ${
                    wsConnected
                      ? "bg-emerald-950/80 text-emerald-400 border-emerald-700/80"
                      : "bg-amber-950/80 text-amber-400 border-amber-700/80"
                  }`}
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${
                      wsConnected ? "bg-emerald-400 animate-ping" : "bg-amber-400"
                    }`}
                  />
                  {wsConnected ? "Live Telemetry Connected" : "Connecting Stream..."}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time geospatial tracking across maritime AIS transponders, port gates, meteorological corridors, and verified supply chain assets.
              </p>
            </div>

            {/* Quick Metrics & Refresh */}
            <div className="flex items-center gap-2">
              <div className="hidden lg:flex items-center gap-2 text-xs font-mono">
                <span className="px-2 py-1 rounded bg-[#0B0F14] border border-[#243044] text-sky-300 flex items-center gap-1.5">
                  <Ship className="w-3.5 h-3.5 text-sky-400" />
                  <strong>{maritimeCount}</strong> Ships
                </span>
                <span className="px-2 py-1 rounded bg-[#0B0F14] border border-[#243044] text-blue-300 flex items-center gap-1.5">
                  <Truck className="w-3.5 h-3.5 text-blue-400" />
                  <strong>{shipmentCount}</strong> Cargo
                </span>
                <span className="px-2 py-1 rounded bg-[#0B0F14] border border-[#243044] text-rose-300 flex items-center gap-1.5">
                  <Wind className="w-3.5 h-3.5 text-rose-400" />
                  <strong>{weatherCount}</strong> Hazards
                </span>
                <span className="px-2 py-1 rounded bg-[#0B0F14] border border-[#243044] text-red-300 flex items-center gap-1.5">
                  <Flame className="w-3.5 h-3.5 text-red-400" />
                  <strong>{incidentCount}</strong> Delays
                </span>
              </div>

              <button
                onClick={fetchInitialData}
                disabled={isLoading}
                className="px-2.5 py-1.5 rounded-lg border border-[#243044] bg-[#0B0F14] hover:bg-[#1E293B] text-slate-300 text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                <span className="hidden sm:inline">Sync</span>
              </button>
            </div>
          </div>

          {/* Map Display Container */}
          {isLoading && objects.length === 0 ? (
            <div className="flex-1 min-h-[600px] flex items-center justify-center">
              <LoadingState message="Establishing live telemetry stream with AISStream, OpenWeather & TomTom..." />
            </div>
          ) : error && objects.length === 0 ? (
            <ErrorState message={error} onRetry={fetchInitialData} />
          ) : (
            <div className="flex-1 min-h-[600px] h-[calc(100vh-170px)] flex flex-col w-full">
              <MapCard
                objects={objects}
                providers={providers}
                wsConnected={wsConnected}
                onRefresh={fetchInitialData}
                title="Multi-Source Real-Time Geospatial Intelligence"
                height="h-full min-h-[550px]"
              />
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
