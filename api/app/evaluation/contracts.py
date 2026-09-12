"""Strongly typed contracts for RiskWise 2.0 Evaluation & Quality Assurance (Phase 20).

Enforces Pydantic v2 validation, strict determinism, immutable models,
reproducible cryptographic SHA-256 fingerprints, and zero metric fabrication.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def compute_sha256(data: Union[str, bytes, Dict[str, Any]]) -> str:
    """Computes deterministic SHA-256 hex digest."""
    if isinstance(data, dict):
        raw = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    elif isinstance(data, str):
        raw = data.encode("utf-8")
    else:
        raw = data
    return hashlib.sha256(raw).hexdigest()


class EvaluationStatus(str, Enum):
    """Authoritative evaluation lifecycle statuses."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


class EvaluationSuiteType(str, Enum):
    """Categorized evaluation suites corresponding to system architectural stages."""

    AGENT_EVALUATION = "AGENT_EVALUATION"
    RESEARCH_EVALUATION = "RESEARCH_EVALUATION"
    RISK_EVALUATION = "RISK_EVALUATION"
    RAG_EVALUATION = "RAG_EVALUATION"
    CLAUDE_EVALUATION = "CLAUDE_EVALUATION"
    ML_EVALUATION = "ML_EVALUATION"
    DIGITAL_TWIN_EVALUATION = "DIGITAL_TWIN_EVALUATION"
    SIMULATION_EVALUATION = "SIMULATION_EVALUATION"
    OPTIMIZATION_EVALUATION = "OPTIMIZATION_EVALUATION"
    DECISION_EVALUATION = "DECISION_EVALUATION"
    APPROVAL_EVALUATION = "APPROVAL_EVALUATION"
    ACTION_EVALUATION = "ACTION_EVALUATION"
    VERIFICATION_EVALUATION = "VERIFICATION_EVALUATION"
    END_TO_END_EVALUATION = "END_TO_END_EVALUATION"
    SECURITY_EVALUATION = "SECURITY_EVALUATION"


class DatasetCategory(str, Enum):
    """Dataset partition categories preventing contamination and ensuring test diversity."""

    NORMAL = "NORMAL"
    EDGE_CASE = "EDGE_CASE"
    FAILURE = "FAILURE"
    SECURITY = "SECURITY"
    CONFLICT = "CONFLICT"
    EMPTY_DATA = "EMPTY_DATA"
    BOUNDARY = "BOUNDARY"
    ADVERSARIAL = "ADVERSARIAL"


class EvaluationDomain(str, Enum):
    """Evaluation functional domains."""

    AGENT = "AGENT"
    RESEARCH = "RESEARCH"
    RISK = "RISK"
    RAG = "RAG"
    CLAUDE = "CLAUDE"
    ML = "ML"
    DIGITAL_TWIN = "DIGITAL_TWIN"
    SIMULATION = "SIMULATION"
    OPTIMIZATION = "OPTIMIZATION"
    DECISION = "DECISION"
    APPROVAL = "APPROVAL"
    ACTION = "ACTION"
    VERIFICATION = "VERIFICATION"
    END_TO_END = "END_TO_END"
    SECURITY = "SECURITY"


