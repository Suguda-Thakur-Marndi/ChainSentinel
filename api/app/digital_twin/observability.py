"""Observability and audit logging helpers for RiskWise Digital Twin.

Enforces:
- Structured telemetry and timing metrics (build duration, validation duration, query duration).
- Audit trail event logging via the existing AuditService and UnitOfWork infrastructure.
- Safe payload scrubbing (no secrets or sensitive source values logged).
- Correlation ID and trace tracking.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from app.services.audit_service import AuditService, sanitize_payload

logger = logging.getLogger("riskwise.digital_twin")

# Standard Digital Twin Audit Action Names
EVENT_BUILD_STARTED = "DIGITAL_TWIN_BUILD_STARTED"
EVENT_BUILD_VALIDATED = "DIGITAL_TWIN_BUILD_VALIDATED"
EVENT_BUILD_SUCCEEDED = "DIGITAL_TWIN_BUILD_SUCCEEDED"
EVENT_BUILD_FAILED = "DIGITAL_TWIN_BUILD_FAILED"
EVENT_QUERY = "DIGITAL_TWIN_QUERY"


class TwinObservability:
    """Helper service managing metrics and audit logging for Digital Twin operations."""

    @staticmethod
    def log_build_started(
        organization_id: str,
        twin_id: str,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> None:
        payload = {
            "organization_id": organization_id,
            "twin_id": twin_id,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        logger.info("Digital twin build started: org=%s, twin_id=%s", organization_id, twin_id)
        if uow and hasattr(uow, "audit_logs"):
            try:
                AuditService.log_event(
                    uow=uow,
                    action=EVENT_BUILD_STARTED,
                    resource_type="digital_twin",
                    org_id=organization_id,
                    resource_id=twin_id,
                    status="SUCCESS",
                    after_data=payload,
                    request_id=request_id,
                )
            except Exception as e:
                logger.warning("Failed to record audit log for %s: %s", EVENT_BUILD_STARTED, e)

    @staticmethod
    def log_build_validated(
        organization_id: str,
        twin_id: str,
        node_count: int,
        edge_count: int,
        validation_duration_ms: float,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> None:
        payload = {
            "organization_id": organization_id,
            "twin_id": twin_id,
            "node_count": node_count,
            "edge_count": edge_count,
            "validation_duration_ms": round(validation_duration_ms, 2),
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        logger.info(
            "Digital twin build validated: org=%s, twin_id=%s, nodes=%d, edges=%d, duration=%.2fms",
            organization_id,
            twin_id,
            node_count,
            edge_count,
            validation_duration_ms,
        )
        if uow and hasattr(uow, "audit_logs"):
            try:
                AuditService.log_event(
                    uow=uow,
                    action=EVENT_BUILD_VALIDATED,
                    resource_type="digital_twin",
                    org_id=organization_id,
                    resource_id=twin_id,
                    status="SUCCESS",
                    after_data=payload,
                    request_id=request_id,
                )
            except Exception as e:
                logger.warning("Failed to record audit log for %s: %s", EVENT_BUILD_VALIDATED, e)

    @staticmethod
    def log_build_succeeded(
        organization_id: str,
        twin_id: str,
        node_count: int,
        edge_count: int,
        source_fingerprint: str,
        twin_fingerprint: str,
        build_duration_ms: float,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> None:
        payload = {
            "organization_id": organization_id,
            "twin_id": twin_id,
            "node_count": node_count,
            "edge_count": edge_count,
            "source_fingerprint": source_fingerprint,
            "twin_fingerprint": twin_fingerprint,
            "build_duration_ms": round(build_duration_ms, 2),
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        logger.info(
            "Digital twin build succeeded: org=%s, twin_id=%s, nodes=%d, edges=%d, duration=%.2fms, fp=%s",
            organization_id,
            twin_id,
            node_count,
            edge_count,
            build_duration_ms,
            twin_fingerprint[:12],
        )
        if uow and hasattr(uow, "audit_logs"):
            try:
                AuditService.log_event(
                    uow=uow,
                    action=EVENT_BUILD_SUCCEEDED,
                    resource_type="digital_twin",
                    org_id=organization_id,
                    resource_id=twin_id,
                    status="SUCCESS",
                    after_data=payload,
                    request_id=request_id,
                )
            except Exception as e:
                logger.warning("Failed to record audit log for %s: %s", EVENT_BUILD_SUCCEEDED, e)

    @staticmethod
    def log_build_failed(
        organization_id: str,
        twin_id: str,
        error_message: str,
        failure_category: str,
        duration_ms: float,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> None:
        payload = {
            "organization_id": organization_id,
            "twin_id": twin_id,
            "error_message": error_message,
            "failure_category": failure_category,
            "duration_ms": round(duration_ms, 2),
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        logger.error(
            "Digital twin build failed: org=%s, twin_id=%s, error=%s, category=%s",
            organization_id,
            twin_id,
            error_message,
            failure_category,
        )
        if uow and hasattr(uow, "audit_logs"):
            try:
                AuditService.log_event(
                    uow=uow,
                    action=EVENT_BUILD_FAILED,
                    resource_type="digital_twin",
                    org_id=organization_id,
                    resource_id=twin_id,
                    status="FAILED",
                    after_data=payload,
                    request_id=request_id,
                )
            except Exception as e:
                logger.warning("Failed to record audit log for %s: %s", EVENT_BUILD_FAILED, e)

    @staticmethod
    def log_query(
        organization_id: str,
        twin_id: str,
        query_type: str,
        query_details: Dict[str, Any],
        query_duration_ms: float,
        result_node_count: int = 0,
        result_edge_count: int = 0,
        correlation_id: Optional[str] = None,
        request_id: Optional[str] = None,
        uow: Any = None,
    ) -> None:
        payload = {
            "organization_id": organization_id,
            "twin_id": twin_id,
            "query_type": query_type,
            "query_details": sanitize_payload(query_details),
            "query_duration_ms": round(query_duration_ms, 2),
            "result_node_count": result_node_count,
            "result_edge_count": result_edge_count,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        logger.debug(
            "Digital twin query executed: org=%s, twin_id=%s, type=%s, duration=%.2fms",
            organization_id,
            twin_id,
            query_type,
            query_duration_ms,
        )
        if uow and hasattr(uow, "audit_logs"):
            try:
                AuditService.log_event(
                    uow=uow,
                    action=EVENT_QUERY,
                    resource_type="digital_twin",
                    org_id=organization_id,
                    resource_id=twin_id,
                    status="SUCCESS",
                    after_data=payload,
                    request_id=request_id,
                )
            except Exception as e:
                logger.warning("Failed to record audit log for %s: %s", EVENT_QUERY, e)
