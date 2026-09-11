"""Scenario Agent execution and orchestration layer.

Coordinates ScenarioRequest validation, tenant boundary enforcement,
deterministic ScenarioGenerator invocation, and structured AgentFinding production.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.agents.contracts import AgentFinding, AgentLimitation
from app.agents.scenario.contract import (
    ScenarioDefinition,
    ScenarioRequest,
    ScenarioResult,
    ScenarioStatus,
)
from app.agents.scenario.errors import (
    InvalidScenarioRequestError,
    ScenarioTenantIsolationError,
)
from app.agents.scenario.generator import ScenarioGenerator


class ScenarioAgent:
    """Orchestration agent for deterministic scenario definition generation."""

    def __init__(self, generator: Optional[ScenarioGenerator] = None) -> None:
        self.generator = generator or ScenarioGenerator()

    def execute(self, request: ScenarioRequest) -> Tuple[ScenarioResult, List[AgentFinding]]:
        """Execute scenario definition and produce structured agent findings.

        Returns:
            Tuple of (ScenarioResult, List[AgentFinding])
        """
        if not request.organization_id or not request.organization_id.strip():
            raise InvalidScenarioRequestError("ScenarioRequest organization_id must be non-empty.")

        # 1. Execute deterministic generation
        result, limitations = ScenarioGenerator.generate(request)

        # 2. Output tenant validation
        if result.organization_id != request.organization_id:
            raise ScenarioTenantIsolationError(
                f"ScenarioResult organization '{result.organization_id}' does not match "
                f"request organization '{request.organization_id}'."
            )

        # 3. Produce structured AgentFinding records
        findings: List[AgentFinding] = []

        if result.status == ScenarioStatus.READY.value and result.scenario_definition is not None:
            definition = result.scenario_definition
            param_desc = ", ".join(f"{p.name}={p.value} {p.unit or ''}".strip() for p in definition.parameters)
            finding = AgentFinding(
                finding_id=f"find-scen-{definition.scenario_id[:8]}",
                category="SCENARIO_DEFINITION",
                title=f"What-If Scenario Defined: {definition.scenario_type.value}",
                summary=(
                    f"Constructed deterministic what-if scenario '{definition.scenario_id}' "
                    f"for target '{definition.target_reference}' with parameters: [{param_desc}]."
                ),
                severity="INFO",
                confidence=1.0,
                evidence_ids=result.evidence_references,
                source_references=[f"scenario:{definition.scenario_id}"],
                limitations=[lim.description for lim in limitations],
                created_by_node="scenario_agent",
            )
            findings.append(finding)

        elif result.status == ScenarioStatus.INSUFFICIENT_EVIDENCE.value:
            finding = AgentFinding(
                finding_id=f"find-scen-insuff-{result.scenario_id[:8]}",
                category="INSUFFICIENT_EVIDENCE",
                title="What-If Scenario: Insufficient Evidence",
                summary=(
                    "What-if scenario could not be computed because upstream prediction results "
                    "or explicit scenario parameters were absent."
                ),
                severity="LOW",
                confidence=1.0,
                evidence_ids=result.evidence_references,
                source_references=[],
                limitations=[lim.description for lim in limitations],
                created_by_node="scenario_agent",
            )
            findings.append(finding)

        return result, findings
