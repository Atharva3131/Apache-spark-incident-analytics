"""
Unit tests for incident correlation.
"""

import pytest
import pandas as pd
from datetime import datetime
from src.correlation.incident_correlator import IncidentCorrelator
from src.detection.anomaly_detector import AnomalyRecord


class TestIncidentCorrelator:
    """Test suite for IncidentCorrelator."""

    @pytest.fixture
    def correlator(self):
        return IncidentCorrelator()

    @pytest.fixture
    def sample_metrics(self):
        return pd.DataFrame([
            {
                "service": "database-service",
                "window_start": "2024-01-01T10:00:00",
                "window_end": "2024-01-01T10:05:00",
                "error_rate": 0.50,
                "avg_latency_ms": 5000.0,
            },
            {
                "service": "order-service",
                "window_start": "2024-01-01T10:01:00",
                "window_end": "2024-01-01T10:06:00",
                "error_rate": 0.30,
                "avg_latency_ms": 3000.0,
            },
        ])

    def test_correlator_init(self):
        """Test correlator initialization."""
        correlator = IncidentCorrelator()
        assert correlator is not None

    def test_empty_anomalies(self, correlator, sample_metrics):
        """Test handling of empty anomaly list."""
        report = correlator.correlate([], sample_metrics)

        assert report.first_anomaly_service is None
        assert len(report.all_affected_services) == 0

    def test_single_anomaly_correlation(self, correlator, sample_metrics):
        """Test correlation of a single anomaly."""
        anomalies = [
            AnomalyRecord(
                service="database-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="high_error_rate",
                observed_value=50.0,
                threshold_value=10.0,
                description="DB error rate too high",
                severity="CRITICAL",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)

        assert report.first_anomaly_service == "database-service"
        assert "database-service" in report.all_affected_services
        assert report.incident_severity == "CRITICAL"

    def test_cascade_detection(self, correlator, sample_metrics):
        """Test detection of cascading failures."""
        anomalies = [
            AnomalyRecord(
                service="database-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="high_error_rate",
                observed_value=50.0,
                threshold_value=10.0,
                description="DB error",
                severity="CRITICAL",
            ),
            AnomalyRecord(
                service="order-service",
                window_start="2024-01-01T10:01:00",
                window_end="2024-01-01T10:06:00",
                anomaly_type="high_error_rate",
                observed_value=30.0,
                threshold_value=10.0,
                description="Order errors",
                severity="HIGH",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)

        # Should detect both services
        assert "database-service" in report.all_affected_services
        assert "order-service" in report.all_affected_services

        # Should identify cascade chain
        assert len(report.cascade_chain) > 0

    def test_root_cause_ranking(self, correlator, sample_metrics):
        """Test root cause candidate ranking."""
        anomalies = [
            AnomalyRecord(
                service="database-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="high_error_rate",
                observed_value=50.0,
                threshold_value=10.0,
                description="Critical DB error",
                severity="CRITICAL",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)

        assert len(report.root_cause_candidates) > 0
        assert report.root_cause_candidates[0]["service"] == "database-service"

    def test_evidence_preservation(self, correlator, sample_metrics):
        """Test that evidence is preserved in correlation report."""
        anomalies = [
            AnomalyRecord(
                service="payment-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="latency_spike",
                observed_value=5000.0,
                threshold_value=2000.0,
                description="Payment latency too high",
                severity="HIGH",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)

        assert len(report.evidence) > 0
        assert any("[FACT]" in e or "[CORRELATION]" in e for e in report.evidence)

    def test_hypothesis_generation(self, correlator, sample_metrics):
        """Test that hypotheses are generated."""
        anomalies = [
            AnomalyRecord(
                service="database-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="high_error_rate",
                observed_value=50.0,
                threshold_value=10.0,
                description="DB errors",
                severity="CRITICAL",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)

        assert len(report.hypotheses) > 0
        assert all("[HYPOTHESIS]" in h for h in report.hypotheses)

    def test_scenario_detection(self, correlator, sample_metrics):
        """Test scenario hinting."""
        # DB exhaustion scenario
        anomalies = [
            AnomalyRecord(
                service="database-service",
                window_start="2024-01-01T10:00:00",
                window_end="2024-01-01T10:05:00",
                anomaly_type="high_error_rate",
                observed_value=50.0,
                threshold_value=10.0,
                description="DB connection pool exhausted",
                severity="CRITICAL",
            ),
        ]

        report = correlator.correlate(anomalies, sample_metrics)
        assert report.scenario_hint in ("db_exhaustion", "unknown")
