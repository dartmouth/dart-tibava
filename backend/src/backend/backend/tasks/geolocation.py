import hashlib
import io
import json
import logging
import os
import shutil
from typing import Dict, List, Optional

import imageio
import PIL.Image

from backend.models import (
    Annotation,
    AnnotationCategory,
    PluginRun,
    Timeline,
    TimelineSegment,
    TimelineSegmentAnnotation,
    TibavaUser,
    Video,
)
from backend.plugin_manager import PluginManager
from backend.utils import image_normalize, image_resize, media_path_to_video
from backend.utils.color import get_color_from_label
from backend.utils.llm_client import (
    GeolocationLLMClient,
    MockGeolocationLLMClient,
    build_geolocation_prompt,
)
from backend.utils.parser import Parser
from backend.utils.task import Task
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

MAX_FRAMES_PER_SHOT = 4
MAX_FRAME_DIM = 1024
GEOLOCATION_CACHE_ROOT = "/predictions/geolocation"


@PluginManager.export_parser("geolocation")
class GeolocationParser(Parser):
    def __init__(self):
        self.valid_parameter = {
            "timeline": {"parser": str, "default": "Geolocation"},
            "shot_timeline_id": {"default": None},
            "fps": {"parser": float, "default": 2},
            "confidence_threshold": {"parser": float, "default": 0.3},
            "year": {"parser": str, "default": None},
            "prompt": {"parser": str, "default": None},
        }


def _sample_timestamps(start: float, end: float, fps: float, max_frames: int) -> List[float]:
    if fps <= 0:
        fps = 1.0
    step = 1.0 / fps

    timestamps = []
    t = start
    while t < end and len(timestamps) < max_frames:
        timestamps.append(t)
        t += step

    if not timestamps:
        timestamps = [start]

    return timestamps


def _extract_shot_frames(video_path: str, shots_with_timestamps) -> Dict[str, List]:
    # Single sequential pass over the video collecting every sampled frame,
    # instead of seeking per-shot (slow/imprecise with ffmpeg-backed readers).
    targets = sorted(
        (
            (timestamp, shot_id)
            for shot_id, timestamps in shots_with_timestamps
            for timestamp in timestamps
        ),
        key=lambda x: x[0],
    )

    frames_by_shot: Dict[str, List] = {}
    if not targets:
        return frames_by_shot

    reader = imageio.get_reader(video_path)
    try:
        fps = reader.get_meta_data().get("fps") or 1.0
        target_idx = 0
        n_targets = len(targets)

        for frame_idx, frame in enumerate(reader):
            if target_idx >= n_targets:
                break
            frame_time = frame_idx / fps
            while target_idx < n_targets and frame_time >= targets[target_idx][0]:
                _, shot_id = targets[target_idx]
                frames_by_shot.setdefault(shot_id, []).append(frame)
                target_idx += 1
    finally:
        reader.close()

    return frames_by_shot


def _encode_frame_jpeg(frame, max_dim: int = MAX_FRAME_DIM) -> bytes:
    frame = image_normalize(frame)
    frame = image_resize(frame, max_dim=max_dim)
    buf = io.BytesIO()
    PIL.Image.fromarray(frame).convert("RGB").save(buf, format="JPEG")
    return buf.getvalue()


# Per-shot LLM results are cached to disk under /predictions (bind-mounted on
# both the backend and celery containers) so an interrupted/retried run only
# resubmits shots it doesn't already have a result for, instead of redoing
# the whole video - the geolocation LLM call is slow and has no overall task
# timeout, so a long run that gets interrupted previously lost all progress.
#
# The cache directory is fingerprinted on whatever affects what's actually
# asked of the LLM (fps, model, resolved prompt) - not confidence_threshold,
# which is applied fresh from the raw cached candidates every time, so
# changing just the threshold never requires new LLM calls. Matching is
# per-shot (by the shot's own start/end), not a whole-sequence comparison, so
# a shot-detection tweak that only changes a few boundaries still reuses
# everything else; a fully different shot list naturally matches nothing and
# falls back to a fresh run.
def _geolocation_cache_dir(video_id: str, fps: float, model: str, prompt: str) -> str:
    fingerprint = hashlib.sha1(f"{fps}|{model}|{prompt}".encode("utf-8")).hexdigest()[:16]
    return os.path.join(GEOLOCATION_CACHE_ROOT, video_id, fingerprint)


