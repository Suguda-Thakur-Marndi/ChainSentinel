import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { apiClient } from "../lib/api/client";
import type { LiveMapObject, LiveMapResponse, ProvidersHealthResponse } from "../lib/api/types";

describe("Live Map Telemetry & Geospatial Contract Suite", () => {
  it("TEST 1: apiClient.map.getLiveWsUrl resolves correct ws/wss protocol without trailing slash", () => {
    const wsUrl = apiClient.map.getLiveWsUrl();
    assert.ok(wsUrl.startsWith("ws://") || wsUrl.startsWith("wss://"));
    assert.ok(wsUrl.endsWith("/api/v1/map/live"));
  });

  it("TEST 2: apiClient.map.getObjects constructs query parameters properly", async () => {
    // Mock fetch for contract verification
    const originalFetch = globalThis.fetch;
    let requestedUrl = "";

    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = input.toString();
      const mockResponse: LiveMapResponse = {
        items: [
          {
            id: "vessel-123",
            type: "vessel",
            source: "aisstream",
            latitude: 51.92,
            longitude: 4.48,
            heading: 180,
            speed: 12.5,
            status: "Under way",
            name: "Container Vessel A",
            identifier: "123456789",
            timestamp: new Date().toISOString(),
            last_seen: new Date().toISOString(),
            metadata: { mmsi: 123456789 },
          },
        ],
        sources: {
          aisstream: { status: "connected", object_count: 1 },
        },
        total_count: 1,
        timestamp: new Date().toISOString(),
      };
      return new Response(JSON.stringify(mockResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    try {
      const res = await apiClient.map.getObjects({
        types: "vessel,shipment",
        source: "aisstream",
        bbox: "4.0,51.0,5.0,52.0",
      });

      assert.ok(requestedUrl.includes("/api/v1/map/objects?"));
      assert.ok(requestedUrl.includes("types=vessel%2Cshipment") || requestedUrl.includes("types=vessel,shipment"));
      assert.ok(requestedUrl.includes("source=aisstream"));
      assert.equal(res.total_count, 1);
      assert.equal(res.items[0].id, "vessel-123");
      assert.equal(res.items[0].type, "vessel");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  it("TEST 3: apiClient.map.getProvidersHealth parses providers health array", async () => {
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async (input: RequestInfo | URL) => {
      const mockHealth: ProvidersHealthResponse = {
        providers: [
          {
            name: "aisstream",
            purpose: "Maritime Vessel Telemetry",
            status: "connected",
            objects: 350,
          },
          {
            name: "aircraft",
            purpose: "Aviation Telemetry",
            status: "unavailable",
            objects: 0,
            reason: "No aircraft telemetry provider configured",
          },
        ],
        timestamp: new Date().toISOString(),
      };
      return new Response(JSON.stringify(mockHealth), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    try {
      const res = await apiClient.map.getProvidersHealth();
      assert.equal(res.providers.length, 2);
      assert.equal(res.providers[0].name, "aisstream");
      assert.equal(res.providers[0].status, "connected");
      assert.equal(res.providers[1].name, "aircraft");
      assert.equal(res.providers[1].status, "unavailable");
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
