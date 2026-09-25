# DEBUG-only dev/testing utility (see README.md, "Testing LLM/API-based
# plugins without a real endpoint"). Point a plugin's outbound LLM/API-URL
# setting (e.g. GEOLOCATION_LLM_API_URL) at
# http://backend:8000/llm/test-echo/<plugin_name>/ to log the outbound
# request instead of hitting a real external API, and to get back a fixed
# response so the rest of the pipeline (parsing, DB writes) can be exercised.
# Returns 404 unless DEBUG=true, so it's kept in the codebase as a reusable
# tool rather than deleted after each use.
#
# To watch the log lines this endpoint writes while testing:
#   docker-compose logs -f backend celery

import hashlib
import json
import logging
import random

from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

MAX_STRING_LEN = 300
SENSITIVE_HEADER_HINTS = ("authorization", "key", "token", "secret")

# Same sample city names/coordinates used by the frontend's LOCATION_FIXTURE
# (frontend/src/plugins/geolocationSampleData.js) so a mocked run's predicted
# locations line up with what was already used to build/test the map UI.
SAMPLE_LOCATIONS = [
    {"label": "Anchorage, United States", "lat": 61.2181, "lon": -149.9003},
    {"label": "Honolulu, United States", "lat": 21.3069, "lon": -157.8583},
    {"label": "Vancouver, Canada", "lat": 49.2827, "lon": -123.1207},
    {"label": "San Francisco, United States", "lat": 37.7749, "lon": -122.4194},
    {"label": "Mexico City, Mexico", "lat": 19.4326, "lon": -99.1332},
    {"label": "New York, United States", "lat": 40.7128, "lon": -74.006},
    {"label": "Sao Paulo, Brazil", "lat": -23.5505, "lon": -46.6333},
    {"label": "Buenos Aires, Argentina", "lat": -34.6037, "lon": -58.3816},
    {"label": "Reykjavik, Iceland", "lat": 64.1466, "lon": -21.9426},
    {"label": "London, United Kingdom", "lat": 51.5072, "lon": -0.1276},
    {"label": "Paris, France", "lat": 48.8566, "lon": 2.3522},
    {"label": "Rome, Italy", "lat": 41.9028, "lon": 12.4964},
    {"label": "Cairo, Egypt", "lat": 30.0444, "lon": 31.2357},
    {"label": "Nairobi, Kenya", "lat": -1.2921, "lon": 36.8219},
    {"label": "Cape Town, South Africa", "lat": -33.9249, "lon": 18.4241},
    {"label": "Moscow, Russia", "lat": 55.7558, "lon": 37.6173},
    {"label": "Dubai, United Arab Emirates", "lat": 25.2048, "lon": 55.2708},
    {"label": "Mumbai, India", "lat": 19.076, "lon": 72.8777},
    {"label": "Delhi, India", "lat": 28.6139, "lon": 77.209},
    {"label": "Bangkok, Thailand", "lat": 13.7563, "lon": 100.5018},
    {"label": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"label": "Beijing, China", "lat": 39.9042, "lon": 116.4074},
    {"label": "Seoul, South Korea", "lat": 37.5665, "lon": 126.978},
    {"label": "Tokyo, Japan", "lat": 35.6762, "lon": 139.6503},
    {"label": "Manila, Philippines", "lat": 14.5995, "lon": 120.9842},
    {"label": "Jakarta, Indonesia", "lat": -6.2088, "lon": 106.8456},
    {"label": "Perth, Australia", "lat": -31.9505, "lon": 115.8605},
    {"label": "Sydney, Australia", "lat": -33.8688, "lon": 151.2093},
    {"label": "Melbourne, Australia", "lat": -37.8136, "lon": 144.9631},
    {"label": "Auckland, New Zealand", "lat": -36.8485, "lon": 174.7633},
]


def _random_geolocation_candidates():
    picks = random.sample(SAMPLE_LOCATIONS, random.randint(1, 3))
    candidates = [
        {**pick, "confidence": round(random.uniform(0.3, 0.98), 2)} for pick in picks
    ]
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


# Canned responses per plugin name, so a plugin whose task expects a
# particular shape (e.g. geolocation's candidate list) can exercise its
# real parsing/DB-write code against a valid reply. A value may be a plain
# list (returned as-is) or a callable (invoked per request, e.g. to
# randomize). Plugins without an entry here get an empty list back.
FIXTURES = {
    "geolocation": _random_geolocation_candidates,
}


def _mask_header(name: str, value: str) -> str:
    if any(hint in name.lower() for hint in SENSITIVE_HEADER_HINTS):
        if len(value) <= 8:
            return "***"
        return f"{value[:6]}***{value[-4:]}"
    return value


def _summarize(value):
    if isinstance(value, str):
        if len(value) > MAX_STRING_LEN:
            # A truncated prefix alone is a poor signal for base64 images:
            # most encoders emit identical header bytes (JPEG's SOI/JFIF
            # segment, default quantization tables) regardless of image
            # content, so distinct frames and accidental duplicate frames
            # look the same in a short prefix. Hash the full string instead
            # so identical vs. distinct values are obvious at a glance.
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
            return f"<string, {len(value)} chars, sha256={digest}> {value[:40]}..."
        return value
    if isinstance(value, list):
        return [_summarize(v) for v in value]
    if isinstance(value, dict):
        return {k: _summarize(v) for k, v in value.items()}
    return value


@csrf_exempt
def llm_test_echo(request, plugin_name: str):
    if not settings.DEBUG:
        return HttpResponseNotFound()

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = f"<{len(request.body)} bytes, not valid JSON>"

    logger.info(
        "llm_test_echo: plugin_name=%s method=%s path=%s content_type=%s "
        "content_length=%s headers=%s body=%s",
        plugin_name,
        request.method,
        request.path,
        request.content_type,
        request.headers.get("Content-Length"),
        {k: _mask_header(k, v) for k, v in request.headers.items()},
        _summarize(body),
    )

    fixture = FIXTURES.get(plugin_name, [])
    return JsonResponse(fixture() if callable(fixture) else fixture, safe=False)
