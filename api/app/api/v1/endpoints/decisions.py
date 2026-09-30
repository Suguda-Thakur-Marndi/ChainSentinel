"""FastAPI endpoints for RiskWise Decision Agent (Phase 15).

Provides authenticated REST APIs for:
- Formulating deterministic decision recommendations (POST /api/v1/decisions)
- Listing historical decision results for authenticated tenant (GET /api/v1/decisions)
- Retrieving specific decision result by ID (GET /api/v1/decisions/{decision_id})

Enforces:
- RBAC: generation requires Analyst, OpsManager, RiskManager, or Admin role; Viewers are read-only
- Strict multi-tenant isolation on all queries and operations
- Transactional persistence via UnitOfWork
- Fail-closed error handling
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.agents.contracts import AgentLimitation, LimitationCategory
from app.agents.decision.agent import DecisionAgent
from app.agents.decision.contract import (
    DecisionBasis,
    DecisionCandidate,
    DecisionConstraint,
    DecisionRationale,
    DecisionRequest,
    DecisionResult,
    DecisionStatus,
    DecisionType,
)
from app.agents.decision.errors import (
    DecisionAgentError,
    DecisionFreshnessError,
    DecisionInfeasibleError,
    DecisionInputValidationError,
    DecisionPolicyError,
    DecisionTenantIsolationError,
    InvalidDecisionCandidateError,
    InvalidDecisionRequestError,
)
from app.agents.decision.persistence import DecisionRepository
from app.api.deps import AuthenticatedContext, get_authenticated_context, require_role
from app.db.session import get_db
from app.db.unit_of_work import UnitOfWork, get_uow

logger = logging.getLogger("riskwise.api.decisions")

router = APIRouter()

READ_ROLES = ("Viewer", "Analyst", "OpsManager", "RiskManager", "Admin")
WRITE_ROLES = ("Analyst", "OpsManager", "RiskManager", "Admin")


@router.post(
    "/decisions",
    response_model=DecisionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Formulate decision recommendation",
    description=(
        "Synthesize authoritative risk, prediction, scenario, and optimization results "
        "to formulate a deterministic decision recommendation. Does NOT execute or approve action."
    ),
)
def create_decision(
    request: DecisionRequest,
    context: AuthenticatedContext = Depends(require_role(*WRITE_ROLES)),
    uow: UnitOfWork = Depends(get_uow),
) -> DecisionResult:
    """Execute deterministic Decision Agent policy and persist recommendation."""
    # Enforce request tenant matches authenticated context
    if request.organization_id != context.organization_id:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Tenant violation: request organization '{request.organization_id}' "
                f"does not match authenticated context '{context.organization_id}'."
            ),
        )

    try:
        agent = DecisionAgent()
        result, findings = agent.execute(request)

        # Persist decision to recommendations table
        DecisionRepository.save_decision(
            db=uow.session,
            result=result,
            request_id=getattr(context, "request_id", None),
            actor_id=context.user_id,
        )
        uow.commit()
        return result

    except DecisionTenantIsolationError as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except (InvalidDecisionRequestError, DecisionInputValidationError) as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (InvalidDecisionCandidateError, DecisionFreshnessError) as e:
        uow.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        uow.rollback()
        raise
    except Exception as e:
        uow.rollback()
        logger.exception("Decision formulation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Decision formulation failed: {str(e)}",
        )


def _normalize_legacy_decision_record(rec: Any) -> DecisionResult:
    """Normalize legacy Recommendation records into strongly-typed DecisionResult contracts.

    Backward-compatible fallback for recommendations created prior to Phase 15.
    Preserves all raw legacy attributes in provenance['legacy_data'].
    """
    raw = rec.expected_benefit_json if isinstance(rec.expected_benefit_json, dict) else {}
    decision_id = str(rec.id)
    org_id = str(rec.org_id or raw.get("organization_id") or "org_unknown")

    # 1. Map recommendation_type or fallback
    rec_type_raw = str(raw.get("recommendation_type") or "OPERATIONAL_REVIEW")
    try:
        dec_type = DecisionType(rec_type_raw)
    except ValueError:
        dec_type = DecisionType.OPERATIONAL_REVIEW

    # 2. Constraints normalization
    constraints: List[DecisionConstraint] = []
    for idx, c in enumerate(raw.get("constraints", [])):
        if isinstance(c, str):
            constraints.append(
                DecisionConstraint(
                    constraint_type="OPERATIONAL",
                    name=f"constraint_{idx + 1}",
                    value=c[:128],
                )
            )
        elif isinstance(c, dict):
            try:
                constraints.append(DecisionConstraint.model_validate(c))
            except Exception:
                pass

    # 3. Limitations normalization
    limitations: List[AgentLimitation] = []
    for idx, lim in enumerate(raw.get("limitations", [])):
        if isinstance(lim, str):
            limitations.append(
                AgentLimitation(
                    limitation_id=f"lim_{idx + 1}",
                    category=LimitationCategory.INSUFFICIENT_EVIDENCE,
                    description=lim[:4000],
                )
            )
        elif isinstance(lim, dict):
            try:
                limitations.append(AgentLimitation.model_validate(lim))
            except Exception:
                pass

    # 4. Formulate candidate
    title = str(getattr(rec, "title", None) or raw.get("title") or "Recommended Action")
    description = str(getattr(rec, "rationale", None) or raw.get("rationale") or title)
    candidate = DecisionCandidate(
        candidate_id=f"cand-{decision_id[:32]}",
        action_type=rec_type_raw[:64],
        title=title[:255],
        description=description[:2000],
        priority=str(raw.get("priority", "MEDIUM"))[:32],
        requires_human_approval=bool(raw.get("requires_human_approval", True)),
        parameters={"scope": raw.get("scope"), "scope_entity_id": raw.get("scope_entity_id")}
        if raw.get("scope")
        else {},
        provenance={"legacy_source": "recommendations_table"},
    )

    # 5. Rationale
    rationales: List[DecisionRationale] = []
    if description:
        rationales.append(
            DecisionRationale(
                basis_type=DecisionBasis.POLICY,
                rule_id="legacy_recommendation_policy",
                explanation_code=str(raw.get("expected_objective", "DETERMINISTIC_EVALUATION"))[:64],
                provenance={"rationale": description[:500]},
            )
        )

    # 6. Provenance preserving all raw legacy fields
    clean_raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    provenance = {
        "is_legacy_normalized": True,
        "legacy_recommendation_id": raw.get("recommendation_id", decision_id),
        "legacy_data": clean_raw,
    }

    eval_time = getattr(rec, "created_at", None)
    if not isinstance(eval_time, datetime):
        eval_time = datetime.now(timezone.utc)
    elif eval_time.tzinfo is None:
        eval_time = eval_time.replace(tzinfo=timezone.utc)

    rec_status = getattr(rec, "status", None)
    status_val = str(rec_status) if rec_status else DecisionStatus.REQUIRES_APPROVAL.value

    rec_conf = getattr(rec, "confidence", None)
    confidence_val = float(rec_conf) if rec_conf is not None else float(raw.get("confidence", 1.0))
    confidence_val = max(0.0, min(1.0, confidence_val))

    return DecisionResult(
        decision_id=decision_id,
        organization_id=org_id,
        decision_type=dec_type,
        status=status_val,
        candidates=[candidate],
        preferred_candidate=candidate,
        preferred_candidate_id=candidate.candidate_id,
        risk_assessment_id=raw.get("assessment_id"),
        rationales=rationales,
        constraints=constraints,
        limitations=limitations,
        requires_human_approval=bool(raw.get("requires_human_approval", True)),
        confidence=confidence_val,
        fingerprint=str(raw.get("fingerprint") or decision_id)[:64],
        provenance=provenance,
        evaluated_at=eval_time,
    )


@router.get(
    "/decisions",
    response_model=List[DecisionResult],
    status_code=status.HTTP_200_OK,
    summary="List decision recommendations",
    description="List historical decision recommendations formulated for the authenticated tenant.",
)
def list_decisions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> List[DecisionResult]:
    """List decision recommendations belonging to the authenticated tenant."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    try:
        records = DecisionRepository.list_by_organization(
            db=db,
            organization_id=org_id,
            limit=limit,
            offset=offset,
        )
        results: List[DecisionResult] = []
        for rec in records:
            if rec.expected_benefit_json and isinstance(rec.expected_benefit_json, dict):
                try:
                    res = DecisionResult.model_validate(rec.expected_benefit_json)
                    results.append(res)
                    continue
                except Exception as parse_err:
                    logger.debug("Decision record '%s' requires legacy normalization: %s", rec.id, parse_err)
            try:
                res = _normalize_legacy_decision_record(rec)
                results.append(res)
            except Exception as norm_err:
                logger.warning("Could not deserialize decision record '%s': %s", rec.id, norm_err)
        return results
    except DecisionTenantIsolationError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except Exception as e:
        logger.exception("Failed to list decisions: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list decisions: {str(e)}",
        )


