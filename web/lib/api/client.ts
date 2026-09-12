/**
 * Unified API Client for RiskWise 2.0 (Phase 19).
 *
 * Centralizes:
 * - Base URL resolution from NEXT_PUBLIC_API_URL
 * - Strict credentials: "include" for HttpOnly session cookie transmission
 * - Standardized error parsing & ApiClientError normalization
 * - Session expiration (401) event subscription
 * - Typed accessor domains matching the authoritative FastAPI backend
 */

import { LogoutResponse, UserMeResponse } from "../auth/types";
import type {
  ActionCreate,
  ActionResponse,
  ApprovalCreate,
  ApprovalResponse,
  AuditLogResponse,
  CarrierResponse,
  ControlTowerMetrics,
  DecisionRequest,
  DecisionResult,
  DigitalTwinSnapshot,
  DigitalTwinSummaryResponse,
  FactoryResponse,
  IncidentCreate,
  IncidentResponse,
  InventoryResponse,
  NotificationResponse,
  OptimizationRequest,
  OptimizationResult,
  PaginatedResponse,
  PortResponse,
  ProductResponse,
  RecommendationResponse,
  RiskAssessmentResponse,
  RiskFactorResponse,
  RiskResponse,
  RouteResponse,
  ShipmentCreate,
  ShipmentEventResponse,
  ShipmentResponse,
  SimulationComparison,
  SimulationResult,
  SimulationScenario,
  SupplierCreate,
  SupplierResponse,
  SystemHealthResponse,
  TwinPathResult,
  VerificationResultResponse,
  WarehouseResponse,
  EvaluationSuiteMetadata,
  EvaluationDatasetMetadata,
  EvaluationReportContract,
  EvaluationRunSummaryContract,
  EvaluationSuiteType,
} from "./types";



export class ApiClientError extends Error {
  public status: number;
  public statusText: string;
  public detail: string;
  public code?: string;

  constructor(status: number, statusText: string, detail: string, code?: string) {
    super(detail || `API Error ${status}: ${statusText}`);
    this.name = "ApiClientError";
    this.status = status;
    this.statusText = statusText;
    this.detail = detail;
    this.code = code;
  }
}

type UnauthorizedListener = (error: ApiClientError) => void;

class ApiClient {
  private baseUrl: string;
  private unauthorizedListeners: Set<UnauthorizedListener> = new Set();

  constructor() {
    this.baseUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/+$/, "");
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Subscribe to 401 Unauthorized responses to trigger global session expiration.
   */
  public onUnauthorized(listener: UnauthorizedListener): () => void {
    this.unauthorizedListeners.add(listener);
    return () => {
      this.unauthorizedListeners.delete(listener);
    };
  }

  private notifyUnauthorized(error: ApiClientError): void {
    for (const listener of this.unauthorizedListeners) {
      try {
        listener(error);
      } catch (e) {
        console.error("Error in onUnauthorized listener:", e);
      }
    }
  }

  /**
   * Core credentialed fetch wrapper.
   */
  public async request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
    const url = path.startsWith("http://") || path.startsWith("https://")
      ? path
      : `${this.baseUrl}${path.startsWith("/") ? "" : "/"}${path}`;

