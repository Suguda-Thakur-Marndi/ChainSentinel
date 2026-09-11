"""Unit tests for lightweight, tenant-aware ModelRegistry."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.contracts import (
    MLModelMetadata,
    ModelFamily,
    ModelMetrics,
    TaskType,
)
from app.ml.errors import MLTenantIsolationError, ModelRegistryError
from app.ml.features.shipment_delay import SHIPMENT_DELAY_SCHEMA, ShipmentDelayFeaturePipeline
from app.ml.models.shipment_delay import ShipmentDelayModel
from app.ml.registry.registry import ModelRegistry
from tests.test_phase11_ml_dataset import make_sample_rows


def make_test_model(model_id: str, org_id: str | None = None, is_prod: bool = True):
    rows = make_sample_rows(25)
    pipeline = ShipmentDelayFeaturePipeline(schema=SHIPMENT_DELAY_SCHEMA)
    pipeline.fit(rows)

    X = pipeline.transform(rows)
    y = np.array([r.target for r in rows], dtype=np.float64)

    model = ShipmentDelayModel(model_id=model_id, random_seed=42)
    model.fit(X, y)
    metrics = model.evaluate(X, y)

    meta = MLModelMetadata(
        model_id=model_id,
        model_family=ModelFamily.SHIPMENT_DELAY,
        model_version="1.0.0",
        task_type=TaskType.REGRESSION,
        target="delay_minutes",
        feature_names=pipeline.get_feature_schema().feature_names,
        training_dataset_fingerprint="ds_fp_test",
        preprocessing_version="shipment_delay_v1",
        hyperparameters={"alpha": 1.0},
        validation_status="VALIDATED",
        metrics=metrics,
        artifact_fingerprint="fp_" + model_id,
        organization_id=org_id,
        is_production=is_prod,
    )
    return model, pipeline, meta


class TestModelRegistry:
    def test_register_and_get_model(self) -> None:
        registry = ModelRegistry()
        model, pipeline, meta = make_test_model("m_delay_001", "org_acme")

        reg_id = registry.register_model(model, pipeline, meta)
        assert reg_id == "m_delay_001"

        entry = registry.get_model("m_delay_001", organization_id="org_acme")
        assert entry is not None
        m, p, retrieved_meta = entry
        assert retrieved_meta.model_id == "m_delay_001"
        assert retrieved_meta.organization_id == "org_acme"

    def test_register_empty_model_id_raises_error(self) -> None:
        registry = ModelRegistry()
        model, pipeline, meta = make_test_model("valid_id", "org_acme")
        bad_meta = meta.model_copy(update={"model_id": "   "})

        with pytest.raises(ModelRegistryError) as exc_info:
            registry.register_model(model, pipeline, bad_meta)
        assert "model_id must be non-empty" in str(exc_info.value)

    def test_get_non_existent_model_returns_none(self) -> None:
        registry = ModelRegistry()
        entry = registry.get_model("unknown_model_xyz")
        assert entry is None

    def test_get_model_cross_tenant_isolation_violation_raises_error(self) -> None:
        registry = ModelRegistry()
        model, pipeline, meta = make_test_model("m_tenant_a", "org_tenant_a")
        registry.register_model(model, pipeline, meta)

        # Org B attempting to fetch Org A's model must raise MLTenantIsolationError
        with pytest.raises(MLTenantIsolationError) as exc_info:
            registry.get_model("m_tenant_a", organization_id="org_tenant_b")
        assert "belongs to tenant 'org_tenant_a'" in str(exc_info.value)
        assert "inaccessible to tenant 'org_tenant_b'" in str(exc_info.value)

    def test_get_active_model_prefers_tenant_specific_over_global(self) -> None:
        registry = ModelRegistry()

        # Register global model
        g_model, g_pipe, g_meta = make_test_model("m_global", org_id=None, is_prod=True)
        registry.register_model(g_model, g_pipe, g_meta)

        # Register tenant-specific model
        t_model, t_pipe, t_meta = make_test_model("m_acme_specific", org_id="org_acme", is_prod=True)
        registry.register_model(t_model, t_pipe, t_meta)

        # Request active model for org_acme -> must get tenant-specific model
        acme_entry = registry.get_active_model(ModelFamily.SHIPMENT_DELAY, organization_id="org_acme")
        assert acme_entry is not None
        assert acme_entry[2].model_id == "m_acme_specific"

        # Request active model for org_other (which has no specific model) -> falls back to global
        other_entry = registry.get_active_model(ModelFamily.SHIPMENT_DELAY, organization_id="org_other")
        assert other_entry is not None
        assert other_entry[2].model_id == "m_global"

    def test_get_active_model_returns_none_when_no_matching_family(self) -> None:
        registry = ModelRegistry()
        entry = registry.get_active_model(ModelFamily.STOCKOUT_PREDICTION, organization_id="org_acme")
        assert entry is None

    def test_list_models_filtering(self) -> None:
        registry = ModelRegistry()
        m1, p1, meta1 = make_test_model("m_acme_1", org_id="org_acme")
        m2, p2, meta2 = make_test_model("m_beta_1", org_id="org_beta")
        m3, p3, meta3 = make_test_model("m_global_1", org_id=None)

        registry.register_model(m1, p1, meta1)
        registry.register_model(m2, p2, meta2)
        registry.register_model(m3, p3, meta3)

        # Filter by org_acme
        acme_list = registry.list_models(organization_id="org_acme")
        assert len(acme_list) == 2  # acme_1 + global_1
        acme_ids = {m.model_id for m in acme_list}
        assert "m_acme_1" in acme_ids
        assert "m_global_1" in acme_ids
        assert "m_beta_1" not in acme_ids

        # Filter by family
        delay_list = registry.list_models(family=ModelFamily.SHIPMENT_DELAY)
        assert len(delay_list) == 3

        stockout_list = registry.list_models(family=ModelFamily.STOCKOUT_PREDICTION)
        assert len(stockout_list) == 0

    def test_clear_resets_registry(self) -> None:
        registry = ModelRegistry()
        m, p, meta = make_test_model("m_to_clear", "org_acme")
        registry.register_model(m, p, meta)
        assert len(registry.list_models()) == 1

        registry.clear()
        assert len(registry.list_models()) == 0
        assert registry.get_model("m_to_clear") is None
