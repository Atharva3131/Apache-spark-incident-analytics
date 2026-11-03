"""
Synthetic microservice log generator.

Generates realistic log data for five services across three failure scenarios:
  1. Database connection pool exhaustion
  2. Payment service latency spike
  3. Inventory service timeout → cascading failures

All random choices are seeded for reproducibility.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Service definitions ──────────────────────────────────────────────────────

SERVICES = [
    "api-gateway",
    "order-service",
    "payment-service",
    "inventory-service",
    "database-service",
]

HOSTNAMES: Dict[str, List[str]] = {
    "api-gateway": ["api-gw-01", "api-gw-02"],
    "order-service": ["order-01", "order-02", "order-03"],
    "payment-service": ["payment-01", "payment-02"],
    "inventory-service": ["inventory-01", "inventory-02"],
    "database-service": ["db-primary", "db-replica-01"],
}

# Normal latency ranges per service (ms)
NORMAL_LATENCY: Dict[str, tuple[float, float]] = {
    "api-gateway": (10, 150),
    "order-service": (20, 300),
    "payment-service": (50, 500),
    "inventory-service": (15, 200),
    "database-service": (5, 80),
}

NORMAL_ERROR_RATE: Dict[str, float] = {
    "api-gateway": 0.01,
    "order-service": 0.02,
    "payment-service": 0.015,
    "inventory-service": 0.01,
    "database-service": 0.005,
}

INFO_MESSAGES: Dict[str, List[str]] = {
    "api-gateway": [
        "Request routed to order-service",
        "Health check passed",
        "Rate limiter: request accepted",
        "Upstream response cached",
        "Auth token validated",
    ],
    "order-service": [
        "Order created successfully",
        "Order status updated to PROCESSING",
        "Payment verification initiated",
        "Inventory check requested",
        "Order dispatched",
    ],
    "payment-service": [
        "Payment authorised",
        "Transaction recorded",
        "Fraud check passed",
        "Payment gateway response received",
        "Refund processed",
    ],
    "inventory-service": [
        "Stock level checked",
        "Reservation created",
        "Warehouse query completed",
        "SKU availability confirmed",
        "Reservation released",
    ],
    "database-service": [
        "Query executed successfully",
        "Connection acquired from pool",
        "Transaction committed",
        "Index scan completed",
        "Cache hit",
    ],
}

ERROR_MESSAGES: Dict[str, List[str]] = {
    "api-gateway": [
        "Upstream service returned 503",
        "Connection timeout to order-service",
        "Circuit breaker OPEN for downstream",
        "Request routing failed",
    ],
    "order-service": [
        "Failed to reserve inventory",
        "Payment service call failed",
        "Database write timeout",
        "Order validation error",
    ],
    "payment-service": [
        "Payment gateway timeout",
        "Transaction declined",
        "Fraud detection service unreachable",
        "Duplicate transaction detected",
    ],
    "inventory-service": [
        "Database connection refused",
        "Stock query timed out",
        "Inventory lock acquisition failed",
        "Warehouse API unreachable",
    ],
    "database-service": [
        "Connection pool exhausted",
        "Query execution timeout",
        "Deadlock detected",
        "Replication lag exceeded threshold",
    ],
}

WARNING_MESSAGES: Dict[str, List[str]] = {
    "api-gateway": [
        "High request rate detected",
        "Slow upstream response",
        "Retry attempt 1/3",
    ],
    "order-service": [
        "Slow inventory check",
        "Payment verification taking longer than expected",
        "Order queue growing",
    ],
    "payment-service": [
        "High latency detected",
        "Connection pool near capacity",
        "Gateway response slow",
    ],
    "inventory-service": [
        "Database connection slow",
        "High query execution time",
        "Lock wait timeout approaching",
    ],
    "database-service": [
        "Connection pool utilisation at 80%",
        "Slow query detected",
        "Replication lag increasing",
    ],
}


# ── LogRecord dict builder ────────────────────────────────────────────────────

def _make_record(
    ts: datetime,
    service: str,
    level: str,
    message: str,
    request_id: str,
    trace_id: str,
    latency_ms: float,
    rng: random.Random,
) -> Dict:
    hostname = rng.choice(HOSTNAMES[service])
    return {
        "timestamp": ts.isoformat(),
        "service": service,
        "log_level": level,
        "message": message,
        "request_id": request_id,
        "trace_id": trace_id,
        "latency_ms": round(latency_ms, 2),
        "hostname": hostname,
    }


def _normal_record(ts: datetime, service: str, rng: random.Random) -> Dict:
    request_id = str(uuid.UUID(int=rng.getrandbits(128)))
    trace_id = str(uuid.UUID(int=rng.getrandbits(128)))
    lo, hi = NORMAL_LATENCY[service]
    latency = rng.uniform(lo, hi)

    if rng.random() < NORMAL_ERROR_RATE[service]:
        level = "ERROR"
        msg = rng.choice(ERROR_MESSAGES[service])
    elif rng.random() < 0.05:
        level = "WARN"
        msg = rng.choice(WARNING_MESSAGES[service])
    else:
        level = "INFO"
        msg = rng.choice(INFO_MESSAGES[service])

    return _make_record(ts, service, level, msg, request_id, trace_id, latency, rng)


# ── Incident scenario generators ─────────────────────────────────────────────

def _scenario_db_exhaustion(
    start: datetime,
    duration_minutes: int,
    rng: random.Random,
) -> List[Dict]:
    """
    Database connection pool exhaustion.
    Starts with DB warnings, then DB errors, which cascade to services that depend on it.
    """
    records: List[Dict] = []
    end = start + timedelta(minutes=duration_minutes)
    t = start
    cascade_start = start + timedelta(minutes=2)

    while t < end:
        # DB service: rapidly escalating errors
        for _ in range(rng.randint(3, 8)):
            latency = rng.uniform(1500, 8000)
            level = "ERROR" if rng.random() < 0.7 else "WARN"
            msg = (
                rng.choice(["Connection pool exhausted", "All connections in use, request queued",
                             "Connection pool exhausted – unable to service request"])
                if level == "ERROR"
                else "Connection pool utilisation at 95%"
            )
            records.append(_make_record(t, "database-service", level, msg,
                                        str(uuid.UUID(int=rng.getrandbits(128))),
                                        str(uuid.UUID(int=rng.getrandbits(128))),
                                        latency, rng))

        # Cascading: order & inventory fail once DB is struggling
        if t >= cascade_start:
            for svc in ["order-service", "inventory-service"]:
                if rng.random() < 0.6:
                    latency = rng.uniform(2000, 10000)
                    records.append(_make_record(
                        t + timedelta(seconds=rng.uniform(0.1, 2)),
                        svc, "ERROR",
                        rng.choice(ERROR_MESSAGES[svc]),
                        str(uuid.UUID(int=rng.getrandbits(128))),
                        str(uuid.UUID(int=rng.getrandbits(128))),
                        latency, rng,
                    ))

        # API gateway starts 502ing
        if t >= cascade_start + timedelta(minutes=1):
            if rng.random() < 0.4:
                records.append(_make_record(
                    t + timedelta(seconds=rng.uniform(0.5, 3)),
                    "api-gateway", "ERROR",
                    "Upstream service returned 503",
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    rng.uniform(5000, 15000), rng,
                ))

        t += timedelta(seconds=rng.uniform(1, 5))

    logger.debug("DB exhaustion scenario: %d records", len(records))
    return records


def _scenario_payment_latency(
    start: datetime,
    duration_minutes: int,
    rng: random.Random,
) -> List[Dict]:
    """Payment service latency spike – gradual rise then plateau."""
    records: List[Dict] = []
    end = start + timedelta(minutes=duration_minutes)
    t = start
    spike_start = start + timedelta(minutes=1)

    while t < end:
        elapsed = (t - spike_start).total_seconds() if t >= spike_start else 0
        # Ramp latency from 500ms to 8000ms over 3 minutes then steady
        ramp_factor = min(elapsed / 180, 1.0)
        base_latency = 500 + ramp_factor * 7500

        latency = rng.uniform(base_latency * 0.8, base_latency * 1.2)
        level = "ERROR" if latency > 5000 else "WARN"
        msg = (
            "Payment gateway timeout" if latency > 5000
            else "High latency detected on payment gateway"
        )
        records.append(_make_record(
            t, "payment-service", level, msg,
            str(uuid.UUID(int=rng.getrandbits(128))),
            str(uuid.UUID(int=rng.getrandbits(128))),
            latency, rng,
        ))

        # Order service starts getting slow responses from payment
        if latency > 3000 and rng.random() < 0.5:
            records.append(_make_record(
                t + timedelta(seconds=rng.uniform(0.1, 1)),
                "order-service", "WARN",
                "Payment verification taking longer than expected",
                str(uuid.UUID(int=rng.getrandbits(128))),
                str(uuid.UUID(int=rng.getrandbits(128))),
                latency + rng.uniform(50, 200), rng,
            ))

        # API gateway sees elevated response times
        if latency > 5000 and rng.random() < 0.3:
            records.append(_make_record(
                t + timedelta(seconds=rng.uniform(0.2, 2)),
                "api-gateway", "WARN",
                "Slow upstream response",
                str(uuid.UUID(int=rng.getrandbits(128))),
                str(uuid.UUID(int=rng.getrandbits(128))),
                latency + rng.uniform(100, 500), rng,
            ))

        t += timedelta(seconds=rng.uniform(1, 4))

    logger.debug("Payment latency scenario: %d records", len(records))
    return records


def _scenario_inventory_cascade(
    start: datetime,
    duration_minutes: int,
    rng: random.Random,
) -> List[Dict]:
    """
    Inventory service timeouts cause cascading failures:
    inventory → order-service → api-gateway.
    """
    records: List[Dict] = []
    end = start + timedelta(minutes=duration_minutes)
    t = start
    cascade_t2 = start + timedelta(minutes=1, seconds=30)
    cascade_t3 = start + timedelta(minutes=3)

    while t < end:
        # Inventory: timeouts
        latency = rng.uniform(8000, 30000)
        level = "ERROR"
        msg = rng.choice([
            "Stock query timed out",
            "Inventory lock acquisition failed",
            "Database connection refused",
            "Warehouse API unreachable",
        ])
        records.append(_make_record(
            t, "inventory-service", level, msg,
            str(uuid.UUID(int=rng.getrandbits(128))),
            str(uuid.UUID(int=rng.getrandbits(128))),
            latency, rng,
        ))

        # Order service cascades
        if t >= cascade_t2:
            if rng.random() < 0.7:
                records.append(_make_record(
                    t + timedelta(seconds=rng.uniform(0.5, 3)),
                    "order-service", "ERROR",
                    "Failed to reserve inventory",
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    latency + rng.uniform(100, 500), rng,
                ))

        # API gateway cascade
        if t >= cascade_t3:
            if rng.random() < 0.5:
                records.append(_make_record(
                    t + timedelta(seconds=rng.uniform(1, 5)),
                    "api-gateway", "ERROR",
                    "Upstream service returned 503",
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    rng.uniform(10000, 30000), rng,
                ))
            # Payment also queues up
            if rng.random() < 0.2:
                records.append(_make_record(
                    t + timedelta(seconds=rng.uniform(0.5, 4)),
                    "payment-service", "WARN",
                    "High latency detected",
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    str(uuid.UUID(int=rng.getrandbits(128))),
                    rng.uniform(1000, 3000), rng,
                ))

        t += timedelta(seconds=rng.uniform(1, 6))

    logger.debug("Inventory cascade scenario: %d records", len(records))
    return records


# ── Public API ────────────────────────────────────────────────────────────────

class LogGenerator:
    """
    Generates synthetic microservice logs with deterministic seeding.
    """

    SCENARIOS = {
        "normal": "Normal traffic (no incidents)",
        "db_exhaustion": "Database connection pool exhaustion",
        "payment_latency": "Payment service latency spike",
        "inventory_cascade": "Inventory service timeout → cascading failures",
    }

    def __init__(self, seed: int = 42):
        self._seed = seed
        self._rng = random.Random(seed)

    def generate(
        self,
        scenario: str = "normal",
        n_normal: int = 2000,
        n_incident: int = 500,
        base_time: Optional[datetime] = None,
    ) -> List[Dict]:
        """
        Generate log records.

        Args:
            scenario: one of the keys in SCENARIOS
            n_normal: number of normal background log records
            n_incident: approximate number of incident-specific records
            base_time: anchor timestamp; defaults to 1 hour ago

        Returns:
            Sorted list of log record dicts
        """
        if scenario not in self.SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'. Choose from: {list(self.SCENARIOS)}")

        # Reset RNG so scenarios are reproducible independently
        self._rng = random.Random(self._seed)

        if base_time is None:
            base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)

        records: List[Dict] = []

        # --- Normal background traffic ---
        duration_seconds = 3600  # 1 hour window
        for _ in range(n_normal):
            offset = self._rng.uniform(0, duration_seconds)
            ts = base_time + timedelta(seconds=offset)
            svc = self._rng.choice(SERVICES)
            records.append(_normal_record(ts, svc, self._rng))

        # --- Incident records ---
        incident_start = base_time + timedelta(minutes=30)

        if scenario == "db_exhaustion":
            records.extend(_scenario_db_exhaustion(incident_start, 15, self._rng))
        elif scenario == "payment_latency":
            records.extend(_scenario_payment_latency(incident_start, 15, self._rng))
        elif scenario == "inventory_cascade":
            records.extend(_scenario_inventory_cascade(incident_start, 15, self._rng))
        # "normal" – no incident records added

        records.sort(key=lambda r: r["timestamp"])
        logger.info("Generated %d log records for scenario '%s'", len(records), scenario)
        return records

    def save_csv(self, records: List[Dict], path: str) -> str:
        """Persist records to a CSV file, returning the resolved path."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        fieldnames = ["timestamp", "service", "log_level", "message",
                      "request_id", "trace_id", "latency_ms", "hostname"]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        logger.info("Saved %d records to %s", len(records), path)
        return path

    def save_json(self, records: List[Dict], path: str) -> str:
        """Persist records to a JSON Lines file, returning the resolved path."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec) + "\n")
        logger.info("Saved %d records to %s", len(records), path)
        return path
