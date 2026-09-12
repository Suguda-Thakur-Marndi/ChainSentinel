"""Contracts for versioned golden evaluation datasets (Phase 20)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.contracts import EvaluationCase, EvaluationSuiteType, compute_sha256
from app.evaluation.errors import ContaminationError


class EvaluationDataset(BaseModel):
    """Immutable, versioned collection of evaluation test cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str = Field(..., min_length=1, max_length=64)
    suite_type: EvaluationSuiteType
    version: str = Field(default="1.0.0", min_length=1, max_length=32)
    description: str = Field(default="", max_length=512)
    cases: List[EvaluationCase] = Field(..., min_length=1)
    dataset_fingerprint: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_immutable: bool = Field(default=True)

    @model_validator(mode="before")
    @classmethod
    def _compute_dataset_fingerprint(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("dataset_fingerprint"):
            cases = data.get("cases", [])
            case_ids = [c.case_id if isinstance(c, EvaluationCase) else c.get("case_id", "") for c in cases]
            payload = f"{data.get('dataset_id')}:{data.get('version')}:{','.join(sorted(case_ids))}"
            data["dataset_fingerprint"] = compute_sha256(payload)
        return data

    @property
    def case_count(self) -> int:
        return len(self.cases)
