"""
Sarvam AI integration layer.

Sends structured incident data to Sarvam's chat completions V2 API and validates
the response using Pydantic models.

Uses the `api-subscription-key` header for authentication and requests JSON output
with `response_format: {"type": "json_object"}`.

If the API key is missing, credentials fail, or the API is unavailable,
this module gracefully falls back to the deterministic RCA engine.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

from config.settings import SarvamConfig
from src.models.incident import RCAResponse, Severity, TimelineEvent

logger = logging.getLogger(__name__)


class SarvamInvestigator:
    """
    Wrapper around the Sarvam AI chat API.
    """

    def __init__(self, config: SarvamConfig):
        self._config = config

    def investigate(
        self,
        incident_summary: str,
        affected_services: list,
        error_evidence: list,
        probable_root_cause: str,
        scenario_hint: str = "unknown",
    ) -> Optional[RCAResponse]:
        """
        Call Sarvam API to generate an investigation report.

        Args:
            incident_summary: summary of the incident
            affected_services: list of service names
            error_evidence: list of error/anomaly descriptions
            probable_root_cause: primary root cause from correlator
            scenario_hint: hint about the incident type

        Returns:
            RCAResponse if successful; None if API is unavailable or response is invalid.
        """

        if not self._config.api_key:
            logger.warning("Sarvam API key not configured – skipping LLM investigation")
            return None

        # Build the prompt
        prompt = self._build_prompt(
            incident_summary,
            affected_services,
            error_evidence,
            probable_root_cause,
            scenario_hint,
        )

        try:
            response = self._call_api(prompt)
            if response is None:
                return None
            return self._parse_response(response)
        except Exception as e:
            logger.error("Sarvam investigation failed: %s", e)
            return None

    def _build_prompt(
        self,
        incident_summary: str,
        affected_services: list,
        error_evidence: list,
        probable_root_cause: str,
        scenario_hint: str,
    ) -> str:
        """
        Construct a structured prompt for the LLM.
        """
        evidence_text = "\n".join(f"  - {e}" for e in error_evidence[:20])
        services_text = ", ".join(affected_services)

        prompt = f"""You are an expert system reliability engineer investigating a production incident.

INCIDENT SUMMARY:
{incident_summary}

AFFECTED SERVICES:
{services_text}

PROBABLE ROOT CAUSE (from correlation engine):
{probable_root_cause}

SCENARIO HINT:
{scenario_hint}

ERROR EVIDENCE:
{evidence_text}

Based on this information, provide a structured root cause analysis. Your response MUST be valid JSON with this exact structure:

{{
  "incident_title": "Clear, concise title",
  "severity": "LOW | MEDIUM | HIGH | CRITICAL",
  "summary": "Concise summary of the incident",
  "probable_root_cause": "Most likely root cause",
  "supporting_evidence": ["Evidence point 1", "Evidence point 2"],
  "affected_services": ["service1", "service2"],
  "timeline": [
    {{"timestamp": "ISO timestamp", "service": "service name", "event_type": "event type", "description": "event description"}}
  ],
  "recommended_actions": ["Action 1", "Action 2"],
  "uncertainties": ["Unverified hypothesis 1", "Unverified hypothesis 2"]
}}

Remember:
- Do NOT fabricate metrics or logs that were not provided
- Clearly distinguish facts from hypotheses
- Severity should match the data provided
- timeline events should use timestamps from the data or current time
- recommended_actions should be concrete and actionable

Respond ONLY with the JSON object, no other text."""
        return prompt

    def _call_api(self, prompt: str) -> Optional[dict]:
        """
        Call the Sarvam chat completions V2 endpoint.

        Returns the parsed response dict, or None if the call fails.
        Uses api-subscription-key header for authentication and requests JSON output.
        """
        url = f"{self._config.api_base_url}/chat/completions"
        headers = {
            "api-subscription-key": self._config.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
            "response_format": {"type": "json_object"},
        }

        try:
            logger.info("Calling Sarvam V2 API – model: %s, endpoint: %s", self._config.model, url)
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._config.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            logger.debug("Sarvam API response received")
            return data
        except requests.exceptions.Timeout:
            logger.error("Sarvam API call timed out after %d seconds", self._config.timeout_seconds)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("Sarvam API connection error: %s", e)
            return None
        except requests.exceptions.HTTPError as e:
            logger.error("Sarvam API HTTP error: %s", e.response.status_code)
            return None

    def _parse_response(self, api_response: dict) -> Optional[RCAResponse]:
        """
        Extract the LLM's JSON response and validate it as RCAResponse.

        The API returns: {"choices": [{"message": {"content": "..."}}]}
        """
        try:
            choices = api_response.get("choices", [])
            if not choices:
                logger.error("Sarvam response has no choices")
                return None

            content = choices[0].get("message", {}).get("content", "")
            if not content:
                logger.error("Sarvam response content is empty")
                return None

            # Try to extract JSON
            # The LLM should return ONLY JSON, but be defensive
            json_str = content.strip()
            if json_str.startswith("```"):
                # Strip markdown code block
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
                json_str = json_str.strip()

            parsed = json.loads(json_str)

            # Validate & construct RCAResponse
            # Convert timeline dicts back to TimelineEvent objects if needed
            timeline_events = []
            for evt in parsed.get("timeline", []):
                if isinstance(evt, dict):
                    timeline_events.append(TimelineEvent(
                        timestamp=evt.get("timestamp", ""),
                        service=evt.get("service", ""),
                        event_type=evt.get("event_type", ""),
                        description=evt.get("description", ""),
                        severity=Severity(evt.get("severity", "MEDIUM")),
                    ))

            rca = RCAResponse(
                incident_title=parsed.get("incident_title", "Unknown Incident"),
                severity=Severity(parsed.get("severity", "MEDIUM").upper()),
                summary=parsed.get("summary", ""),
                probable_root_cause=parsed.get("probable_root_cause", ""),
                supporting_evidence=parsed.get("supporting_evidence", []),
                affected_services=parsed.get("affected_services", []),
                timeline=timeline_events,
                recommended_actions=parsed.get("recommended_actions", []),
                uncertainties=parsed.get("uncertainties", []),
                generated_by="sarvam_ai",
            )
            logger.info("Sarvam RCAResponse validated successfully")
            return rca

        except json.JSONDecodeError as e:
            logger.error("Failed to parse Sarvam JSON response: %s", e)
            return None
        except (KeyError, ValueError, TypeError) as e:
            logger.error("Sarvam response validation failed: %s", e)
            return None


def investigate_with_sarvam(
    config: SarvamConfig,
    incident_summary: str,
    affected_services: list,
    error_evidence: list,
    probable_root_cause: str,
    scenario_hint: str = "unknown",
) -> Optional[RCAResponse]:
    """
    Convenience function – creates an investigator and calls the API.
    """
    investigator = SarvamInvestigator(config)
    return investigator.investigate(
        incident_summary,
        affected_services,
        error_evidence,
        probable_root_cause,
        scenario_hint,
    )
