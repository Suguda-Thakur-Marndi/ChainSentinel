"""Phase 6 Semantic Normalization Package.

Provides strongly typed internal risk signal contracts, deterministic unit
and status normalizers, domain handlers, and the end-to-end normalization pipeline.
"""

from app.normalization.contract import (
    CorroboratingEvidence,
    CorrelationStatus,
    NormalizedRiskSignal,
    OperationalValues,
    SignalDomain,
    SignalEntityReferences,
    SignalStatus,
    SignalType,
)
from app.normalization.handlers import (
    AirFreightNormalizationHandler,
    BaseDomainNormalizationHandler,
    DomainNormalizationRegistry,
    GeneralNormalizationHandler,
    IntelligenceNewsNormalizationHandler,
    LogisticsTrackingNormalizationHandler,
    OceanAISNormalizationHandler,
    RailTransitNormalizationHandler,
    RoadTrafficNormalizationHandler,
    WeatherNormalizationHandler,
)
from app.normalization.pipeline import (
    BatchNormalizationResult,
    NormalizationPipeline,
    NormalizationResult,
    NormalizationStatus,
)
from app.normalization.status import StatusNormalizer
from app.normalization.units import UnitConversionResult, UnitNormalizer

__all__ = [
    # Contracts & Enums
    "NormalizedRiskSignal",
    "SignalDomain",
    "SignalType",
    "SignalStatus",
    "CorrelationStatus",
    "SignalEntityReferences",
    "CorroboratingEvidence",
    "OperationalValues",
    # Units & Status
    "UnitNormalizer",
    "UnitConversionResult",
    "StatusNormalizer",
    # Handlers & Registry
    "BaseDomainNormalizationHandler",
    "DomainNormalizationRegistry",
    "WeatherNormalizationHandler",
    "RoadTrafficNormalizationHandler",
    "OceanAISNormalizationHandler",
    "AirFreightNormalizationHandler",
    "RailTransitNormalizationHandler",
    "LogisticsTrackingNormalizationHandler",
    "IntelligenceNewsNormalizationHandler",
    "GeneralNormalizationHandler",
    # Pipeline & Results
    "NormalizationPipeline",
    "NormalizationStatus",
    "NormalizationResult",
    "BatchNormalizationResult",
]
