"""Phase 6 Semantic Normalization Package.

Provides strongly typed internal risk signal contracts, deterministic unit
and status normalizers, domain handlers, and the end-to-end normalization pipeline.
"""

from app.normalization.contract import (
    CorroboratingEvidence,
    CorrelationConfidence,
    CorrelationMethod,
    CorrelationStatus,
    EntityReference,
    EntityType,
    NormalizedRiskSignal,
    OperationalValues,
    SignalDomain,
    SignalEntityReferences,
    SignalStatus,
    SignalType,
)
from app.normalization.correlation import CrossSourceCorrelator
from app.normalization.entity_resolver import (
    EntityLookupProvider,
    EntityNormalizer,
    InMemoryEntityLookupProvider,
)
from app.normalization.handlers import (
    AirFreightNormalizationHandler,
    BaseDomainNormalizationHandler,
    DomainNormalizationRegistry,
    GeneralNormalizationHandler,
    IntelligenceNewsNormalizationHandler,
    LogisticsTrackingNormalizationHandler,
    MaritimePortNormalizationHandler,
    OceanAISNormalizationHandler,
    PortNormalizationHandler,
    RailTransitNormalizationHandler,
    RoadTrafficNormalizationHandler,
    WeatherNormalizationHandler,
)
from app.normalization.identifiers import (
    IdentifierNormalizer,
    NormalizedIdentifier,
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
    "EntityType",
    "CorrelationConfidence",
    "CorrelationMethod",
    "EntityReference",
    "SignalEntityReferences",
    "CorroboratingEvidence",
    "OperationalValues",
    # Identifiers & Resolution (Step 3)
    "NormalizedIdentifier",
    "IdentifierNormalizer",
    "EntityLookupProvider",
    "InMemoryEntityLookupProvider",
    "EntityNormalizer",
    "CrossSourceCorrelator",
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
    "MaritimePortNormalizationHandler",
    "PortNormalizationHandler",
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

