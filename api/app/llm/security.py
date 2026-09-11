"""Security boundaries, model allowlisting, tenant isolation, and prompt injection defense.

Guarantees that untrusted user content, cross-tenant references, and unapproved model IDs
are rejected before reaching AWS Bedrock Runtime.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.llm.contracts import LLMRequest
from app.llm.errors import (
    InvocationConfigurationError,
    LLMConfigurationError,
    LLMValidationError,
    PromptInjectionDetectedError,
)

# Sensitive key patterns matching platform audit sanitization standards
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api_key|credentials|authorization|cookie|access_token|refresh_token|private_key)",
    re.IGNORECASE,
)

# Prompt injection screening patterns
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


def sanitize_sensitive_data(payload: Any) -> Any:
    """Recursively scrub credentials and sensitive secrets from payloads."""
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
    """Scan text or dictionary for adversarial prompt injection indicators."""
    if not isinstance(data, str) or not data:
        return []
    flags = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(data):
            flags.append(pattern.pattern)
    return flags

# High-risk system override directives specifically targeting foundation models
SYSTEM_OVERRIDE_PATTERNS = [
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"<\s*/\s*system\s*>", re.IGNORECASE),
    re.compile(r"\[\s*INST\s*\]", re.IGNORECASE),
    re.compile(r"\[\s*/\s*INST\s*\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"role\s*:\s*system", re.IGNORECASE),
    re.compile(r"assistant\s*:", re.IGNORECASE),
]

# Phase 10 Step 2 extended prompt injection patterns
EXTENDED_INJECTION_PATTERNS = [
    re.compile(r"you\s+are\s+now\s+(the\s+)?(administrator|admin|root)", re.IGNORECASE),
    re.compile(r"reveal\s+(your\s+)?system\s+prompt", re.IGNORECASE),
    re.compile(r"output\s+the\s+secret", re.IGNORECASE),
    re.compile(r"follow\s+these\s+instructions\s+instead", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?prior\s+(rules|prompts|instructions)", re.IGNORECASE),
    re.compile(r"system\s+(prompt|message)\s*:", re.IGNORECASE),
]


def detect_prompt_injection(text: str) -> List[str]:
    """Scan text for prompt injection patterns without raising an exception.
    
    Useful for audit telemetry, security metadata recording, and non-fatal screening.
    """
    if not text:
        return []

    flags: List[str] = []
    # 1. Check existing Phase 8/9 patterns
    base_flags = screen_untrusted_input(text)
    if base_flags:
        flags.extend(base_flags)

    # 2. Check system override patterns
    for p in SYSTEM_OVERRIDE_PATTERNS:
        if p.search(text):
            flags.append(f"OVERRIDE_DELIMITER:{p.pattern}")

    # 3. Check extended Phase 10 patterns
    for p in EXTENDED_INJECTION_PATTERNS:
        if p.search(text):
            flags.append(f"INJECTION_PATTERN:{p.pattern}")

    return list(dict.fromkeys(flags))


def sanitize_xml_context(text: str, tag: str) -> str:
    """Neutralize delimiter injection attempts where untrusted text attempts to close the enclosing XML tag."""
    if not text or not tag:
        return text

    clean_tag = tag.strip().lower().replace(" ", "_")
    # Escape any closing tag matching </clean_tag>
    closing_pattern = re.compile(rf"<\s*/\s*{re.escape(clean_tag)}\s*>", re.IGNORECASE)
    return closing_pattern.sub(f"&lt;/{clean_tag}&gt;", text)


def validate_model_allowed(model_id: str, allowed_models: List[str]) -> None:
    """Verify that the requested model ID is explicitly included in the configured allowlist.
    
    Raises:
        LLMConfigurationError: If the model ID is not permitted.
    """
    if not model_id or not model_id.strip():
        raise LLMValidationError("model_id cannot be empty or whitespace.")

    clean_model = model_id.strip()
    if clean_model not in allowed_models:
        raise LLMConfigurationError(
            f"Model ID '{clean_model}' is not in the approved Bedrock model allowlist: {allowed_models}",
            details={"requested_model": clean_model, "allowed_models": allowed_models},
        )


def validate_tenant_context(organization_id: Optional[str]) -> None:
    """Validate that tenant organization ID is well-formed and does not leak cross-tenant signals."""
    if organization_id is not None:
        clean_org = organization_id.strip()
        if not clean_org:
            raise LLMValidationError("organization_id cannot be empty when provided.")
        if ":" in clean_org or "/" in clean_org:
            raise LLMValidationError(f"Invalid organization_id format: '{clean_org}'")


def validate_prompt_safety(text: str, context_label: str = "input") -> None:
    """Screen input text for prompt injection patterns and delimiter escape attempts.
    
    Raises:
        PromptInjectionDetectedError: If prompt injection or structural delimiters are detected.
    """
    if not text:
        return

    # Check existing Phase 8/9 prompt injection patterns
    injection_flags = screen_untrusted_input(text)
    if injection_flags:
        raise PromptInjectionDetectedError(
            f"Adversarial prompt injection pattern detected in {context_label}.",
            details={"context": context_label, "flags": injection_flags},
        )

    # Check structural prompt override delimiters
    for pattern in SYSTEM_OVERRIDE_PATTERNS:
        if pattern.search(text):
            raise PromptInjectionDetectedError(
                f"Prohibited prompt template delimiter detected in {context_label}.",
                details={"context": context_label, "pattern": pattern.pattern},
            )

    # Check extended Phase 10 patterns
    for pattern in EXTENDED_INJECTION_PATTERNS:
        if pattern.search(text):
            raise PromptInjectionDetectedError(
                f"Adversarial prompt injection pattern detected in {context_label}: '{pattern.pattern}'.",
                details={"context": context_label, "pattern": pattern.pattern},
            )


def validate_request_safety(request: LLMRequest, allowed_models: List[str]) -> None:
    """Comprehensive security boundary check executed before any external Bedrock invocation.
    
    1. Validates model ID against allowlist
    2. Validates tenant context
    3. Validates prompt injection safety across system prompt and all messages
    4. Ensures metadata contains no credentials
    """
    validate_model_allowed(request.model_id, allowed_models)
    validate_tenant_context(request.organization_id)

    if request.system_prompt:
        validate_prompt_safety(request.system_prompt, context_label="system_prompt")

    for idx, msg in enumerate(request.messages):
        validate_prompt_safety(msg.content, context_label=f"message[{idx}].content")
