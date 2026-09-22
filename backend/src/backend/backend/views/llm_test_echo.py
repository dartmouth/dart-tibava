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

from django.conf import settings
from django.http import HttpResponseNotFound, JsonResponse
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

MAX_STRING_LEN = 300
SENSITIVE_HEADER_HINTS = ("authorization", "key", "token", "secret")

# Canned responses per plugin name, so a plugin whose task expects a
# particular shape (e.g. geolocation's candidate list) can exercise its
# real parsing/DB-write code against a valid reply. Plugins without an
# entry here get an empty list back.
FIXTURES = {
    "geolocation": [
        {"label": "Test Location A", "lat": 48.8566, "lon": 2.3522, "confidence": 0.9},
        {"label": "Test Location B", "lat": 40.7128, "lon": -74.006, "confidence": 0.5},
    ],
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

    return JsonResponse(FIXTURES.get(plugin_name, []), safe=False)
