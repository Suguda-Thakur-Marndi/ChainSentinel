/**
 * Comprehensive TypeScript API Contracts for RiskWise 2.0 (Phase 19).
 * Derived directly from authoritative FastAPI schemas and agent contracts.
 */

export type Role = "Admin" | "RiskManager" | "OpsManager" | "Analyst" | "Viewer";

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ==========================================
// AUTH & TENANCY
// ==========================================
export interface OrganizationInfo {
  id: string;
  name: string;
  domain?: string;
  slug?: string;
}

export interface UserMeResponse {
  id: string;
  email: string;
  full_name: string;
  organization_id: string;
  role: Role;
  avatar_url?: string | null;
  organization?: OrganizationInfo;
}

// ==========================================
// HEALTH
// ==========================================
export interface SystemHealthResponse {
  status: string;
  timestamp: string;
  version?: string;
  components?: Record<string, { status: string; latency_ms?: number }>;
}

// ==========================================
// LOGISTICS & SHIPMENTS
// ==========================================
export type ShipmentStatus =
  | "PLANNED"
  | "IN_TRANSIT"
  | "DELAYED"
  | "DELIVERED"
  | "CANCELLED"
  | "EXCEPTION";

export type DataProvenance = "REAL" | "SYNTHETIC" | "ESTIMATED" | "SIMULATED";

