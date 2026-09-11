"""Deterministic feature pipeline for shipment delay regression.

Defines the exact feature schema and provides shared preprocessing transformations
guaranteed to be identical between training and inference.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.preprocessing import StandardScaler

from app.ml.contracts import FeatureSchema, FeatureSpec, FeatureType
from app.ml.datasets.contracts import DatasetRow
from app.ml.errors import FeatureEngineeringError, FeatureSchemaError
from app.ml.features.contracts import BaseFeaturePipeline

SUPPORTED_TRANSPORT_MODES = ["OCEAN", "AIR", "RAIL", "ROAD", "UNKNOWN"]

# 12 explicit, non-leaking shipment features
SHIPMENT_DELAY_FEATURE_SPECS = [
    FeatureSpec(
        name="transport_mode",
        feature_type=FeatureType.CATEGORICAL,
        unit="category",
        description="Transport mode (OCEAN, AIR, RAIL, ROAD)",
        source_field="shipment.mode",
        missing_value_strategy="unknown",
    ),
    FeatureSpec(
        name="planned_duration_hours",
        feature_type=FeatureType.NUMERIC,
        unit="hours",
        description="Scheduled transit duration from origin to destination",
        source_field="route.standard_lead_time_days * 24.0 or (eta - created_at)",
        missing_value_strategy="median",
    ),
    FeatureSpec(
        name="route_distance_km",
        feature_type=FeatureType.NUMERIC,
        unit="km",
        description="Route geographical corridor distance in kilometers",
        source_field="route.distance_km",
        missing_value_strategy="median",
    ),
    FeatureSpec(
        name="route_lead_time_days",
        feature_type=FeatureType.NUMERIC,
        unit="days",
        description="Standard historical lead time along corridor",
        source_field="route.standard_lead_time_days",
        missing_value_strategy="median",
    ),
    FeatureSpec(
        name="route_risk_score",
        feature_type=FeatureType.NUMERIC,
        unit="score",
        description="Authoritative corridor risk assessment score",
        source_field="route.risk_score",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="carrier_reliability",
        feature_type=FeatureType.NUMERIC,
        unit="ratio",
        description="Carrier historical on-time delivery reliability (0.0 - 1.0)",
        source_field="carrier.on_time_reliability",
        missing_value_strategy="median",
    ),
    FeatureSpec(
        name="origin_congestion",
        feature_type=FeatureType.NUMERIC,
        unit="score",
        description="Congestion index at origin port/hub prior to dispatch",
        source_field="port.congestion_score",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="destination_congestion",
        feature_type=FeatureType.NUMERIC,
        unit="score",
        description="Congestion index at destination facility prior to dispatch",
        source_field="port.congestion_score",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="events_count_before_cutoff",
        feature_type=FeatureType.NUMERIC,
        unit="count",
        description="Number of telemetry milestone events logged before inference cutoff",
        source_field="count(shipment_events where timestamp <= cutoff)",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="intermediate_delays_before_cutoff",
        feature_type=FeatureType.NUMERIC,
        unit="minutes",
        description="Cumulative delay reported in milestones before inference cutoff",
        source_field="sum(shipment_events.delay_minutes where timestamp <= cutoff)",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="weather_disruption_flag",
        feature_type=FeatureType.BOOLEAN,
        unit="flag",
        description="Signal indicating verified weather disruption along corridor",
        source_field="incident.weather_active",
        missing_value_strategy="zero",
    ),
    FeatureSpec(
        name="port_disruption_flag",
        feature_type=FeatureType.BOOLEAN,
        unit="flag",
        description="Signal indicating verified port strike, outage, or bottleneck",
        source_field="incident.port_active",
        missing_value_strategy="zero",
    ),
]

SHIPMENT_DELAY_SCHEMA = FeatureSchema(
    version="shipment_delay_v1",
    features=SHIPMENT_DELAY_FEATURE_SPECS,
    target_name="delay_minutes",
    target_type=FeatureType.NUMERIC,
)


FEATURE_ALIASES: Dict[str, List[str]] = {
    "port_disruption_flag": ["port_disruption_detected", "port_disruption"],
    "weather_disruption_flag": ["weather_disruption_detected", "weather_disruption"],
    "planned_duration_hours": ["scheduled_transit_hours", "transit_hours", "planned_hours"],
    "route_risk_score": ["risk_composite_score", "risk_score"],
    "carrier_reliability": ["carrier_on_time_reliability", "on_time_reliability"],
}


class ShipmentDelayFeaturePipeline(BaseFeaturePipeline):
    """Preprocessing and feature transformation pipeline for shipment delay prediction."""

    def __init__(self, schema: FeatureSchema = SHIPMENT_DELAY_SCHEMA) -> None:
        self._schema = schema
        self._scaler = StandardScaler()
        self._is_fitted = False
        self._numeric_feature_names = [
            f.name for f in self._schema.features if f.feature_type in (FeatureType.NUMERIC, FeatureType.BOOLEAN)
        ]
        self._mode_categories = SUPPORTED_TRANSPORT_MODES

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    def get_feature_schema(self) -> FeatureSchema:
        return self._schema

    def _encode_mode(self, mode: str) -> List[float]:
        """Deterministic one-hot encoding for transport_mode."""
        clean_mode = str(mode).upper().strip()
        vec = [0.0] * len(self._mode_categories)
        if clean_mode in self._mode_categories:
            idx = self._mode_categories.index(clean_mode)
        else:
            idx = self._mode_categories.index("UNKNOWN")
        vec[idx] = 1.0
        return vec

    def _extract_numeric_vector(self, feat_dict: Dict[str, Any]) -> List[float]:
        vec: List[float] = []
        for name in self._numeric_feature_names:
            val = feat_dict.get(name)
            if val is None:
                # Check aliases
                for alias in FEATURE_ALIASES.get(name, []):
                    if alias in feat_dict:
                        val = feat_dict[alias]
                        break
            if val is None:
                val = 0.0

            if isinstance(val, bool):
                vec.append(1.0 if val else 0.0)
            elif isinstance(val, (int, float)):
                if math.isnan(val) or math.isinf(val):
                    raise FeatureEngineeringError(f"Non-finite value for feature '{name}': {val}")
                vec.append(float(val))
            else:
                try:
                    num_val = float(val)
                    if math.isnan(num_val) or math.isinf(num_val):
                        raise FeatureEngineeringError(f"Non-finite value for feature '{name}': {val}")
                    vec.append(num_val)
                except (ValueError, TypeError):
                    raise FeatureSchemaError(f"Expected numeric for feature '{name}', got '{val}'.")
        return vec

    def fit(self, rows: List[DatasetRow]) -> "ShipmentDelayFeaturePipeline":
        if not rows:
            raise FeatureEngineeringError("Cannot fit feature pipeline on 0 rows.")

        raw_numerics = np.array([self._extract_numeric_vector(r.features) for r in rows], dtype=np.float64)
        self._scaler.fit(raw_numerics)
        self._is_fitted = True
        return self

    def transform(self, rows: List[DatasetRow]) -> np.ndarray:
        if not self._is_fitted:
            raise FeatureEngineeringError("Feature pipeline must be fitted before transform().")
        if not rows:
            return np.empty((0, len(self._numeric_feature_names) + len(self._mode_categories)), dtype=np.float64)

        raw_numerics = np.array([self._extract_numeric_vector(r.features) for r in rows], dtype=np.float64)
        scaled_numerics = self._scaler.transform(raw_numerics)

        cat_encoded = np.array([self._encode_mode(r.features.get("transport_mode", "UNKNOWN")) for r in rows], dtype=np.float64)
        return np.hstack([scaled_numerics, cat_encoded])

    def transform_single(self, features: Dict[str, Any]) -> np.ndarray:
        if not self._is_fitted:
            raise FeatureEngineeringError("Feature pipeline must be fitted before transform_single().")

        raw_num = np.array([self._extract_numeric_vector(features)], dtype=np.float64)
        scaled_num = self._scaler.transform(raw_num)
        cat_enc = np.array([self._encode_mode(features.get("transport_mode", "UNKNOWN"))], dtype=np.float64)
        return np.hstack([scaled_num, cat_enc])

    def get_output_feature_names(self) -> List[str]:
        """Return the complete ordered list of features produced by transform."""
        cat_names = [f"mode_{m}" for m in self._mode_categories]
        return list(self._numeric_feature_names) + cat_names

