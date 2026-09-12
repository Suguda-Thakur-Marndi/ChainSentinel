"""Reusable Metric Engine for RiskWise 2.0 Evaluation & Quality Assurance (Phase 20).

Enforces strict determinism, sample count validation, reproducible calculations,
and returns status=NOT_AVAILABLE whenever sample count is insufficient (never fabricates metrics).
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from app.evaluation.contracts import (
    EvaluationDomain,
    EvaluationMetric,
    EvaluationScore,
    EvaluationStatus,
)


class MetricEngine:
    """Standardized deterministic quality metric engine."""

    @classmethod
    def compute_accuracy(
        cls,
        name: str,
        correct: int,
        total: int,
        domain: EvaluationDomain = EvaluationDomain.AGENT,
        dataset_version: str = "v1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Compute accuracy from raw correct count and total sample size."""
        if total < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                numerator=float(correct),
                denominator=float(total),
                sample_size=total,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
            )
        rate = correct / total if total > 0 else 0.0
        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rate, 4),
            numerator=float(correct),
            denominator=float(total),
            sample_size=total,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rate >= 1.0 else EvaluationStatus.FAILED,
        )

    @classmethod
    def compute_rate_metric(
        cls,
        name: str,
        numerator: float,
        denominator: float,
        domain: EvaluationDomain = EvaluationDomain.AGENT,
        dataset_version: str = "v1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Compute rate from numerator and denominator."""
        if denominator < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                numerator=float(numerator),
                denominator=float(denominator),
                sample_size=int(denominator),
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
            )
        rate = numerator / denominator if denominator > 0 else 0.0
        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rate, 4),
            numerator=float(numerator),
            denominator=float(denominator),
            sample_size=int(denominator),
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED,
        )

    @classmethod
    def compute_mae(
        cls,
        predictions: Sequence[float],
        actuals: Sequence[float],
        name: str = "MAE",
        domain: EvaluationDomain = EvaluationDomain.ML,
        dataset_version: str = "v1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        n = min(len(predictions), len(actuals))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_size=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
            )
        total_err = sum(abs(p - a) for p, a in zip(predictions, actuals))
        mae = total_err / n if n > 0 else 0.0
        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(mae, 4),
            numerator=float(total_err),
            denominator=float(n),
            sample_size=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if mae <= 3.0 else EvaluationStatus.FAILED,
        )

    @classmethod
    def compute_rmse(
        cls,
        predictions: Sequence[float],
        actuals: Sequence[float],
        name: str = "RMSE",
        domain: EvaluationDomain = EvaluationDomain.ML,
        dataset_version: str = "v1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        n = min(len(predictions), len(actuals))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_size=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
            )
        sq_err = sum((p - a) ** 2 for p, a in zip(predictions, actuals))
        rmse = math.sqrt(sq_err / n) if n > 0 else 0.0
        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rmse, 4),
            numerator=float(sq_err),
            denominator=float(n),
            sample_size=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rmse <= 4.0 else EvaluationStatus.FAILED,
        )


    # =========================================================================
    # 1. CLASSIFICATION & DECISION ACCURACY
    # =========================================================================

    @staticmethod
    def calculate_accuracy(
        actual: Sequence[Any],
        expected: Sequence[Any],
        name: str = "Accuracy",
        domain: EvaluationDomain = EvaluationDomain.AGENT,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate exact binary or multiclass match accuracy."""
        n = min(len(actual), len(expected))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                numerator=0.0,
                denominator=float(n),
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"reason": f"Sample count {n} below required minimum {min_samples}"},
            )

        correct = sum(1 for i in range(n) if actual[i] == expected[i])
        rate = correct / n if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rate, 4),
            numerator=float(correct),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rate >= 1.0 else EvaluationStatus.FAILED,
            config_summary={"correct_count": correct, "total_count": n},
        )

    # =========================================================================
    # 2. RETRIEVAL & RANKING (RAG)
    # =========================================================================

    @staticmethod
    def calculate_precision_at_k(
        retrieved_items: Sequence[str],
        relevant_items: Sequence[str],
        k: int = 5,
        name: str = "Precision@K",
        domain: EvaluationDomain = EvaluationDomain.RAG,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate Precision@K: (relevant items in top-k) / k."""
        k = max(1, k)
        top_k = retrieved_items[:k]
        if len(top_k) < min_samples:
            return EvaluationMetric(
                name=f"{name}:{k}",
                domain=domain,
                value=None,
                sample_count=len(top_k),
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"k": k, "reason": "Insufficient samples retrieved"},
            )

        relevant_set = set(relevant_items)
        hits = sum(1 for item in top_k if item in relevant_set)
        prec = hits / k

        return EvaluationMetric(
            name=f"{name}:{k}",
            domain=domain,
            value=round(prec, 4),
            numerator=float(hits),
            denominator=float(k),
            sample_count=len(top_k),
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if prec > 0.0 else EvaluationStatus.FAILED,
            config_summary={"k": k, "hits": hits, "relevant_count": len(relevant_set)},
        )

    @staticmethod
    def calculate_recall_at_k(
        retrieved_items: Sequence[str],
        relevant_items: Sequence[str],
        k: int = 5,
        name: str = "Recall@K",
        domain: EvaluationDomain = EvaluationDomain.RAG,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate Recall@K: (relevant items in top-k) / (total relevant items)."""
        k = max(1, k)
        if not relevant_items:
            return EvaluationMetric(
                name=f"{name}:{k}",
                domain=domain,
                value=None,
                sample_count=0,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"k": k, "reason": "No ground truth relevant items provided"},
            )

        top_k = retrieved_items[:k]
        relevant_set = set(relevant_items)
        hits = sum(1 for item in top_k if item in relevant_set)
        rec = hits / len(relevant_set)

        return EvaluationMetric(
            name=f"{name}:{k}",
            domain=domain,
            value=round(rec, 4),
            numerator=float(hits),
            denominator=float(len(relevant_set)),
            sample_count=len(top_k),
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rec >= 0.5 else EvaluationStatus.FAILED,
            config_summary={"k": k, "hits": hits, "relevant_count": len(relevant_set)},
        )

    @staticmethod
    def calculate_mrr(
        query_rankings: List[Tuple[Sequence[str], Sequence[str]]],
        name: str = "MRR",
        domain: EvaluationDomain = EvaluationDomain.RAG,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate Mean Reciprocal Rank (MRR) across multiple queries."""
        n = len(query_rankings)
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"reason": f"Queries evaluated {n} below required minimum {min_samples}"},
            )

        rr_sum = 0.0
        for retrieved, relevant in query_rankings:
            rel_set = set(relevant)
            rank = None
            for idx, item in enumerate(retrieved, start=1):
                if item in rel_set:
                    rank = idx
                    break
            if rank is not None:
                rr_sum += 1.0 / rank

        mrr = rr_sum / n if n > 0 else 0.0
        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(mrr, 4),
            numerator=round(rr_sum, 4),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if mrr >= 0.5 else EvaluationStatus.FAILED,
            config_summary={"queries_count": n},
        )

    # =========================================================================
    # 3. GROUNDING & CITATION INTEGRITY
    # =========================================================================

    @staticmethod
    def calculate_groundedness_rate(
        claims_with_support: Sequence[bool],
        name: str = "GroundednessRate",
        domain: EvaluationDomain = EvaluationDomain.RAG,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate percentage of claims verified with authoritative ground truth."""
        n = len(claims_with_support)
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"reason": "Insufficient claims evaluated"},
            )

        grounded = sum(1 for supported in claims_with_support if supported)
        rate = grounded / n if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rate, 4),
            numerator=float(grounded),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rate >= 0.9 else EvaluationStatus.FAILED,
            config_summary={"grounded_claims": grounded, "total_claims": n},
        )

    @staticmethod
    def calculate_citation_precision(
        cited_doc_ids: Sequence[str],
        verified_valid_doc_ids: Sequence[str],
        name: str = "CitationPrecision",
        domain: EvaluationDomain = EvaluationDomain.RAG,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
    ) -> EvaluationMetric:
        """Calculate fraction of citations that refer to valid, existent documents."""
        n = len(cited_doc_ids)
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"reason": "No citations provided to verify"},
            )

        valid_set = set(verified_valid_doc_ids)
        valid_citations = sum(1 for c in cited_doc_ids if c in valid_set)
        prec = valid_citations / n if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(prec, 4),
            numerator=float(valid_citations),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if prec >= 0.95 else EvaluationStatus.FAILED,
            config_summary={"valid_citations": valid_citations, "total_citations": n},
        )

    # =========================================================================
    # 4. MACHINE LEARNING REGRESSION (Phase 11 Delay Prediction)
    # =========================================================================

    @staticmethod
    def calculate_mae(
        y_true: Sequence[float],
        y_pred: Sequence[float],
        name: str = "MAE",
        domain: EvaluationDomain = EvaluationDomain.ML,
        dataset_version: str = "1.0.0",
        min_samples: int = 5,
        threshold: float = 30.0,
    ) -> EvaluationMetric:
        """Calculate Mean Absolute Error with strict minimum sample enforcement."""
        n = min(len(y_true), len(y_pred))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"min_samples": min_samples, "actual_samples": n},
            )

        error_sum = sum(abs(y_true[i] - y_pred[i]) for i in range(n))
        mae = error_sum / n if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(mae, 4),
            numerator=round(error_sum, 4),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if mae <= threshold else EvaluationStatus.FAILED,
            config_summary={"threshold": threshold, "unit": "minutes"},
        )

    @staticmethod
    def calculate_rmse(
        y_true: Sequence[float],
        y_pred: Sequence[float],
        name: str = "RMSE",
        domain: EvaluationDomain = EvaluationDomain.ML,
        dataset_version: str = "1.0.0",
        min_samples: int = 5,
        threshold: float = 45.0,
    ) -> EvaluationMetric:
        """Calculate Root Mean Squared Error with strict minimum sample enforcement."""
        n = min(len(y_true), len(y_pred))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"min_samples": min_samples, "actual_samples": n},
            )

        sq_sum = sum((y_true[i] - y_pred[i]) ** 2 for i in range(n))
        rmse = math.sqrt(sq_sum / n) if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rmse, 4),
            numerator=round(sq_sum, 4),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rmse <= threshold else EvaluationStatus.FAILED,
            config_summary={"threshold": threshold, "unit": "minutes"},
        )

    @staticmethod
    def calculate_r2(
        y_true: Sequence[float],
        y_pred: Sequence[float],
        name: str = "R2",
        domain: EvaluationDomain = EvaluationDomain.ML,
        dataset_version: str = "1.0.0",
        min_samples: int = 5,
    ) -> EvaluationMetric:
        """Calculate R² (coefficient of determination)."""
        n = min(len(y_true), len(y_pred))
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"min_samples": min_samples, "actual_samples": n},
            )

        mean_y = sum(y_true[:n]) / n
        ss_tot = sum((y_true[i] - mean_y) ** 2 for i in range(n))
        if ss_tot == 0.0:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=1.0 if all(y_pred[i] == y_true[i] for i in range(n)) else 0.0,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.PASSED,
                config_summary={"note": "Variance of y_true is 0"},
            )

        ss_res = sum((y_true[i] - y_pred[i]) ** 2 for i in range(n))
        r2 = 1.0 - (ss_res / ss_tot)

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(r2, 4),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if r2 >= 0.3 else EvaluationStatus.FAILED,
            config_summary={"ss_tot": ss_tot, "ss_res": ss_res},
        )

    # =========================================================================
    # 5. GOVERNANCE & OPERATIONS (Idempotency, Constraint Satisfaction)
    # =========================================================================

    @staticmethod
    def calculate_rate_metric(
        success_conditions: Sequence[bool],
        name: str,
        domain: EvaluationDomain,
        dataset_version: str = "1.0.0",
        min_samples: int = 1,
        target_rate: float = 1.0,
    ) -> EvaluationMetric:
        """Generic rate computation for governance invariants (e.g. Idempotency, RBAC)."""
        n = len(success_conditions)
        if n < min_samples:
            return EvaluationMetric(
                name=name,
                domain=domain,
                value=None,
                sample_count=n,
                dataset_version=dataset_version,
                status=EvaluationStatus.NOT_AVAILABLE,
                config_summary={"min_samples": min_samples, "actual_samples": n},
            )

        success_count = sum(1 for c in success_conditions if c)
        rate = success_count / n if n > 0 else 0.0

        return EvaluationMetric(
            name=name,
            domain=domain,
            value=round(rate, 4),
            numerator=float(success_count),
            denominator=float(n),
            sample_count=n,
            dataset_version=dataset_version,
            status=EvaluationStatus.PASSED if rate >= target_rate else EvaluationStatus.FAILED,
            config_summary={"target_rate": target_rate, "successes": success_count, "total": n},
        )

    # =========================================================================
    # 6. DOMAIN SCORE AGGREGATION
    # =========================================================================

    @staticmethod
    def aggregate_domain_score(
        domain: EvaluationDomain,
        metrics: List[EvaluationMetric],
        weights: Optional[Dict[str, float]] = None,
        min_metrics: int = 1,
    ) -> EvaluationScore:
        """Aggregate domain score using defined weights, strictly separating domains."""
        domain_metrics = [m for m in metrics if m.domain == domain and m.value is not None]
        if len(domain_metrics) < min_metrics:
            return EvaluationScore(
                domain=domain,
                score_value=None,
                status=EvaluationStatus.NOT_AVAILABLE,
                metric_count=len(domain_metrics),
                summary=f"Insufficient valid metrics in domain {domain.value} (need {min_metrics})",
            )

        total_weight = 0.0
        weighted_sum = 0.0
        default_weight = 1.0

        for m in domain_metrics:
            w = weights.get(m.name, default_weight) if weights else default_weight
            total_weight += w
            # Normalize to 0.0 - 1.0 if metric is a rate or bounded
            norm_val = m.value
            if norm_val > 1.0:
                # If error metric like MAE/RMSE, lower is better; clamp to 0-1
                norm_val = max(0.0, min(1.0, 1.0 / (1.0 + (norm_val / 30.0))))
            elif norm_val < 0.0:
                norm_val = 0.0
            weighted_sum += norm_val * w

        score = weighted_sum / total_weight if total_weight > 0 else 0.0
        has_failed = any(m.status == EvaluationStatus.FAILED for m in domain_metrics)

        return EvaluationScore(
            domain=domain,
            score_value=round(score, 4),
            status=EvaluationStatus.FAILED if has_failed else EvaluationStatus.PASSED,
            metric_count=len(domain_metrics),
            weights_applied=weights or {},
            summary=f"Aggregated {len(domain_metrics)} metrics for {domain.value}: {round(score * 100, 1)}%",
        )