export interface ShipmentResponse {
  id: string;
  org_id?: string | null;
  tracking_number: string;
  route_id?: string | null;
  product_id?: string | null;
  carrier_id?: string | null;
  origin?: string | null;
  destination?: string | null;
  status: ShipmentStatus;
  mode: string;
  current_lat?: number | null;
  current_lng?: number | null;
  eta?: string | null;
  eta_confidence?: number | null;
  delay_minutes?: number | null;
  data_provenance: DataProvenance;
  risk_id?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface ShipmentCreate {
  tracking_number: string;
  route_id?: string | null;
  product_id?: string | null;
  carrier_id?: string | null;
  origin?: string | null;
  destination?: string | null;
  status?: ShipmentStatus;
  mode?: string;
  current_lat?: number | null;
  current_lng?: number | null;
  eta?: string | null;
  eta_confidence?: number | null;
  delay_minutes?: number | null;
  data_provenance?: DataProvenance;
  risk_id?: string | null;
}

export interface ShipmentEventResponse {
  id: string;
  shipment_id: string;
  event_type: string;
  timestamp: string;
  latitude?: number | null;
  longitude?: number | null;
  location_name?: string | null;
  raw_payload?: Record<string, unknown> | null;
}

// ==========================================
// RISKS & INCIDENTS
// ==========================================
export type RiskSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL" | "INFORMATIONAL";
export type RiskTrend = "INCREASING" | "DECREASING" | "STABLE" | "VOLATILE";

export interface RiskResponse {
  id: string;
  org_id?: string | null;
  title: string;
  risk_type?: string | null;
  severity: RiskSeverity;
  location?: string | null;
  probability?: number | null;
  impact?: number | null;
  risk_score?: number | null;
  confidence?: number | null;
  trend: RiskTrend;
  source?: string | null;
  detected_at: string;
  updated_at?: string | null;
}

export interface RiskFactorResponse {
  id: string;
  risk_id: string;
  factor_name: string;
  weight: number;
  score: number;
  contributing_data?: Record<string, unknown> | null;
}

export interface RiskAssessmentResponse {
  id: string;
  risk_id: string;
  assessor_type: "AI_AGENT" | "HUMAN_ANALYST" | "DETERMINISTIC_ENGINE";
  assessor_id?: string | null;
  overall_score: number;
  confidence: number;
  rationale?: string | null;
  created_at: string;
}

export type IncidentStatus =
  | "DETECTED"
  | "INVESTIGATING"
  | "MITIGATING"
  | "RESOLVED"
  | "CLOSED";

export interface IncidentResponse {
  id: string;
  org_id?: string | null;
  title: string;
  description?: string | null;
  severity: RiskSeverity;
  status: IncidentStatus;
  primary_risk_id?: string | null;
  affected_shipment_ids?: string[];
  detected_at: string;
  resolved_at?: string | null;
}

export interface IncidentCreate {
  title: string;
  description?: string | null;
  severity: RiskSeverity;
  status?: IncidentStatus;
  primary_risk_id?: string | null;
}

// ==========================================
// DIGITAL TWIN (Phase 12)
// ==========================================
export type TwinNodeType =
  | "SUPPLIER"
  | "SUPPLIER_SITE"
  | "FACTORY"
  | "WAREHOUSE"
  | "PORT"
  | "CARRIER"
  | "ROUTE"
  | "NODE";

export type TwinEdgeType =
  | "SUPPLIES"
  | "TRANSPORTS"
  | "CONNECTS"
  | "DEPENDS_ON"
  | "SERVES";

export interface TwinNodeContract {
  id?: string;
  node_id?: string;
  node_type: TwinNodeType;
  label: string;
  latitude?: number | null;
  longitude?: number | null;
  criticality?: string | null;
  status?: string | null;
  properties?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  risk_score?: number | null;
  health_score?: number | null;
  is_spof?: boolean;
}

export interface TwinEdgeContract {
  id?: string;
  edge_id?: string;
  source?: string;
  target?: string;
  from_node_id?: string;
  to_node_id?: string;
  edge_type: TwinEdgeType;
  transport_mode?: string | null;
  distance_km?: number | null;
  lead_time_days?: number | null;
  properties?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface DigitalTwinSummaryResponse {
  twin_id: string;
  organization_id: string;
  version: string;
  node_count: number;
  edge_count: number;
  source_fingerprint: string;
  twin_fingerprint: string;
  generated_at: string;
  status: string;
}

export interface DigitalTwinSnapshot {
  twin_id: string;
  organization_id: string;
  version: string;
  nodes: TwinNodeContract[] | Record<string, TwinNodeContract>;
  edges: TwinEdgeContract[] | Record<string, TwinEdgeContract>;
  source_fingerprint: string;
  twin_fingerprint: string;
  generated_at: string;
  status: string;
}

export interface TwinPathResult {
  path_found: boolean;
  nodes: string[];
  edges: string[];
  total_distance_km?: number | null;
  estimated_lead_time_days?: number | null;
}

// ==========================================
// SIMULATION (Phase 13)
// ==========================================
export type DisruptionType =
  | "PORT_CLOSURE"
  | "SUPPLIER_OUTAGE"
  | "CANAL_BLOCKAGE"
  | "WEATHER_EVENT"
  | "DEMAND_SURGE"
  | "CUSTOM";

export interface DisruptionEvent {
  disruption_type: DisruptionType;
  target_node_id?: string | null;
  target_edge_id?: string | null;
  duration_days: number;
  severity: number;
}

export interface SimulationScenario {
  scenario_id: string;
  organization_id: string;
  twin_version?: string;
  name: string;
  description?: string;
  disruptions: DisruptionEvent[];
  created_at?: string;
}

export interface SimulationResult {
  result_id: string;
  scenario_id: string;
  organization_id: string;
  status: "COMPLETED" | "RUNNING" | "FAILED";
  impact_score: number;
  affected_nodes: string[];
  affected_edges: string[];
  affected_shipments: string[];
  cost_impact_usd: number;
  delay_impact_hours: number;
  unmet_demand_units?: number;
  created_at: string;
}

export interface SimulationComparison {
  scenario_a: SimulationResult;
  scenario_b: SimulationResult;
  delta_impact_score: number;
  delta_cost_usd: number;
  delta_delay_hours: number;
}

// ==========================================
// OPTIMIZATION (Phase 14)
// ==========================================
export type OptimizationStatus =
  | "OPTIMAL"
  | "FEASIBLE"
  | "INFEASIBLE"
  | "UNBOUNDED"
  | "TIME_LIMIT"
  | "NOT_AVAILABLE"
  | "FAILED";

export interface OptimizationCandidate {
  candidate_id: string;
  action_type: string;
  target_id: string;
  utility: number;
  cost_usd: number;
  delay_hours: number;
  risk_mitigation: number;
  pareto_optimal?: boolean;
}

export interface OptimizationRequest {
  objective: "MINIMIZE_COST" | "MINIMIZE_DELAY" | "MAXIMIZE_RISK_REDUCTION" | "MULTI_OBJECTIVE";
  scenario_id?: string | null;
  shipment_ids?: string[];
  budget_max_usd?: number | null;
  max_delay_hours?: number | null;
}

export interface OptimizationResult {
  optimization_id: string;
  organization_id: string;
  status: OptimizationStatus;
  objective: string;
  objective_value?: number | null;
  runtime_ms: number;
  solver_status: string;
  candidates: OptimizationCandidate[];
  selected_candidate_id?: string | null;
  solution_payload?: Record<string, unknown>;
  created_at: string;
}

// ==========================================
// RECOMMENDATIONS & DECISIONS (Phase 15)
// ==========================================
export type RecommendationStatus = "PENDING" | "APPROVED" | "REJECTED" | "EXECUTED";

export interface RecommendationResponse {
  id: string;
  org_id?: string | null;
  incident_id?: string | null;
  title: string;
  rationale?: string | null;
  estimated_cost?: number | null;
  expected_benefit_json: Record<string, unknown>;
  confidence?: number | null;
  status: RecommendationStatus;
  created_at: string;
}

export interface DecisionCandidate {
  candidate_id: string;
  action_type: string;
  target_entity_type: string;
  target_entity_id: string;
  utility: number;
  cost_usd: number;
  delay_hours: number;
  risk_delta: number;
  is_pareto: boolean;
  trade_offs?: string[];
}

export interface DecisionResult {
  decision_id: string;
  organization_id: string;
  title: string;
  rationale: string;
  ai_explanation?: string | null;
  rag_citations?: Array<{ source: string; document_id: string; snippet: string }>;
  candidates: DecisionCandidate[];
  selected_candidate_id: string;
  deterministic_score: number;
  decision_status: "FORMULATED" | "SUBMITTED" | "APPROVED" | "REJECTED";
  created_at: string;
}

export interface DecisionRequest {
  incident_id?: string | null;
  risk_id?: string | null;
  simulation_result_id?: string | null;
  optimization_id?: string | null;
  constraints?: Record<string, unknown>;
}

// ==========================================
// APPROVALS (Phase 16)
// ==========================================
export type ApprovalDecision = "APPROVE" | "REJECT" | "REQUEST_MODIFICATION";

export interface ApprovalResponse {
  id: string;
  recommendation_id: string;
  decision_id?: string | null;
  decided_by_user_id?: string | null;
  decided_by_name?: string | null;
  decision: ApprovalDecision;
  comments?: string | null;
  decided_at: string;
  fingerprint?: string | null;
  integrity_status?: "VALID" | "TAMPERED" | "PENDING";
}

export interface ApprovalCreate {
  recommendation_id: string;
  decision: ApprovalDecision;
  comments?: string | null;
}

// ==========================================
// ACTIONS (Phase 17)
// ==========================================
export type ActionExecutionStatus =
  | "PENDING"
  | "VALIDATING"
  | "EXECUTING"
  | "SUCCEEDED"
  | "SUBMITTED"
  | "FAILED"
  | "TIMEOUT"
  | "AMBIGUOUS"
  | "NOT_AVAILABLE";

export interface ActionResponse {
  id: string;
  org_id?: string | null;
  recommendation_id?: string | null;
  decision_id?: string | null;
  action_type: string;
  target_entity_type?: string | null;
  target_entity_id?: string | null;
  status: ActionExecutionStatus;
  execution_payload: Record<string, unknown>;
  result_payload?: Record<string, unknown> | null;
  executed_at: string;
  executed_by?: string | null;
  adapter_ack_id?: string | null;
}

export interface ActionCreate {
  recommendation_id?: string | null;
  action_type: string;
  target_entity_type?: string | null;
  target_entity_id?: string | null;
  execution_payload?: Record<string, unknown>;
}

// ==========================================
// VERIFICATION (Phase 18)
// ==========================================
export type VerificationStatus =
  | "VERIFIED"
  | "PARTIALLY_VERIFIED"
  | "FAILED"
  | "PENDING"
  | "INSUFFICIENT_EVIDENCE"
  | "NOT_APPLICABLE"
  | "EXPIRED"
  | "CONFLICT"
  | "ERROR";

export type EvidenceSourcePrecedence = "REAL" | "ESTIMATED" | "SIMULATED";

export interface VerificationResultResponse {
  id: string;
  action_id: string;
  decision_id?: string | null;
  status: VerificationStatus;
  verified: boolean;
  evidence_precedence: EvidenceSourcePrecedence;
  intended_outcome?: string | null;
  observed_outcome?: string | null;
  risk_score_before?: number | null;
  risk_score_after?: number | null;
  observation_summary?: string | null;
  evidence_items?: Array<{
    source_type: EvidenceSourcePrecedence;
    source_id: string;
    description: string;
    timestamp: string;
  }>;
  policy_checks_passed?: boolean;
  verified_at: string;
}

// ==========================================
// AUDIT LOG
// ==========================================
export interface AuditLogResponse {
  id: string;
  org_id?: string | null;
  actor_type: "USER" | "SYSTEM" | "AGENT";
  actor_id?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  status: "SUCCESS" | "FAILED";
  details?: Record<string, unknown> | null;
  timestamp: string;
  request_id?: string | null;
  trace_id?: string | null;
  fingerprint?: string | null;
}

// ==========================================
// NETWORK ENTITIES (Phase 4)
// ==========================================
export interface SupplierResponse {
  id: string;
  org_id?: string | null;
  name: string;
  code?: string | null;
  country?: string | null;
  tier?: string | null;
  criticality?: string | null;
  reliability_score?: number | null;
  financial_exposure?: number | null;
  lead_time_days?: number | null;
  current_risk_id?: string | null;
  metadata_json?: Record<string, unknown> | null;
  created_at: string;
  updated_at?: string | null;
}

export interface SupplierCreate {
  name: string;
  code?: string | null;
  country?: string | null;
  tier?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  criticality?: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  reliability_score?: number | null;
  financial_exposure?: number | null;
  lead_time_days?: number | null;
}

export interface PortResponse {
  id: string;
  name: string;
  code: string;
  country: string;
  port_type: "SEA" | "AIR" | "INLAND";
  latitude?: number | null;
  longitude?: number | null;
  congestion_level?: string | null;
  is_operational: boolean;
}

export interface CarrierResponse {
  id: string;
  name: string;
  code: string;
  mode: string;
  reliability_rating?: number | null;
  contact_email?: string | null;
}

export interface FactoryResponse {
  id: string;
  name: string;
  country: string;
  city?: string | null;
  capacity_utilization?: number | null;
  status: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface WarehouseResponse {
  id: string;
  name: string;
  country: string;
  city?: string | null;
  capacity_utilization?: number | null;
  status: string;
  latitude?: number | null;
  longitude?: number | null;
}

export interface RouteResponse {
  id: string;
  origin_id: string;
  destination_id: string;
  mode: string;
  transit_time_days?: number | null;
  cost_usd?: number | null;
  status: string;
}

export interface ProductResponse {
  id: string;
  sku: string;
  name: string;
  category?: string | null;
  unit_cost?: number | null;
  criticality?: string | null;
}

export interface InventoryResponse {
  id: string;
  product_id: string;
  warehouse_id: string;
  quantity_on_hand: number;
  safety_stock: number;
  reorder_point: number;
  last_updated: string;
}

// ==========================================
// NOTIFICATIONS
// ==========================================
export interface NotificationResponse {
  id: string;
  title: string;
  message: string;
  category: "RISK_ALERT" | "SHIPMENT_DELAY" | "RECOMMENDATION" | "SYSTEM";
  severity: "INFO" | "WARNING" | "CRITICAL";
  is_read: boolean;
  created_at: string;
  link_url?: string | null;
}

// ==========================================
// CONTROL TOWER AGGREGATED METRICS
// ==========================================
export interface ControlTowerMetrics {
  active_critical_risks: number;
  shipments_in_transit: number;
  pending_approvals: number;
  verified_actions_30d: number;
  pipeline: {
    ingestion: number;
    risk: number;
    twin: number;
    simulation: number;
    optimization: number;
    decision: number;
    approval: number;
    action: number;
    verification: number;
  };
}

// ==========================================
// PHASE 20 — EVALUATION & QUALITY ASSURANCE
// ==========================================
export type EvaluationStatus =
  | "PENDING"
  | "RUNNING"
  | "PASSED"
  | "FAILED"
  | "PARTIAL"
  | "NOT_AVAILABLE"
  | "ERROR"
  | "CANCELLED";

export type EvaluationSuiteType =
  | "AGENT_EVALUATION"
  | "RESEARCH_EVALUATION"
  | "RISK_EVALUATION"
  | "RAG_EVALUATION"
  | "CLAUDE_EVALUATION"
  | "ML_EVALUATION"
  | "DIGITAL_TWIN_EVALUATION"
  | "SIMULATION_EVALUATION"
  | "OPTIMIZATION_EVALUATION"
  | "DECISION_EVALUATION"
  | "APPROVAL_EVALUATION"
  | "ACTION_EVALUATION"
  | "VERIFICATION_EVALUATION"
  | "END_TO_END_EVALUATION"
  | "SECURITY_EVALUATION";

export interface EvaluationMetricContract {
  name: string;
  domain: string;

