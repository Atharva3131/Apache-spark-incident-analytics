#!/usr/bin/env python
"""
Production Incident Detection & Root Cause Analysis System
Comprehensive Demo

Demonstrates:
1. Synthetic log generation with three incident scenarios
2. Apache Spark log processing
3. Anomaly detection
4. Incident correlation
5. Deterministic RCA report generation

Run with: python demo.py
"""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from src.generator.log_generator import LogGenerator
from src.ingestion.log_ingestion import ingest_records
from src.processing.spark_processor import SparkProcessor, get_spark_session
from src.detection.anomaly_detector import AnomalyDetector, AnomalyThresholds
from src.correlation.incident_correlator import IncidentCorrelator
from src.investigation.rca_engine import generate_deterministic_rca


def print_header(text: str):
    """Print a formatted header."""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_section(text: str):
    """Print a formatted section."""
    print(f"\n>> {text}")
    print("-" * 70)


def demo_scenario(scenario: str, description: str):
    """Run a complete demo for a single scenario."""
    print_header(f"SCENARIO: {scenario.upper()}")
    print(f"Description: {description}\n")

    # Step 1: Generate logs
    print_section("Step 1: Generating Synthetic Logs")
    gen = LogGenerator(seed=42)
    records = gen.generate(scenario=scenario, n_normal=1500, n_incident=400)
    print("[OK] Generated {:,} log records".format(len(records)))
    print("   Normal records: {} (mostly)".format(len([r for r in records if r['log_level'] == 'INFO'])))
    print("   Error records: {}".format(len([r for r in records if r['log_level'] == 'ERROR'])))
    print("   Services: {}".format(len(set(r['service'] for r in records))))

    # Step 2: Ingest to Spark
    print_section("Step 2: Ingesting Logs into Apache Spark")
    spark = get_spark_session(master="local[1]", log_level="ERROR")
    df = ingest_records(spark, records)
    print("[OK] Spark DataFrame created")
    print("   Total rows: {:,}".format(df.count()))
    print("   Partitions: {}".format(df.rdd.getNumPartitions()))

    # Step 3: Process with Spark
    print_section("Step 3: Processing with Spark (Aggregation & Metrics)")
    processor = SparkProcessor(spark, window_minutes=settings.thresholds.window_minutes)
    results = processor.run_full_pipeline(df)

    summary = results["summary"]
    print("[OK] Spark processing complete")
    print("   Total logs processed: {:,}".format(summary['total_logs']))
    print("   Services: {}".format(summary['service_count']))
    error_pct = summary['error_count']/max(summary['total_logs'], 1)*100
    print("   Errors: {} ({:.1f}%)".format(summary['error_count'], error_pct))
    print("   Average latency: {:.0f} ms".format(summary['avg_latency_ms']))
    print("   Time range: {} -> {}".format(summary['first_event'], summary['last_event']))

    # Step 4: Detect anomalies
    print_section("Step 4: Anomaly Detection (Threshold-Based)")
    detector = AnomalyDetector(
        thresholds=AnomalyThresholds(
            error_rate_threshold=settings.thresholds.error_rate_threshold,
            latency_spike_threshold_ms=settings.thresholds.latency_spike_threshold_ms,
            min_error_count=settings.thresholds.min_error_count,
        )
    )
    anomalies = detector.detect(results["service_metrics"])
    print("[OK] Anomaly detection complete")
    print("   Anomalies found: {}".format(len(anomalies)))

    if anomalies:
        severity_counts = {}
        for a in anomalies:
            severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1

        print("   By severity:")
        for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            count = severity_counts.get(severity, 0)
            if count > 0:
                print("      {}: {}".format(severity, count))

        print("\n   Top anomalies:")
        sorted_anomalies = sorted(anomalies, 
                                 key=lambda x: ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(x.severity), 
                                 reverse=True)
        for i, a in enumerate(sorted_anomalies[:5], 1):
            print("      {}. [{}] {}: {}".format(i, a.severity, a.service, a.anomaly_type))
            print("         {}".format(a.description))
    else:
        print("   [INFO] No anomalies detected in this scenario")

    # Step 5: Correlate incidents
    print_section("Step 5: Incident Correlation (Dependency Graph)")
    correlator = IncidentCorrelator()
    correlation = correlator.correlate(anomalies, results["service_metrics"], results["error_samples"])

    print("[OK] Correlation complete")
    if correlation.first_anomaly_service:
        print("   First anomaly: {} @ {}".format(correlation.first_anomaly_service, 
                                                correlation.first_anomaly_time))
    affected = ', '.join(correlation.all_affected_services) or 'None'
    print("   Affected services: {}".format(affected))
    if correlation.cascade_chain:
        print("   Cascade chain: {}".format(' -> '.join(correlation.cascade_chain)))
    print("   Incident severity: {}".format(correlation.incident_severity))
    print("   Scenario hint: {}".format(correlation.scenario_hint))

    if correlation.root_cause_candidates:
        print("\n   Root cause candidates (ranked):")
        for i, candidate in enumerate(correlation.root_cause_candidates[:3], 1):
            print("      {}. {} (confidence: {})".format(i, candidate['service'], 
                                                        candidate['confidence']))
            print("         {}...".format(candidate['explanation'][:80]))

    # Step 6: Generate RCA
    print_section("Step 6: Root Cause Analysis (Deterministic Engine)")
    rca = generate_deterministic_rca(correlation, results["service_metrics"], results["error_samples"])

    print("[OK] RCA report generated")
    print("   Title: {}".format(rca.incident_title))
    print("   Severity: {}".format(rca.severity))
    print("   Summary: {}...".format(rca.summary[:120]))
    print("   Root cause: {}...".format(rca.probable_root_cause[:100]))
    print("   Affected services: {}".format(', '.join(rca.affected_services)))
    print("   Evidence points: {}".format(len(rca.supporting_evidence)))
    print("   Recommended actions: {}".format(len(rca.recommended_actions)))
    print("   Uncertainties: {}".format(len(rca.uncertainties)))

    if rca.recommended_actions:
        print("\n   Top recommendations:")
        for i, action in enumerate(rca.recommended_actions[:3], 1):
            print("      {}. {}...".format(i, action[:70]))

    spark.stop()
    print()