    const headers = new Headers(options.headers || {});
    if (!headers.has("Accept")) {
      headers.set("Accept", "application/json");
    }
    if (options.body && typeof options.body === "string" && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "include", // Enforce HttpOnly cookie inclusion
    });

    if (!response.ok) {
      let detail = response.statusText;
      let code: string | undefined;

      try {
        const errorBody = await response.json();
        if (typeof errorBody === "object" && errorBody !== null) {
          if (typeof errorBody.detail === "string") {
            detail = errorBody.detail;
          } else if (Array.isArray(errorBody.detail)) {
            detail = errorBody.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(", ");
          }
          if (typeof errorBody.code === "string") {
            code = errorBody.code;
          }
        }
      } catch {
        // Non-JSON response body
      }

      const clientError = new ApiClientError(response.status, response.statusText, detail, code);

      if (response.status === 401) {
        this.notifyUnauthorized(clientError);
      }

      throw clientError;
    }

    // 204 No Content
    if (response.status === 204) {
      return null as T;
    }

    return (await response.json()) as T;
  }

  public get<T = unknown>(path: string, options?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...options, method: "GET" });
  }

  public post<T = unknown>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public put<T = unknown>(path: string, body?: unknown, options?: RequestInit): Promise<T> {
    return this.request<T>(path, {
      ...options,
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public delete<T = unknown>(path: string, options?: RequestInit): Promise<T> {
    return this.request<T>(path, { ...options, method: "DELETE" });
  }

  // ==========================================
  // AUTH
  // ==========================================
  public readonly auth = {
    getMe: (): Promise<UserMeResponse> => {
      return this.get<UserMeResponse>("/api/v1/auth/me");
    },

    logout: (): Promise<LogoutResponse> => {
      return this.post<LogoutResponse>("/api/v1/auth/logout");
    },

    getGoogleAuthUrl: (returnTo: string = "/"): string => {
      const sanitizedReturnTo = returnTo.startsWith("/") && !returnTo.startsWith("//") ? returnTo : "/";
      const targetUrl = new URL("/api/v1/auth/google", this.baseUrl);
      targetUrl.searchParams.set("return_to", sanitizedReturnTo);
      return targetUrl.href;
    },
  };

  // ==========================================
  // HEALTH
  // ==========================================
  public readonly health = {
    get: (): Promise<SystemHealthResponse> => {
      return this.get<SystemHealthResponse>("/health");
    },
  };

  // ==========================================
  // SHIPMENTS
  // ==========================================
  public readonly shipments = {
    list: (params?: { limit?: number; offset?: number; status?: string }): Promise<PaginatedResponse<ShipmentResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      if (params?.status) q.set("status", params.status);
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<ShipmentResponse>>(`/api/v1/shipments${qs}`);
    },
    get: (id: string): Promise<ShipmentResponse> => {
      return this.get<ShipmentResponse>(`/api/v1/shipments/${id}`);
    },
    create: (data: ShipmentCreate): Promise<ShipmentResponse> => {
      return this.post<ShipmentResponse>("/api/v1/shipments", data);
    },
    getEvents: (shipmentId: string): Promise<ShipmentEventResponse[]> => {
      return this.get<ShipmentEventResponse[]>(`/api/v1/shipment-events?shipment_id=${shipmentId}`);
    },
  };

  // ==========================================
  // RISKS
  // ==========================================
  public readonly risks = {
    list: (params?: { limit?: number; offset?: number; severity?: string }): Promise<PaginatedResponse<RiskResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      if (params?.severity) q.set("severity", params.severity);
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<RiskResponse>>(`/api/v1/risks${qs}`);
    },
    get: (id: string): Promise<RiskResponse> => {
      return this.get<RiskResponse>(`/api/v1/risks/${id}`);
    },
    create: (data: Partial<RiskResponse>): Promise<RiskResponse> => {
      return this.post<RiskResponse>("/api/v1/risks", data);
    },
    getFactors: (riskId: string): Promise<RiskFactorResponse[]> => {
      return this.get<RiskFactorResponse[]>(`/api/v1/risk-factors?risk_id=${riskId}`);
    },
    getAssessments: (riskId: string): Promise<RiskAssessmentResponse[]> => {
      return this.get<RiskAssessmentResponse[]>(`/api/v1/risk-assessments?risk_id=${riskId}`);
    },
  };

  // ==========================================
  // INCIDENTS
  // ==========================================
  public readonly incidents = {
    list: (params?: { limit?: number; offset?: number; status?: string }): Promise<PaginatedResponse<IncidentResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      if (params?.status) q.set("status", params.status);
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<IncidentResponse>>(`/api/v1/incidents${qs}`);
    },
    get: (id: string): Promise<IncidentResponse> => {
      return this.get<IncidentResponse>(`/api/v1/incidents/${id}`);
    },
    create: (data: IncidentCreate): Promise<IncidentResponse> => {
      return this.post<IncidentResponse>("/api/v1/incidents", data);
    },
  };

  // ==========================================
  // DIGITAL TWIN (Phase 12)
  // ==========================================
  public readonly digitalTwin = {
    getCurrent: (): Promise<DigitalTwinSummaryResponse> => {
      return this.get<DigitalTwinSummaryResponse>("/api/v1/digital-twin/current");
    },
    getSnapshot: (): Promise<DigitalTwinSnapshot> => {
      return this.get<DigitalTwinSnapshot>("/api/v1/digital-twin/snapshot");
    },
    getPath: (source: string, target: string, maxDepth: number = 5): Promise<TwinPathResult> => {
      return this.post<TwinPathResult>("/api/v1/digital-twin/path", {
        source_node_id: source,
        target_node_id: target,
        max_depth: maxDepth,
      });
    },
  };

  // ==========================================
  // SIMULATION (Phase 13)
  // ==========================================
  public readonly simulation = {
    createScenario: (scenario: Partial<SimulationScenario>): Promise<SimulationScenario> => {
      return this.post<SimulationScenario>("/api/v1/simulation/scenarios", scenario);
    },
    run: (input: { scenario_id: string; twin_version?: string }): Promise<SimulationResult> => {
      return this.post<SimulationResult>("/api/v1/simulation/run", input);
    },
    getResult: (resultId: string): Promise<SimulationResult> => {
      return this.get<SimulationResult>(`/api/v1/simulation/results/${resultId}`);
    },
    compare: (scenarioAId: string, scenarioBId: string): Promise<SimulationComparison> => {
      return this.post<SimulationComparison>("/api/v1/simulation/compare", {
        scenario_a_id: scenarioAId,
        scenario_b_id: scenarioBId,
      });
    },
  };

  // ==========================================
  // OPTIMIZATION (Phase 14)
  // ==========================================
  public readonly optimization = {
    list: (params?: { limit?: number; offset?: number }): Promise<OptimizationResult[]> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<OptimizationResult[]>(`/api/v1/optimization-runs${qs}`);
    },
    create: (request: OptimizationRequest): Promise<OptimizationResult> => {
      return this.post<OptimizationResult>("/api/v1/optimization-runs", request);
    },
    get: (id: string): Promise<OptimizationResult> => {
      return this.get<OptimizationResult>(`/api/v1/optimization-runs/${id}`);
    },
  };

  // ==========================================
  // RECOMMENDATIONS (Phase 4 / 15)
  // ==========================================
  public readonly recommendations = {
    list: (params?: { limit?: number; offset?: number; status?: string }): Promise<PaginatedResponse<RecommendationResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      if (params?.status) q.set("status", params.status);
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<RecommendationResponse>>(`/api/v1/recommendations${qs}`);
    },
    get: (id: string): Promise<RecommendationResponse> => {
      return this.get<RecommendationResponse>(`/api/v1/recommendations/${id}`);
    },
  };

  // ==========================================
  // DECISIONS (Phase 15)
  // ==========================================
  public readonly decisions = {
    list: (params?: { limit?: number; offset?: number }): Promise<DecisionResult[]> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<DecisionResult[]>(`/api/v1/decisions${qs}`);
    },
    create: (request: DecisionRequest): Promise<DecisionResult> => {
      return this.post<DecisionResult>("/api/v1/decisions", request);
    },
    get: (id: string): Promise<DecisionResult> => {
      return this.get<DecisionResult>(`/api/v1/decisions/${id}`);
    },
  };

  // ==========================================
  // APPROVALS (Phase 16)
  // ==========================================
  public readonly approvals = {
    list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<ApprovalResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<ApprovalResponse>>(`/api/v1/approvals${qs}`);
    },
    create: (payload: ApprovalCreate): Promise<ApprovalResponse> => {
      return this.post<ApprovalResponse>("/api/v1/approvals", payload);
    },
  };

  // ==========================================
  // ACTIONS (Phase 17)
  // ==========================================
  public readonly actions = {
    list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<ActionResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<ActionResponse>>(`/api/v1/actions${qs}`);
    },
    create: (payload: ActionCreate): Promise<ActionResponse> => {
      return this.post<ActionResponse>("/api/v1/actions", payload);
    },
    get: (id: string): Promise<ActionResponse> => {
      return this.get<ActionResponse>(`/api/v1/actions/${id}`);
    },
  };

  // ==========================================
  // VERIFICATION (Phase 18)
  // ==========================================
  public readonly verification = {
    list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<VerificationResultResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<VerificationResultResponse>>(`/api/v1/verification-results${qs}`);
    },
    get: (id: string): Promise<VerificationResultResponse> => {
      return this.get<VerificationResultResponse>(`/api/v1/verification-results/${id}`);
    },
  };

  // ==========================================
  // AUDIT LOG
  // ==========================================
  public readonly audit = {
    list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<AuditLogResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<AuditLogResponse>>(`/api/v1/audit-logs${qs}`);
    },
  };

  // ==========================================
  // NETWORK & MASTER DATA
  // ==========================================
  public readonly network = {
    suppliers: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<SupplierResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<SupplierResponse>>(`/api/v1/suppliers${qs}`);
      },
      create: (data: SupplierCreate): Promise<SupplierResponse> => {
        return this.post<SupplierResponse>("/api/v1/suppliers", data);
      },
      get: (id: string): Promise<SupplierResponse> => {
        return this.get<SupplierResponse>(`/api/v1/suppliers/${id}`);
      },
    },
    ports: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<PortResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<PortResponse>>(`/api/v1/ports${qs}`);
      },
    },
    carriers: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<CarrierResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<CarrierResponse>>(`/api/v1/carriers${qs}`);
      },
    },
    factories: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<FactoryResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<FactoryResponse>>(`/api/v1/factories${qs}`);
      },
    },
    warehouses: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<WarehouseResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<WarehouseResponse>>(`/api/v1/warehouses${qs}`);
      },
    },
    routes: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<RouteResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<RouteResponse>>(`/api/v1/routes${qs}`);
      },
    },
    products: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<ProductResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<ProductResponse>>(`/api/v1/products${qs}`);
      },
    },
    inventory: {
      list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<InventoryResponse>> => {
        const q = new URLSearchParams();
        if (params?.limit) q.set("limit", String(params.limit));
        if (params?.offset) q.set("offset", String(params.offset));
        const qs = q.toString() ? `?${q.toString()}` : "";
        return this.get<PaginatedResponse<InventoryResponse>>(`/api/v1/inventory${qs}`);
      },
    },
  };

  // ==========================================
  // NOTIFICATIONS
  // ==========================================
  public readonly notifications = {
    list: (params?: { limit?: number; offset?: number }): Promise<PaginatedResponse<NotificationResponse>> => {
      const q = new URLSearchParams();
      if (params?.limit) q.set("limit", String(params.limit));
      if (params?.offset) q.set("offset", String(params.offset));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<PaginatedResponse<NotificationResponse>>(`/api/v1/notifications${qs}`);
    },
    markRead: (id: string): Promise<void> => {
      return this.put<void>(`/api/v1/notifications/${id}/read`);
    },
  };

  // ==========================================
  // AGGREGATED DASHBOARD
  // ==========================================
  public async getDashboardMetrics(): Promise<ControlTowerMetrics> {
    try {
      const [risksRes, shipmentsRes, approvalsRes, verificationRes] = await Promise.allSettled([
        this.risks.list({ limit: 100 }),
        this.shipments.list({ limit: 100 }),
        this.approvals.list({ limit: 100 }),
        this.verification.list({ limit: 100 }),
      ]);

      const risks = risksRes.status === "fulfilled" ? risksRes.value.items || [] : [];
      const shipments = shipmentsRes.status === "fulfilled" ? shipmentsRes.value.items || [] : [];
      const approvals = approvalsRes.status === "fulfilled" ? approvalsRes.value.items || [] : [];
      const verification = verificationRes.status === "fulfilled" ? verificationRes.value.items || [] : [];

      const activeCriticalRisks = risks.filter((r) => r.severity === "CRITICAL").length;
      const inTransit = shipments.filter((s) => s.status === "IN_TRANSIT").length;
      const pendingApprovals = approvals.filter((a) => a.decision === "APPROVE" || !a.decision).length;
      const verified30d = verification.filter((v) => v.verified).length;

      return {
        active_critical_risks: activeCriticalRisks,
        shipments_in_transit: inTransit,
        pending_approvals: pendingApprovals,
        verified_actions_30d: verified30d,
        pipeline: {
          ingestion: shipments.length + risks.length,
          risk: risks.length,
          twin: 1,
          simulation: 0,
          optimization: 0,
          decision: approvals.length,
          approval: pendingApprovals,
          action: 0,
          verification: verified30d,
        },
      };
    } catch {
      return {
        active_critical_risks: 0,
        shipments_in_transit: 0,
        pending_approvals: 0,
        verified_actions_30d: 0,
        pipeline: {
          ingestion: 0,
          risk: 0,
          twin: 0,
          simulation: 0,
          optimization: 0,
          decision: 0,
          approval: 0,
          action: 0,
          verification: 0,
        },
      };
    }
  }

  // ==========================================
  // EVALUATIONS (Phase 20)
  // ==========================================
  public readonly evaluations = {
    listSuites: (): Promise<EvaluationSuiteMetadata[]> => {
      return this.get<EvaluationSuiteMetadata[]>("/api/v1/evaluations/suites");
    },
    listDatasets: (): Promise<EvaluationDatasetMetadata[]> => {
      return this.get<EvaluationDatasetMetadata[]>("/api/v1/evaluations/datasets");
    },
    runSuite: (suiteType: EvaluationSuiteType, datasetVersion: string = "v1.0.0"): Promise<EvaluationReportContract> => {
      return this.post<EvaluationReportContract>("/api/v1/evaluations/run", {
        suite_type: suiteType,
        dataset_version: datasetVersion,
        persist_results: true,
      });
    },
    listRuns: (params?: { suite_type?: string; limit?: number }): Promise<EvaluationRunSummaryContract[]> => {
      const q = new URLSearchParams();
      if (params?.suite_type) q.set("suite_type", params.suite_type);
      if (params?.limit) q.set("limit", String(params.limit));
      const qs = q.toString() ? `?${q.toString()}` : "";
      return this.get<EvaluationRunSummaryContract[]>(`/api/v1/evaluations/runs${qs}`);
    },
    getRun: (id: string): Promise<EvaluationRunSummaryContract> => {
      return this.get<EvaluationRunSummaryContract>(`/api/v1/evaluations/runs/${id}`);
    },
    getReport: (id: string): Promise<EvaluationReportContract> => {
      return this.get<EvaluationReportContract>(`/api/v1/evaluations/runs/${id}/report`);
    },
  };
}

export const apiClient = new ApiClient();

