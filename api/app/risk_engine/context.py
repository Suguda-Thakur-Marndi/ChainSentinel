"""Risk evaluation context contract and tenant isolation boundaries for RiskWise Risk Engine.

Ensures only valid, tenant-isolated NormalizedRiskSignal instances enter the
evaluation pipeline while rejecting raw events, canonical events, or cross-tenant data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.canonical import EventQuality
from app.normalization.contract import EntityType, NormalizedRiskSignal
from app.risk_engine.errors import (
    InvalidContextError,
    InvalidSignalQualityError,
    RiskEngineInputError,
    TenantMismatchError,
)


def generate_deterministic_evaluation_id(
    organization_id: str,
    evaluation_time: datetime,
    scope: str = "GLOBAL",
    scope_entity_id: Optional[str] = None,
) -> str:
    """Generate a reproducible UUIDv5 evaluation ID based on tenant, scope, entity, and timestamp."""
    org = organization_id.strip() if organization_id else "global"
    entity = scope_entity_id or "root"
    time_str = evaluation_time.strftime("%Y-%m-%d-%H-%M-%S")
    token = f"{org}:eval:{scope.upper()}:{entity}:{time_str}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, token))


class RiskEvaluationContext(BaseModel):
    """Execution context and operational state for a deterministic risk evaluation run."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    organization_id: str = Field(..., min_length=1, description="Tenant organization scope.")
    evaluation_id: Optional[str] = Field(None, description="Deterministic run identifier.")
    correlation_id: Optional[str] = Field(None, description="End-to-end tracing correlation identifier.")
    trace_id: Optional[str] = Field(None, description="Distributed trace identifier.")
    evaluation_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC evaluation instant.",
    )
    scope: str = Field(default="GLOBAL", description="Evaluation scope (e.g. GLOBAL, SHIPMENT, SUPPLIER, PORT, ROUTE).")
    scope_entity_id: Optional[str] = Field(None, description="Target entity ID if evaluated for a specific network node.")
    scope_entity_type: Optional[EntityType] = Field(None, description="Target entity type if applicable.")
    allow_partial_signals: bool = Field(default=True, description="Whether PARTIAL quality signals are permissible.")
    signals: List[NormalizedRiskSignal] = Field(
        default_factory=list,
        description="Tenant-isolated NormalizedRiskSignal instances to evaluate.",
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operational context for shipments, suppliers, ports, routes, etc.",
    )
    operations: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operational state (e.g. inventory, delay buffers, active alerts).",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Preserved audit, trace, and runtime diagnostic metadata.",
    )

    @field_validator("organization_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise InvalidContextError("organization_id is required and cannot be empty.")
        return v.strip()

    @field_validator("evaluation_time")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @model_validator(mode="before")
    @classmethod
    def enforce_strict_input_boundary(cls, values: Any) -> Any:
        """Reject unvalidated dictionaries, raw events, or canonical events before Pydantic parsing."""
        if not isinstance(values, dict):
            raise RiskEngineInputError(f"Expected dict context input, got {type(values).__name__}")

        raw_signals = values.get("signals")
        if raw_signals is not None:
            if not isinstance(raw_signals, list):
                raise RiskEngineInputError(f"signals must be a list, got {type(raw_signals).__name__}")

            validated_signals: List[Any] = []
            for item in raw_signals:
                # Check for prohibited input types
                item_cls_name = type(item).__name__
                if item_cls_name in ("RawEvent", "CanonicalExternalEvent"):
                    raise RiskEngineInputError(
                        f"Strict input boundary violated: {item_cls_name} cannot be passed directly "
                        f"to RiskEvaluationContext. Only NormalizedRiskSignal is accepted."
                    )
                if isinstance(item, dict):
                    raise RiskEngineInputError(
                        "Strict input boundary violated: Raw dictionaries cannot be passed directly "
                        "as signals to RiskEvaluationContext. Only NormalizedRiskSignal is accepted."
                    )
                if not isinstance(item, NormalizedRiskSignal):
                    raise RiskEngineInputError(
                        f"Strict input boundary violated: Expected NormalizedRiskSignal, got {item_cls_name}."
                    )
                validated_signals.append(item)

        return values

    @model_validator(mode="after")
    def validate_tenant_and_quality(self) -> "RiskEvaluationContext":
        """Enforce strict tenant isolation, quality gating, and signal deduplication."""
        # 1. Deterministic evaluation_id if not supplied
        if not self.evaluation_id:
            self.evaluation_id = generate_deterministic_evaluation_id(
                organization_id=self.organization_id,
                evaluation_time=self.evaluation_time,
                scope=self.scope,
                scope_entity_id=self.scope_entity_id,
            )

        # 2. Validate tenant isolation and quality gating
        deduped_signals: List[NormalizedRiskSignal] = []
        seen_fingerprints = set()

        for signal in self.signals:
            # Tenant isolation
            if signal.organization_id != self.organization_id:
                raise TenantMismatchError(
                    f"Tenant isolation violated: Signal {signal.signal_id} belongs to "
                    f"organization '{signal.organization_id}', but evaluation context is "
                    f"scoped to '{self.organization_id}'."
                )

            # Quality gating
            if signal.quality == EventQuality.INVALID:
                reasons = [r.value if hasattr(r, "value") else str(r) for r in signal.quality_reasons]
                raise InvalidSignalQualityError(
                    f"Quality gating rejection: Signal {signal.signal_id} has INVALID quality "
                    f"due to {reasons}."
                )

            if signal.quality == EventQuality.PARTIAL and not self.allow_partial_signals:
                raise InvalidSignalQualityError(
                    f"Quality gating rejection: Signal {signal.signal_id} has PARTIAL quality "
                    f"and allow_partial_signals is set to False."
                )

            # Signal Deduplication based on Phase 6 fingerprint
            fp = signal.fingerprint or signal.signal_id
            if fp not in seen_fingerprints:
                seen_fingerprints.add(fp)
                deduped_signals.append(signal)

        self.signals = deduped_signals
        return self

    def add_signal(self, signal: Any) -> None:
        """Add a single NormalizedRiskSignal with immediate boundary validation."""
        if not isinstance(signal, NormalizedRiskSignal):
            cls_name = type(signal).__name__
            raise RiskEngineInputError(
                f"Strict input boundary violated: Expected NormalizedRiskSignal, got {cls_name}."
            )

        if signal.organization_id != self.organization_id:
            raise TenantMismatchError(
                f"Tenant isolation violated: Signal {signal.signal_id} belongs to "
                f"organization '{signal.organization_id}', but context is scoped to '{self.organization_id}'."
            )

        if signal.quality == EventQuality.INVALID:
            reasons = [r.value if hasattr(r, "value") else str(r) for r in signal.quality_reasons]
            raise InvalidSignalQualityError(
                f"Quality gating rejection: Signal {signal.signal_id} has INVALID quality ({reasons})."
            )

        if signal.quality == EventQuality.PARTIAL and not self.allow_partial_signals:
            raise InvalidSignalQualityError(
                f"Quality gating rejection: Signal {signal.signal_id} has PARTIAL quality."
            )

        fp = signal.fingerprint or signal.signal_id
        for existing in self.signals:
            if (existing.fingerprint or existing.signal_id) == fp:
                return  # Deduplicated

        self.signals.append(signal)
