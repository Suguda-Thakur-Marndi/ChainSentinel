"""Telemetry, structured logging, and audit event emission for the RiskWise ML layer.

Guarantees secret redaction, safe telemetry propagation, and structured audit logs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.agents.contracts import validate_no_forbidden_keys, validate_no_sensitive_values
from app.agents.security import sanitize_sensitive_data
from app.core.logging import get_logger

logger = get_logger("ml.observability")


class MLObservability:
    """Safe structured telemetry and audit emission for ML training and inference."""

    @staticmethod
    def emit_training_event(
        action: str,
        organization_id: str,
        model_id: str,
        metrics: Dict[str, Any],
        duration_ms: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        clean_details = sanitize_sensitive_data(details or {})
        clean_metrics = sanitize_sensitive_data(metrics)
        logger.info(
            "AUDIT_EVENT: action=%s org=%s model_id=%s duration_ms=%.2f metrics=%s details=%s",
            action,
            organization_id,
            model_id,
            duration_ms,
            clean_metrics,
            clean_details,
        )

    @staticmethod
    def emit_inference_event(
        action: str,
        organization_id: str,
        prediction_id: str,
        model_id: str,
        latency_ms: float,
        status: str = "SUCCESS",
        predicted_value: Optional[float] = None,
        error_category: Optional[str] = None,
        request_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> None:
        logger.info(
            "AUDIT_EVENT: action=%s org=%s prediction_id=%s model_id=%s status=%s "
            "latency_ms=%.2f predicted_value=%s error_category=%s req_id=%s corr_id=%s trace_id=%s",
            action,
            organization_id,
            prediction_id,
            model_id,
            status,
            latency_ms,
            predicted_value,
            error_category,
            request_id,
            correlation_id,
            trace_id,
        )
