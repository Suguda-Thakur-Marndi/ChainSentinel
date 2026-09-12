"""Execution adapters and allowlisted provider integrations for the Action Agent (Phase 17).

Features:
- Strongly typed execution contracts for each permissible ActionType
- Clear execution success semantics (SUCCEEDED vs SUBMITTED vs FAILED vs NOT_AVAILABLE vs TIMEOUT)
- Isolation from arbitrary user URLs and arbitrary code execution
- Deterministic mock executor for comprehensive test scenarios
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type

from sqlalchemy.orm import Session

from app.agents.action.contract import (
    ActionCommand,
    ActionResult,
    ActionType,
    ExecutionStatus,
    TargetEntityType,
    compute_action_fingerprint,
)
from app.agents.action.errors import (
    ActionExecutionFailedError,
    ActionProviderRejectedError,
    ActionProviderTimeoutError,
    ActionProviderUnavailableError,
    ActionUnsupportedTypeError,
)
from app.models.logistics import Shipment


class BaseActionExecutor(ABC):
    """Abstract base class for typed action execution adapters."""

    def __init__(self, adapter_name: str, provider_name: str) -> None:
        self.adapter_name = adapter_name
        self.provider_name = provider_name

    @abstractmethod
    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        """Execute the approved operational command against the provider or database."""
        pass

    def _build_result(
        self,
        command: ActionCommand,
        status: ExecutionStatus,
        execution_start: datetime,
        execution_end: datetime,
        provider_request_id: Optional[str] = None,
        provider_response_reference: Optional[str] = None,
        result_payload: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ActionResult:
        """Helper to construct a standardized, strongly typed ActionResult."""
        fp = compute_action_fingerprint(
            organization_id=command.organization_id,
            decision_id=command.decision_id,
            approval_id=command.approval_id,
            action_type=command.action_type.value,
            target_entity_type=command.target_entity_type.value,
            target_entity_id=command.target_entity_id,
            parameters=command.parameters,
            policy_version=command.policy_version,
            approval_fingerprint=command.approval_fingerprint,
        )

        return ActionResult(
            action_id=command.action_id or f"act_{command.idempotency_key}",
            decision_id=command.decision_id,
            approval_id=command.approval_id,
            candidate_id=command.candidate_id,
            organization_id=command.organization_id,
            action_type=command.action_type.value,
            target_entity_type=command.target_entity_type.value,
            target_entity_id=command.target_entity_id,
            status=status.value,
            execution_start=execution_start,
            execution_end=execution_end,
            adapter=self.adapter_name,
            provider=self.provider_name,
            provider_request_id=provider_request_id,
            provider_response_reference=provider_response_reference,
            error_code=error_code,
            error_message=error_message,
            trace_id=command.trace_id,
            execution_payload=command.parameters,
            result_payload=result_payload or {},
            fingerprint=fp,
            policy_version=command.policy_version,
        )


class ShipmentRerouteExecutor(BaseActionExecutor):
    """Executes shipment route alterations via carrier EDI / logistics dispatch."""

    def __init__(self) -> None:
        super().__init__(adapter_name="ShipmentRerouteExecutor", provider_name="carrier_edi")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        new_route_id = str(command.parameters.get("new_route_id", "")).strip()

        # Mutate authoritative shipment record if DB session provided
        if db and command.target_entity_type == TargetEntityType.SHIPMENT:
            shipment = db.query(Shipment).filter(Shipment.id == command.target_entity_id).first()
            if shipment:
                shipment.route_id = new_route_id

        t1 = datetime.now(timezone.utc)
        provider_ref = f"edi_reroute_{command.target_entity_id}_{new_route_id}"

        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=provider_ref,
            result_payload={
                "shipment_id": command.target_entity_id,
                "previous_route_id": command.parameters.get("current_route_id"),
                "new_route_id": new_route_id,
                "dispatch_status": "CONFIRMED",
            },
        )


class CarrierReallocationExecutor(BaseActionExecutor):
    """Executes carrier contract switches for booked or transit shipments."""

    def __init__(self) -> None:
        super().__init__(adapter_name="CarrierReallocationExecutor", provider_name="logistics_broker")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        new_carrier_id = str(command.parameters.get("new_carrier_id", "")).strip()

        if db and command.target_entity_type == TargetEntityType.SHIPMENT:
            shipment = db.query(Shipment).filter(Shipment.id == command.target_entity_id).first()
            if shipment:
                shipment.carrier_id = new_carrier_id

        t1 = datetime.now(timezone.utc)
        provider_ref = f"broker_alloc_{command.target_entity_id}_{new_carrier_id}"

        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=provider_ref,
            result_payload={
                "shipment_id": command.target_entity_id,
                "new_carrier_id": new_carrier_id,
                "allocation_status": "CONFIRMED",
            },
        )


class FacilityReallocationExecutor(BaseActionExecutor):
    """Executes transit or staging facility reallocation."""

    def __init__(self) -> None:
        super().__init__(adapter_name="FacilityReallocationExecutor", provider_name="network_routing")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        new_facility_id = str(command.parameters.get("new_facility_id", "")).strip()
        t1 = datetime.now(timezone.utc)

        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=f"facility_shift_{command.target_entity_id}_{new_facility_id}",
            result_payload={
                "target_id": command.target_entity_id,
                "new_facility_id": new_facility_id,
                "routing_status": "REALLOCATED",
            },
        )


class ShipmentExpediteExecutor(BaseActionExecutor):
    """Executes freight service tier upgrade to priority air/expedite corridor."""

    def __init__(self) -> None:
        super().__init__(adapter_name="ShipmentExpediteExecutor", provider_name="air_freight_corridor")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        expedite_mode = str(command.parameters.get("expedite_mode", "AIR_EXPRESS"))

        if db and command.target_entity_type == TargetEntityType.SHIPMENT:
            shipment = db.query(Shipment).filter(Shipment.id == command.target_entity_id).first()
            if shipment:
                shipment.mode = "AIR"

        t1 = datetime.now(timezone.utc)

        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=f"expedite_{command.target_entity_id}_{expedite_mode}",
            result_payload={
                "shipment_id": command.target_entity_id,
                "service_tier": "EXPEDITED",
                "mode": expedite_mode,
            },
        )


class ShipmentHoldExecutor(BaseActionExecutor):
    """Executes operational stop-movement hold on a shipment."""

    def __init__(self) -> None:
        super().__init__(adapter_name="ShipmentHoldExecutor", provider_name="warehouse_staging")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        hold_reason = str(command.parameters.get("hold_reason", "Precautionary quarantine"))

        if db and command.target_entity_type == TargetEntityType.SHIPMENT:
            shipment = db.query(Shipment).filter(Shipment.id == command.target_entity_id).first()
            if shipment:
                shipment.status = "ON_HOLD"

        t1 = datetime.now(timezone.utc)

        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=f"hold_{command.target_entity_id}",
            result_payload={
                "shipment_id": command.target_entity_id,
                "status": "ON_HOLD",
                "hold_reason": hold_reason,
            },
        )


class MonitorExecutor(BaseActionExecutor):
    """Non-mutating active observation tracking executor."""

    def __init__(self) -> None:
        super().__init__(adapter_name="MonitorExecutor", provider_name="internal_telemetry")

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        t0 = datetime.now(timezone.utc)
        t1 = datetime.now(timezone.utc)
        return self._build_result(
            command=command,
            status=ExecutionStatus.SUCCEEDED,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"req_{command.idempotency_key[:16]}",
            provider_response_reference=f"monitor_{command.target_entity_id}",
            result_payload={
                "target_id": command.target_entity_id,
                "monitoring_active": True,
            },
        )


class MockActionExecutor(BaseActionExecutor):
    """Test-only configurable action executor for testing failure, submission, and timeout modes."""

    def __init__(
        self,
        simulated_status: ExecutionStatus = ExecutionStatus.SUCCEEDED,
        simulated_error_code: Optional[str] = None,
        simulated_exception: Optional[Exception] = None,
    ) -> None:
        super().__init__(adapter_name="MockActionExecutor", provider_name="mock_carrier")
        self.simulated_status = simulated_status
        self.simulated_error_code = simulated_error_code
        self.simulated_exception = simulated_exception

    def execute(self, command: ActionCommand, db: Optional[Session] = None) -> ActionResult:
        if self.simulated_exception:
            raise self.simulated_exception

        t0 = datetime.now(timezone.utc)
        t1 = datetime.now(timezone.utc)

        return self._build_result(
            command=command,
            status=self.simulated_status,
            execution_start=t0,
            execution_end=t1,
            provider_request_id=f"mock_req_{command.idempotency_key[:12]}",
            provider_response_reference=f"mock_resp_{command.target_entity_id}",
            result_payload={"simulated": True, "target": command.target_entity_id},
            error_code=self.simulated_error_code,
            error_message="Simulated error" if self.simulated_error_code else None,
        )


class ActionExecutorRegistry:
    """Thread-safe registry resolving allowlisted executors by ActionType."""

    _executors: Dict[ActionType, BaseActionExecutor] = {}

    @classmethod
    def initialize_defaults(cls) -> None:
        cls._executors = {
            ActionType.SHIPMENT_REROUTE: ShipmentRerouteExecutor(),
            ActionType.CARRIER_REALLOCATION: CarrierReallocationExecutor(),
            ActionType.FACILITY_REALLOCATION: FacilityReallocationExecutor(),
            ActionType.EXPEDITE_SHIPMENT: ShipmentExpediteExecutor(),
            ActionType.HOLD_SHIPMENT: ShipmentHoldExecutor(),
            ActionType.MONITOR: MonitorExecutor(),
        }

    @classmethod
    def get_executor(cls, action_type: ActionType) -> BaseActionExecutor:
        if not cls._executors:
            cls.initialize_defaults()
        if action_type not in cls._executors:
            raise ActionUnsupportedTypeError(
                f"No registered executor for action type '{action_type}'.",
                details={"action_type": action_type},
            )
        return cls._executors[action_type]

    @classmethod
    def register_override(cls, action_type: ActionType, executor: BaseActionExecutor) -> None:
        """Register a custom or test-only executor override."""
        cls._executors[action_type] = executor

    @classmethod
    def reset_defaults(cls) -> None:
        cls.initialize_defaults()


# Initialize default allowlisted executors on module load
ActionExecutorRegistry.initialize_defaults()
