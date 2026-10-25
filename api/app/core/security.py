"""Cryptographic security utilities for authentication, passwords, and tokens.

Standardizes:
- PBKDF2-HMAC-SHA256 password hashing (600,000 iterations, 16-byte cryptographically secure salt)
- Constant-time password verification via hmac.compare_digest
- High-entropy cryptographic token generation (secrets.token_urlsafe)
- SHA-256 token hashing for secure database persistence (prevents token leakage from db dumps)
- Password complexity validation
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Tuple

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600000
SALT_BYTES = 16


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """Validate that a plain password meets minimum enterprise complexity rules.

    Rules:
    - Between 8 and 128 characters
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one digit (0-9) or special character
    """
    if not password or not isinstance(password, str):
        return False, "Password cannot be empty"
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if len(password) > 128:
        return False, "Password cannot exceed 128 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r"[0-9!@#$%^&*()_+\-=\[\]{}|;:,.<>?]", password):
        return False, "Password must contain at least one number or special character"
    return True, ""


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random 16-byte salt.

    Returns:
        Formatted string: pbkdf2_sha256${iterations}${salt_hex}${hash_hex}
    """
    if not password or not isinstance(password, str):
        raise ValueError("Password must be a non-empty string")

    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_hex = salt.hex()
    hash_hex = derived.hex()
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a stored PBKDF2 hash using constant-time comparison.

    Gracefully returns False on invalid formats or mismatch, avoiding exception leakage.
    """
    if not plain_password or not hashed_password or not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False

    parts = hashed_password.split("$")
    if len(parts) != 4:
        return False

    algo, iterations_str, salt_hex, expected_hash_hex = parts
    if algo != PBKDF2_ALGORITHM:
        return False

    try:
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(expected_hash_hex)
    except (ValueError, TypeError):
        return False

    computed_hash = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(computed_hash, expected_hash)


def generate_secure_token() -> str:
    """Generate a high-entropy URL-safe cryptographic token (32 bytes / 43 chars)."""
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    """Compute SHA-256 digest of a raw token for secure database storage.

    Only hashed tokens are persisted to protect against replay attacks if database is compromised.
    """
    if not raw_token or not isinstance(raw_token, str):
        raise ValueError("Token must be a non-empty string")
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