def _shot_cache_path(cache_dir: str, start: float, end: float) -> str:
    return os.path.join(cache_dir, f"{start:.3f}_{end:.3f}.json")


def _load_cached_shot(cache_dir: str, start: float, end: float) -> Optional[List[dict]]:
    path = _shot_cache_path(cache_dir, start, end)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)["candidates"]
    except (OSError, ValueError, KeyError) as e:
        logger.warning("Ignoring unreadable geolocation cache entry %s: %s", path, e)
        return None


def _save_cached_shot(cache_dir: str, start: float, end: float, candidates: List[dict]) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    path = _shot_cache_path(cache_dir, start, end)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump({"start": start, "end": end, "candidates": candidates}, f)
    os.replace(tmp_path, path)


def _clear_geolocation_cache(cache_dir: str) -> None:
    shutil.rmtree(cache_dir, ignore_errors=True)


@PluginManager.export_plugin("geolocation")
class Geolocation(Task):
    def __init__(self):
        self.config = {
            "max_frames_per_shot": MAX_FRAMES_PER_SHOT,
        }

    def __call__(
        self,
        parameters: Dict,
        video: Video = None,
        user: TibavaUser = None,
        plugin_run: PluginRun = None,
        dry_run: bool = False,
        **kwargs,
    ):
        shot_timeline_id = parameters.get("shot_timeline_id")
        if not shot_timeline_id:
            raise ValueError("Geolocation requires a shot_timeline_id")

        if settings.DEBUG:
            client = MockGeolocationLLMClient()
        else:
            api_url = settings.GEOLOCATION_LLM_API_URL
            api_key = settings.GEOLOCATION_LLM_API_KEY
            model = settings.GEOLOCATION_LLM_API_MODEL
            if not api_url or not api_key or not model:
                raise ValueError(
                    "Geolocation LLM is not configured: set GEOLOCATION_LLM_API_URL, "
                    "GEOLOCATION_LLM_API_KEY, and GEOLOCATION_LLM_API_MODEL"
                )
            client = GeolocationLLMClient(
                api_url=api_url,
                api_key=api_key,
                model=model,
                timeout=settings.GEOLOCATION_LLM_TIMEOUT_SECONDS,
            )

        if plugin_run is not None:
            plugin_run.status = PluginRun.STATUS_RUNNING
            plugin_run.save()

        shot_timeline_db = Timeline.objects.get(id=shot_timeline_id)
        shot_segments = list(TimelineSegment.objects.filter(timeline=shot_timeline_db))
        if not shot_segments:
            raise ValueError("Selected shot timeline has no segments")

        video_path = media_path_to_video(video.file.hex, video.ext)
        fps = parameters.get("fps")
        confidence_threshold = parameters.get("confidence_threshold")
        prompt = build_geolocation_prompt(parameters.get("year"), parameters.get("prompt"))

        cache_dir = _geolocation_cache_dir(
            video.id.hex, fps, getattr(client, "model", "mock"), prompt
        )

        n_shots = len(shot_segments)
        results_by_shot = {}
        for shot in shot_segments:
            cached = _load_cached_shot(cache_dir, shot.start, shot.end)
            if cached is not None:
                results_by_shot[shot.id] = cached

        cache_hits = len(results_by_shot)
        if plugin_run is not None:
            plugin_run.progress = cache_hits / n_shots
            plugin_run.save()

        remaining_shots = [shot for shot in shot_segments if shot.id not in results_by_shot]

        shots_with_timestamps = [
            (shot.id, _sample_timestamps(shot.start, shot.end, fps, MAX_FRAMES_PER_SHOT))
            for shot in remaining_shots
        ]
        frames_by_shot = _extract_shot_frames(video_path, shots_with_timestamps)

        for i, shot in enumerate(remaining_shots):
            frames = frames_by_shot.get(shot.id, [])
            if not frames:
                logger.warning("No frames extracted for shot %s, skipping", shot.id)
                candidates = []
            else:
                encoded_frames = [_encode_frame_jpeg(frame) for frame in frames]
                candidates = client.locate(
                    encoded_frames, prompt, request_label=f"shot={shot.id}"
                )
                logger.info(
                    "Geolocation parsed candidates shot=%s: %s",
                    shot.id,
                    [(c["label"], c["confidence"]) for c in candidates],
                )

            results_by_shot[shot.id] = candidates
            _save_cached_shot(cache_dir, shot.start, shot.end, candidates)

            if plugin_run is not None:
                plugin_run.progress = (cache_hits + i + 1) / n_shots
                plugin_run.save()

        if dry_run or plugin_run is None:
            logging.warning("dry_run or plugin_run is None")
            return {}

        results_by_shot = {
            shot_id: [c for c in candidates if c["confidence"] >= confidence_threshold]
            for shot_id, candidates in results_by_shot.items()
        }

        with transaction.atomic():
            category_db, _ = AnnotationCategory.objects.get_or_create(
                name="Geolocation", video=video, owner=user
            )

            # Replace a previous run's results for this video/category instead of
            # stacking a second timeline next to it. Matches both the parent and
            # its child timelines (each carries category-tagged annotations too),
            # and cascades to their segments/annotations.
            Timeline.objects.filter(
                video=video,
                timelinesegment__annotations__category=category_db,
            ).distinct().delete()
            Annotation.objects.filter(video=video, category=category_db).delete()

            # Discover the unique set of locations detected anywhere in the video
            # (order of first appearance) - each becomes a real child timeline.
            unique_labels = []
            first_candidate_by_label = {}
            for shot in shot_segments:
                for candidate in results_by_shot.get(shot.id, []):
                    label = candidate["label"]
                    if label not in first_candidate_by_label:
                        first_candidate_by_label[label] = candidate
                        unique_labels.append(label)

            parent_timeline_db = Timeline.objects.create(
                video=video,
                name=parameters.get("timeline"),
                type=Timeline.TYPE_ANNOTATION,
            )

            child_timeline_by_label = {
                label: Timeline.objects.create(
                    video=video,
                    name=label,
                    type=Timeline.TYPE_ANNOTATION,
                    parent=parent_timeline_db,
                    geo_point={
                        "lat": first_candidate_by_label[label]["lat"],
                        "lon": first_candidate_by_label[label]["lon"],
                    },
                )
                for label in unique_labels
            }

            for shot in shot_segments:
                candidates = results_by_shot.get(shot.id, [])
                candidates_by_label = {c["label"]: c for c in candidates}

                parent_segment_db = TimelineSegment.objects.create(
                    timeline=parent_timeline_db,
                    start=shot.start,
                    end=shot.end,
                )

                top_candidate = max(
                    candidates, key=lambda c: c["confidence"], default=None
                )
                if top_candidate is not None:
                    label = top_candidate["label"]
                    annotation_db = Annotation.objects.create(
                        name=label,
                        video=video,
                        category=category_db,
                        owner=user,
                        color=get_color_from_label(label),
                    )
                    TimelineSegmentAnnotation.objects.create(
                        annotation=annotation_db,
                        timeline_segment=parent_segment_db,
                    )

                for label in unique_labels:
                    child_segment_db = TimelineSegment.objects.create(
                        timeline=child_timeline_by_label[label],
                        start=shot.start,
                        end=shot.end,
                    )

                    candidate = candidates_by_label.get(label)
                    if candidate is not None:
                        annotation_db = Annotation.objects.create(
                            name=f"{round(candidate['confidence'] * 100)}%",
                            video=video,
                            category=category_db,
                            owner=user,
                            color=get_color_from_label(label),
                        )
                        TimelineSegmentAnnotation.objects.create(
                            annotation=annotation_db,
                            timeline_segment=child_segment_db,
                        )

            # Only clear the cache once every shot's result has been
            # successfully written to the DB - if anything above raised, the
            # cache is left in place so a retry can resume from it.
            _clear_geolocation_cache(cache_dir)

            return {
                "plugin_run": plugin_run.id.hex,
                "plugin_run_results": [],
                "timelines": {
                    "annotations": parent_timeline_db.id.hex,
                    **{
                        f"location_{label}": timeline.id.hex
                        for label, timeline in child_timeline_by_label.items()
                    },
                },
                "data": {},
            }
