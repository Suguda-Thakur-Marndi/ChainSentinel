"""Action safety policy, action allowlist, target validation, and approval binding verification (Phase 17).

Enforces:
- Explicit allowlist of permissible action types, targets, and parameters
- Strict approval binding (prevents "Approve A -> mutate request -> execute B")
- Tenant scoping on all target entities (shipments, carriers, facilities, routes)
- Decision and approval freshness protection
- Operational state conflict prevention (e.g. shipment already delivered or rerouted)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from sqlalchemy.orm import Session

from app.agents.action.contract import (
    ActionCommand,
    ActionType,
    TargetEntityType,
)
from app.agents.action.errors import (
    ActionApprovalInvalidError,
    ActionApprovalMismatchError,
    ActionApprovalMissingError,
    ActionAuthorizationError,
    ActionStaleDecisionError,
    ActionTargetNotFoundError,
    ActionTargetStateConflictError,
    ActionTenantIsolationError,
    ActionUnsupportedTypeError,
    InvalidActionRequestError,
)
from app.models.governance import Approval, Recommendation
from app.models.logistics import Shipment
from app.models.network import Carrier, Route


# Explicit action allowlist mapping ActionType to execution specs
ACTION_ALLOWLIST: Dict[ActionType, Dict[str, Any]] = {
    ActionType.SHIPMENT_REROUTE: {
        "allowed_targets": {TargetEntityType.SHIPMENT},
        "required_params": {"new_route_id"},
        "allowed_executor": "ShipmentRerouteExecutor",
        "provider": "carrier_edi",
        "timeout_seconds": 30.0,
        "max_retries": 1,
    },
    ActionType.CARRIER_REALLOCATION: {
        "allowed_targets": {TargetEntityType.SHIPMENT, TargetEntityType.CARRIER},
        "required_params": {"new_carrier_id"},
        "allowed_executor": "CarrierReallocationExecutor",
        "provider": "logistics_broker",
        "timeout_seconds": 30.0,
        "max_retries": 1,
    },
    ActionType.EXPEDITE_SHIPMENT: {
        "allowed_targets": {TargetEntityType.SHIPMENT},
        "required_params": {"expedite_mode"},
        "allowed_executor": "ShipmentExpediteExecutor",
        "provider": "air_freight_corridor",
        "timeout_seconds": 30.0,
        "max_retries": 1,
    },
    ActionType.HOLD_SHIPMENT: {
        "allowed_targets": {TargetEntityType.SHIPMENT},
        "required_params": {"hold_reason"},
        "allowed_executor": "ShipmentHoldExecutor",
        "provider": "warehouse_staging",
        "timeout_seconds": 15.0,
        "max_retries": 0,
    },
    ActionType.FACILITY_REALLOCATION: {
        "allowed_targets": {TargetEntityType.SHIPMENT, TargetEntityType.FACILITY},
        "required_params": {"new_facility_id"},
        "allowed_executor": "FacilityReallocationExecutor",
        "provider": "network_routing",
        "timeout_seconds": 30.0,
        "max_retries": 1,
    },
    ActionType.MONITOR: {
        "allowed_targets": {TargetEntityType.SHIPMENT, TargetEntityType.ROUTE},
        "required_params": set(),
        "allowed_executor": "MonitorExecutor",
        "provider": "internal_telemetry",
        "timeout_seconds": 10.0,
        "max_retries": 2,
    },
}

AUTHORIZED_EXECUTION_ROLES: Set[str] = {"RiskManager", "Admin"}


def _extract_approval_field(obj: Any, *keys: str) -> Any:
    """Safely extract field from a dict or an object instance."""
    if obj is None:
        return None
    for k in keys:
        if isinstance(obj, dict):
            if k in obj and obj[k] is not None:
                return obj[k]
        else:
            val = getattr(obj, k, None)
            if val is not None:
                return val
    return None


class ActionSafetyPolicy:
    """Deterministic safety policy engine for operational action dispatch."""

    def __init__(
        self,
        policy_version: str = "1.0",
        max_freshness_seconds: float = 86400.0,  # 24 hours
    ) -> None:
        self.policy_version = policy_version
        self.max_freshness_seconds = max_freshness_seconds

    def validate_command_against_policy(self, command: ActionCommand) -> Dict[str, Any]:
        """Validate command against explicit action allowlist."""
        action_type = command.action_type
        if action_type not in ACTION_ALLOWLIST:
            raise ActionUnsupportedTypeError(
                f"Action type '{action_type}' is not supported by the action allowlist.",
                details={"action_type": action_type, "allowed": [at.value for at in ACTION_ALLOWLIST.keys()]},
            )

        spec = ACTION_ALLOWLIST[action_type]

        if command.target_entity_type not in spec["allowed_targets"]:
            raise ActionUnsupportedTypeError(
                f"Target entity type '{command.target_entity_type}' is not permitted for action '{action_type}'.",
                details={"target_type": command.target_entity_type, "allowed": [t.value for t in spec["allowed_targets"]]},
            )

        missing_params = spec["required_params"] - set(command.parameters.keys())
        if missing_params:
            raise InvalidActionRequestError(
                f"Missing required parameters for action '{action_type}': {sorted(list(missing_params))}.",
                details={"missing": sorted(list(missing_params))},
            )

        return spec

    def validate_approval(
        self,
        command: ActionCommand,
        approval: Any,
    ) -> None:
        """Validate that the operational command has an authentic, matching, approved human sign-off."""
        if not approval:
            raise ActionApprovalMissingError(
                f"Action command '{command.action_id}' strictly requires human approval, but approval is missing.",
                details={"action_id": command.action_id, "approval_id": command.approval_id},
            )

        # 1. Tenant match
        appr_org = _extract_approval_field(approval, "organization_id", "org_id")
        if appr_org and str(appr_org).strip() != command.organization_id:
            raise ActionTenantIsolationError(
                f"Cross-tenant approval: approval tenant '{appr_org}' does not match command tenant '{command.organization_id}'.",
                details={"approval_tenant": appr_org, "command_tenant": command.organization_id},
            )

        # 2. Decision match
        appr_dec_id = _extract_approval_field(approval, "decision_id", "recommendation_id")
        if appr_dec_id and str(appr_dec_id).strip() != command.decision_id:
            raise ActionApprovalMismatchError(
                f"Approval decision ID '{appr_dec_id}' does not match command decision ID '{command.decision_id}'.",
                details={"approval_decision_id": appr_dec_id, "command_decision_id": command.decision_id},
            )

        # 3. Candidate match if provided
        appr_cand_id = _extract_approval_field(approval, "candidate_id")
        if appr_cand_id and command.candidate_id and str(appr_cand_id).strip() != command.candidate_id.strip():
            raise ActionApprovalMismatchError(
                f"Approval candidate ID '{appr_cand_id}' does not match command candidate ID '{command.candidate_id}'.",
                details={"approval_candidate_id": appr_cand_id, "command_candidate_id": command.candidate_id},
            )

        # 4. Status check: must be APPROVED
        appr_status = _extract_approval_field(approval, "status", "decision")
        if not appr_status or str(appr_status).upper() not in ("APPROVED", "APPROVE"):
            raise ActionApprovalInvalidError(
                f"Approval status is '{appr_status}'. Operational actions require an APPROVED human sign-off.",
                details={"status": appr_status},
            )

        # 5. Approver role check
        appr_role = _extract_approval_field(approval, "actor_role", "role")
        if appr_role and str(appr_role) not in AUTHORIZED_EXECUTION_ROLES:
            raise ActionAuthorizationError(
                f"Approval signer role '{appr_role}' is not authorized to approve operational execution.",
                details={"role": appr_role, "authorized_roles": sorted(list(AUTHORIZED_EXECUTION_ROLES))},
            )

        # 6. Expiration check
        exp_ts = _extract_approval_field(approval, "expiration_timestamp") or command.expiration_timestamp
        if exp_ts:
            if isinstance(exp_ts, str):
                try:
                    exp_ts = datetime.fromisoformat(exp_ts)
                except ValueError:
                    exp_ts = None
            if isinstance(exp_ts, datetime):
                exp_utc = exp_ts if exp_ts.tzinfo else exp_ts.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                if exp_utc < now_utc:
                    raise ActionStaleDecisionError(
                        f"Approval '{command.approval_id}' expired at '{exp_utc.isoformat()}'.",
                        details={"expired_at": exp_utc.isoformat()},
                    )

        # 7. Freshness check against policy max_freshness_seconds
        decided_at = _extract_approval_field(approval, "decided_at")
        if decided_at:
            if isinstance(decided_at, str):
                try:
                    decided_at = datetime.fromisoformat(decided_at)
                except ValueError:
                    decided_at = None
            if isinstance(decided_at, datetime):
                dec_utc = decided_at if decided_at.tzinfo else decided_at.replace(tzinfo=timezone.utc)
                now_utc = datetime.now(timezone.utc)
                age_seconds = (now_utc - dec_utc).total_seconds()
                if age_seconds > self.max_freshness_seconds:
                    raise ActionStaleDecisionError(
                        f"Approval '{command.approval_id}' was decided {age_seconds:.0f}s ago, exceeding freshness limit ({self.max_freshness_seconds}s).",
                        details={"age_seconds": age_seconds, "limit_seconds": self.max_freshness_seconds},
                    )

        # 8. Cryptographic fingerprint check if provided
        appr_fp = _extract_approval_field(approval, "fingerprint")
        if appr_fp and command.approval_fingerprint and str(appr_fp) != str(command.approval_fingerprint):
            raise ActionApprovalMismatchError(
                f"Approval cryptographic fingerprint mismatch: expected '{appr_fp}', command carries '{command.approval_fingerprint}'.",
                details={"expected": appr_fp, "actual": command.approval_fingerprint},
            )

    def validate_target_entity(
        self,
        command: ActionCommand,
        db: Optional[Session] = None,
    ) -> None:
        """Verify that target entity exists in DB and strictly belongs to the current tenant."""
        if not db:
            return

        target_id = command.target_entity_id
        target_type = command.target_entity_type
        org_id = command.organization_id

        if target_type == TargetEntityType.SHIPMENT:
            shipment = db.query(Shipment).filter(Shipment.id == target_id).first()
            if not shipment:
                raise ActionTargetNotFoundError(
                    f"Shipment with ID '{target_id}' not found.",
                    details={"target_id": target_id},
                )
            if shipment.org_id != org_id:
                raise ActionTenantIsolationError(
                    f"Shipment '{target_id}' belongs to tenant '{shipment.org_id}', cannot be targeted by '{org_id}'.",
                    details={"shipment_tenant": shipment.org_id, "command_tenant": org_id},
                )

            # Operational state conflict check
            if shipment.status in ("DELIVERED", "CANCELLED"):
                raise ActionTargetStateConflictError(
                    f"Shipment '{target_id}' is in terminal state '{shipment.status}' and cannot be modified.",
                    details={"shipment_status": shipment.status},
                )

            # Reroute specific target checks
            if command.action_type == ActionType.SHIPMENT_REROUTE:
                new_route_id = str(command.parameters.get("new_route_id", "")).strip()
                if shipment.route_id == new_route_id:
                    raise ActionTargetStateConflictError(
                        f"Shipment '{target_id}' is already assigned to route '{new_route_id}'.",
                        details={"current_route_id": shipment.route_id, "new_route_id": new_route_id},
                    )
                route = db.query(Route).filter(Route.id == new_route_id).first()
                if not route:
                    raise ActionTargetNotFoundError(
                        f"Target route with ID '{new_route_id}' does not exist.",
                        details={"new_route_id": new_route_id},
                    )
                if route.org_id != org_id:
                    raise ActionTenantIsolationError(
                        f"Target route '{new_route_id}' belongs to tenant '{route.org_id}', not '{org_id}'.",
                        details={"route_tenant": route.org_id, "command_tenant": org_id},
                    )

            # Carrier reallocation checks
            if command.action_type == ActionType.CARRIER_REALLOCATION:
                new_carrier_id = str(command.parameters.get("new_carrier_id", "")).strip()
                carrier = db.query(Carrier).filter(Carrier.id == new_carrier_id).first()
                if not carrier:
                    raise ActionTargetNotFoundError(
                        f"Target carrier with ID '{new_carrier_id}' does not exist.",
                        details={"new_carrier_id": new_carrier_id},
                    )
                if carrier.org_id != org_id:
                    raise ActionTenantIsolationError(
                        f"Target carrier '{new_carrier_id}' belongs to tenant '{carrier.org_id}', not '{org_id}'.",
                        details={"carrier_tenant": carrier.org_id, "command_tenant": org_id},
                    )

        elif target_type == TargetEntityType.CARRIER:
            carrier = db.query(Carrier).filter(Carrier.id == target_id).first()
            if not carrier:
                raise ActionTargetNotFoundError(
                    f"Carrier with ID '{target_id}' not found.",
                    details={"target_id": target_id},
                )
            if carrier.org_id != org_id:
                raise ActionTenantIsolationError(
                    f"Carrier '{target_id}' belongs to tenant '{carrier.org_id}', not '{org_id}'.",
                    details={"carrier_tenant": carrier.org_id, "command_tenant": org_id},
                )

        elif target_type == TargetEntityType.ROUTE:
            route = db.query(Route).filter(Route.id == target_id).first()
            if not route:
                raise ActionTargetNotFoundError(
                    f"Route with ID '{target_id}' not found.",
                    details={"target_id": target_id},
                )
            if route.org_id != org_id:
                raise ActionTenantIsolationError(
                    f"Route '{target_id}' belongs to tenant '{route.org_id}', not '{org_id}'.",
                    details={"route_tenant": route.org_id, "command_tenant": org_id},
                )
