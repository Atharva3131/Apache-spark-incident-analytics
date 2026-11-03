"""
Unit tests for Sarvam AI integration.

These tests verify request construction and response parsing without making actual API calls.
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from config.settings import SarvamConfig
from src.investigation.sarvam_client import SarvamInvestigator
from src.models.incident import RCAResponse, Severity


class TestSarvamIntegration:
    """Test Sarvam AI integration."""

    @pytest.fixture
    def sarvam_config(self):
        """Create a Sarvam config for testing."""
        return SarvamConfig(
            api_key="test-key-12345",
            api_base_url="https://api.sarvam.ai/v2",
            model="sarvam-105b",
            timeout_seconds=60,
        )

    @pytest.fixture
    def investigator(self, sarvam_config):
        """Create a Sarvam investigator for testing."""
        return SarvamInvestigator(sarvam_config)

    def test_sarvam_config_defaults(self):
        """Test that Sarvam config has correct V2 defaults."""
        config = SarvamConfig()
        assert config.api_base_url == "https://api.sarvam.ai/v2"
        assert config.model == "sarvam-105b"
        assert config.timeout_seconds == 60

    def test_sarvam_config_from_env(self):
        """Test that Sarvam config can be customized via environment."""
        import os
        os.environ["SARVAM_API_BASE_URL"] = "https://custom.api.sarvam.ai/v2"
        os.environ["SARVAM_MODEL"] = "custom-model"

        # Force reload by creating new config
        config = SarvamConfig(
            api_key="test-key",
            api_base_url=os.getenv("SARVAM_API_BASE_URL", "https://api.sarvam.ai/v2"),
            model=os.getenv("SARVAM_MODEL", "sarvam-105b"),
        )

        assert config.api_base_url == "https://custom.api.sarvam.ai/v2"
        assert config.model == "custom-model"

        # Clean up
        del os.environ["SARVAM_API_BASE_URL"]
        del os.environ["SARVAM_MODEL"]

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_request_uses_api_subscription_key_header(self, mock_post, investigator):
        """Test that Sarvam requests use api-subscription-key header (not Bearer token)."""
        # Mock a successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Test Incident",
                            "severity": "HIGH",
                            "summary": "Test summary",
                            "probable_root_cause": "Test root cause",
                            "supporting_evidence": [],
                            "affected_services": ["test-service"],
                            "timeline": [],
                            "recommended_actions": [],
                            "uncertainties": [],
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        # Call the API
        result = investigator.investigate(
            incident_summary="Test incident",
            affected_services=["test-service"],
            error_evidence=["error 1"],
            probable_root_cause="Root cause",
        )

        # Verify the request was made
        assert mock_post.called
        call_kwargs = mock_post.call_args[1]

        # Verify headers use api-subscription-key (not Authorization: Bearer)
        headers = call_kwargs["headers"]
        assert "api-subscription-key" in headers
        assert headers["api-subscription-key"] == "test-key-12345"
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_request_includes_json_response_format(self, mock_post, investigator):
        """Test that Sarvam requests include response_format for JSON output."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Test",
                            "severity": "MEDIUM",
                            "summary": "Test",
                            "probable_root_cause": "Test",
                            "supporting_evidence": [],
                            "affected_services": [],
                            "timeline": [],
                            "recommended_actions": [],
                            "uncertainties": [],
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        investigator.investigate("Summary", [], [], "Root cause")

        # Verify request payload includes response_format
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_object"

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_request_url_is_v2(self, mock_post, investigator):
        """Test that Sarvam requests go to the V2 endpoint."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Test",
                            "severity": "LOW",
                            "summary": "Test",
                            "probable_root_cause": "Test",
                            "supporting_evidence": [],
                            "affected_services": [],
                            "timeline": [],
                            "recommended_actions": [],
                            "uncertainties": [],
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        investigator.investigate("Summary", [], [], "Root cause")

        # Verify URL is V2 endpoint
        call_args = mock_post.call_args
        url = call_args[0][0]

        assert url == "https://api.sarvam.ai/v2/chat/completions"

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_response_parsing_success(self, mock_post, investigator):
        """Test that Sarvam successfully parses valid JSON responses."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Database Pool Exhaustion",
                            "severity": "CRITICAL",
                            "summary": "Database connection pool exhausted",
                            "probable_root_cause": "Long-running queries",
                            "supporting_evidence": ["High error rate", "Connection timeouts"],
                            "affected_services": ["order-service", "api-gateway"],
                            "timeline": [],
                            "recommended_actions": ["Increase pool size", "Optimize queries"],
                            "uncertainties": ["External factor?"],
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Database issue",
            affected_services=["order-service"],
            error_evidence=["Connection refused"],
            probable_root_cause="Connection pool",
        )

        assert result is not None
        assert isinstance(result, RCAResponse)
        assert result.incident_title == "Database Pool Exhaustion"
        assert result.severity == Severity.CRITICAL
        assert len(result.affected_services) == 2
        assert "Increase pool size" in result.recommended_actions

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_no_api_key_returns_none(self, mock_post):
        """Test that investigation returns None when API key is not configured."""
        config = SarvamConfig(api_key=None)
        investigator = SarvamInvestigator(config)

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None
        assert not mock_post.called

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_malformed_json_returns_none(self, mock_post, investigator):
        """Test that malformed JSON responses are handled gracefully."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "This is not valid JSON"
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_connection_error_returns_none(self, mock_post, investigator):
        """Test that connection errors are handled gracefully."""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_timeout_returns_none(self, mock_post, investigator):
        """Test that timeout errors are handled gracefully."""
        import requests
        mock_post.side_effect = requests.exceptions.Timeout("Timeout")

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None


    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_empty_content_with_finish_reason(self, mock_post, investigator):
        """Test that empty content with diagnostic finish_reason is handled."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "sarvam-105b",
            "id": "test-id",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "Some reasoning but no output"
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            }
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_finish_reason_length_token_budget_fallback(self, mock_post, investigator):
        """Test that finish_reason='length' triggers controlled fallback (returns None, logs warning)."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "sarvam-105b",
            "id": "test-id-length",
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Truncated",
                            "severity": "HIGH",
                            "summary": "Incomplete",
                            "probable_root_cause": "Budget exceeded",
                            "supporting_evidence": [],
                            "affected_services": [],
                            "timeline": [],
                            "recommended_actions": [],
                            "uncertainties": [],
                        })
                    },
                    "finish_reason": "length"
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 2048,
                "total_tokens": 3048
            }
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        # Should return None and let dashboard fall back to deterministic RCA
        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_content_null(self, mock_post, investigator):
        """Test that null content is handled."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_max_tokens_2048(self, mock_post, investigator):
        """Test that max_tokens is optimized to 2048 for concise RCA."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Test",
                            "severity": "MEDIUM",
                            "summary": "Test",
                            "probable_root_cause": "Test",
                            "root_cause_reasoning": "Reasoning",
                            "supporting_evidence": [],
                            "affected_services": [],
                            "failure_propagation": "Chain",
                            "recommended_actions": [],
                            "confidence": "HIGH",
                            "uncertainties": [],
                        })
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        investigator.investigate("Summary", [], [], "Root cause")

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        assert payload["max_tokens"] == 2048

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_reasoning_content_not_in_response(self, mock_post, investigator):
        """Test that reasoning_content is not mistaken for output."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "sarvam-105b",
            "id": "test-reasoning",
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Final Response",
                            "severity": "HIGH",
                            "summary": "Actual response",
                            "probable_root_cause": "Root cause",
                            "supporting_evidence": ["Evidence"],
                            "affected_services": ["service1"],
                            "timeline": [],
                            "recommended_actions": ["Action"],
                            "uncertainties": [],
                        }),
                        "reasoning_content": "Internal reasoning not for user..."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 800,
                "total_tokens": 1300
            }
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=["service1"],
            error_evidence=["Error"],
            probable_root_cause="Root cause",
        )

        assert result is not None
        assert result.incident_title == "Final Response"
        assert result.summary == "Actual response"

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_optimized_concise_response(self, mock_post, investigator):
        """Test that optimized Sarvam response with confidence and reasoning is parsed correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "model": "sarvam-105b",
            "id": "test-optimized",
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Database Connection Pool Exhaustion",
                            "severity": "CRITICAL",
                            "summary": "Database connection pool exhausted due to long-running queries.",
                            "probable_root_cause": "Unoptimized query in inventory-service",
                            "root_cause_reasoning": "Query took 45s average, blocking 95% of connections.",
                            "supporting_evidence": [
                                "Avg query latency: 45000ms",
                                "Connection errors: 2000/min",
                                "Error rate in inventory-service: 95%"
                            ],
                            "affected_services": ["inventory-service", "order-service", "api-gateway"],
                            "failure_propagation": "inventory-service blocked → order-service timeouts → api-gateway failures",
                            "recommended_actions": [
                                "Optimize inventory query or add query timeout",
                                "Increase database connection pool size",
                                "Implement circuit breaker in order-service"
                            ],
                            "confidence": "HIGH",
                            "uncertainties": []
                        })
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 400,
                "completion_tokens": 350,
                "total_tokens": 750
            }
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Database connection errors in production",
            affected_services=["inventory-service", "order-service", "api-gateway"],
            error_evidence=[
                "Avg query latency: 45000ms",
                "Connection errors: 2000/min",
                "Error rate: 95%"
            ],
            probable_root_cause="Unoptimized query",
            scenario_hint="db_exhaustion"
        )

        assert result is not None
        assert result.incident_title == "Database Connection Pool Exhaustion"
        assert result.severity == Severity.CRITICAL
        # Verify propagation chain is captured in uncertainties
        assert any("inventory-service" in u for u in result.uncertainties)
        assert len(result.affected_services) == 3
        # Verify summary is concise and to the point
        assert "pool" in result.summary.lower()
        assert len(result.summary) < 200  # Should be concise

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_evidence_limited_to_top_5(self, mock_post, investigator):
        """Test that prompt limits evidence to top 5 findings."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "incident_title": "Test",
                "severity": "MEDIUM",
                "summary": "Test",
                "probable_root_cause": "Test",
                "supporting_evidence": [],
                "affected_services": [],
                "failure_propagation": "",
                "recommended_actions": [],
                "confidence": "MEDIUM",
                "uncertainties": []
            })}}]
        }
        mock_post.return_value = mock_response

        # Pass 10 evidence items
        many_evidence = [f"Evidence {i}" for i in range(10)]
        
        investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=many_evidence,
            probable_root_cause="Test"
        )

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        prompt = payload["messages"][0]["content"]

        # Verify prompt contains only first 5 evidence items
        for i in range(5):
            assert f"Evidence {i}" in prompt
        # Verify evidence beyond index 5 is NOT in prompt
        for i in range(5, 10):
            assert f"Evidence {i}" not in prompt

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_prompt_is_concise(self, mock_post, investigator):
        """Test that optimized prompt is concise and doesn't include raw logs."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "incident_title": "Test",
                "severity": "MEDIUM",
                "summary": "Test",
                "probable_root_cause": "Test",
                "supporting_evidence": [],
                "affected_services": [],
                "failure_propagation": "",
                "recommended_actions": [],
                "confidence": "MEDIUM",
                "uncertainties": []
            })}}]
        }
        mock_post.return_value = mock_response

        investigator.investigate(
            incident_summary="Test incident",
            affected_services=["svc1", "svc2"],
            error_evidence=["Error 1"],
            probable_root_cause="Root cause",
            scenario_hint="test_scenario"
        )

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]
        prompt = payload["messages"][0]["content"]

        # Verify concise prompt structure
        assert "INCIDENT:" in prompt
        assert "SERVICES:" in prompt
        assert "ROOT CAUSE (from correlation):" in prompt
        assert "KEY EVIDENCE (top 5 findings):" in prompt
        
        # Verify it requires concise output
        assert "brief" in prompt.lower() or "concise" in prompt.lower()
        
        # Verify word limit constraint
        assert "<500 words" in prompt or "concise" in prompt.lower()

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_malformed_json_with_fallback_signal(self, mock_post, investigator):
        """Test that malformed JSON is detected and None is returned for fallback."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "{ malformed json, missing quotes }"
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        # Should return None to trigger deterministic fallback
        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_api_failure_returns_none_for_fallback(self, mock_post, investigator):
        """Test that API failures gracefully return None to trigger fallback."""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError("Network error")

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=[],
            error_evidence=[],
            probable_root_cause="Test",
        )

        # Should return None to trigger deterministic fallback
        assert result is None

    @patch("src.investigation.sarvam_client.requests.post")
    def test_sarvam_confidence_field_logged(self, mock_post, investigator):
        """Test that Sarvam confidence field is recognized and logged."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "incident_title": "Test",
                            "severity": "HIGH",
                            "summary": "Test",
                            "probable_root_cause": "Test root cause",
                            "root_cause_reasoning": "High confidence due to clear evidence",
                            "supporting_evidence": ["Fact 1"],
                            "affected_services": ["svc1"],
                            "failure_propagation": "svc1 → svc2",
                            "recommended_actions": ["Action 1"],
                            "confidence": "HIGH",
                            "uncertainties": []
                        })
                    },
                    "finish_reason": "stop"
                }
            ]
        }
        mock_post.return_value = mock_response

        result = investigator.investigate(
            incident_summary="Test",
            affected_services=["svc1"],
            error_evidence=["Fact 1"],
            probable_root_cause="Root cause",
        )

        # Should successfully parse and return RCA
        assert result is not None
        assert result.incident_title == "Test"
        # Failure propagation should be appended to uncertainties
        assert any("svc1 → svc2" in u for u in result.uncertainties)
