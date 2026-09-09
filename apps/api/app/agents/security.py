"""Security, tenant isolation, credential scrubbing, and prompt injection defense.

Enforces absolute tenant boundaries, eliminates credential leakage from state dictionaries,
and guards agent boundaries against untrusted input and prompt injection attempts.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agents.contracts import FORBIDDEN_STATE_KEY_PATTERNS
from app.agents.errors import AgentTenantIsolationError, AgentValidationError

# Sensitive key patterns matching platform audit sanitization standards
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api_key|credentials|authorization|cookie|access_token|refresh_token|private_key)",
    re.IGNORECASE,
)

# Prompt injection heuristic screening patterns aligned with Phase 8 trust boundaries
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+(rules|prompts|instructions)", re.IGNORECASE),
    re.compile(r"system\s+(prompt|message)\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(an?\s+)?unrestricted", re.IGNORECASE),
    re.compile(r"override\s+instructions", re.IGNORECASE),
    re.compile(r"call\s+(the\s+)?([a-z0-9_]+\s+)?([a-z0-9_]+_)?tool", re.IGNORECASE),
    re.compile(r"<script[\s>]", re.IGNORECASE),
    re.compile(r"eval\s*\(", re.IGNORECASE),
    re.compile(r"exec\s*\(", re.IGNORECASE),
]


def validate_tenant_isolation(
    context_organization_id: str,
    state_organization_id: str,
    evidence_bundle_org: Optional[str] = None,
    risk_assessment_org: Optional[str] = None,
    evidence_references: Optional[List[str]] = None,
    risk_alert_references: Optional[List[str]] = None,
    recommendation_references: Optional[List[str]] = None,
    approval_reference: Optional[str] = None,
) -> None:
    """Enforce strict multi-tenant isolation across context, state, and bounded resources.
    
    Raises:
        AgentTenantIsolationError: On any tenant absence or mismatch.
    """
    if not context_organization_id or not context_organization_id.strip():
        raise AgentTenantIsolationError("Execution context is missing a valid organization_id.")

    if not state_organization_id or not state_organization_id.strip():
        raise AgentTenantIsolationError("Agent state is missing a valid organization_id.")

    ctx_org = context_organization_id.strip()
    st_org = state_organization_id.strip()

    if ctx_org != st_org:
        raise AgentTenantIsolationError(
            f"Tenant mismatch between context organization '{ctx_org}' and state organization '{st_org}'."
        )

    if evidence_bundle_org and evidence_bundle_org.strip() != ctx_org:
        raise AgentTenantIsolationError(
            f"Cross-tenant evidence bundle detected from foreign tenant: bundle belongs to '{evidence_bundle_org}', "
            f"execution scoped to '{ctx_org}'."
        )

    if risk_assessment_org and risk_assessment_org.strip() != ctx_org:
        raise AgentTenantIsolationError(
            f"Cross-tenant risk assessment detected from foreign tenant: assessment belongs to '{risk_assessment_org}', "
            f"execution scoped to '{ctx_org}'."
        )

    for ref_list, name in [
        (evidence_references, "evidence_references"),
        (risk_alert_references, "risk_alert_references"),
        (recommendation_references, "recommendation_references"),
    ]:
        if ref_list:
            for ref in ref_list:
                if ":" in ref:
                    prefix = ref.split(":", 1)[0]
                    if (prefix.startswith("org_") or "tenant" in prefix or "foreign" in prefix) and prefix != ctx_org:
                        raise AgentTenantIsolationError(
                            f"Cross-tenant reference '{ref}' in '{name}' from foreign tenant does not match organization '{ctx_org}'."
                        )

    if approval_reference and ":" in approval_reference:
        prefix = approval_reference.split(":", 1)[0]
        if (prefix.startswith("org_") or "tenant" in prefix or "foreign" in prefix) and prefix != ctx_org:
            raise AgentTenantIsolationError(
                f"Cross-tenant approval reference '{approval_reference}' from foreign tenant does not match organization '{ctx_org}'."
            )



def sanitize_sensitive_data(payload: Any) -> Any:
    """Recursively scrub credentials and sensitive secrets from agent payloads."""
    if isinstance(payload, str):
        scrubbed = re.sub(r"bearer\s+[a-z0-9_\-\.]+", "[REDACTED_BEARER_TOKEN]", payload, flags=re.IGNORECASE)
        scrubbed = re.sub(r"sk-[a-z0-9_\-]{10,}", "[REDACTED_API_KEY]", scrubbed, flags=re.IGNORECASE)
        return scrubbed
    elif isinstance(payload, dict):
        sanitized = {}
        for k, v in payload.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_sensitive_data(v)
        return sanitized
    elif isinstance(payload, list):
        return [sanitize_sensitive_data(item) for item in payload]
    return payload


def screen_untrusted_input(data: Any) -> List[str]:
    """Scan text or dictionary for adversarial prompt injection indicators or CoT keys.
    
    Returns:
        List of matching pattern descriptions.
    """
    if isinstance(data, dict):
        flags = []
        for k, v in data.items():
            for pattern in FORBIDDEN_STATE_KEY_PATTERNS:
                if pattern.search(str(k)):
                    raise AgentValidationError(
                        f"Prohibited chain-of-thought or sensitive key '{k}' detected."
                    )
            flags.extend(screen_untrusted_input(v))
        return flags
    if not isinstance(data, str) or not data:
        return []
    text = data
    flags = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            flags.append(pattern.pattern)
    return flags


def validate_input_safety(text: str, field_name: str = "input") -> None:
    """Validate that input text does not contain high-risk prompt injection patterns.
    
    Raises:
        AgentValidationError: If prompt injection indicators are detected.
    """
    flags = screen_untrusted_input(text)
    if flags:
        raise AgentValidationError(
            f"Untrusted input in field '{field_name}' contains adversarial prompt injection indicators.",
            details={"field": field_name, "flags": flags},
        )
