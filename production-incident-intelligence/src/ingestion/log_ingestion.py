"""
Log ingestion layer.

Supports:
  - CSV files (local or S3 path)
  - JSON Lines files (local or S3 path)
  - In-memory Python list (from the generator)

Returns a PySpark DataFrame with a canonical schema.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

logger = logging.getLogger(__name__)

# ── Canonical schema ──────────────────────────────────────────────────────────

LOG_SCHEMA = StructType([
    StructField("timestamp", StringType(), nullable=True),
    StructField("service", StringType(), nullable=True),
    StructField("log_level", StringType(), nullable=True),
    StructField("message", StringType(), nullable=True),
    StructField("request_id", StringType(), nullable=True),
    StructField("trace_id", StringType(), nullable=True),
    StructField("latency_ms", DoubleType(), nullable=True),
    StructField("hostname", StringType(), nullable=True),
])


def _apply_schema_and_clean(df: DataFrame) -> DataFrame:
    """
    Normalise timestamp to proper TimestampType, uppercase log_level,
    and drop records missing mandatory fields.
    """
    df = df.withColumn(
        "timestamp",
        F.coalesce(
            F.to_timestamp(F.col("timestamp"), "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"),
            F.to_timestamp(F.col("timestamp"), "yyyy-MM-dd'T'HH:mm:ss"),
            F.to_timestamp(F.col("timestamp")),
        ).cast(TimestampType()),
    )
    df = df.withColumn("log_level", F.upper(F.trim(F.col("log_level"))))
    df = df.withColumn("latency_ms", F.col("latency_ms").cast(DoubleType()))

    # Drop records with no timestamp, service, or log_level
    df = df.dropna(subset=["timestamp", "service", "log_level"])

    # Fill optional string columns
    for col_name in ("request_id", "trace_id", "hostname", "message"):
        df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit("unknown")))

    logger.info("Schema applied – row count after cleaning: %d", df.count())
    return df


# ── Public ingestion functions ────────────────────────────────────────────────

def ingest_csv(spark: SparkSession, path: str) -> DataFrame:
    """
    Read a CSV log file.

    The path may be a local filesystem path or an S3 URL (s3://bucket/key).
    S3 requires hadoop-aws and appropriate credentials configured externally.
    """
    logger.info("Ingesting CSV from: %s", path)
    df = spark.read.option("header", "true").schema(LOG_SCHEMA).csv(path)
    return _apply_schema_and_clean(df)


def ingest_json(spark: SparkSession, path: str) -> DataFrame:
    """
    Read a JSON Lines log file.

    The path may be a local filesystem path or an S3 URL.
    """
    logger.info("Ingesting JSON Lines from: %s", path)
    df = spark.read.schema(LOG_SCHEMA).json(path)
    return _apply_schema_and_clean(df)


def ingest_records(spark: SparkSession, records: List[dict]) -> DataFrame:
    """
    Convert an in-memory list of log record dicts (from the generator)
    into a Spark DataFrame.
    """
    logger.info("Ingesting %d in-memory records", len(records))
    if not records:
        # Return an empty DataFrame with the right schema
        return spark.createDataFrame([], schema=LOG_SCHEMA)

    # Convert to Row-compatible form; ensure latency_ms is float
    clean = []
    for rec in records:
        clean.append({
            "timestamp": str(rec.get("timestamp", "")),
            "service": str(rec.get("service", "unknown")),
            "log_level": str(rec.get("log_level", "INFO")),
            "message": str(rec.get("message", "")),
            "request_id": str(rec.get("request_id", "unknown")),
            "trace_id": str(rec.get("trace_id", "unknown")),
            "latency_ms": float(rec["latency_ms"]) if rec.get("latency_ms") is not None else None,
            "hostname": str(rec.get("hostname", "unknown")),
        })

    df = spark.createDataFrame(clean, schema=LOG_SCHEMA)
    return _apply_schema_and_clean(df)


def ingest_auto(
    spark: SparkSession,
    path: Optional[str] = None,
    records: Optional[List[dict]] = None,
) -> DataFrame:
    """
    Convenience wrapper – chooses ingestion method automatically.

    Priority: records > path (CSV/JSON detected by extension).
    """
    if records is not None:
        return ingest_records(spark, records)
    if path is None:
        raise ValueError("Provide either 'path' or 'records'.")
    lower = path.lower()
    if lower.endswith(".json") or lower.endswith(".jsonl") or lower.endswith(".ndjson"):
        return ingest_json(spark, path)
    return ingest_csv(spark, path)
