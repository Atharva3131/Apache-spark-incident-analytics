"""
Unit tests for anomaly detection.
"""

import pytest
import pandas as pd
from src.detection.anomaly_detector import (
    AnomalyDetector,
    AnomalyThresholds,
    AnomalyRecord,
)


class TestAnomalyDetector:
    """Test suite for AnomalyDetector."""

    @pytest.fixture
    def detector(self):
        thresholds = AnomalyThresholds(
            error_rate_threshold=0.10,
            latency_spike_threshold_ms=2000,
            p95_latency_threshold_ms=5000,
            min_error_count=5,
        )
        return AnomalyDetector(thresholds)

    @pytest.fixture
    def sample_metrics_clean(self):
        """Create sample metrics DataFrame with no anomalies."""
        return pd.DataFrame([
            {
                "service": "order-service",
                "window_start": "2024-01-01T10:00:00",
                "window_end": "2024-01-01T10:05:00",
                "total_logs": 1000,
                "error_count": 5,
                "error_rate": 0.005,
                "avg_latency_ms": 150.0,
                "p95_latency_ms": 300.0,
                "p99_latency_ms": 400.0,
            },
            {
                "service": "payment-service",
                "window_start": "2024-01-01T10:00:00",
                "window_end": "2024-01-01T10:05:00",
                "total_logs": 500,
                "error_count": 2,
                "error_rate": 0.004,
                "avg_latency_ms": 200.0,
                "p95_latency_ms": 500.0,
                "p99_latency_ms": 600.0,
            },
        ])

    @pytest.fixture
    def sample_metrics_anomalous(self):
        """Create sample metrics DataFrame with anomalies."""
        return pd.DataFrame([
            {
                "service": "database-service",
                "window_start": "2024-01-01T10:00:00",
                "window_end": "2024-01-01T10:05:00",
                "total_logs": 100,
                "error_count": 50,
                "error_rate": 0.50,
                "avg_latency_ms": 5000.0,
                "p95_latency_ms": 8000.0,
                "p99_latency_ms": 9000.0,
            },
        ])

    def test_detector_init(self):
        """Test detector initialization."""
        detector = AnomalyDetector()
        assert detector is not None

    def test_no_anomalies_in_clean_data(self, detector, sample_metrics_clean):
        """Test that clean data produces no anomalies."""
        anomalies = detector.detect(sample_metrics_clean)
        assert len(anomalies) == 0, "Clean data should produce no anomalies"

    def test_high_error_rate_detection(self, detector, sample_metrics_anomalous):
        """Test detection of high error rate."""
        anomalies = detector.detect(sample_metrics_anomalous)

        error_rate_anomalies = [a for a in anomalies if a.anomaly_type == "high_error_rate"]
        assert len(error_rate_anomalies) > 0, "Should detect high error rate"

    def test_latency_spike_detection(self, detector, sample_metrics_anomalous):
        """Test detection of latency spike."""
        anomalies = detector.detect(sample_metrics_anomalous)

        latency_anomalies = [a for a in anomalies if a.anomaly_type == "latency_spike"]
        assert len(latency_anomalies) > 0, "Should detect latency spike"

    def test_p95_latency_detection(self, detector, sample_metrics_anomalous):
        """Test detection of p95 latency spike."""
        anomalies = detector.detect(sample_metrics_anomalous)

        p95_anomalies = [a for a in anomalies if a.anomaly_type == "p95_spike"]
        assert len(p95_anomalies) > 0, "Should detect p95 spike"

    def test_anomaly_record_dataframe_conversion(self, detector, sample_metrics_anomalous):
        """Test conversion of anomalies to DataFrame."""
        anomalies = detector.detect(sample_metrics_anomalous)
        df = detector.to_dataframe(anomalies)

        assert len(df) == len(anomalies)
        assert "service" in df.columns
        assert "anomaly_type" in df.columns
        assert "severity" in df.columns

    def test_anomaly_summary_by_service(self, detector, sample_metrics_anomalous):
        """Test summary generation by service."""
        anomalies = detector.detect(sample_metrics_anomalous)
        summary = detector.summarise_by_service(anomalies)

        assert "database-service" in summary
        assert len(summary["database-service"]) > 0

    def test_empty_dataframe_handling(self, detector):
        """Test that empty DataFrames are handled gracefully."""
        empty_df = pd.DataFrame()
        anomalies = detector.detect(empty_df)
        assert len(anomalies) == 0

    def test_severity_assignment(self, detector, sample_metrics_anomalous):
        """Test that anomalies get appropriate severity levels."""
        anomalies = detector.detect(sample_metrics_anomalous)

        assert all(a.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL") for a in anomalies)

        # High error rate should get CRITICAL or HIGH
        high_error = [a for a in anomalies if a.anomaly_type == "high_error_rate"]
        if high_error:
            assert high_error[0].severity in ("HIGH", "CRITICAL")

    def test_min_error_count_threshold(self):
        """Test that min_error_count threshold is respected."""
        thresholds = AnomalyThresholds(
            error_rate_threshold=0.10,
            min_error_count=10,
        )
        detector = AnomalyDetector(thresholds)

        # Low error count, high rate but below threshold
        df = pd.DataFrame([
            {
                "service": "test-service",
                "window_start": "2024-01-01T10:00:00",
                "window_end": "2024-01-01T10:05:00",
                "total_logs": 100,
                "error_count": 5,
                "error_rate": 0.15,
                "avg_latency_ms": 100.0,
                "p95_latency_ms": 200.0,
            },
        ])

        anomalies = detector.detect(df)
        # Should not flag because error_count < min_error_count
        error_anomalies = [a for a in anomalies if a.anomaly_type == "high_error_rate"]
        assert len(error_anomalies) == 0
