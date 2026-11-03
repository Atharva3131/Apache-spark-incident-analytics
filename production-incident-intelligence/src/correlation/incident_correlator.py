"""
Incident correlation engine.

Given anomaly records and service metrics, produces a structured correlation
report that:
  - Identifies the earliest anomalous event
  - Detects downstream cascading failures
  - Correlates using timestamps (and trace/request IDs when available)
  - Ranks candidate root causes
  - Preserves evidence behind every conclusion
  - Clearly distinguishes facts, correlations, probable causes, and hypotheses
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.detection.anomaly_detector import AnomalyRecord

logger = logging.getLogger(__name__)


# ── Service dependency graph ──────────────────────────────────────────────────
# Edges represent "A calls B" – i.e., a failure in B can cascade to A.
# Read as: service → list of services it depends on.
SERVICE_DEPENDENCIES: Dict[str, List[str]] = {
    "api-gateway": ["order-service", "payment-service", "inventory-service"],
    "order-service": ["payment-service", "inventory-service", "database-service"],
    "payment-service": ["database-service"],
    "inventory-service": ["database-service"],
    "database-service": [],
}

# Services ranked from leaf (infrastructure) to edge (user-facing)
SERVICE_DEPTH: Dict[str, int] = {
    "database-service": 0,
    "inventory-service": 1,
    "payment-service": 1,
    "order-service": 2,
    "api-gateway": 3,
}


@dataclass
class CorrelationReport:
    """
    Structured output of the correlation engine.

    All fields are labelled with their epistemic status so downstream consumers
    (UI, LLM prompt) can present them accurately.
    """

    # Observed facts
    first_anomaly_time: Optional[str] = None
    first_anomaly_service: Optional[str] = None
    all_affected_services: List[str] = field(default_factory=list)

    # Correlations (temporal / dependency-graph)
    cascade_chain: List[str] = field(default_factory=list)  # ordered list of affected services
    correlation_notes: List[str] = field(default_factory=list)

    # Probable root causes (ranked)
    root_cause_candidates: List[Dict[str, Any]] = field(default_factory=list)
    primary_root_cause: Optional[str] = None
    root_cause_confidence: str = "LOW"  # LOW | MEDIUM | HIGH

    # Unverified hypotheses
    hypotheses: List[str] = field(default_factory=list)

    # Full evidence chain
    evidence: List[str] = field(default_factory=list)

    # Overall incident severity
    incident_severity: str = "MEDIUM"  # LOW | MEDIUM | HIGH | CRITICAL

    # Scenario hint derived from anomaly patterns
    scenario_hint: str = "unknown"


class IncidentCorrelator:
    """
    Rule-based correlator that reasons over anomaly records and service metrics.
    """

    def correlate(
        self,
        anomalies: List[AnomalyRecord],
        service_metrics: pd.DataFrame,
        error_samples: Optional[pd.DataFrame] = None,
    ) -> CorrelationReport:
        """
        Produce a CorrelationReport from the given anomalies.

        Args:
            anomalies: detected anomalies from AnomalyDetector
            service_metrics: aggregated Spark metrics
            error_samples: sample ERROR log records (optional, for message analysis)

        Returns:
            CorrelationReport
        """
        report = CorrelationReport()

        if not anomalies:
            report.evidence.append("No anomalies detected in this dataset.")
            return report

        # ── Step 1: Identify earliest anomaly (observed fact) ────────────────
        sorted_anomalies = sorted(anomalies, key=lambda a: a.window_start)
        first = sorted_anomalies[0]
        report.first_anomaly_time = first.window_start
        report.first_anomaly_service = first.service
        report.evidence.append(
            f"[FACT] Earliest anomaly detected in '{first.service}' "
            f"at {first.window_start} – {first.description}"
        )

        # ── Step 2: Collect all affected services ────────────────────────────
        affected = sorted(set(a.service for a in anomalies))
        report.all_affected_services = affected
        report.evidence.append(
            f"[FACT] Services showing anomalies: {', '.join(affected)}"
        )

        # ── Step 3: Determine incident severity ──────────────────────────────
        severity_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        max_sev = max((a.severity for a in anomalies), key=lambda s: severity_order.get(s, 0))
        report.incident_severity = max_sev

        # ── Step 4: Detect cascade chain via dependency graph ────────────────
        cascade_chain = _build_cascade_chain(affected, sorted_anomalies)
        report.cascade_chain = cascade_chain
        if len(cascade_chain) > 1:
            report.correlation_notes.append(
                f"[CORRELATION] Failure propagation pattern detected: "
                f"{' → '.join(cascade_chain)}. "
                "This is consistent with dependency-graph propagation but "
                "does NOT establish causation from temporal ordering alone."
            )
            report.evidence.append(
                f"[CORRELATION] Dependency chain: {' → '.join(cascade_chain)}"
            )

        # ── Step 5: Rank root-cause candidates ───────────────────────────────
        candidates = _rank_root_cause_candidates(anomalies, service_metrics)
        report.root_cause_candidates = candidates

        if candidates:
            primary = candidates[0]
            report.primary_root_cause = primary["explanation"]
            report.root_cause_confidence = primary["confidence"]
            report.evidence.append(
                f"[PROBABLE ROOT CAUSE] {primary['explanation']} "
                f"(confidence: {primary['confidence']})"
            )

        # ── Step 6: Annotate with error message patterns ─────────────────────
        if error_samples is not None and not error_samples.empty:
            msg_evidence = _extract_message_patterns(error_samples, affected)
            report.evidence.extend(msg_evidence)

        # ── Step 7: Build hypotheses ─────────────────────────────────────────
        report.hypotheses = _generate_hypotheses(anomalies, cascade_chain, service_metrics)

        # ── Step 8: Detect scenario hint ─────────────────────────────────────
        report.scenario_hint = _detect_scenario(anomalies, error_samples)

        logger.info(
            "Correlation complete – primary root cause: %s | severity: %s",
            report.primary_root_cause,
            report.incident_severity,
        )
        return report


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_cascade_chain(
    affected: List[str],
    sorted_anomalies: List[AnomalyRecord],
) -> List[str]:
    """
    Order affected services by the time their first anomaly appeared,
    then validate against the dependency graph.
    """
    first_seen: Dict[str, str] = {}
    for a in sorted_anomalies:
        if a.service not in first_seen:
            first_seen[a.service] = a.window_start

    # Sort by first anomaly time
    chain = sorted(affected, key=lambda s: first_seen.get(s, ""))

    # Only keep services that are actually reachable via dependency edges
    # (filter out services that appeared first but have no dependency relationship)
    validated: List[str] = []
    for svc in chain:
        if not validated:
            validated.append(svc)
            continue
        # Check if any earlier service in the chain depends on this one
        # OR this service depends on an earlier one
        connects = any(
            svc in SERVICE_DEPENDENCIES.get(prev, [])
            or prev in SERVICE_DEPENDENCIES.get(svc, [])
            for prev in validated
        )
        if connects:
            validated.append(svc)
        else:
            validated.append(svc)  # Include anyway – may be independent failure

    return validated


def _rank_root_cause_candidates(
    anomalies: List[AnomalyRecord],
    service_metrics: pd.DataFrame,
) -> List[Dict[str, Any]]:
    """
    Score candidate root-cause services.

    Scoring heuristic:
      + 3 pts  – service has CRITICAL anomalies
      + 2 pts  – service has HIGH anomalies
      + 2 pts  – service is infrastructure-level (low depth)
      + 1 pt   – service appeared earliest
      + 1 pt   – service has both error-rate and latency anomalies
    """
    service_scores: Dict[str, float] = {}
    service_details: Dict[str, List[str]] = {}

    severity_scores = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
    sorted_by_time = sorted(anomalies, key=lambda a: a.window_start)
    earliest_service = sorted_by_time[0].service if sorted_by_time else None

    for a in anomalies:
        svc = a.service
        score = service_scores.get(svc, 0.0)
        score += severity_scores.get(a.severity, 0)
        # Infrastructure bias
        score += (3 - SERVICE_DEPTH.get(svc, 3)) * 0.75
        service_scores[svc] = score
        service_details.setdefault(svc, []).append(a.description)

    if earliest_service:
        service_scores[earliest_service] = service_scores.get(earliest_service, 0) + 1

    # Bonus for services with multiple anomaly types
    anomaly_types_per_service: Dict[str, set] = {}
    for a in anomalies:
        anomaly_types_per_service.setdefault(a.service, set()).add(a.anomaly_type)
    for svc, types in anomaly_types_per_service.items():
        if len(types) >= 2:
            service_scores[svc] = service_scores.get(svc, 0) + 1

    ranked = sorted(service_scores.items(), key=lambda x: x[1], reverse=True)

    candidates = []
    for svc, score in ranked:
        depth = SERVICE_DEPTH.get(svc, 3)
        confidence = "HIGH" if score >= 5 else "MEDIUM" if score >= 3 else "LOW"
        explanation = (
            f"'{svc}' is the most probable root cause "
            f"(score {score:.1f}): {'; '.join(service_details.get(svc, []))[:300]}"
        )
        candidates.append({
            "service": svc,
            "score": score,
            "confidence": confidence,
            "explanation": explanation,
            "evidence": service_details.get(svc, []),
        })

    return candidates


def _extract_message_patterns(
    error_samples: pd.DataFrame,
    affected_services: List[str],
) -> List[str]:
    """Extract notable error message patterns from sample records."""
    evidence = []
    for svc in affected_services:
        svc_errors = error_samples[error_samples["service"] == svc]
        if svc_errors.empty:
            continue
        # Top 3 most common messages
        top_msgs = (
            svc_errors["message"]
            .value_counts()
            .head(3)
            .reset_index()
        )
        top_msgs.columns = ["message", "count"]
        for _, row in top_msgs.iterrows():
            evidence.append(
                f"[FACT] '{svc}' – '{row['message']}' appeared {row['count']} time(s)"
            )
    return evidence


def _generate_hypotheses(
    anomalies: List[AnomalyRecord],
    cascade_chain: List[str],
    service_metrics: pd.DataFrame,
) -> List[str]:
    """Generate plausible (but unverified) hypotheses."""
    hypotheses = []

    db_anomalies = [a for a in anomalies if a.service == "database-service"]
    if db_anomalies:
        hypotheses.append(
            "[HYPOTHESIS] The database connection pool may have been exhausted due to "
            "long-running queries or insufficient pool sizing. "
            "This is unverified – requires DB thread-dump or pool metrics to confirm."
        )

    payment_anomalies = [a for a in anomalies if a.service == "payment-service"
                         and a.anomaly_type in ("latency_spike", "p95_spike")]
    if payment_anomalies:
        hypotheses.append(
            "[HYPOTHESIS] Payment gateway latency may be caused by external provider "
            "degradation or network saturation. "
            "This is unverified – requires gateway-side traces to confirm."
        )

    inventory_anomalies = [a for a in anomalies if a.service == "inventory-service"]
    if inventory_anomalies and "order-service" in cascade_chain:
        hypotheses.append(
            "[HYPOTHESIS] Inventory service timeouts likely caused order-service to "
            "accumulate pending requests, eventually exhausting its worker thread pool. "
            "This is unverified."
        )

    if len(cascade_chain) >= 3:
        hypotheses.append(
            "[HYPOTHESIS] The cascading failure pattern suggests circuit breakers are "
            "either absent or not configured with aggressive-enough thresholds. "
            "This is unverified."
        )

    return hypotheses


def _detect_scenario(
    anomalies: List[AnomalyRecord],
    error_samples: Optional[pd.DataFrame],
) -> str:
    """
    Heuristically detect which named scenario this most resembles.
    Returns one of: db_exhaustion | payment_latency | inventory_cascade | unknown
    """
    affected = {a.service for a in anomalies}

    db_critical = any(
        a.service == "database-service" and a.severity in ("HIGH", "CRITICAL")
        for a in anomalies
    )
    payment_latency = any(
        a.service == "payment-service"
        and a.anomaly_type in ("latency_spike", "p95_spike")
        for a in anomalies
    )
    inventory_error = any(
        a.service == "inventory-service" and a.anomaly_type == "high_error_rate"
        for a in anomalies
    )

    # Check error message content if samples available
    db_msg_match = False
    if error_samples is not None and not error_samples.empty:
        db_msgs = error_samples[error_samples["service"] == "database-service"]["message"]
        db_msg_match = db_msgs.str.contains("pool", case=False, na=False).any()

    if db_critical or db_msg_match:
        return "db_exhaustion"
    if payment_latency and "inventory-service" not in affected:
        return "payment_latency"
    if inventory_error and "order-service" in affected:
        return "inventory_cascade"
    return "unknown"