  value: number | null;
  numerator?: number | null;
  denominator?: number | null;
  sample_size: number;
  dataset_version: string;
  status: EvaluationStatus;
  timestamp: string;
}

export interface EvaluationScoreContract {
  domain: string;
  overall_score: number | null;
  status: EvaluationStatus;
  weights: Record<string, number>;
  sample_count: number;
  minimum_sample_met: boolean;
  summary: string;
}

export interface EvaluationFailureContract {
  case_id: string;
  reason: string;
  expected?: any;
  actual?: any;
}

export interface EvaluationReportContract {
  report_id: string;
  run_id: string;
  suite_type: EvaluationSuiteType;
  domain: string;
  status: EvaluationStatus;
  summary: string;
  dataset_version: string;
  configuration_fingerprint: string;
  result_fingerprint: string;
  metrics: EvaluationMetricContract[];
  domain_score?: EvaluationScoreContract | null;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  results: any[];
  failures: EvaluationFailureContract[];
  duration_ms: number;
  tenant_id?: string | null;
  timestamp: string;
}

export interface EvaluationRunSummaryContract {
  id: string;
  suite_type: string;
  domain: string;
  status: EvaluationStatus;
  tenant_id?: string | null;
  dataset_version: string;
  config_fingerprint: string;
  result_fingerprint: string;
  duration_ms: number;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  summary?: string | null;
  created_at?: string | null;
}

export interface EvaluationSuiteMetadata {
  suite_type: string;
  domain: string;
  version: string;
  description: string;
}

export interface EvaluationDatasetMetadata {
  dataset_id: string;
  name: string;
  domain: string;
  version: string;
  case_count: number;
  fingerprint: string;
  is_eval_only: boolean;
}

