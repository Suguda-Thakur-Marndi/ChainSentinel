# Phase 7 — Baseline Risk Scoring Architecture (Step 2)

> **IMPORTANT ARCHITECTURAL NOTICE**
> "This is a deterministic baseline risk model, not a calibrated probability model."

---

## 1. Scoring Architecture Overview

Phase 7 Step 2 establishes the first operational, deterministic risk-scoring algorithm for RiskWise 2.0.
Building directly upon the strongly typed contracts of Step 1 and the normalized signals of Phase 6, this baseline scoring engine translates complex supply chain disruptions into an explainable, auditable, and bounded composite score in the interval $[0.0, 100.0]$.

```
NormalizedRiskSignal (Phase 6)
            ↓
    Quality Gating & Tenant Isolation (Context)
            ↓
    Domain Factor Evaluators (9 Domains)
            ↓
    Factor Contribution Calculation (Bounded [0.0, 1.0])
            ↓
    Diminishing Marginal Compound Aggregation (Aggregator)
            ↓
    Categorical Risk Level Mapping (Thresholds)
            ↓
    Deterministic Narrative Explanation
            ↓
    RiskAssessment
```

---

## 2. Severity Mapping

External signal severities defined in Phase 6 (`EventSeverity`) map directly to deterministic baseline magnitudes:

| EventSeverity | Baseline Magnitude Weight | Default RiskLevel |
|---|---|---|
| `INFO` | `0.10` | `LOW` |
| `LOW` | `0.30` | `LOW` |
| `MEDIUM` | `0.60` | `MEDIUM` |
| `HIGH` | `0.85` | `HIGH` |
| `CRITICAL` | `1.00` | `CRITICAL` |

This mapping prevents arbitrary magic numbers and guarantees reproducible severity scaling across all domain evaluators.

---

## 3. Confidence Adjustment

Signal certainty is modeled through a bounded multiplicative factor $C \in [0.0, 1.0]$:
- If `signal.confidence` is present, it is bounded to $[0.0, 1.0]$.
- If `signal.confidence` is missing, it defaults to `0.80` (standard observational confidence).
- Confidence directly modulates the base severity magnitude:
  $$\text{effective\_magnitude} = \text{base\_severity} \times \text{confidence}$$

---

## 4. Quality Policy

Data quality from Phase 6 (`EventQuality`) directly controls factor eligibility:
- `EventQuality.VALID`: Evaluated at full weight ($\text{multiplier} = 1.00$).
- `EventQuality.PARTIAL`: Incurs an explicit, documented 20% completeness discount ($\text{multiplier} = 0.80$) due to missing coordinates or partial correlations.
- `EventQuality.INVALID`: Strictly yields zero contribution ($\text{multiplier} = 0.00$) and is rejected at the engine context boundary.

---

## 5. Source-Type Policy

Observation origin from Phase 6 (`EventSourceType`) is preserved and weighted according to observational reliability:
- `EventSourceType.REAL`: Physical observation / telemetry ($\text{multiplier} = 1.00$).
- `EventSourceType.ESTIMATED`: Extrapolated or modeled data ($\text{multiplier} = 0.90$).
- `EventSourceType.SIMULATED`: Synthetic scenario / simulation ($\text{multiplier} = 0.70$).

*Simulated signals are never deleted; their synthetic nature is disclosed in assessment metadata and explanation limitations.*

---

## 6. Conflict Handling

When Phase 6 flags `has_conflict = True` (indicating uncorroborated source disagreement):
- A documented 15% uncertainty penalty ($\text{multiplier} = 0.85$) is applied to the factor contribution.
- The conflict records are preserved in full and exposed in `assessment.explanation.unresolved_conflicts`.

---

## 7. Factor Contribution Formula

For any evaluated risk factor, its normalized contribution $c \in [0.0, 1.0]$ is computed as:

$$c = \text{round}\Big(\max\big(0.0, \min(1.0, \text{base\_severity} \times \text{confidence} \times Q \times S \times K)\big), 4\Big)$$

where:
- $\text{base\_severity} \in \{0.10, 0.30, 0.60, 0.85, 1.00\}$
- $\text{confidence} \in [0.0, 1.0]$
- $Q \in \{1.00, 0.80, 0.00\}$ (Quality multiplier)
- $S \in \{1.00, 0.90, 0.70\}$ (Source-type multiplier)
- $K \in \{0.85, 1.00\}$ (Conflict multiplier)

Each factor preserves this complete mathematical breakdown in its `metadata`.

---

## 8. 9 Domain Factor Evaluators

All evaluators implement the `BaseRiskFactorEvaluator` protocol and operate in a strictly provider-independent manner:

1. **`WeatherRiskFactorEvaluator`** (`WEATHER`):
   Evaluates storm warnings, cyclones, floods, extreme temperatures ($< -20^\circ\text{C}$ or $> 45^\circ\text{C}$), high winds ($\ge 60\text{ km/h}$), and alerts. Routine mild weather reports are ignored as benign.