@router.get(
    "/decisions/{decision_id}",
    response_model=DecisionResult,
    status_code=status.HTTP_200_OK,
    summary="Get decision recommendation by ID",
    description="Retrieve specific decision recommendation result by ID enforcing tenant isolation.",
)
def get_decision(
    decision_id: str,
    context: AuthenticatedContext = Depends(require_role(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> DecisionResult:
    """Retrieve a decision recommendation by ID."""
    org_id = context.organization_id or ""
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: organization context required",
        )
    try:
        rec = DecisionRepository.get_by_id(
            db=db,
            organization_id=org_id,
            decision_id=decision_id,
        )
        if not rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Decision '{decision_id}' not found.",
            )

        if not rec.expected_benefit_json or not isinstance(rec.expected_benefit_json, dict):
            try:
                return _normalize_legacy_decision_record(rec)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Decision payload for '{decision_id}' is empty or corrupt.",
                )

        try:
            return DecisionResult.model_validate(rec.expected_benefit_json)
        except Exception as parse_err:
            logger.info("Decision record '%s' requires legacy normalization: %s", decision_id, parse_err)
            try:
                return _normalize_legacy_decision_record(rec)
            except Exception as norm_err:
                logger.error("Failed to normalize legacy decision '%s': %s", decision_id, norm_err)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Decision payload for '{decision_id}' is invalid and could not be normalized: {str(norm_err)}",
                )

    except DecisionTenantIsolationError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get decision '%s': %s", decision_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get decision: {str(e)}",
        )
