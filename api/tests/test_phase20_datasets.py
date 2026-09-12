"""Tests for Phase 20 Golden Datasets, Registry, and Anti-Contamination Guards."""

import pytest
from app.evaluation.contracts import EvaluationSuiteType, EvaluationDomain
from app.evaluation.datasets.registry import DatasetRegistry
from app.evaluation.errors import ContaminationError, DatasetContaminationError


def test_dataset_registry_initialization():
    DatasetRegistry.initialize()
    datasets = DatasetRegistry.list_datasets()
    assert len(datasets) >= 10
    suite_types = {d.dataset_id for d in datasets}
    assert any("agent" in sid for sid in suite_types)
    assert any("risk" in sid for sid in suite_types)
    assert any("security" in sid for sid in suite_types)


def test_dataset_retrieval_by_suite():
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.AGENT_EVALUATION)
    assert dataset.domain == EvaluationDomain.AGENT
    assert len(dataset.cases) > 0
    assert dataset.is_eval_only is True
    assert len(dataset.fingerprint) == 64


def test_dataset_contamination_guard_blocks_training():
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.ML_EVALUATION)
    # Attempting to use eval dataset for training must raise ContaminationError
    with pytest.raises((ContaminationError, DatasetContaminationError)):
        DatasetRegistry.guard_against_contamination(dataset, target_subsystem="TRAINING")

    with pytest.raises((ContaminationError, DatasetContaminationError)):
        DatasetRegistry.guard_against_contamination(dataset, target_subsystem="RAG_KNOWLEDGE_BASE")


def test_dataset_contamination_guard_permits_eval():
    dataset = DatasetRegistry.get_dataset(EvaluationSuiteType.RAG_EVALUATION)
    # Evaluation harness usage is permitted
    DatasetRegistry.guard_against_contamination(dataset, target_subsystem="EVALUATION_HARNESS")
