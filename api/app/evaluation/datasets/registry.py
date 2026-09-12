"""Dataset Registry for RiskWise 2.0 Evaluation.

Provides:
- Versioned immutable evaluation datasets
- Explicit domain mappings
- Contamination prevention guards (ensures eval data is never used for training or RAG vector storage)
"""

from typing import Dict, List, Optional
import hashlib
from app.evaluation.contracts import (
    EvaluationDataset,
    EvaluationDomain,
    EvaluationSuiteType,
    DatasetCategory,
)
from app.evaluation.datasets.golden import (
    GOLDEN_AGENT_CASES,
    GOLDEN_RESEARCH_CASES,
    GOLDEN_RISK_CASES,
    GOLDEN_RAG_CASES,
    GOLDEN_CLAUDE_CASES,
    GOLDEN_ML_CASES,
    GOLDEN_DIGITAL_TWIN_CASES,
    GOLDEN_SIMULATION_CASES,
    GOLDEN_OPTIMIZATION_CASES,
    GOLDEN_DECISION_CASES,
    GOLDEN_APPROVAL_CASES,
    GOLDEN_ACTION_CASES,
    GOLDEN_VERIFICATION_CASES,
    GOLDEN_E2E_CASES,
    GOLDEN_SECURITY_CASES,
)
from app.evaluation.errors import DatasetContaminationError

DEFAULT_DATASET_VERSION = "v1.0.0"

SUITE_TO_DOMAIN: Dict[EvaluationSuiteType, EvaluationDomain] = {
    EvaluationSuiteType.AGENT_EVALUATION: EvaluationDomain.AGENT,
    EvaluationSuiteType.RESEARCH_EVALUATION: EvaluationDomain.RESEARCH,
    EvaluationSuiteType.RISK_EVALUATION: EvaluationDomain.RISK,
    EvaluationSuiteType.RAG_EVALUATION: EvaluationDomain.RAG,
    EvaluationSuiteType.CLAUDE_EVALUATION: EvaluationDomain.CLAUDE,
    EvaluationSuiteType.ML_EVALUATION: EvaluationDomain.ML,
    EvaluationSuiteType.DIGITAL_TWIN_EVALUATION: EvaluationDomain.DIGITAL_TWIN,
    EvaluationSuiteType.SIMULATION_EVALUATION: EvaluationDomain.SIMULATION,
    EvaluationSuiteType.OPTIMIZATION_EVALUATION: EvaluationDomain.OPTIMIZATION,
    EvaluationSuiteType.DECISION_EVALUATION: EvaluationDomain.DECISION,
    EvaluationSuiteType.APPROVAL_EVALUATION: EvaluationDomain.APPROVAL,
    EvaluationSuiteType.ACTION_EVALUATION: EvaluationDomain.ACTION,
    EvaluationSuiteType.VERIFICATION_EVALUATION: EvaluationDomain.VERIFICATION,
    EvaluationSuiteType.END_TO_END_EVALUATION: EvaluationDomain.END_TO_END,
    EvaluationSuiteType.SECURITY_EVALUATION: EvaluationDomain.SECURITY,
}

SUITE_CASES_MAP = {
    EvaluationSuiteType.AGENT_EVALUATION: GOLDEN_AGENT_CASES,
    EvaluationSuiteType.RESEARCH_EVALUATION: GOLDEN_RESEARCH_CASES,
    EvaluationSuiteType.RISK_EVALUATION: GOLDEN_RISK_CASES,
    EvaluationSuiteType.RAG_EVALUATION: GOLDEN_RAG_CASES,
    EvaluationSuiteType.CLAUDE_EVALUATION: GOLDEN_CLAUDE_CASES,
    EvaluationSuiteType.ML_EVALUATION: GOLDEN_ML_CASES,
    EvaluationSuiteType.DIGITAL_TWIN_EVALUATION: GOLDEN_DIGITAL_TWIN_CASES,
    EvaluationSuiteType.SIMULATION_EVALUATION: GOLDEN_SIMULATION_CASES,
    EvaluationSuiteType.OPTIMIZATION_EVALUATION: GOLDEN_OPTIMIZATION_CASES,
    EvaluationSuiteType.DECISION_EVALUATION: GOLDEN_DECISION_CASES,
    EvaluationSuiteType.APPROVAL_EVALUATION: GOLDEN_APPROVAL_CASES,
    EvaluationSuiteType.ACTION_EVALUATION: GOLDEN_ACTION_CASES,
    EvaluationSuiteType.VERIFICATION_EVALUATION: GOLDEN_VERIFICATION_CASES,
    EvaluationSuiteType.END_TO_END_EVALUATION: GOLDEN_E2E_CASES,
    EvaluationSuiteType.SECURITY_EVALUATION: GOLDEN_SECURITY_CASES,
}


def _compute_dataset_fingerprint(suite: str, version: str, case_ids: List[str]) -> str:
    raw = f"{suite}:{version}:" + ",".join(sorted(case_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DatasetRegistry:
    """Registry maintaining golden evaluation datasets with anti-contamination safeguards."""

    _datasets: Dict[str, EvaluationDataset] = {}

    @classmethod
    def initialize(cls) -> None:
        if cls._datasets:
            return

        for suite_type, cases in SUITE_CASES_MAP.items():
            dataset_id = f"ds-{suite_type.value.lower().replace('_', '-')}-{DEFAULT_DATASET_VERSION}"
            fingerprint = _compute_dataset_fingerprint(
                suite_type.value, DEFAULT_DATASET_VERSION, [c.case_id for c in cases]
            )
            dataset = EvaluationDataset(
                dataset_id=dataset_id,
                name=f"Golden {suite_type.value} Benchmark Dataset",
                domain=SUITE_TO_DOMAIN[suite_type],
                version=DEFAULT_DATASET_VERSION,
                cases=cases,
                fingerprint=fingerprint,
                is_eval_only=True,
                metadata={
                    "contamination_guard": "STRICT_ISOLATION",
                    "case_count": len(cases),
                    "suite_type": suite_type.value,
                },
            )
            cls._datasets[dataset_id] = dataset

    @classmethod
    def get_dataset(cls, suite_type: EvaluationSuiteType, version: str = DEFAULT_DATASET_VERSION) -> EvaluationDataset:
        cls.initialize()
        dataset_id = f"ds-{suite_type.value.lower().replace('_', '-')}-{version}"
        if dataset_id not in cls._datasets:
            raise KeyError(f"Dataset for suite {suite_type} with version {version} not found in registry")
        return cls._datasets[dataset_id]

    @classmethod
    def get_dataset_by_id(cls, dataset_id: str) -> Optional[EvaluationDataset]:
        cls.initialize()
        return cls._datasets.get(dataset_id)

    @classmethod
    def list_datasets(cls) -> List[EvaluationDataset]:
        cls.initialize()
        return list(cls._datasets.values())

    @classmethod
    def guard_against_contamination(cls, dataset: EvaluationDataset, target_subsystem: str) -> None:
        """Verifies that an evaluation dataset is never injected into training or vector storage."""
        if dataset.is_eval_only and target_subsystem.upper() in ["TRAINING", "MODEL_FIT", "RAG_KNOWLEDGE_BASE"]:
            raise DatasetContaminationError(
                f"Contamination Violation: Evaluation dataset '{dataset.dataset_id}' "
                f"is strictly guarded and cannot be ingested into '{target_subsystem}'"
            )


DatasetRegistry.initialize()
