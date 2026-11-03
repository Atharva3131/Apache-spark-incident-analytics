"""
Production Incident Detection & Root Cause Analysis System
Streamlit Dashboard

Main entry point for the application. Orchestrates all components:
- Log generation
- Spark processing
- Anomaly detection
- Incident correlation
- RCA (deterministic + Sarvam)
- MongoDB persistence
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from src.correlation.incident_correlator import IncidentCorrelator
from src.detection.anomaly_detector import AnomalyDetector, AnomalyThresholds
from src.generator.log_generator import LogGenerator
from src.ingestion.log_ingestion import ingest_auto
from src.investigation.rca_engine import generate_deterministic_rca
from src.investigation.sarvam_client import investigate_with_sarvam
from src.models.incident import IncidentRecord, RCAResponse
from src.processing.spark_processor import SparkProcessor, get_spark_session
from src.storage.mongodb_store import MongoDBStore

# ── Setup logging ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ── Streamlit page config ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Production Incident Intelligence",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 20px;
        border-radius: 8px;
        color: white;
        text-align: center;
        margin: 10px 0;
    }
    .severity-critical {
        background-color: #ff4757;
        color: white;
        padding: 5px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    .severity-high {
        background-color: #ffa502;
        color: white;
        padding: 5px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    .severity-medium {
        background-color: #ffd93d;
        color: black;
        padding: 5px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    .severity-low {
        background-color: #6bcf7f;
        color: white;
        padding: 5px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ── Global state initialization ────────────────────────────────────────────────

if "spark" not in st.session_state:
    st.session_state.spark = get_spark_session(
        app_name=settings.spark.app_name,
        master=settings.spark.master,
        driver_memory=settings.spark.driver_memory,
        log_level=settings.spark.log_level,
    )

if "mongo_store" not in st.session_state:
    st.session_state.mongo_store = MongoDBStore(settings.mongo)

if "current_incident" not in st.session_state:
    st.session_state.current_incident = None

# ── Helper functions ──────────────────────────────────────────────────────────

@st.cache_data
def load_or_generate_logs(scenario: str, n_normal: int, n_incident: int):
    """Generate or load synthetic logs."""
    gen = LogGenerator(seed=settings.generator.random_seed)
    records = gen.generate(
        scenario=scenario,
        n_normal=n_normal,
        n_incident=n_incident,
    )
    return records


def process_logs(records, scenario):
    """Full processing pipeline: ingest → process → detect → correlate → rca."""
    try:
        # Ingest
        df = ingest_auto(st.session_state.spark, records=records)

        # Process
        processor = SparkProcessor(
            st.session_state.spark,
            window_minutes=settings.thresholds.window_minutes,
        )
        results = processor.run_full_pipeline(df)

        # Detect anomalies
        detector = AnomalyDetector(
            thresholds=AnomalyThresholds(
                error_rate_threshold=settings.thresholds.error_rate_threshold,
                latency_spike_threshold_ms=settings.thresholds.latency_spike_threshold_ms,
                min_error_count=settings.thresholds.min_error_count,
            )
        )
        anomalies = detector.detect(results["service_metrics"])

        # Correlate
        correlator = IncidentCorrelator()
        correlation = correlator.correlate(
            anomalies,
            results["service_metrics"],
            results["error_samples"],
        )

        # RCA
        rca_response = None

        # Try Sarvam first
        if settings.sarvam.api_key:
            rca_response = investigate_with_sarvam(
                settings.sarvam,
                incident_summary=f"Incident detected in scenario: {scenario}",
                affected_services=correlation.all_affected_services,
                error_evidence=correlation.evidence[:10],
                probable_root_cause=correlation.primary_root_cause or "Unknown",
                scenario_hint=correlation.scenario_hint,
            )

        # Fallback to deterministic
        if rca_response is None:
            rca_response = generate_deterministic_rca(
                correlation,
                results["service_metrics"],
                results["error_samples"],
            )

        # Store incident
        incident = IncidentRecord(
            incident_id=str(uuid.uuid4()),
            scenario=scenario,
            metrics_snapshot=[
                {
                    "service": row["service"],
                    "error_rate": row["error_rate"],
                    "avg_latency": row["avg_latency_ms"],
                }
                for _, row in results["service_metrics"].iterrows()
            ],
            anomalies=[
                {
                    "service": a.service,
                    "type": a.anomaly_type,
                    "value": a.observed_value,
                }
                for a in anomalies
            ],
            rca=rca_response,
            raw_evidence=correlation.evidence[:5],
        )

        st.session_state.mongo_store.store_incident(incident)
        st.session_state.current_incident = incident

        return {
            "success": True,
            "incident": incident,
            "results": results,
            "anomalies": anomalies,
            "correlation": correlation,
            "rca": rca_response,
        }

    except Exception as e:
        logger.error("Processing failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


# ── Sidebar controls ───────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🎛️ Demo Controls")

    scenario = st.selectbox(
        "Select Incident Scenario",
        options=list(LogGenerator.SCENARIOS.keys()),
        format_func=lambda x: f"{x}: {LogGenerator.SCENARIOS[x]}",
    )

    col1, col2 = st.columns(2)
    with col1:
        n_normal = st.number_input("Normal Records", value=2000, min_value=500, max_value=10000)
    with col2:
        n_incident = st.number_input("Incident Records", value=500, min_value=100, max_value=2000)

    st.markdown("---")

    if st.button("▶️ Generate & Investigate", use_container_width=True, type="primary"):
        with st.spinner("Processing... this may take a minute"):
            records = load_or_generate_logs(scenario, n_normal, n_incident)
            result = process_logs(records, scenario)
            if result["success"]:
                st.success(f"✅ Investigation complete – Incident ID: {result['incident'].incident_id[:8]}")
            else:
                st.error(f"❌ Error: {result['error']}")

    st.markdown("---")
    st.markdown("""
    **MongoDB**: {}
    **Sarvam API**: {}
    """.format(
        "✅ Connected" if st.session_state.mongo_store.is_connected() else "⚠️ Not connected",
        "✅ Configured" if settings.sarvam.api_key else "⚠️ Not configured",
    ))

# ── Main dashboard ─────────────────────────────────────────────────────────────

st.title("🔍 Production Incident Intelligence")
st.markdown("*AI-powered root cause analysis using Apache Spark & Sarvam*")

# ── Tabs ───────────────────────────────────────────────────────────────────────

tabs = st.tabs([
    "📊 Overview",
    "📈 Log Analytics",
    "🔎 Incident Investigation",
    "📜 Historical Incidents",
])

# ── Tab 1: Overview ────────────────────────────────────────────────────────────

with tabs[0]:
    if st.session_state.current_incident is None:
        st.info("👈 Use the controls on the left to generate and investigate an incident.")
    else:
        incident = st.session_state.current_incident

        # Metrics row
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("📋 Incident ID", incident.incident_id[:8] + "...")
        with col2:
            st.metric("⏰ Detected", incident.detected_at.strftime("%H:%M:%S"))
        with col3:
            st.metric("📍 Scenario", incident.scenario)
        with col4:
            severity = incident.rca.severity if incident.rca else "UNKNOWN"
            st.metric("🚨 Severity", severity)

        st.markdown("---")

        # Summary
        if incident.rca:
            st.subheader("📝 Incident Summary")
            st.write(incident.rca.summary)

            st.subheader("🔴 Probable Root Cause")
            st.warning(incident.rca.probable_root_cause)

            # Affected services
            st.subheader("🏢 Affected Services")
            cols = st.columns(len(incident.rca.affected_services) or 1)
            for i, svc in enumerate(incident.rca.affected_services or []):
                with cols[i]:
                    st.write(f"• {svc}")

# ── Tab 2: Log Analytics ──────────────────────────────────────────────────────

with tabs[1]:
    if st.session_state.current_incident is None:
        st.info("👈 Generate an incident first to see analytics.")
    else:
        # This is where we'd display Spark results
        incident = st.session_state.current_incident
        st.subheader("📊 Service Health Metrics")

        if incident.metrics_snapshot:
            metrics_df = pd.DataFrame(incident.metrics_snapshot)
            st.dataframe(metrics_df, use_container_width=True)

            # Charts
            col1, col2 = st.columns(2)
            with col1:
                fig = px.bar(
                    metrics_df,
                    x="service",
                    y="error_rate",
                    title="Error Rate by Service",
                    labels={"error_rate": "Error Rate", "service": "Service"},
                )
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                fig = px.bar(
                    metrics_df,
                    x="service",
                    y="avg_latency",
                    title="Average Latency by Service",
                    labels={"avg_latency": "Latency (ms)", "service": "Service"},
                )
                st.plotly_chart(fig, use_container_width=True)

# ── Tab 3: Incident Investigation ──────────────────────────────────────────────

with tabs[2]:
    if st.session_state.current_incident is None or st.session_state.current_incident.rca is None:
        st.info("👈 Generate an incident first to see the investigation.")
    else:
        rca = st.session_state.current_incident.rca

        st.subheader(rca.incident_title)

        col1, col2, col3 = st.columns(3)
        with col1:
            sev_color = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢",
            }
            st.metric("Severity", f"{sev_color.get(rca.severity.value, '❓')} {rca.severity.value}")
        with col2:
            st.metric("Generated By", rca.generated_by)
        with col3:
            st.metric("Services Affected", len(rca.affected_services))

        st.markdown("---")

        st.subheader("📋 Supporting Evidence")
        for i, ev in enumerate(rca.supporting_evidence[:10], 1):
            st.write(f"{i}. {ev}")

        st.subheader("✅ Recommended Actions")
        for i, action in enumerate(rca.recommended_actions[:10], 1):
            st.write(f"{i}. {action}")

        if rca.uncertainties:
            st.subheader("❓ Unverified Hypotheses")
            for hyp in rca.uncertainties[:5]:
                st.write(f"• {hyp}")

# ── Tab 4: Historical Incidents ────────────────────────────────────────────────

with tabs[3]:
    st.subheader("📜 Previous Investigations")

    if st.session_state.mongo_store.is_connected():
        incidents = st.session_state.mongo_store.list_incidents(limit=50)
        if incidents:
            hist_df = pd.DataFrame([
                {
                    "Incident ID": inc.incident_id[:8] + "...",
                    "Scenario": inc.scenario,
                    "Detected": inc.detected_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Severity": inc.rca.severity.value if inc.rca else "N/A",
                    "Status": inc.status,
                }
                for inc in incidents
            ])
            st.dataframe(hist_df, use_container_width=True)
        else:
            st.info("No incidents stored yet.")
    else:
        st.warning("MongoDB not connected – historical data unavailable.")

# ── Footer ─────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("""
**Production Incident Detection & Root Cause Analysis System**
- Built with Apache Spark, Streamlit, Sarvam AI
- Demonstrates incident correlation and deterministic RCA
- [Source Code](https://github.com)
""")
