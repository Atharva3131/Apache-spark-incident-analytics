"""
Apache Spark processing engine.

Performs:
  - Log parsing & schema validation  (handled in ingestion; reused here)
  - Timestamp normalisation
  - Aggregation by service + time window
  - Error counts / error rates
  - Average and approximate percentile latency (p95, p99)
  - Service-level health metrics
  - Returns results as Pandas DataFrames for downstream use
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import Window
from pyspark.sql.types import StringType

logger = logging.getLogger(__name__)


# ── SparkSession factory ──────────────────────────────────────────────────────

def get_spark_session(
    app_name: str = "ProductionIncidentDetection",
    master: str = "local[*]",
    driver_memory: str = "2g",
    log_level: str = "WARN",
) -> SparkSession:
    """Create (or reuse) a SparkSession configured for local mode."""
    spark = (
        SparkSession.builder
        .appName(app_name)
        .master(master)
        .config("spark.driver.memory", driver_memory)
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.showConsoleProgress", "false")
        # Avoid Spark 3.x legacy time-parsing issues
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel(log_level)
    logger.info("SparkSession ready – master: %s", master)
    return spark


# ── Processing steps ──────────────────────────────────────────────────────────

class SparkProcessor:
    """
    Wraps the PySpark processing pipeline.

    All heavy computation stays in Spark; results are collected to Pandas
    only at the very end so the rest of the application can work with
    ordinary DataFrames.
    """

    def __init__(self, spark: SparkSession, window_minutes: int = 5):
        self._spark = spark
        self._window_minutes = window_minutes

    # ── helpers ───────────────────────────────────────────────────────────────

    def _window_duration(self) -> str:
        return f"{self._window_minutes} minutes"

    def _slide_duration(self) -> str:
        # Non-overlapping windows (tumbling)
        return self._window_duration()

    # ── public API ────────────────────────────────────────────────────────────

    def compute_service_metrics(self, df: DataFrame) -> pd.DataFrame:
        """
        Aggregate logs by service and tumbling time window.

        Returns a Pandas DataFrame with columns:
          service, window_start, window_end,
          total_logs, error_count, warn_count, info_count,
          error_rate, avg_latency_ms, p95_latency_ms, p99_latency_ms
        """
        window = F.window(F.col("timestamp"), self._window_duration())

        agg = (
            df.groupBy(F.col("service"), window)
            .agg(
                F.count("*").alias("total_logs"),
                F.sum(F.when(F.col("log_level") == "ERROR", 1).otherwise(0)).alias("error_count"),
                F.sum(F.when(F.col("log_level") == "WARN", 1).otherwise(0)).alias("warn_count"),
                F.sum(F.when(F.col("log_level") == "INFO", 1).otherwise(0)).alias("info_count"),
                F.avg("latency_ms").alias("avg_latency_ms"),
                F.percentile_approx("latency_ms", 0.95).alias("p95_latency_ms"),
                F.percentile_approx("latency_ms", 0.99).alias("p99_latency_ms"),
            )
            .withColumn("error_rate", F.col("error_count") / F.col("total_logs"))
            .withColumn("window_start", F.col("window.start"))
            .withColumn("window_end", F.col("window.end"))
            .drop("window")
            .orderBy("service", "window_start")
        )

        result = agg.toPandas()
        logger.info("Service metrics computed – %d rows", len(result))
        return result

    def compute_overall_summary(self, df: DataFrame) -> Dict:
        """
        High-level summary statistics across the whole dataset.
        """
        row = df.agg(
            F.count("*").alias("total_logs"),
            F.countDistinct("service").alias("service_count"),
            F.sum(F.when(F.col("log_level") == "ERROR", 1).otherwise(0)).alias("error_count"),
            F.sum(F.when(F.col("log_level") == "WARN", 1).otherwise(0)).alias("warn_count"),
            F.avg("latency_ms").alias("avg_latency_ms"),
            F.min("timestamp").alias("first_event"),
            F.max("timestamp").alias("last_event"),
        ).collect()[0]

        summary = {
            "total_logs": int(row["total_logs"]),
            "service_count": int(row["service_count"]),
            "error_count": int(row["error_count"]),
            "warn_count": int(row["warn_count"]),
            "avg_latency_ms": float(row["avg_latency_ms"] or 0),
            "first_event": str(row["first_event"]),
            "last_event": str(row["last_event"]),
        }
        logger.info("Overall summary: %s", summary)
        return summary

    def compute_error_distribution(self, df: DataFrame) -> pd.DataFrame:
        """Error counts per service."""
        result = (
            df.filter(F.col("log_level") == "ERROR")
            .groupBy("service")
            .agg(F.count("*").alias("error_count"))
            .orderBy(F.desc("error_count"))
            .toPandas()
        )
        return result

    def compute_log_volume_over_time(self, df: DataFrame) -> pd.DataFrame:
        """Log volume aggregated in 1-minute buckets across all services."""
        result = (
            df.withColumn("minute", F.date_trunc("minute", F.col("timestamp")))
            .groupBy("minute", "service")
            .agg(F.count("*").alias("log_count"))
            .orderBy("minute", "service")
            .toPandas()
        )
        return result

    def compute_latency_stats(self, df: DataFrame) -> pd.DataFrame:
        """Per-service latency statistics (avg, p95, p99)."""
        result = (
            df.filter(F.col("latency_ms").isNotNull())
            .groupBy("service")
            .agg(
                F.avg("latency_ms").alias("avg_latency_ms"),
                F.percentile_approx("latency_ms", 0.50).alias("p50_latency_ms"),
                F.percentile_approx("latency_ms", 0.95).alias("p95_latency_ms"),
                F.percentile_approx("latency_ms", 0.99).alias("p99_latency_ms"),
                F.max("latency_ms").alias("max_latency_ms"),
            )
            .orderBy("service")
            .toPandas()
        )
        return result

    def get_high_latency_samples(self, df: DataFrame, threshold_ms: float = 5000, limit: int = 50) -> pd.DataFrame:
        """Return sample records with latency above threshold."""
        result = (
            df.filter(F.col("latency_ms") > threshold_ms)
            .orderBy(F.desc("latency_ms"))
            .limit(limit)
            .toPandas()
        )
        return result

    def get_error_samples(self, df: DataFrame, limit: int = 100) -> pd.DataFrame:
        """Return sample ERROR records for evidence gathering."""
        result = (
            df.filter(F.col("log_level") == "ERROR")
            .orderBy(F.desc("latency_ms"))
            .limit(limit)
            .toPandas()
        )
        return result

    def run_full_pipeline(self, df: DataFrame) -> Dict:
        """
        Run the complete processing pipeline and return all results as a dict of Pandas DataFrames / dicts.
        """
        logger.info("Running full Spark processing pipeline …")
        results = {
            "summary": self.compute_overall_summary(df),
            "service_metrics": self.compute_service_metrics(df),
            "error_distribution": self.compute_error_distribution(df),
            "log_volume": self.compute_log_volume_over_time(df),
            "latency_stats": self.compute_latency_stats(df),
            "high_latency_samples": self.get_high_latency_samples(df),
            "error_samples": self.get_error_samples(df),
        }
        logger.info("Full pipeline complete.")
        return results