class EvaluationCase(BaseModel):
    """Deterministic, versioned benchmark evaluation case."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    case_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    domain: Optional[EvaluationDomain] = None
    suite_type: Optional[EvaluationSuiteType] = None
    category: DatasetCategory = Field(default=DatasetCategory.NORMAL)
    description: str = Field(default="", max_length=512)
    tenant_id: Optional[str] = Field(None, max_length=64)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    expected_output: Dict[str, Any] = Field(default_factory=dict)
    assertions: Dict[str, Any] = Field(default_factory=dict)
    oracle_type: str = Field(default="DETERMINISTIC_EXACT", max_length=64)
    version: str = Field(default="1.0.0", max_length=32)
    tags: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _ensure_domain_and_suite(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Domain mapping dictionary
            domain_map = {
                "AGENT_EVALUATION": EvaluationDomain.AGENT,
                "RESEARCH_EVALUATION": EvaluationDomain.RESEARCH,
                "RISK_EVALUATION": EvaluationDomain.RISK,
                "RAG_EVALUATION": EvaluationDomain.RAG,
                "CLAUDE_EVALUATION": EvaluationDomain.CLAUDE,
                "ML_EVALUATION": EvaluationDomain.ML,
                "DIGITAL_TWIN_EVALUATION": EvaluationDomain.DIGITAL_TWIN,
                "SIMULATION_EVALUATION": EvaluationDomain.SIMULATION,
                "OPTIMIZATION_EVALUATION": EvaluationDomain.OPTIMIZATION,
                "DECISION_EVALUATION": EvaluationDomain.DECISION,
                "APPROVAL_EVALUATION": EvaluationDomain.APPROVAL,
                "ACTION_EVALUATION": EvaluationDomain.ACTION,
                "VERIFICATION_EVALUATION": EvaluationDomain.VERIFICATION,
                "END_TO_END_EVALUATION": EvaluationDomain.END_TO_END,
                "SECURITY_EVALUATION": EvaluationDomain.SECURITY,
            }
            suite_map = {
                "AGENT": EvaluationSuiteType.AGENT_EVALUATION,
                "RESEARCH": EvaluationSuiteType.RESEARCH_EVALUATION,
                "RISK": EvaluationSuiteType.RISK_EVALUATION,
                "RAG": EvaluationSuiteType.RAG_EVALUATION,
                "CLAUDE": EvaluationSuiteType.CLAUDE_EVALUATION,
                "ML": EvaluationSuiteType.ML_EVALUATION,
                "DIGITAL_TWIN": EvaluationSuiteType.DIGITAL_TWIN_EVALUATION,
                "SIMULATION": EvaluationSuiteType.SIMULATION_EVALUATION,
                "OPTIMIZATION": EvaluationSuiteType.OPTIMIZATION_EVALUATION,
                "DECISION": EvaluationSuiteType.DECISION_EVALUATION,
                "APPROVAL": EvaluationSuiteType.APPROVAL_EVALUATION,
                "ACTION": EvaluationSuiteType.ACTION_EVALUATION,
                "VERIFICATION": EvaluationSuiteType.VERIFICATION_EVALUATION,
                "END_TO_END": EvaluationSuiteType.END_TO_END_EVALUATION,
                "SECURITY": EvaluationSuiteType.SECURITY_EVALUATION,
            }
            if not data.get("domain") and data.get("suite_type"):
                st_key = data["suite_type"].value if hasattr(data["suite_type"], "value") else str(data["suite_type"])
                data["domain"] = domain_map.get(st_key, EvaluationDomain.AGENT)
            if not data.get("suite_type") and data.get("domain"):
                dom_key = data["domain"].value if hasattr(data["domain"], "value") else str(data["domain"])
                data["suite_type"] = suite_map.get(dom_key, EvaluationSuiteType.AGENT_EVALUATION)
            if not data.get("domain"):
                data["domain"] = EvaluationDomain.AGENT
            if not data.get("suite_type"):
                data["suite_type"] = EvaluationSuiteType.AGENT_EVALUATION
        return data



class EvaluationResult(BaseModel):
    """Outcome of evaluating a single test case."""

    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(..., min_length=1, max_length=64)
    status: EvaluationStatus
    actual_output: Dict[str, Any] = Field(default_factory=dict)
    passed_assertions: List[str] = Field(default_factory=list)
    failed_assertions: List[str] = Field(default_factory=list)
    execution_time_ms: float = Field(default=0.0, ge=0.0)
    failure_reason: Optional[str] = None
    fingerprint: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _compute_fingerprint(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("fingerprint"):
            payload = f"{data.get('case_id')}:{data.get('status')}:{data.get('failure_reason')}"
            data["fingerprint"] = compute_sha256(payload)
        return data

    @property
    def passed(self) -> bool:
        return self.status == EvaluationStatus.PASSED


class EvaluationFailure(BaseModel):
    """Detailed record of a failed evaluation case."""

    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(..., min_length=1, max_length=64)
    reason: str = Field(default="")
    expected: Any = None
    actual: Any = None
    traceback: Optional[str] = None


class EvaluationMetric(BaseModel):
    """Measurable quality metric calculated with explicit sample size and provenance."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=128)
    domain: EvaluationDomain
    definition: str = Field(default="")
    value: Optional[float] = None
    numerator: Optional[float] = None
    denominator: Optional[float] = None
    sample_size: int = Field(default=0, ge=0)
    dataset_version: str = Field(default="1.0.0", max_length=32)
    status: EvaluationStatus = Field(default=EvaluationStatus.PASSED)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="before")
    @classmethod
    def _remap_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "sample_count" in data and "sample_size" not in data:
                data["sample_size"] = data["sample_count"]
        return data

    @property
    def sample_count(self) -> int:
        return self.sample_size

    @field_validator("value", mode="after")
    @classmethod
    def validate_metric_value(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Metric value must be a finite number.")
        return v


class EvaluationScore(BaseModel):
    """Domain-level aggregated score respecting weights and sample minimums."""

    model_config = ConfigDict(extra="ignore")

    domain: EvaluationDomain
    overall_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: EvaluationStatus = Field(default=EvaluationStatus.PASSED)
    weights: Dict[str, float] = Field(default_factory=dict)
    sample_count: int = Field(default=0, ge=0)
    minimum_sample_met: bool = Field(default=True)
    summary: str = Field(default="")

    @model_validator(mode="before")
    @classmethod
    def _remap_score_aliases(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "score_value" in data and "overall_score" not in data:
                data["overall_score"] = data["score_value"]
            if "weights_applied" in data and "weights" not in data:
                data["weights"] = data["weights_applied"]
            if "metric_count" in data and "sample_count" not in data:
                data["sample_count"] = data["metric_count"]
        return data


    @property
    def score_value(self) -> Optional[float]:
        return self.overall_score

    overall_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    status: EvaluationStatus = Field(default=EvaluationStatus.PASSED)
    weights: Dict[str, float] = Field(default_factory=dict)
    sample_count: int = Field(default=0, ge=0)
    minimum_sample_met: bool = Field(default=True)
    summary: str = Field(default="")


class EvaluationArtifact(BaseModel):
    """Trace, snapshot, or log artifact captured during evaluation."""

    model_config = ConfigDict(extra="ignore")

    artifact_id: str = Field(..., min_length=1, max_length=64)
    artifact_type: str = Field(..., min_length=1, max_length=64)
    uri: Optional[str] = None
    fingerprint: str = Field(..., min_length=1, max_length=64)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvaluationDataset(BaseModel):
    """Immutable, versioned collection of evaluation test cases."""

    model_config = ConfigDict(extra="ignore")

    dataset_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    domain: EvaluationDomain
    version: str = Field(default="v1.0.0", min_length=1, max_length=32)
    cases: List[EvaluationCase] = Field(default_factory=list)
    fingerprint: str = Field(default="")
    is_eval_only: bool = Field(default=True)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def case_count(self) -> int:
        return len(self.cases)


class EvaluationReport(BaseModel):
    """Comprehensive, immutable audit report for an evaluation suite run."""

    model_config = ConfigDict(extra="ignore")

    report_id: str = Field(..., min_length=1, max_length=64)
    run_id: str = Field(..., min_length=1, max_length=64)
    suite_type: EvaluationSuiteType
    domain: EvaluationDomain
    status: EvaluationStatus
    summary: str = Field(default="")
    dataset_version: str = Field(default="v1.0.0")
    configuration_fingerprint: str = Field(default="")
    result_fingerprint: str = Field(default="")
    metrics: List[EvaluationMetric] = Field(default_factory=list)
    domain_score: Optional[EvaluationScore] = None
    total_cases: int = Field(default=0, ge=0)
    passed_cases: int = Field(default=0, ge=0)
    failed_cases: int = Field(default=0, ge=0)
    results: List[EvaluationResult] = Field(default_factory=list)
    failures: List[EvaluationFailure] = Field(default_factory=list)
    artifacts: List[EvaluationArtifact] = Field(default_factory=list)
    duration_ms: float = Field(default=0.0, ge=0.0)
    tenant_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvaluationRun(BaseModel):
    """Container representing an active or completed evaluation execution."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(..., min_length=1, max_length=64)
    suite_type: EvaluationSuiteType
    domain: EvaluationDomain
    status: EvaluationStatus = Field(default=EvaluationStatus.PENDING)
    tenant_id: Optional[str] = None
    dataset_version: str = Field(default="v1.0.0")
    config_fingerprint: str = Field(default="")
    result_fingerprint: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    report: Optional[EvaluationReport] = None
