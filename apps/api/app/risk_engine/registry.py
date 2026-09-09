"""Risk factor evaluator interface and deterministic registry for RiskWise Risk Engine.

Defines the abstract interface for future factor evaluators and provides a
provider-independent registry mapping normalized signals to factor evaluators.
"""

from __future__ import annotations

import abc
import logging
from typing import Dict, List, Optional, Set

from app.normalization.contract import NormalizedRiskSignal, SignalDomain, SignalType
from app.risk_engine.context import RiskEvaluationContext
from app.risk_engine.contract import RiskFactor
from app.risk_engine.errors import EvaluatorRegistrationError

logger = logging.getLogger("riskwise.risk_engine.registry")


class BaseRiskFactorEvaluator(abc.ABC):
    """Abstract base class and contract for all deterministic risk factor evaluators."""

    @property
    @abc.abstractmethod
    def evaluator_id(self) -> str:
        """Unique deterministic identifier of this factor evaluator."""
        pass

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name of the evaluator."""
        pass

    @property
    @abc.abstractmethod
    def target_domains(self) -> List[SignalDomain]:
        """List of signal domains this evaluator can process."""
        pass

    @property
    def supported_signal_types(self) -> List[SignalType]:
        """List of signal types this evaluator can process. Empty means all types in target domains."""
        return []

    def can_evaluate(self, signal: NormalizedRiskSignal, context: RiskEvaluationContext) -> bool:
        """Determine if this evaluator applies to the given normalized signal and context."""
        if signal.domain not in self.target_domains:
            return False
        if self.supported_signal_types and signal.signal_type not in self.supported_signal_types:
            return False
        return True

    @abc.abstractmethod
    def evaluate(
        self,
        signal: NormalizedRiskSignal,
        context: RiskEvaluationContext,
    ) -> Optional[RiskFactor]:
        """Evaluate a single normalized signal in context to produce a RiskFactor.

        Must be deterministic, side-effect free, and perform no network or DB calls.
        Returns None if signal does not generate a risk factor.
        """
        pass


class RiskFactorRegistry:
    """Deterministic, provider-independent registry of risk factor evaluators."""

    def __init__(self) -> None:
        self._evaluators: Dict[str, BaseRiskFactorEvaluator] = {}
        self._domain_index: Dict[SignalDomain, Set[str]] = {d: set() for d in SignalDomain}

    def register(self, evaluator: BaseRiskFactorEvaluator, overwrite: bool = False) -> None:
        """Register a factor evaluator with duplicate registration protection."""
        eid = evaluator.evaluator_id.strip()
        if not eid:
            raise EvaluatorRegistrationError("Evaluator ID cannot be empty.")

        if eid in self._evaluators and not overwrite:
            raise EvaluatorRegistrationError(
                f"Evaluator with ID '{eid}' is already registered in RiskFactorRegistry."
            )

        self._evaluators[eid] = evaluator
        for domain in evaluator.target_domains:
            if domain not in self._domain_index:
                self._domain_index[domain] = set()
            self._domain_index[domain].add(eid)

        logger.debug("Registered risk factor evaluator %s for domains %s", eid, evaluator.target_domains)

    def unregister(self, evaluator_id: str) -> bool:
        """Unregister an evaluator by ID. Returns True if removed, False otherwise."""
        if evaluator_id not in self._evaluators:
            return False
        evaluator = self._evaluators.pop(evaluator_id)
        for domain in evaluator.target_domains:
            if domain in self._domain_index:
                self._domain_index[domain].discard(evaluator_id)
        return True

    def get_evaluator(self, evaluator_id: str) -> Optional[BaseRiskFactorEvaluator]:
        """Retrieve an evaluator by ID."""
        return self._evaluators.get(evaluator_id)

    def resolve_evaluators(
        self,
        domain: SignalDomain,
        signal_type: Optional[SignalType] = None,
    ) -> List[BaseRiskFactorEvaluator]:
        """Resolve applicable evaluators for a given domain and optional signal type deterministically."""
        candidate_ids = sorted(list(self._domain_index.get(domain, set())))
        matched: List[BaseRiskFactorEvaluator] = []
        for cid in candidate_ids:
            ev = self._evaluators[cid]
            if signal_type is not None and ev.supported_signal_types:
                if signal_type in ev.supported_signal_types:
                    matched.append(ev)
            else:
                matched.append(ev)
        return matched

    def list_evaluators(self) -> List[BaseRiskFactorEvaluator]:
        """List all registered evaluators in deterministic sorted order by evaluator_id."""
        return [self._evaluators[k] for k in sorted(self._evaluators.keys())]

    def clear(self) -> None:
        """Clear all registered evaluators."""
        self._evaluators.clear()
        self._domain_index = {d: set() for d in SignalDomain}


default_risk_factor_registry = RiskFactorRegistry()
