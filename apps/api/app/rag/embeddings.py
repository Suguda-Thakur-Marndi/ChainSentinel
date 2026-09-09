"""Embedding provider abstractions and vector generation backends for RiskWise RAG subsystem.

Provides a provider-independent interface supporting LocalMock, OpenAI, and AWS Bedrock
embedding backends. Strictly enforces 1536-dimensional vector representations,
L2 normalization, and deterministic fingerprinting for idempotent vector storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import math
import os
import random
from typing import Any, Dict, List, Optional, Union

from app.rag.contracts import (
    EmbeddingMetadata,
    EmbeddingProvider,
    EmbeddingVector,
)
from app.rag.errors import (
    RAGEmbeddingDimensionError,
    RAGEmbeddingError,
    RAGMalformedInputError,
    RAGSecurityPolicyViolationError,
)

# Canonical RAG vector dimension specified in Technical Spec §4 & database schema
TARGET_EMBEDDING_DIMENSION = 1536


def compute_embedding_fingerprint(
    text: str,
    model_name: str,
    dimension: int = TARGET_EMBEDDING_DIMENSION,
) -> str:
    """Generate a collision-resistant SHA-256 fingerprint for text, model, and dimension.

    Enables O(1) idempotent deduplication: if chunk content, embedding model, and
    dimension are unchanged, previously generated vectors are reused without API calls.
    """
    clean_text = text.strip()
    text_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()
    fingerprint_key = f"{model_name.lower().strip()}:{dimension}:{text_hash}"
    return hashlib.sha256(fingerprint_key.encode("utf-8")).hexdigest()


class BaseEmbeddingProvider(ABC):
    """Abstract interface defining standard embedding generation operations."""

    @property
    @abstractmethod
    def provider(self) -> EmbeddingProvider:
        """The recognized provider enumeration identifier."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model identifier for this provider."""
        ...

    @property
    def dimension(self) -> int:
        """Expected vector dimension (strictly 1536)."""
        return TARGET_EMBEDDING_DIMENSION

    @abstractmethod
    def embed_text(self, text: str, model: Optional[str] = None) -> EmbeddingVector:
        """Generate a normalized 1536-dimensional embedding vector for a single text string."""
        ...

    @abstractmethod
    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[EmbeddingVector]:
        """Generate normalized 1536-dimensional embedding vectors for a batch of strings."""
        ...


class LocalMockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, zero-dependency embedding generator for testing and air-gapped deployments.

    Uses SHA-256 hash of the input text as a PRNG seed to generate reproducible,
    L2-normalized 1536-dimensional vectors. Cosine similarity between identical texts is
    exactly 1.0; different texts produce realistic, deterministic similarities in [-1.0, 1.0].
    """

    def __init__(self, model_name: str = "mock-embedding-1536") -> None:
        self._model_name = model_name

    @property
    def provider(self) -> EmbeddingProvider:
        return EmbeddingProvider.LOCAL_MOCK

    @property
    def default_model(self) -> str:
        return self._model_name

    def embed_text(self, text: str, model: Optional[str] = None) -> EmbeddingVector:
        clean_text = text.strip()
        if not clean_text:
            raise RAGMalformedInputError("Cannot generate embedding for empty text.")

        # Seed PRNG deterministically from text's SHA-256 digest
        seed_int = int(hashlib.sha256(clean_text.encode("utf-8")).hexdigest(), 16)
        rng = random.Random(seed_int)

        # Generate 1536 pseudo-random values with zero mean
        raw_values = [rng.gauss(0.0, 1.0) for _ in range(self.dimension)]

        # L2-normalize vector to unit length (||v|| = 1.0)
        norm = math.sqrt(sum(x * x for x in raw_values))
        if norm == 0.0:
            norm = 1.0
        normalized_values = [round(x / norm, 7) for x in raw_values]

        return EmbeddingVector(
            values=normalized_values,
            dimension=self.dimension,
            is_normalized=True,
        )

    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[EmbeddingVector]:
        if not texts:
            return []
        return [self.embed_text(t, model=model) for t in texts]


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding backend supporting text-embedding-3-small (1536 dims).

    Enforces strict dimension verification, batching, and credential protection.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "text-embedding-3-small",
    ) -> None:
        self._model_name = model_name
        self._api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")

    @property
    def provider(self) -> EmbeddingProvider:
        return EmbeddingProvider.OPENAI

    @property
    def default_model(self) -> str:
        return self._model_name

    def embed_text(self, text: str, model: Optional[str] = None) -> EmbeddingVector:
        results = self.embed_batch([text], model=model)
        if not results:
            raise RAGEmbeddingError("OpenAI provider returned empty response for text embedding.")
        return results[0]

    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[EmbeddingVector]:
        clean_texts = [t.strip() for t in texts if t and t.strip()]
        if not clean_texts:
            return []

        # If no API key configured (e.g. testing or air-gapped without key), raise typed error
        if not self._api_key:
            raise RAGEmbeddingError(
                "OPENAI_API_KEY is not configured on the server. Cannot generate commercial embeddings."
            )

        target_model = model or self.default_model

        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "input": clean_texts,
                "model": target_model,
                "dimensions": self.dimension,
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers=headers,
                    json=payload,
                )

            if response.status_code != 200:
                # Sanitize error message to prevent token leakage
                safe_err = response.text.replace(self._api_key, "[REDACTED_API_KEY]")
                raise RAGEmbeddingError(
                    f"OpenAI API embedding request failed with HTTP {response.status_code}: {safe_err}"
                )

            data = response.json()
            items = data.get("data", [])
            vectors: List[EmbeddingVector] = []

            for item in items:
                emb_values = item.get("embedding", [])
                if len(emb_values) != self.dimension:
                    raise RAGEmbeddingDimensionError(
                        f"OpenAI returned vector of dimension {len(emb_values)}, expected {self.dimension}."
                    )
                vectors.append(
                    EmbeddingVector(
                        values=emb_values,
                        dimension=self.dimension,
                        is_normalized=True,
                    )
                )

            return vectors

        except (RAGEmbeddingError, RAGEmbeddingDimensionError):
            raise
        except Exception as err:
            err_msg = str(err)
            if self._api_key:
                err_msg = err_msg.replace(self._api_key, "[REDACTED_API_KEY]")
            raise RAGEmbeddingError(f"OpenAI embedding execution error: {err_msg}") from err


class BedrockEmbeddingProvider(BaseEmbeddingProvider):
    """AWS Bedrock Titan Embeddings backend supporting amazon.titan-embed-text-v2 (1536 dims)."""

    def __init__(
        self,
        region_name: str = "ap-southeast-2",
        model_name: str = "amazon.titan-embed-text-v2",
    ) -> None:
        self._model_name = model_name
        self._region_name = region_name

    @property
    def provider(self) -> EmbeddingProvider:
        return EmbeddingProvider.BEDROCK

    @property
    def default_model(self) -> str:
        return self._model_name

    def embed_text(self, text: str, model: Optional[str] = None) -> EmbeddingVector:
        results = self.embed_batch([text], model=model)
        if not results:
            raise RAGEmbeddingError("Bedrock provider returned empty response for text embedding.")
        return results[0]

    def embed_batch(self, texts: List[str], model: Optional[str] = None) -> List[EmbeddingVector]:
        clean_texts = [t.strip() for t in texts if t and t.strip()]
        if not clean_texts:
            return []

        # AWS Bedrock payload wrapper
        target_model = model or self.default_model
        vectors: List[EmbeddingVector] = []

        try:
            # When running without active AWS credentials or in offline mode, raise typed error
            import boto3

            client = boto3.client("bedrock-runtime", region_name=self._region_name)
            for t in clean_texts:
                import json
                body = json.dumps({"inputText": t, "dimensions": self.dimension, "normalize": True})
                response = client.invoke_model(
                    modelId=target_model,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                response_body = json.loads(response.get("body").read())
                emb_values = response_body.get("embedding", [])
                if len(emb_values) != self.dimension:
                    raise RAGEmbeddingDimensionError(
                        f"Bedrock returned vector of dimension {len(emb_values)}, expected {self.dimension}."
                    )
                vectors.append(
                    EmbeddingVector(
                        values=emb_values,
                        dimension=self.dimension,
                        is_normalized=True,
                    )
                )
            return vectors
        except (RAGEmbeddingError, RAGEmbeddingDimensionError):
            raise
        except Exception as err:
            raise RAGEmbeddingError(f"Bedrock embedding execution error: {err}") from err


def get_embedding_provider(
    provider: Union[str, EmbeddingProvider] = EmbeddingProvider.LOCAL_MOCK,
    **kwargs: Any,
) -> BaseEmbeddingProvider:
    """Factory resolving embedding provider backend instance."""
    prov_str = str(provider.value if isinstance(provider, EmbeddingProvider) else provider).upper()

    if prov_str == EmbeddingProvider.LOCAL_MOCK.value:
        return LocalMockEmbeddingProvider(**kwargs)
    elif prov_str == EmbeddingProvider.OPENAI.value:
        return OpenAIEmbeddingProvider(**kwargs)
    elif prov_str == EmbeddingProvider.BEDROCK.value:
        return BedrockEmbeddingProvider(**kwargs)
    else:
        raise RAGMalformedInputError(f"Unrecognized embedding provider: '{provider}'")
