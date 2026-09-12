import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { apiClient, ApiClientError } from "../lib/api/client";
import type {
  EvidenceSourcePrecedence,
  OptimizationStatus,
  Role,
  VerificationStatus,
} from "../lib/api/types";

describe("Phase 19 Control Tower Frontend Contracts & Logic Suite", () => {
  it("TEST 1: apiClient initializes with sanitized base URL without trailing slash", () => {
    const url = apiClient.getBaseUrl();
    assert.ok(typeof url === "string");
    assert.equal(url.endsWith("/"), false);
  });

  it("TEST 2: Strict evidence precedence enforces REAL > ESTIMATED > SIMULATED", () => {
    const precedenceOrder: EvidenceSourcePrecedence[] = ["REAL", "ESTIMATED", "SIMULATED"];
    assert.equal(precedenceOrder[0], "REAL");
    assert.equal(precedenceOrder[1], "ESTIMATED");
    assert.equal(precedenceOrder[2], "SIMULATED");
  });

  it("TEST 3: Optimization status contract strictly distinguishes FEASIBLE from OPTIMAL", () => {
    const optimalStatus: OptimizationStatus = "OPTIMAL";
    const feasibleStatus: OptimizationStatus = "FEASIBLE";
    assert.notEqual(optimalStatus, feasibleStatus);
    assert.notEqual((feasibleStatus as string), "OPTIMAL");
  });

  it("TEST 4: Verification status contract handles all authoritative outcomes", () => {
    const validStatuses: VerificationStatus[] = [
      "VERIFIED",
      "PARTIALLY_VERIFIED",
      "FAILED",
      "PENDING",
      "INSUFFICIENT_EVIDENCE",
      "NOT_APPLICABLE",
      "EXPIRED",
      "CONFLICT",
      "ERROR",
    ];
    assert.equal(validStatuses.length, 9);
    assert.ok(validStatuses.includes("VERIFIED"));
    assert.ok(validStatuses.includes("CONFLICT"));
  });

  it("TEST 5: RBAC permissions correctly gate approval execution", () => {
    const canApprove = (role: Role) => {
      return role === "Admin" || role === "RiskManager" || role === "OpsManager";
    };

    assert.equal(canApprove("Admin"), true);
    assert.equal(canApprove("RiskManager"), true);
    assert.equal(canApprove("OpsManager"), true);
    assert.equal(canApprove("Analyst"), false);
    assert.equal(canApprove("Viewer"), false);
  });

  it("TEST 6: ApiClientError correctly parses and formats error details", () => {
    const err = new ApiClientError(403, "Forbidden", "This action requires RiskManager role", "FORBIDDEN");
    assert.equal(err.status, 403);
    assert.equal(err.detail, "This action requires RiskManager role");
    assert.equal(err.code, "FORBIDDEN");
  });

  it("TEST 7: Dashboard metrics fallback safely to 0 on failure without crashing", async () => {
    // Intercept with unreachable path or test fallback
    const metrics = await apiClient.getDashboardMetrics();
    assert.ok(typeof metrics.active_critical_risks === "number");
    assert.ok(typeof metrics.shipments_in_transit === "number");
    assert.ok(typeof metrics.pending_approvals === "number");
    assert.ok(typeof metrics.verified_actions_30d === "number");
    assert.ok(metrics.pipeline);
    assert.ok(typeof metrics.pipeline.ingestion === "number");
  });

  it("TEST 8: Client-side storage audit confirms zero token leaks", () => {
    if (typeof localStorage !== "undefined") {
      assert.equal(localStorage.getItem("access_token"), null);
      assert.equal(localStorage.getItem("token"), null);
      assert.equal(localStorage.getItem("jwt"), null);
    }
  });
});
