"""
Unit tests for the log generator.
"""

import pytest
from datetime import datetime, timedelta, timezone
from src.generator.log_generator import LogGenerator


class TestLogGenerator:
    """Test suite for LogGenerator."""

    def test_generator_init(self):
        """Test generator initialization."""
        gen = LogGenerator(seed=42)
        assert gen is not None

    def test_normal_scenario(self):
        """Test normal traffic scenario generation."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="normal", n_normal=100, n_incident=0)

        assert len(records) >= 100
        assert all(rec.get("service") in ["api-gateway", "order-service", "payment-service",
                                          "inventory-service", "database-service"]
                   for rec in records)
        assert all(rec.get("timestamp") for rec in records)

    def test_db_exhaustion_scenario(self):
        """Test database exhaustion scenario."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="db_exhaustion", n_normal=100, n_incident=100)

        db_errors = [r for r in records if r["service"] == "database-service" and r["log_level"] == "ERROR"]
        assert len(db_errors) > 0, "Database should have errors in exhaustion scenario"

        # Check for cascade to dependent services
        order_errors = [r for r in records if r["service"] == "order-service" and r["log_level"] == "ERROR"]
        assert len(order_errors) > 0, "Order service should have cascading errors"

    def test_payment_latency_scenario(self):
        """Test payment latency spike scenario."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="payment_latency", n_normal=100, n_incident=100)

        payment_records = [r for r in records if r["service"] == "payment-service"]
        avg_latency = sum(r.get("latency_ms", 0) for r in payment_records) / max(len(payment_records), 1)

        assert avg_latency > 2000, "Payment service should have elevated latency"

    def test_inventory_cascade_scenario(self):
        """Test inventory cascade scenario."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="inventory_cascade", n_normal=100, n_incident=100)

        inventory_errors = [r for r in records if r["service"] == "inventory-service"
                           and r["log_level"] == "ERROR"]
        assert len(inventory_errors) > 0, "Inventory should have errors"

        # Check for cascade
        order_errors = [r for r in records if r["service"] == "order-service"
                       and r["log_level"] == "ERROR"]
        assert len(order_errors) > 0, "Order service should show cascade effects"

    def test_reproducibility(self):
        """Test that same seed produces same records."""
        base_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        
        gen1 = LogGenerator(seed=42)
        records1 = gen1.generate(scenario="db_exhaustion", n_normal=50, n_incident=50, base_time=base_time)

        gen2 = LogGenerator(seed=42)
        records2 = gen2.generate(scenario="db_exhaustion", n_normal=50, n_incident=50, base_time=base_time)

        assert len(records1) == len(records2)
        assert records1[0]["timestamp"] == records2[0]["timestamp"]
        assert records1[0]["service"] == records2[0]["service"]

    def test_different_seeds_produce_different_records(self):
        """Test that different seeds produce different records."""
        gen1 = LogGenerator(seed=42)
        records1 = gen1.generate(scenario="normal", n_normal=100, n_incident=0)

        gen2 = LogGenerator(seed=99)
        records2 = gen2.generate(scenario="normal", n_normal=100, n_incident=0)

        # At least some records should differ
        differences = sum(
            1 for r1, r2 in zip(records1, records2)
            if r1["service"] != r2["service"] or r1["log_level"] != r2["log_level"]
        )
        assert differences > 0, "Different seeds should produce different records"

    def test_record_schema(self):
        """Test that generated records have expected schema."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="normal", n_normal=10, n_incident=0)

        required_fields = {"timestamp", "service", "log_level", "message",
                          "request_id", "trace_id", "latency_ms", "hostname"}

        for record in records:
            assert required_fields.issubset(set(record.keys())), f"Record missing fields: {record}"

    def test_csv_persistence(self, tmp_path):
        """Test CSV file persistence."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="normal", n_normal=50, n_incident=0)

        csv_path = str(tmp_path / "test_logs.csv")
        saved_path = gen.save_csv(records, csv_path)

        import csv
        with open(saved_path, "r") as fh:
            reader = csv.DictReader(fh)
            loaded = list(reader)

        assert len(loaded) == len(records), "Persisted record count should match"

    def test_json_persistence(self, tmp_path):
        """Test JSON Lines persistence."""
        gen = LogGenerator(seed=42)
        records = gen.generate(scenario="normal", n_normal=50, n_incident=0)

        json_path = str(tmp_path / "test_logs.jsonl")
        saved_path = gen.save_json(records, json_path)

        import json
        with open(saved_path, "r") as fh:
            loaded = [json.loads(line) for line in fh]

        assert len(loaded) == len(records), "Persisted record count should match"
