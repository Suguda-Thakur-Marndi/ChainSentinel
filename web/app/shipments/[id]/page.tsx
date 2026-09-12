"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  Activity,
  AlertOctagon,
  Anchor,
  ArrowLeft,
  Calendar,
  Clock,
  ExternalLink,
  GitCommit,
  MapPin,
  RefreshCw,
  Route,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import { AppShell } from "@/components/layout/AppShell";
import { EvidenceBadge, RiskBadge, StatusBadge } from "@/components/ui/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/FeedbackStates";
import { MapCard, MapEntity } from "@/components/map/MapCard";
import { apiClient } from "@/lib/api/client";
import type {
  RiskResponse,
  ShipmentEventResponse,
  ShipmentResponse,
} from "@/lib/api/types";

export default function ShipmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params?.id as string;

  const [shipment, setShipment] = useState<ShipmentResponse | null>(null);
  const [events, setEvents] = useState<ShipmentEventResponse[]>([]);
  const [linkedRisk, setLinkedRisk] = useState<RiskResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!id) return;
    setIsLoading(true);
    setError(null);
    try {
      const ship = await apiClient.shipments.get(id);
      setShipment(ship);

      // Fetch telemetry events
      try {
        const ev = await apiClient.shipments.getEvents(id);
        setEvents(ev || []);
      } catch {
        setEvents([]);
      }

      // Fetch linked risk if present
      if (ship.risk_id) {
        try {
          const r = await apiClient.risks.get(ship.risk_id);
          setLinkedRisk(r);
        } catch {
          setLinkedRisk(null);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load shipment dossier");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [id]);

  if (isLoading) {
    return (
      <ProtectedRoute>
        <AppShell>
          <LoadingState message="Retrieving authoritative shipment dossier..." />
        </AppShell>
      </ProtectedRoute>
    );
  }

  if (error || !shipment) {
    return (
      <ProtectedRoute>
        <AppShell>
          <div className="space-y-4">
            <button
              onClick={() => router.push("/shipments")}
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Shipments
            </button>
            <ErrorState message={error || "Shipment record not found."} onRetry={fetchData} />
          </div>
        </AppShell>
      </ProtectedRoute>
    );
  }

  const mapEntities: MapEntity[] =
    shipment.current_lat !== null &&
    shipment.current_lat !== undefined &&
    shipment.current_lng !== null &&
    shipment.current_lng !== undefined
      ? [
          {
            id: shipment.id,
            name: shipment.tracking_number,
            type: shipment.mode.toUpperCase() === "OCEAN" ? "vessel" : "truck",
            lat: shipment.current_lat,
            lng: shipment.current_lng,
            provenance: shipment.data_provenance,
            carrier: shipment.carrier_id || undefined,
            shipment_id: shipment.id,
            destination: shipment.destination || undefined,
            last_ping: shipment.updated_at || shipment.created_at,
          },
        ]
      : [];

  return (
    <ProtectedRoute>
      <AppShell>
        <div className="space-y-6">
          {/* Back link & Actions */}
          <div className="flex items-center justify-between">
            <Link
              href="/shipments"
              className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="w-4 h-4" /> Back to Shipments Monitor
            </Link>

            <button
              onClick={fetchData}
              className="p-1.5 rounded bg-[#111827] hover:bg-[#1A2332] text-slate-300 border border-[#243044]"
              title="Refresh"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Dossier Header */}
          <div className="p-5 rounded-lg bg-[#111827] border border-[#243044] flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs uppercase font-mono text-slate-500">Tracking Dossier</span>
                <EvidenceBadge source={shipment.data_provenance} />
              </div>
              <h1 className="text-2xl font-bold font-mono text-white tracking-tight">
                {shipment.tracking_number}
              </h1>
              <p className="text-xs text-slate-400 flex items-center gap-2">
                <span>Created: {new Date(shipment.created_at).toLocaleString()}</span>
                <span>•</span>
                <span className="font-mono">UUID: {shipment.id}</span>
              </p>
            </div>

            <div className="flex items-center gap-3">
              <div className="text-right">
                <span className="text-[10px] uppercase font-mono text-slate-500 block">Status</span>
                <StatusBadge status={shipment.status} />
              </div>
              <div className="text-right pl-3 border-l border-[#243044]">
                <span className="text-[10px] uppercase font-mono text-slate-500 block">Mode</span>
                <span className="font-mono text-xs uppercase px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                  {shipment.mode}
                </span>
              </div>
            </div>
          </div>

          {/* 3-Column Metrics Row */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Transit Route */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Route className="w-3.5 h-3.5 text-blue-400" /> Transit Route
              </span>
              <div className="flex items-center justify-between text-xs pt-1">
                <div>
                  <span className="text-[10px] text-slate-500 block">Origin Hub</span>
                  <span className="font-medium text-slate-200">{shipment.origin || "Unassigned"}</span>
                </div>
                <div className="text-slate-600">→</div>
                <div className="text-right">
                  <span className="text-[10px] text-slate-500 block">Destination Hub</span>
                  <span className="font-medium text-slate-200">{shipment.destination || "Unassigned"}</span>
                </div>
              </div>
            </div>

            {/* Prediction Delay & ETA */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-amber-400" /> ML Predicted Delay & ETA
              </span>
              <div className="flex items-center justify-between text-xs pt-1">
                <div>
                  <span className="text-[10px] text-slate-500 block">Delay Variance</span>
                  <span
                    className={`font-mono-tnum font-bold ${
                      (shipment.delay_minutes || 0) > 0 ? "text-amber-400" : "text-emerald-400"
                    }`}
                  >
                    {shipment.delay_minutes !== null && shipment.delay_minutes !== undefined
                      ? `+${Math.round(shipment.delay_minutes)} mins`
                      : "Zero Variance"}
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-[10px] text-slate-500 block">Authoritative ETA</span>
                  <span className="font-mono text-slate-200">
                    {shipment.eta ? new Date(shipment.eta).toLocaleDateString() : "Pending"}
                  </span>
                </div>
              </div>
            </div>

            {/* Spatial Position */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] space-y-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <MapPin className="w-3.5 h-3.5 text-emerald-400" /> GPS / AIS Coordinate
              </span>
              <div className="pt-1">
                {shipment.current_lat !== null && shipment.current_lat !== undefined ? (
                  <span className="font-mono text-xs text-slate-200">
                    {shipment.current_lat.toFixed(4)}°, {shipment.current_lng?.toFixed(4)}°
                  </span>
                ) : (
                  <span className="text-xs text-slate-500 italic">No GPS coordinates locked</span>
                )}
                <span className="text-[10px] text-slate-500 block mt-0.5">
                  Carrier: {shipment.carrier_id || "Unassigned"}
                </span>
              </div>
            </div>
          </div>

          {/* Spatial Map & Telemetry Events */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Map Card */}
            <div>
              <MapCard
                entities={mapEntities}
                title="Current Position Telemetry"
                height="h-[380px]"
              />
            </div>

            {/* Telemetry Event Stream */}
            <div className="p-4 rounded-lg bg-[#111827] border border-[#243044] flex flex-col justify-between h-[380px]">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-200 mb-3 border-b border-[#243044] pb-2 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-blue-400" /> Append-Only Telemetry Events
                </h3>

                <div className="space-y-3 overflow-y-auto max-h-[290px] pr-1">
                  {events.length === 0 ? (
                    <EmptyState
                      title="No Events Recorded"
                      message="No raw telemetry pings logged for this container yet."
                    />
                  ) : (
                    events.map((ev, idx) => (
                      <div
                        key={ev.id || idx}
                        className="flex items-start gap-3 p-2.5 rounded bg-[#1A2332]/60 border border-slate-800 text-xs"
                      >
                        <div className="p-1 rounded bg-blue-950 text-blue-400 mt-0.5">
                          <GitCommit className="w-3.5 h-3.5" />
                        </div>
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-slate-200">{ev.event_type}</span>
                            <span className="font-mono text-[10px] text-slate-500">
                              {new Date(ev.timestamp).toLocaleTimeString()}
                            </span>
                          </div>
                          {ev.location_name && (
                            <p className="text-[11px] text-slate-400 mt-0.5">{ev.location_name}</p>
                          )}
                          {ev.latitude && ev.longitude && (
                            <span className="font-mono text-[10px] text-slate-500 block mt-0.5">
                              {ev.latitude.toFixed(4)}°, {ev.longitude.toFixed(4)}°
                            </span>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="pt-2 border-t border-[#243044] text-[10px] font-mono text-slate-500 text-right">
                Immutable Telemetry Stream
              </div>
            </div>
          </div>

          {/* Linked Risk Engine Assessment */}
          {linkedRisk && (
            <div className="p-4 rounded-lg bg-[#111827] border border-rose-900/40 space-y-3">
              <div className="flex items-center justify-between border-b border-[#243044] pb-2">
                <div className="flex items-center gap-2">
                  <AlertOctagon className="w-4 h-4 text-rose-400" />
                  <h3 className="text-xs font-bold uppercase tracking-wider text-rose-300">
                    Linked Authoritative Risk Signal
                  </h3>
                </div>
                <Link
                  href={`/risks/${linkedRisk.id}`}
                  className="text-xs text-blue-400 hover:underline flex items-center gap-1"
                >
                  Inspect Risk Detail <ExternalLink className="w-3 h-3" />
                </Link>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-4 text-xs">
                <div>
                  <span className="font-semibold text-slate-200 block text-sm">{linkedRisk.title}</span>
                  <span className="text-slate-400">{linkedRisk.location || "Global Corridor"}</span>
                </div>
                <div className="flex items-center gap-3">
                  <RiskBadge severity={linkedRisk.severity} score={linkedRisk.risk_score} />
                  <span className="font-mono text-xs text-slate-400">
                    Trend: <strong className="text-slate-200">{linkedRisk.trend}</strong>
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </AppShell>
    </ProtectedRoute>
  );
}
