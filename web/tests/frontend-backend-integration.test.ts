/**
 * RiskWise 2.0 Frontend ↔ Backend Integration & Contract Validation Test Suite
 * Master Verification of Section 34 (18 Critical Requirements)
 */

import { describe, it, afterEach } from "node:test";
import assert from "node:assert/strict";
import { apiClient, ApiClientError } from "../lib/api/client";
import type {
  ActionCommand,
  ApprovalDossier,
  OptimizationRequest,
  OptimizationResult,
  ShipmentCreate,
  ShipmentResponse,
  SimulationScenario,
  SupplierCreate,
  SupplierResponse,
} from "../lib/api/types";

const originalFetch = global.fetch;

describe("Frontend ↔ Backend Integration Suite (Section 34 Verification)", () => {
  afterEach(() => {
    global.fetch = originalFetch;
  });

  // 1. Unauthenticated user cannot access protected pages
  it("CRITICAL 1: Unauthenticated session rejection on protected API endpoint", async () => {
    global.fetch = async () => {
      return new Response(JSON.stringify({ detail: "Not authenticated" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    };

    await assert.rejects(
      async () => {
        await apiClient.auth.me();
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError || (err as Error).name === "ApiClientError");
        assert.equal((err as ApiClientError).status, 401);
        return true;
      }
    );
  });

  // 2. Authenticated user can load dashboard
  it("CRITICAL 2: Authenticated user loads dashboard metrics from backend endpoints", async () => {
    global.fetch = async (input) => {
      const url = String(input);
      if (url.includes("/api/v1/shipments/metrics")) {
        return new Response(
          JSON.stringify({
            total_shipments: 42,
            active_shipments: 12,
            delayed_shipments: 2,
            delivered_on_time: 28,
            avg_delay_days: 0.8,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (url.includes("/api/v1/risks")) {
        return new Response(
          JSON.stringify({ items: [{ id: "r1", risk_score: 85, severity: "CRITICAL" }], total: 1 }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    const metrics = await apiClient.getDashboardMetrics();
    assert.ok(typeof metrics.active_critical_risks === "number");
    assert.ok(typeof metrics.shipments_in_transit === "number");
    assert.ok(metrics.pipeline);
  });

  // 3. API client sends correct auth/session (credentials: "include")
  it("CRITICAL 3: API client strictly includes credentials and propagation headers", async () => {
    let capturedInit: RequestInit | undefined;
    global.fetch = async (_input, init) => {
      capturedInit = init;
      return new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    };

    await apiClient.suppliers.list();
    assert.ok(capturedInit);
    assert.equal(capturedInit.credentials, "include");
    const headers = capturedInit.headers as Headers;
    assert.ok(headers.get("X-Request-ID"), "Must generate and send X-Request-ID header");
  });

  // 4. Supplier list renders backend data
  it("CRITICAL 4: Supplier list fetches from GET /api/v1/suppliers and parses contract", async () => {
    global.fetch = async (input) => {
      assert.ok(String(input).includes("/api/v1/suppliers"));
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "sup_1",
              name: "Apex Electronics",
              code: "APEX-01",
              country: "TW",
              tier: "HIGH",
              criticality: "HIGH",
              risk_score: 42.5,
              status: "ACTIVE",
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.suppliers.list();
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].name, "Apex Electronics");
    assert.equal(res.items[0].criticality, "HIGH");
  });

  // 5. Supplier creation sends correct payload
  it("CRITICAL 5: Supplier creation dispatches exact POST /api/v1/suppliers payload", async () => {
    let capturedBody: string | undefined;
    global.fetch = async (input, init) => {
      assert.ok(String(input).endsWith("/api/v1/suppliers"));
      assert.equal(init?.method, "POST");
      capturedBody = init?.body as string;
      return new Response(
        JSON.stringify({
          id: "sup_new",
          name: "Tokyo Sensors",
          code: "TKY-02",
          country: "JP",
          tier: "CRITICAL",
          criticality: "CRITICAL",
          status: "ACTIVE",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const payload: SupplierCreate = {
      name: "Tokyo Sensors",
      code: "TKY-02",
      country: "JP",
      tier: "CRITICAL",
      criticality: "CRITICAL",
    };

    const created = await apiClient.suppliers.create(payload);
    assert.equal(created.id, "sup_new");
    assert.ok(capturedBody);
    const parsed = JSON.parse(capturedBody);
    assert.equal(parsed.name, "Tokyo Sensors");
    assert.equal(parsed.country, "JP");
  });

  // 6. Shipment list renders backend data
  it("CRITICAL 6: Shipment list queries GET /api/v1/shipments with pagination params", async () => {
    global.fetch = async (input) => {
      const url = String(input);
      assert.ok(url.includes("/api/v1/shipments"));
      assert.ok(url.includes("limit=10"));
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "shp_1",
              tracking_number: "TRK-98765",
              origin: "Shanghai",
              destination: "Rotterdam",
              status: "IN_TRANSIT",
              mode: "OCEAN",
              carrier_id: "car_1",
            },
          ],
          total: 1,
          page: 1,
          page_size: 10,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.shipments.list({ limit: 10 });
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].tracking_number, "TRK-98765");
    assert.equal(res.items[0].mode, "OCEAN");
  });

  // 7. Shipment creation sends correct payload
  it("CRITICAL 7: Shipment creation sends validated POST /api/v1/shipments payload", async () => {
    let capturedBody: string | undefined;
    global.fetch = async (input, init) => {
      assert.ok(String(input).endsWith("/api/v1/shipments"));
      assert.equal(init?.method, "POST");
      capturedBody = init?.body as string;
      return new Response(
        JSON.stringify({
          id: "shp_created",
          tracking_number: "TRK-112233",
          origin: "Shenzhen",
          destination: "Los Angeles",
          status: "PLANNED",
          carrier_id: "car_ocean_01",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      );
    };

    const payload: ShipmentCreate = {
      tracking_number: "TRK-112233",
      origin: "Shenzhen",
      destination: "Los Angeles",
      status: "PLANNED",
      carrier_id: "car_ocean_01",
    };

    const res = await apiClient.shipments.create(payload);
    assert.equal(res.id, "shp_created");
    assert.ok(capturedBody);
    const parsed = JSON.parse(capturedBody);
    assert.equal(parsed.tracking_number, "TRK-112233");
  });

  // 8. Shipment event renders
  it("CRITICAL 8: Shipment event timeline renders authoritative telemetry", async () => {
    global.fetch = async (input) => {
      assert.ok(String(input).includes("/api/v1/shipment-events"));
      return new Response(
        JSON.stringify([
          {
            id: "evt_1",
            shipment_id: "shp_1",
            event_type: "PORT_CONGESTION",
            location_name: "Port of Singapore",
            timestamp: new Date().toISOString(),
          },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const events = await apiClient.shipments.getEvents("shp_1");
    assert.equal(events.length, 1);
    assert.equal(events[0].event_type, "PORT_CONGESTION");
    assert.equal(events[0].location_name, "Port of Singapore");
  });

  // 9. Risk assessment renders
  it("CRITICAL 9: Risk assessment details fetch and render authoritative risk score", async () => {
    global.fetch = async (input) => {
      assert.ok(String(input).includes("/api/v1/risks"));
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "rsk_101",
              title: "Typhoon Malakas Route Hazard",
              risk_score: 88,
              severity: "CRITICAL",
              trend: "INCREASING",
              detected_at: new Date().toISOString(),
            },
          ],
          total: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.risks.list();
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].severity, "CRITICAL");
    assert.equal(res.items[0].risk_score, 88);
  });

  // 10. Unauthorized mutation is rejected
  it("CRITICAL 10: Unauthorized mutation is rejected by backend and mapped to 403 ApiClientError", async () => {
    global.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: "Operator role Viewer lacks required RiskManager permissions." }),
        { status: 403, headers: { "Content-Type": "application/json" } }
      );
    };

    await assert.rejects(
      async () => {
        await apiClient.approvals.approve("dec_123", "Rejecting mutation");
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError || (err as Error).name === "ApiClientError");
        assert.equal((err as ApiClientError).status, 403);
        assert.ok((err as ApiClientError).detail.includes("RiskManager"));
        return true;
      }
    );
  });

  // 11. Approval mutation uses real API
  it("CRITICAL 11: Approval sign-off calls POST /api/v1/approvals/{id}/approve and receives dossier", async () => {
    let capturedUrl = "";
    let capturedBody: string | undefined;

    global.fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedBody = init?.body as string;
      return new Response(
        JSON.stringify({
          id: "appr_1",
          decision_id: "dec_1",
          organization_id: "org_test",
          status: "APPROVED",
          title: "Authorize Reroute",
          rationale: "Mitigate 4-day berth congestion",
          recommendation_summary: "Reroute vessel to Busan",
          urgency: "HIGH",
          impact_level: "SIGNIFICANT",
          fingerprint: "sha256_mock_fingerprint",
          requires_role: "RiskManager",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.approvals.approve("dec_1", "Approved after reviewing AIS congestion");
    assert.ok(capturedUrl.includes("/api/v1/approvals/dec_1/approve"));
    assert.ok(capturedBody);
    const body = JSON.parse(capturedBody);
    assert.equal(body.comments, "Approved after reviewing AIS congestion");
    assert.equal(res.status, "APPROVED");
  });

  // 12. Action execution uses real API
  it("CRITICAL 12: Action dispatch invokes POST /api/v1/actions/execute with ActionCommand", async () => {
    let capturedUrl = "";
    let capturedBody: string | undefined;

    global.fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedBody = init?.body as string;
      return new Response(
        JSON.stringify({
          action_id: "act_001",
          action_type: "REROUTE_SHIPMENT",
          status: "SUBMITTED",
          execution_timestamp: new Date().toISOString(),
          adapter_name: "TMS_CARRIER_ADAPTER",
          idempotency_key: "idem_key_12345",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const cmd: ActionCommand = {
      decision_id: "dec_1",
      approval_id: "appr_1",
      organization_id: "org_1",
      action_type: "REROUTE_SHIPMENT",
      target_entity_type: "SHIPMENT",
      target_entity_id: "shp_999",
      idempotency_key: "idem_key_12345",
      trace_id: "trc_12345",
      approval_fingerprint: "sha256_fp",
      parameters: { alternate_port: "KRBUS" },
    };

    const res = await apiClient.actions.execute(cmd);
    assert.ok(capturedUrl.includes("/api/v1/actions/execute"));
    assert.equal(res.status, "SUBMITTED");
    assert.equal(res.action_id, "act_001");
  });

  // 13. Verification renders backend result
  it("CRITICAL 13: Verification query renders ground-truth observation result", async () => {
    global.fetch = async (input) => {
      assert.ok(String(input).includes("/api/v1/verification-results"));
      return new Response(
        JSON.stringify({
          items: [
            {
              id: "ver_01",
              action_id: "act_001",
              status: "VERIFIED",
              evidence_precedence: "REAL",
              observation_summary: "AIS telemetry verified berth at Busan within window",
              verified_at: new Date().toISOString(),
              risk_score_before: 85,
              risk_score_after: 25,
            },
          ],
          total: 1,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.verification.list({ action_id: "act_001" });
    assert.equal(res.items.length, 1);
    assert.equal(res.items[0].status, "VERIFIED");
    assert.equal(res.items[0].evidence_precedence, "REAL");
  });

  // 14. Simulation uses real API
  it("CRITICAL 14: Simulation scenario execution calls POST /api/v1/simulation/scenarios/{id}/simulate", async () => {
    let capturedUrl = "";

    global.fetch = async (input) => {
      capturedUrl = String(input);
      return new Response(
        JSON.stringify({
          simulation_id: "sim_99",
          scenario_id: "scen_test",
          status: "COMPLETED",
          changes_applied_count: 1,
          propagation_depth_reached: 2,
          entity_impacts_count: 5,
          total_effects_count: 8,
          execution_duration_ms: 120,
          generated_at: new Date().toISOString(),
          source_type: "SIMULATED",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const run = await apiClient.simulation.run("scen_test");
    assert.ok(capturedUrl.includes("/api/v1/simulation/scenarios/scen_test/simulate"));
    assert.equal(run.simulation_id, "sim_99");
    assert.equal(run.status, "COMPLETED");
  });

  // 15. Optimization uses real API
  it("CRITICAL 15: Optimization solver executes via POST /api/v1/optimization-runs", async () => {
    let capturedUrl = "";
    global.fetch = async (input) => {
      capturedUrl = String(input);
      return new Response(
        JSON.stringify({
          status: "OPTIMAL",
          objective_value: 12450.0,
          total_cost: 12450.0,
          solve_time_ms: 45.2,
          allocations: [],
          algorithm: "OR-Tools CBC/SCIP",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const req: OptimizationRequest = {
      objective: "MINIMIZE_COST",
      scenario_id: "scen_test_01",
      shipment_ids: ["shp_1"],
      budget_max_usd: 50000,
      max_delay_hours: 48,
    };

    const opt = await apiClient.optimization.run(req);
    assert.ok(capturedUrl.includes("/api/v1/optimization-runs"));
    assert.equal(opt.status, "OPTIMAL");
  });

  // 16. Empty API response renders empty state safely
  it("CRITICAL 16: Empty API response correctly resolves without undefined crashes", async () => {
    global.fetch = async () => {
      return new Response(
        JSON.stringify({ items: [], total: 0, page: 1, page_size: 20 }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    };

    const res = await apiClient.suppliers.list();
    assert.equal(res.items.length, 0);
    assert.equal(res.total, 0);
  });

  // 17. Backend validation error renders correctly
  it("CRITICAL 17: Backend 422 validation error detail is accurately parsed into ApiClientError", async () => {
    global.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "tracking_number"], msg: "Field required", type: "value_error.missing" },
          ],
        }),
        { status: 422, headers: { "Content-Type": "application/json" } }
      );
    };

    await assert.rejects(
      async () => {
        await apiClient.shipments.create({} as ShipmentCreate);
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError || (err as Error).name === "ApiClientError");
        assert.equal((err as ApiClientError).status, 422);
        assert.ok((err as ApiClientError).detail.includes("Field required") || (err as ApiClientError).detail.includes("tracking_number"));
        return true;
      }
    );
  });

  // 18. Network failure renders error state
  it("CRITICAL 18: Network failure (TypeError) gracefully translates to connection error ApiClientError", async () => {
    global.fetch = async () => {
      throw new TypeError("Failed to fetch");
    };

    await assert.rejects(
      async () => {
        await apiClient.health.get();
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError || (err as Error).name === "ApiClientError");
        assert.equal((err as ApiClientError).status, 0);
        assert.equal((err as ApiClientError).code, "NETWORK_ERROR");
        assert.ok((err as ApiClientError).detail.includes("Failed to connect to backend service"));
        return true;
      }
    );
  });
});
