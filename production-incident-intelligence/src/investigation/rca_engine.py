"""
Root Cause Analysis (RCA) engine – deterministic fallback.

When Sarvam API is unavailable or unconfigured, this engine produces
a structured RCA response using the correlation report and metrics.

The output follows the same schema as Sarvam so the UI never knows the difference.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.correlation.incident_correlator import CorrelationReport
from src.models.incident import RCAResponse, Severity, TimelineEvent

logger = logging.getLogger(__name__)


class DeterministicRCAEngine:
    """
    Produces RCA responses entirely from data – no external API calls.
    """

    def generate_report(
        self,
        correlation: CorrelationReport,
        service_metrics: pd.DataFrame,
        error_samples: Optional[pd.DataFrame] = None,
    ) -> RCAResponse:
        """
        Convert a CorrelationReport into a structured RCAResponse.

        Args:
            correlation: output from IncidentCorrelator
            service_metrics: Spark-processed aggregated metrics
            error_samples: optional sample ERROR records

        Returns:
            RCAResponse ready for storage/display
        """

        # Build title
        title = _build_title(correlation)

        # Map severity
        severity = Severity(correlation.incident_severity)

        # Build summary
        summary = _build_summary(correlation)

        # Extract probable root cause
        probable_root_cause = (
            correlation.primary_root_cause
            or "Unable to determine – requires further investigation"
        )

        # Supporting evidence from correlation report
        supporting_evidence = correlation.evidence[:15]  # Cap at 15

        # Affected services
        affected = correlation.all_affected_services

        # Timeline
        timeline = _build_timeline(correlation, service_metrics)

        # Recommended actions
        recommended = _build_recommendations(correlation, service_metrics)

        # Uncertainties / hypotheses
        uncertainties = correlation.hypotheses

        return RCAResponse(
            incident_title=title,
            severity=severity,
            summary=summary,
            probable_root_cause=probable_root_cause,
            supporting_evidence=supporting_evidence,
            affected_services=affected,
            timeline=timeline,
            recommended_actions=recommended,
            uncertainties=uncertainties,
            generated_by="deterministic_engine",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_title(correlation: CorrelationReport) -> str:
    """Generate a concise incident title."""
    if correlation.scenario_hint == "db_exhaustion":
        return "Database Connection Pool Exhaustion"
    if correlation.scenario_hint == "payment_latency":
        return "Payment Service Latency Spike"
    if correlation.scenario_hint == "inventory_cascade":
        return "Inventory Service Timeout – Cascading Failure"

    if len(correlation.all_affected_services) == 1:
        svc = correlation.all_affected_services[0]
        return f"Incident in {svc}"

    return f"Multi-service incident ({len(correlation.all_affected_services)} services affected)"


def _build_summary(correlation: CorrelationReport) -> str:
    """Build a human-readable incident summary."""
    parts = []

    if correlation.first_anomaly_time and correlation.first_anomaly_service:
        parts.append(
            f"Incident began at {correlation.first_anomaly_time} in {correlation.first_anomaly_service}."
        )

    if len(correlation.all_affected_services) > 1:
        parts.append(
            f"Cascading failures detected across {len(correlation.all_affected_services)} services: "
            f"{', '.join(correlation.all_affected_services)}."
        )

    if correlation.cascade_chain:
        parts.append(
            f"Failure propagation chain: {' → '.join(correlation.cascade_chain)}."
        )

    if correlation.root_cause_confidence in ("HIGH", "MEDIUM"):
        parts.append(
            f"Root cause confidence: {correlation.root_cause_confidence}."
        )

    if not parts:
        parts.append("A multi-service incident was detected.")

    return " ".join(parts)


def _build_timeline(
    correlation: CorrelationReport,
    service_metrics: pd.DataFrame,
) -> List[TimelineEvent]:
    """Build an ordered incident timeline."""
    events: List[TimelineEvent] = []

    # Add first anomaly
    if correlation.first_anomaly_time and correlation.first_anomaly_service:
        try:
            ts = datetime.fromisoformat(correlation.first_anomaly_time)
        except (ValueError, TypeError):
            ts = datetime.utcnow()
        events.append(TimelineEvent(
            timestamp=ts,
            service=correlation.first_anomaly_service,
            event_type="anomaly_detected",
            description="First anomaly detected – likely root cause or trigger",
            severity=Severity.HIGH,
        ))

    # Add cascade events
    if len(correlation.cascade_chain) > 1:
        for i, svc in enumerate(correlation.cascade_chain[1:], 1):
            try:
                first_time = correlation.first_anomaly_time or "unknown"
                ts = datetime.fromisoformat(first_time) if first_time != "unknown" else datetime.utcnow()
            except (ValueError, TypeError):
                ts = datetime.utcnow()
            events.append(TimelineEvent(
                timestamp=ts,
                service=svc,
                event_type="cascade",
                description=f"Cascading failure propagated from upstream ({i} hops)",
                severity=Severity.MEDIUM,
            ))

    # Add root-cause event
    if correlation.primary_root_cause:
        events.append(TimelineEvent(
            timestamp=datetime.utcnow(),
            service=correlation.first_anomaly_service or "unknown",
            event_type="root_cause_identified",
            description=correlation.primary_root_cause,
            severity=Severity.HIGH,
        ))

    return events


def _build_recommendations(
    correlation: CorrelationReport,
    service_metrics: pd.DataFrame,
) -> List[str]:
    """Generate remediation recommendations based on root cause."""
    recommendations = []

    primary = (
        correlation.root_cause_candidates[0]["service"]
        if correlation.root_cause_candidates
        else correlation.first_anomaly_service
    )

    # Generic recommendations
    if primary == "database-service":
        recommendations.extend([
            "Increase database connection pool size or add connection pooling proxy (PgBouncer, ProxySQL).",
            "Identify and terminate long-running queries or add query timeouts.",
            "Scale database replicas if read-heavy workload.",
            "Monitor replication lag to prevent consistency issues.",
        ])
    elif primary == "payment-service":
        recommendations.extend([
            "Check external payment gateway status and response times.",
            "Implement circuit breaker if not present; set aggressive timeout (e.g., 5s).",
            "Add request queuing to smooth traffic spikes.",
            "Consider caching frequently-used gateway responses.",
        ])
    elif primary == "inventory-service":
        recommendations.extend([
            "Reduce database query timeout or add query caching.",
            "Implement distributed locking mechanism to prevent lock contention.",
            "Scale inventory service horizontally if CPU/memory bound.",
            "Add circuit breaker to prevent cascading timeouts.",
        ])
    elif primary == "order-service":
        recommendations.extend([
            "Review order processing logic for inefficiencies.",
            "Implement bulkheads / thread pool isolation per downstream service.",
            "Add comprehensive request timeout configuration.",
        ])
    elif primary == "api-gateway":
        recommendations.extend([
            "Implement rate limiting and backpressure handling.",
            "Add circuit breaker for each upstream service.",
            "Monitor gateway resource utilisation (CPU, memory, file descriptors).",
        ])

    # Universal recommendations
    recommendations.extend([
        "Enable detailed distributed tracing (e.g., Jaeger) to correlate failures across services.",
        "Set up alerting for error rates, latency percentiles, and resource saturation.",
        "Document runbook for this incident type and train on-call team.",
        "Consider chaos engineering exercises to validate resilience assumptions.",
    ])

    return recommendations


# ── Standalone helper ─────────────────────────────────────────────────────────

def generate_deterministic_rca(
    correlation: CorrelationReport,
    service_metrics: pd.DataFrame,
    error_samples: Optional[pd.DataFrame] = None,
) -> RCAResponse:
    """
    Convenience function – creates an engine and generates a report in one call.
    """
    engine = DeterministicRCAEngine()
    return engine.generate_report(correlation, service_metrics, error_samples)
