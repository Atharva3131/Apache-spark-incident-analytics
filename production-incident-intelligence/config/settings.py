"""
Central configuration for the Production Incident Detection System.
All environment variables are read here; no other module should call os.getenv directly.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class SparkConfig:
    app_name: str = "ProductionIncidentDetection"
    master: str = "local[*]"
    driver_memory: str = "2g"
    # Optional HDFS / S3 base path – leave empty to use local filesystem
    input_base_path: str = ""
    log_level: str = "WARN"


@dataclass
class MongoConfig:
    uri: str = field(default_factory=lambda: os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
    database: str = field(default_factory=lambda: os.getenv("MONGODB_DATABASE", "incident_intelligence"))
    collection_incidents: str = "incidents"
    collection_history: str = "investigation_history"
    enabled: bool = field(default_factory=lambda: os.getenv("MONGODB_ENABLED", "true").lower() == "true")


@dataclass
class SarvamConfig:
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("SARVAM_API_KEY"))
    api_base_url: str = field(
        default_factory=lambda: os.getenv("SARVAM_API_BASE_URL", "https://api.sarvam.ai/v2")
    )
    model: str = field(default_factory=lambda: os.getenv("SARVAM_MODEL", "sarvam-105b"))
    timeout_seconds: int = 60
    max_retries: int = 2


@dataclass
class AnomalyThresholds:
    # Error rate above which a service is flagged anomalous (0‑1 fraction)
    error_rate_threshold: float = field(
        default_factory=lambda: float(os.getenv("ERROR_RATE_THRESHOLD", "0.1"))
    )
    # Latency (ms) above which a window is considered anomalous
    latency_spike_threshold_ms: float = field(
        default_factory=lambda: float(os.getenv("LATENCY_SPIKE_THRESHOLD_MS", "2000"))
    )
    # Minimum number of errors in a window to consider it an incident
    min_error_count: int = field(
        default_factory=lambda: int(os.getenv("MIN_ERROR_COUNT", "5"))
    )
    # Time window size in minutes for aggregation
    window_minutes: int = field(
        default_factory=lambda: int(os.getenv("WINDOW_MINUTES", "5"))
    )


@dataclass
class GeneratorConfig:
    random_seed: int = 42
    normal_records: int = 2000
    incident_records: int = 500
    output_dir: str = "data/generated"


@dataclass
class AppConfig:
    spark: SparkConfig = field(default_factory=SparkConfig)
    mongo: MongoConfig = field(default_factory=MongoConfig)
    sarvam: SarvamConfig = field(default_factory=SarvamConfig)
    thresholds: AnomalyThresholds = field(default_factory=AnomalyThresholds)
    generator: GeneratorConfig = field(default_factory=GeneratorConfig)
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))


# Singleton
settings = AppConfig()
