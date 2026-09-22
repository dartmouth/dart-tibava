import base64
import json
import logging
import re
from typing import List, Optional

import requests

from .communication import ExponentialBackoff

logger = logging.getLogger(__name__)

MAX_LABEL_LENGTH = 200
MAX_CANDIDATES = 3

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def build_geolocation_prompt(year: Optional[str] = None) -> str:
    year_hint = ""
    if year:
        year_hint = f" This footage is from approximately the year {year}."

    return (
        "You are given one or more video frames from the same shot of a video."
        " Identify the most likely real-world geographic location shown in"
        f" these frames.{year_hint} Respond with a JSON array of up to 3"
        ' candidate locations, ranked from most to least likely, each an'
        ' object with the keys "label" (a short human-readable place name),'
        ' "lat" and "lon" (decimal degrees), and "confidence" (a number'
        " between 0 and 1). If no reasonable guess can be made, respond with"
        " an empty JSON array. Respond with only the JSON array and no"
        " additional text."
    )


class GeolocationLLMError(Exception):
    pass


class GeolocationLLMClient:
    def __init__(self, api_url: str, api_key: str, max_attempts: int = 4):
        self.api_url = api_url
        self.api_key = api_key
        self.max_attempts = max_attempts
        self.backoff = ExponentialBackoff(
            init_backoff_ms=500, max_backoff_ms=8000, multiplier=2
        )

    def locate(self, images: List[bytes], prompt: str) -> List[dict]:
        # Placeholder request shape: the external LLM endpoint isn't finalized
        # yet, so this is the seam to adjust once it is.
        payload = {
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii") for image in images],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_error = None
        for attempt in range(self.max_attempts):
            try:
                response = requests.post(
                    self.api_url, json=payload, headers=headers, timeout=60
                )
                response.raise_for_status()
                return self._parse_response(response.text)
            except (requests.RequestException, GeolocationLLMError) as e:
                last_error = e
                logger.warning(
                    "Geolocation LLM request failed (attempt %s/%s): %s",
                    attempt + 1,
                    self.max_attempts,
                    e,
                )
                if attempt < self.max_attempts - 1:
                    self.backoff.sleep(attempt)

        raise GeolocationLLMError(
            f"Geolocation LLM request failed after {self.max_attempts} attempts: {last_error}"
        )

    def _parse_response(self, text: str) -> List[dict]:
        cleaned = _JSON_FENCE_RE.sub("", text.strip()).strip()
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise GeolocationLLMError(f"Could not parse LLM response as JSON: {e}")

        if not isinstance(data, list):
            raise GeolocationLLMError("Expected a JSON array of candidate locations")

        candidates = []
        for item in data[:MAX_CANDIDATES]:
            try:
                candidates.append(
                    {
                        "label": str(item["label"])[:MAX_LABEL_LENGTH],
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "confidence": float(item.get("confidence", 0.0)),
                    }
                )
            except (KeyError, TypeError, ValueError) as e:
                logger.warning("Skipping malformed geolocation candidate %r: %s", item, e)

        return candidates
