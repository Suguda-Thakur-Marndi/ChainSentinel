"use client";

import React, { useEffect, useState } from "react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { MapCard, MapEntity } from "@/components/map/MapCard";
import { ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { apiClient } from "@/lib/api/client";
import type { ShipmentResponse } from "@/lib/api/types";

export default function GlobalLiveMapPage() {
  const [shipments, setShipments] = useState<ShipmentResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchShipments = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.shipments.list({ limit: 100 });
      setShipments(res.items || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load telemetry data");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchShipments();
  }, []);

  const mapEntities: MapEntity[] = shipments
    .filter((s) => s.current_lat !== null && s.current_lat !== undefined && s.current_lng !== null && s.current_lng !== undefined)
    .map((s) => ({
      id: s.id,
      name: s.tracking_number,
      type: s.mode.toUpperCase() === "OCEAN" ? "vessel" : "truck",
      lat: s.current_lat!,
      lng: s.current_lng!,
      provenance: s.data_provenance,
      carrier: s.carrier_id || undefined,
      shipment_id: s.id,
      destination: s.destination || undefined,
      last_ping: s.updated_at || s.created_at,
    }));

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-4 flex-1 flex flex-col">
          <div className="flex items-center justify-between border-b border-[#243044] pb-3">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                Global Live Telemetry Map
                <span className="w-2 h-2 rounded-full bg-emerald-400 pulse-dot" />
              </h1>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-time multi-modal spatial awareness across maritime corridors, aviation, and road lanes.
              </p>
            </div>
            <div className="text-xs font-mono text-slate-400">
              Active Transponders: <span className="text-emerald-400 font-bold">{mapEntities.length}</span>
            </div>
          </div>

          {isLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <LoadingState message="Fetching live vessel and shipment telemetry..." />
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={fetchShipments} />
          ) : (
            <div className="flex-1 flex flex-col">
              <MapCard
                entities={mapEntities}
                title="Multi-Modal AIS & GPS Fleet Tracker"
                height="h-[calc(100vh-180px)]"
              />
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
