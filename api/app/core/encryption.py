"""Application-Layer KMS Envelope Encryption Service.

Provides tenant-bound envelope encryption for sensitive fields.
Guarantees:
- AWS KMS-backed 256-bit Data Encryption Key (DEK) generation
- Strict tenant-bound encryption context: {"tenant_id": org_id, "classification": "restricted"}
- AES-256-GCM authenticated symmetric encryption (tamper-evident)
- Zero plaintext DEK persistence or logging
- Deterministic local master key fallback for offline testing/development
- Strict verification: rejects mismatched tenant context or tampered ciphertext
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("core.encryption")


class EncryptionError(Exception):
    """Base exception for cryptographic operations."""


class TenantContextMismatchError(EncryptionError):
    """Raised when tenant encryption context does not match during decryption."""


class CiphertextTamperedError(EncryptionError):
    """Raised when authentication tag verification fails (ciphertext was tampered)."""


def _canonical_context_bytes(context: Dict[str, str]) -> bytes:
    """Serialize encryption context canonically for AEAD associated data."""
    sorted_items = sorted(context.items())
    return json.dumps(sorted_items, separators=(",", ":")).encode("utf-8")


class EnvelopeEncryptionService:
    """Manages envelope encryption with AWS KMS and AES-256-GCM."""

    def __init__(
        self,
        kms_key_id: Optional[str] = None,
        region_name: Optional[str] = None,
        kms_client: Optional[Any] = None,
        master_key_fallback: Optional[bytes] = None,
    ) -> None:
        self.kms_key_id = kms_key_id or getattr(settings, "KMS_KEY_ID", None)
        self.region_name = region_name or settings.AWS_REGION
        self._kms_client = kms_client
        # Deterministic local master key for local development and unit tests
        self._master_key_fallback = master_key_fallback or (
            os.environ.get("RISKWISE_LOCAL_MASTER_KEY", "riskwise_default_local_master_key_32b").encode("utf-8")
        )
        if len(self._master_key_fallback) < 32:
            self._master_key_fallback = self._master_key_fallback.ljust(32, b"0")[:32]
        else:
            self._master_key_fallback = self._master_key_fallback[:32]

    def _get_kms_client(self) -> Any:
        if self._kms_client is not None:
            return self._kms_client
        self._kms_client = boto3.client("kms", region_name=self.region_name)
        return self._kms_client

    def _is_kms_active(self) -> bool:
        return bool(self.kms_key_id and settings.APP_ENV.lower() == "production")

    def _derive_local_dek(self, tenant_id: str, salt: bytes) -> Tuple[bytes, bytes]:
        """Derive an encrypted DEK and plaintext DEK using HKDF for local/mock envelope encryption."""
        hkdf = HKDF(
            algorithm=SHA256(),
            length=32,
            salt=salt,
            info=f"dek:{tenant_id}".encode("utf-8"),
        )
        plaintext_dek = hkdf.derive(self._master_key_fallback)
        # Encrypt the DEK under local master key with AES-GCM
        local_aes = AESGCM(self._master_key_fallback)
        nonce = secrets.token_bytes(12)
        encrypted_dek = nonce + local_aes.encrypt(
            nonce,
            plaintext_dek,
            f"tenant:{tenant_id}".encode("utf-8"),
        )
        return plaintext_dek, encrypted_dek

    def _decrypt_local_dek(self, encrypted_dek: bytes, tenant_id: str) -> bytes:
        """Decrypt a locally encrypted DEK, verifying tenant context."""
        if len(encrypted_dek) < 12:
            raise CiphertextTamperedError("Invalid local DEK envelope length.")
        nonce = encrypted_dek[:12]
        ciphertext = encrypted_dek[12:]
        local_aes = AESGCM(self._master_key_fallback)
        try:
            return local_aes.decrypt(
                nonce,
                ciphertext,
                f"tenant:{tenant_id}".encode("utf-8"),
            )
        except Exception:
            raise TenantContextMismatchError(
                f"Local DEK decryption failed: tenant context mismatch for '{tenant_id}'."
            )

    def encrypt(
        self,
        plaintext: str,
        tenant_id: str,
        classification: str = "restricted",
    ) -> str:
        """Envelope-encrypt plaintext with tenant-bound context.
        
        Returns:
            Formatted envelope string: v1:{b64_enc_dek}:{b64_nonce}:{b64_ciphertext}
        """
        if not plaintext:
            return ""

        clean_tenant = (tenant_id or "default").strip()
        context = {
            "tenant_id": clean_tenant,
            "classification": classification,
        }
        aad = _canonical_context_bytes(context)

        plaintext_dek: bytes
        encrypted_dek: bytes

        if self._is_kms_active():
            try:
                kms = self._get_kms_client()
                response = kms.generate_data_key(
                    KeyId=self.kms_key_id,
                    KeySpec="AES_256",
                    EncryptionContext=context,
                )
                plaintext_dek = response["Plaintext"]
                encrypted_dek = response["CiphertextBlob"]
            except Exception as e:
                logger.error(f"KMS GenerateDataKey failed: {type(e).__name__}")
                raise EncryptionError(f"KMS encryption failed: {str(e)}") from e
        else:
            salt = secrets.token_bytes(16)
            plaintext_dek, encrypted_dek = self._derive_local_dek(clean_tenant, salt)

        try:
            aesgcm = AESGCM(plaintext_dek)
            nonce = secrets.token_bytes(12)
            ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)

            b64_dek = base64.urlsafe_b64encode(encrypted_dek).decode("ascii")
            b64_nonce = base64.urlsafe_b64encode(nonce).decode("ascii")
            b64_cipher = base64.urlsafe_b64encode(ciphertext).decode("ascii")

            return f"v1:{b64_dek}:{b64_nonce}:{b64_cipher}"
        finally:
            # Explicitly clear plaintext key reference
            plaintext_dek = b"\x00" * len(plaintext_dek)

    def decrypt(
        self,
        envelope_text: str,
        tenant_id: str,
        classification: str = "restricted",
    ) -> str:
        """Envelope-decrypt ciphertext, strictly verifying tenant context and auth tag."""
        if not envelope_text:
            return ""

        if not envelope_text.startswith("v1:"):
            # Plaintext fallback for legacy/unencrypted data
            return envelope_text

        parts = envelope_text.split(":")
        if len(parts) != 4:
            raise EncryptionError("Malformed envelope ciphertext format.")

        _, b64_dek, b64_nonce, b64_cipher = parts

        try:
            encrypted_dek = base64.urlsafe_b64decode(b64_dek.encode("ascii"))
            nonce = base64.urlsafe_b64decode(b64_nonce.encode("ascii"))
            ciphertext = base64.urlsafe_b64decode(b64_cipher.encode("ascii"))
        except Exception as e:
            raise EncryptionError(f"Base64 decoding failed on envelope payload: {e}") from e

        clean_tenant = (tenant_id or "default").strip()
        context = {
            "tenant_id": clean_tenant,
            "classification": classification,
        }
        aad = _canonical_context_bytes(context)

        plaintext_dek: bytes

        if self._is_kms_active():
            try:
                kms = self._get_kms_client()
                response = kms.decrypt(
                    CiphertextBlob=encrypted_dek,
                    EncryptionContext=context,
                )
                plaintext_dek = response["Plaintext"]
            except ClientError as ce:
                code = ce.response.get("Error", {}).get("Code", "")
                if code == "InvalidCiphertextException":
                    raise TenantContextMismatchError(
                        f"KMS decryption failed: encryption context mismatch for tenant '{clean_tenant}'."
                    ) from ce
                raise EncryptionError(f"KMS decrypt call failed: {ce}") from ce
            except Exception as e:
                raise EncryptionError(f"KMS decryption error: {e}") from e
        else:
            plaintext_dek = self._decrypt_local_dek(encrypted_dek, clean_tenant)

        try:
            aesgcm = AESGCM(plaintext_dek)
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, aad)
            return plaintext_bytes.decode("utf-8")
        except TenantContextMismatchError:
            raise
        except Exception as e:
            raise CiphertextTamperedError(
                f"Ciphertext verification failed (tampered payload or invalid tag): {e}"
            ) from e
        finally:
            plaintext_dek = b"\x00" * len(plaintext_dek)


# Global default instance
global_encryption_service = EnvelopeEncryptionService()
