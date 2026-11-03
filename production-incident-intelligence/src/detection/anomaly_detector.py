"""
Anomaly detection engine.

Works on the Pandas DataFrames produced by SparkProcessor and applies
configurable threshold-based rules to flag anomalous service windows.

Deliberately avoids statistical models that would require calibration data –
this keeps the MVP deterministic and explainable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class AnomalyThresholds:
    error_rate_threshold: float = 0.10        # 10 % error rate
    latency_spike_threshold_ms: float = 2000  # avg latency above 2 s
    p95_latency_threshold_ms: float = 5000    # p95 latency above 5 s
    min_error_count: int = 5                  # at least N errors to flag


@dataclass
class AnomalyRecord:
    service: str
    window_start: str
    window_end: str
    anomaly_type: str          # "high_error_rate" | "latency_spike" | "p95_spike"
    observed_value: float
    threshold_value: float
    description: str
    severity: str = "MEDIUM"   # LOW | MEDIUM | HIGH | CRITICAL


class AnomalyDetector:
    """
    Rule-based anomaly detector that operates on aggregated service metrics.
    """

    def __init__(self, thresholds: Optional[AnomalyThresholds] = None):
        self._t = thresholds or AnomalyThresholds()

    def detect(self, service_metrics: pd.DataFrame) -> List[AnomalyRecord]:
        """
        Evaluate each service/window row against the configured thresholds.

        Args:
            service_metrics: output of SparkProcessor.compute_service_metrics()

        Returns:
            List of AnomalyRecord; empty if nothing anomalous found.
        """
        anomalies: List[AnomalyRecord] = []

        if service_metrics.empty:
            logger.warning("service_metrics DataFrame is empty – nothing to detect")
            return anomalies

        for _, row in service_metrics.iterrows():
            service = str(row.get("service", "unknown"))
            w_start = str(row.get("window_start", ""))
            w_end = str(row.get("window_end", ""))
            error_count = int(row.get("error_count", 0) or 0)
            error_rate = float(row.get("error_rate", 0.0) or 0.0)
            avg_lat = float(row.get("avg_latency_ms", 0.0) or 0.0)
            p95_lat = float(row.get("p95_latency_ms", 0.0) or 0.0)

            # ── Rule 1: High error rate ────────────────────────────────────
            if (error_rate >= self._t.error_rate_threshold
                    and error_count >= self._t.min_error_count):
                severity = _error_rate_severity(error_rate)
                anomalies.append(AnomalyRecord(
                    service=service,
                    window_start=w_start,
                    window_end=w_end,
                    anomaly_type="high_error_rate",
                    observed_value=round(error_rate * 100, 2),
                    threshold_value=self._t.error_rate_threshold * 100,
                    description=(
                        f"{service}: error rate {error_rate * 100:.1f}% "
                        f"({error_count} errors) exceeds threshold "
                        f"{self._t.error_rate_threshold * 100:.0f}%"
                    ),
                    severity=severity,
                ))

            # ── Rule 2: Average latency spike ─────────────────────────────
            if avg_lat >= self._t.latency_spike_threshold_ms:
                severity = _latency_severity(avg_lat)
                anomalies.append(AnomalyRecord(
                    service=service,
                    window_start=w_start,
                    window_end=w_end,
                    anomaly_type="latency_spike",
                    observed_value=round(avg_lat, 1),
                    threshold_value=self._t.latency_spike_threshold_ms,
                    description=(
                        f"{service}: avg latency {avg_lat:.0f} ms exceeds "
                        f"threshold {self._t.latency_spike_threshold_ms:.0f} ms"
                    ),
                    severity=severity,
                ))

            # ── Rule 3: p95 latency spike ─────────────────────────────────
            if p95_lat >= self._t.p95_latency_threshold_ms:
                severity = _latency_severity(p95_lat)
                anomalies.append(AnomalyRecord(
                    service=service,
                    window_start=w_start,
                    window_end=w_end,
                    anomaly_type="p95_spike",
                    observed_value=round(p95_lat, 1),
                    threshold_value=self._t.p95_latency_threshold_ms,
                    description=(
                        f"{service}: p95 latency {p95_lat:.0f} ms exceeds "
                        f"threshold {self._t.p95_latency_threshold_ms:.0f} ms"
                    ),
                    severity=severity,
                ))

        logger.info("Anomaly detection complete – %d anomalies found", len(anomalies))
        return anomalies

    def to_dataframe(self, anomalies: List[AnomalyRecord]) -> pd.DataFrame:
        """Convert a list of AnomalyRecords to a Pandas DataFrame."""
        if not anomalies:
            return pd.DataFrame(columns=[
                "service", "window_start", "window_end",
                "anomaly_type", "observed_value", "threshold_value",
                "description", "severity",
            ])
        return pd.DataFrame([
            {
                "service": a.service,
                "window_start": a.window_start,
                "window_end": a.window_end,
                "anomaly_type": a.anomaly_type,
                "observed_value": a.observed_value,
                "threshold_value": a.threshold_value,
                "description": a.description,
                "severity": a.severity,
            }
            for a in anomalies
        ])

    def summarise_by_service(self, anomalies: List[AnomalyRecord]) -> Dict[str, Any]:
        """
        Return a dict mapping service name → list of anomaly descriptions.
        Useful for building LLM prompts without passing raw DataFrames.
        """
        summary: Dict[str, List[str]] = {}
        for a in anomalies:
            summary.setdefault(a.service, []).append(a.description)
        return summary


# ── Severity helpers ──────────────────────────────────────────────────────────

def _error_rate_severity(rate: float) -> str:
    if rate >= 0.50:
        return "CRITICAL"
    if rate >= 0.25:
        return "HIGH"
    if rate >= 0.10:
        return "MEDIUM"
    return "LOW"


def _latency_severity(latency_ms: float) -> str:
    if latency_ms >= 10000:
        return "CRITICAL"
    if latency_ms >= 5000:
        return "HIGH"
    if latency_ms >= 2000:
        return "MEDIUM"
    return "LOW"