def main():
    """Run the complete demo."""
    print_header("PRODUCTION INCIDENT DETECTION & RCA SYSTEM - COMPREHENSIVE DEMO")
    print("""
This demo showcases the complete incident investigation pipeline:
  * Synthetic log generation for realistic microservice scenarios
  * Apache Spark distributed log processing
  * Threshold-based anomaly detection
  * Service dependency correlation
  * Deterministic root cause analysis

The system processes real Spark DataFrames and generates evidence-backed
investigation reports WITHOUT requiring external APIs or ML models.
""")

    # Run demos for each scenario
    scenarios = [
        ("normal", "Baseline - no incidents, normal operation"),
        ("db_exhaustion", "Database connection pool exhaustion -> cascading failures"),
        ("payment_latency", "Payment service latency spike from external provider"),
        ("inventory_cascade", "Inventory timeout -> order failures -> API errors"),
    ]

    for scenario, desc in scenarios:
        try:
            demo_scenario(scenario, desc)
        except Exception as e:
            print("\n[ERROR] Error in {}: {}".format(scenario, e))
            import traceback
            traceback.print_exc()

    print_header("DEMO COMPLETE")
    print("""
Next steps:
  1. Start interactive dashboard:
     streamlit run app.py

  2. Run test suite:
     pytest tests/ -v

  3. Explore the code:
     - src/generator/     -> Log generation
     - src/processing/    -> Spark aggregations
     - src/detection/     -> Anomaly detection
     - src/correlation/   -> Incident correlation
     - src/investigation/ -> RCA engines
     - config/            -> Configuration

System is ready for production deployment!
""")


if __name__ == "__main__":
    main()
