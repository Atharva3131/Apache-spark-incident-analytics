"""
Pydantic models for incidents, RCA responses, and supporting evidence.
These models are the canonical data contracts for the whole application.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LogRecord(BaseModel):
    """Single parsed log entry."""

    timestamp: datetime
    service: str
    log_level: str
    message: str
    request_id: Optional[str] = None
    trace_id: Optional[str] = None
    latency_ms: Optional[float] = None
    hostname: Optional[str] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ServiceMetrics(BaseModel):
    """Aggregated metrics for a single service in a time window."""

    service: str
    window_start: datetime
    window_end: datetime
    total_logs: int
    error_count: int
    error_rate: float
    avg_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None
    p99_latency_ms: Optional[float] = None
    is_anomalous: bool = False
    anomaly_reasons: List[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """A single event in an incident timeline."""

    timestamp: datetime
    service: str
    event_type: str
    description: str
    severity: Severity = Severity.LOW


class RCAResponse(BaseModel):
    """
    Structured investigation report – produced by Sarvam AI or the deterministic engine.
    The schema is validated regardless of the source so the UI always gets a consistent shape.
    """

    incident_title: str
    severity: Severity
    summary: str
    probable_root_cause: str
    supporting_evidence: List[str] = Field(default_factory=list)
    affected_services: List[str] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)
    generated_by: str = "deterministic_engine"  # "sarvam_ai" | "deterministic_engine"

    @validator("severity", pre=True)
    def normalise_severity(cls, v: Any) -> str:  # noqa: N805
        if isinstance(v, str):
            return v.upper()
        return v


class IncidentRecord(BaseModel):
    """
    Full incident as persisted to MongoDB and displayed in the dashboard.
    """

    incident_id: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    scenario: str
    metrics_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    rca: Optional[RCAResponse] = None
    raw_evidence: List[str] = Field(default_factory=list)
    status: str = "open"  # open | investigating | resolved

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
