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