2. **`RoadRiskFactorEvaluator`** (`ROAD`):
   Evaluates highway closures, major accidents, and congestion with delays $> 15\text{ mins}$. Free-flowing traffic updates with zero delay are ignored as benign.
3. **`PortRiskFactorEvaluator`** (`OCEAN`, `LOGISTICS`):
   Evaluates berth congestion, container terminal closures, and port delays $> 30\text{ mins}$. Open port status updates are ignored as benign.
4. **`MaritimeRiskFactorEvaluator`** (`OCEAN`):
   Evaluates vessel navigation warnings, maritime casualties, and abnormal vessel hazards. Routine AIS position tracking pings are classified as benign.
5. **`AirRiskFactorEvaluator`** (`AIR`):
   Evaluates flight cancellations, airport ground stops, and flight delays $> 30\text{ mins}$. Routine in-flight position updates are classified as benign.
6. **`RailRiskFactorEvaluator`** (`RAIL`):
   Evaluates track obstructions, rail delays $> 20\text{ mins}$, and train cancellations. On-time passage scans are ignored as benign.
7. **`LogisticsRiskFactorEvaluator`** (`LOGISTICS`):
   Evaluates package exceptions, customs holds, missed milestones, and transit delays $> 30\text{ mins}$. On-schedule milestone scans are ignored as benign.
8. **`IntelligenceRiskFactorEvaluator`** (`INTELLIGENCE`):
   Evaluates geopolitical events, border blockades, and labor strikes. Employs a conservative policy: general news articles with low severity are ignored as benign.
9. **`GeneralRiskFactorEvaluator`** (`GENERAL`):
   Safe fallback evaluator for unclassified supply chain anomalies with elevated severity.

---

## 9. Factor Aggregation Algorithm (Bounded Saturation)

To avoid uncontrolled simple addition that can exceed 100 or double-count identical signals:
1. Factors are sorted descending by contribution: $c_1 \ge c_2 \ge \dots \ge c_n$.
2. Primary factor establishes the initial baseline score:
   $$S_1 = 100.0 \times c_1$$
3. Each secondary factor $k \ge 2$ compounds into the remaining risk headroom $(100.0 - S_{k-1})$ with diminishing marginal weight:
   $$\Delta S_k = (100.0 - S_{k-1}) \times \left(c_k \times \frac{0.50}{1.0 + 0.20 \times (k - 1)}\right)$$
   $$S_k = S_{k-1} + \Delta S_k$$
4. Final score is bounded: $\text{score} = \text{round}(\min(100.0, \max(0.0, S_n)), 2)$.

**Mathematical Properties**:
- Empty factor set: $\text{score} = 0.0$.
- Single factor: $\text{score} = 100.0 \times c_1$.
- Multi-factor: Smoothly saturates towards $100.0$ without artificial clipping.

---

## 10. Risk Level Thresholds

Continuous scores map deterministically to categorical operational risk levels:

$$\text{RiskLevel} = \begin{cases}
\text{LOW} & 0.0 \le \text{score} < 30.0 \\
\text{MEDIUM} & 30.0 \le \text{score} < 60.0 \\
\text{HIGH} & 60.0 \le \text{score} < 85.0 \\
\text{CRITICAL} & 85.0 \le \text{score} \le 100.0
\end{cases}$$

---

## 11. Probability & Impact Policy

- **`probability`**: Strictly kept as `None`. The baseline score is an operational severity index, not a calibrated statistical probability. Writing $\text{probability} = \text{score} / 100$ is strictly prohibited.
- **`impact`**: Strictly kept as `None` unless an explicit operational/financial model is evaluated.
- **`confidence`**: Aggregate confidence reflects the minimum certainty across contributing factors: $\min_{f}(f.\text{confidence})$.

---

## 12. Evidence Lineage

Every risk factor retains an unbroken audit chain linking back to the raw external provider:
$$\text{RiskAssessment} \rightarrow \text{RiskFactor} \rightarrow \text{RiskEvidence} \rightarrow \text{NormalizedRiskSignal} \rightarrow \text{CanonicalExternalEvent} \rightarrow \text{RawEvent}$$

---

## 13. Deterministic Explanations (Zero LLM)

All narrative summaries and factor explanations are generated via deterministic, rule-based formatting:
- Cites overall score, categorical risk level, and top contributing factor.
- Details each factor's primary reason, delay magnitude, and evidence count.
- Discloses data caveats (simulations, missing fields) under `limitations`.
- Discloses uncorroborated source disputes under `unresolved_conflicts`.

---

## 14. Tenant Isolation

All context ingestion, factor evaluations, and score aggregations enforce strict organization boundary:
$$\text{signal.organization\_id} == \text{context.organization\_id}$$
Cross-tenant signals are rejected with `TenantMismatchError` (HTTP 403). Cross-tenant factor bleed is mathematically impossible.

---

## 15. Limitations & Future Extensions

- **Current Baseline**: Deterministic rule-based heuristic with diminishing compound aggregation.
- **Future Phase Extensions**:
  - Historical calibration and Bayesian likelihood estimation.
  - Multi-echelon graph propagation across suppliers and inventory routes.
  - ML-driven predictive disruption windows.
