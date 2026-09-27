// Derives the geolocation UI's "parent row + one child row per location"
// timeline structure from the real Annotation/Timeline data a geolocation
// plugin run writes to the backend (see backend/.../tasks/geolocation.py).
// There, Annotation.name is JSON: {label, lat, lon, confidence}. This module
// parses that once and reshapes it into plain-string-named Timeline/Annotation
// objects, so the existing generic annotation-timeline renderer (which only
// knows how to print annotation.name as text) can display it unmodified.

import axios from "@/plugins/axios";
import config from "../../app.config";
import { useAnnotationCategoryStore } from "@/store/annotation_category";
import { useAnnotationStore } from "@/store/annotation";
import { useTimelineStore } from "@/store/timeline";
import { useTimelineSegmentStore } from "@/store/timeline_segment";
import { useTimelineSegmentAnnotationStore } from "@/store/timeline_segment_annotation";

const CATEGORY_NAME = "Geolocation";

// Blended toward white by confidence; borrowed from the app's original
// sample-data fixture so colors stay visually consistent.
const COLOR_PALETTE = [
  "#4f46e5", "#7c3aed", "#2563eb", "#0891b2", "#0f766e",
  "#16a34a", "#65a30d", "#ca8a04", "#d97706", "#ea580c",
  "#dc2626", "#e11d48", "#db2777", "#9333ea", "#6d28d9",
];

function hashString(value) {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function colorForLabel(label) {
  return COLOR_PALETTE[hashString(label) % COLOR_PALETTE.length];
}

function slugify(label) {
  return label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-+|-+$)/g, "");
}

function hexToRgb(hex) {
  const parsed = hex.replace("#", "");
  const bigint = parseInt(parsed, 16);
  return { r: (bigint >> 16) & 255, g: (bigint >> 8) & 255, b: bigint & 255 };
}

function rgbToHex({ r, g, b }) {
  return `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, "0")).join("")}`;
}

// Blends a base location color toward white as confidence drops, so lower-confidence
// detections render as a paler block on the primary timeline.
function blendTowardWhite(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  const blend = (channel) => channel + (255 - channel) * amount;
  return rgbToHex({ r: blend(r), g: blend(g), b: blend(b) });
}

function parseCandidate(annotation) {
  let candidate;
  try {
    candidate = JSON.parse(annotation.name);
  } catch (e) {
    return null;
  }
  if (!candidate || typeof candidate.label !== "string") return null;
  return {
    tag: candidate.label,
    location: candidate.label,
    latitude: candidate.lat,
    longitude: candidate.lon,
    confidence: candidate.confidence ?? 0,
    color: colorForLabel(candidate.label),
  };
}

// Finds the real "Geolocation" timeline for this video: identified by the
// annotations attached to its segments actually belonging to the given
// AnnotationCategory AND being genuinely raw (JSON-shaped) candidates — not
// by timeline name (user-configurable via the run's `timeline` parameter),
// and not just by category (which our own derived, plain-text rows also
// carry, so a stale derived timeline is never mistaken for the raw source).
function findRawTimeline({ videoId, category }) {
  const annotationStore = useAnnotationStore();
  const timelineSegmentStore = useTimelineSegmentStore();
  const timelineSegmentAnnotationStore = useTimelineSegmentAnnotationStore();

  const hasRawCandidate = (segment) =>
    timelineSegmentAnnotationStore
      .forTimelineSegment(segment.id)
      .some((tsa) => {
        const annotation = annotationStore.get(tsa.annotation_id);
        return annotation && annotation.category_id === category.id && parseCandidate(annotation) !== null;
      });

  return useTimelineStore()
    .forVideo(videoId)
    .find((timeline) => timelineSegmentStore.forTimeline(timeline.id).some(hasRawCandidate));
}

// Both deriveGeolocationSequence (the map) and buildGeolocationTimelineRows
// (the timeline rows) read through this. Once computed for a video, the
// result is cached: VideoAnalysis.vue deletes the raw backend timeline from
// timelineStore right after deriving the nicer rows from it (to avoid a
// duplicate row), which would otherwise leave a later caller (e.g. the map,
// mounted after that runs) with nothing left to scan for.
const derivedCache = new Map();

// Reshapes the real raw timeline into a per-shot candidate-list sequence.
// Returns null when the plugin has never been run for this video.
function deriveGeolocationData({ videoId }) {
  if (derivedCache.has(videoId)) {
    return derivedCache.get(videoId);
  }

  const category = useAnnotationCategoryStore().all.find((c) => c.name === CATEGORY_NAME);
  if (!category) return null;

  const rawTimeline = findRawTimeline({ videoId, category });
  if (!rawTimeline) return null;

  const annotationStore = useAnnotationStore();
  const timelineSegmentStore = useTimelineSegmentStore();
  const timelineSegmentAnnotationStore = useTimelineSegmentAnnotationStore();

  const sequence = timelineSegmentStore.forTimeline(rawTimeline.id).map((segment) => {
    const locations = timelineSegmentAnnotationStore
      .forTimelineSegment(segment.id)
      .map((tsa) => annotationStore.get(tsa.annotation_id))
      .filter((a) => a && a.category_id === category.id)
      .map(parseCandidate)
      .filter(Boolean)
      .sort((a, b) => b.confidence - a.confidence);

    return { start: segment.start, end: segment.end, locations };
  });

  const data = { category, rawTimelineId: rawTimeline.id, sequence };
  derivedCache.set(videoId, data);
  return data;
}

// An intentionally *uncached* raw-timeline lookup, for use from a Vue
// computed in VideoAnalysis.vue to detect exactly when fresh backend results
// have landed. Evaluating this touches annotationCategoryStore, annotationStore,
// timelineStore, timelineSegmentStore and timelineSegmentAnnotationStore —
// every store the real data is spread across — so a computed wrapping it
// naturally depends on all of them, and only settles to a non-null value
// once every one of them has the new data (not just whichever resolves
// first — see store/plugin_run.js's fire-and-forget refetch chain, where
// "run finished" and "data landed" are not the same moment, and the pieces
// land at different times).
export function findRawGeolocationTimelineId({ videoId }) {
  const category = useAnnotationCategoryStore().all.find((c) => c.name === CATEGORY_NAME);
  if (!category) return null;
  return findRawTimeline({ videoId, category })?.id ?? null;
}

// Clears the cached derivation for a video (e.g. before re-deriving after a
// re-run replaces the backend's rows) and returns the ids of whatever this
// module previously injected into the stores, so the caller can remove them
// first. Returns null if nothing had been derived/injected yet.
export function resetGeolocationRows({ videoId }) {
  const data = derivedCache.get(videoId);
  derivedCache.delete(videoId);
  return data?.injected ?? null;
}

// Id-prefix predicates for the synthetic rows this module injects, so
// callers outside this module (the generic delete UI) can special-case
// geolocation rows without needing to know their internal id format.
export function isGeolocationParentTimelineId(id) {
  return typeof id === "string" && id.startsWith("geolocation-timeline-");
}
export function isGeolocationChildTimelineId(id) {
  return typeof id === "string" && id.startsWith("geolocation-child-");
}

// Read-only peek at the real backend timeline id behind this video's derived
// rows, without invalidating the cache the way resetGeolocationRows() does
// (deleteGeolocationResults needs the id *before* it knows the backend
// delete will succeed).
export function getRawTimelineId({ videoId }) {
  return derivedCache.get(videoId)?.rawTimelineId ?? null;
}

// Deletes the real backend "Geolocation" Timeline for this video (via the
// generic /timeline/delete endpoint, which cascades to its segments/links
// server-side), then removes this module's synthetic parent+child rows from
// the local stores. Only runs the local cleanup once the backend delete has
// actually confirmed success, so a failed request never leaves the UI
// showing "deleted" while the real data is still there to reappear later.
export async function deleteGeolocationResults({ videoId }) {
  const rawTimelineId = getRawTimelineId({ videoId });
  if (!rawTimelineId) {
    return;
  }

  const res = await axios.post(`${config.API_LOCATION}/timeline/delete`, {
    id: rawTimelineId,
  });
  if (res.data.status !== "ok") {
    return;
  }

  const previous = resetGeolocationRows({ videoId });
  if (previous) {
    useTimelineStore().deleteFromStore(previous.timelineIds);
    useTimelineSegmentStore().deleteFromStore(previous.timelineSegmentIds);
    useTimelineSegmentAnnotationStore().deleteFromStore(
      previous.timelineSegmentAnnotationIds,
    );
  }
}

// Per-shot candidate sequence for the map: [{ start, end, locations: [{tag,
// latitude, longitude, location, confidence, color}, ...] }, ...], sourced
// from the real plugin run's annotations. Returns null if none exist yet.
export function deriveGeolocationSequence({ videoId }) {
  return deriveGeolocationData({ videoId })?.sequence ?? null;
}

// Shapes the real geolocation sequence into the same Timeline/TimelineSegment/
// Annotation objects the app's generic annotation-timeline renderer expects:
// one parent ANNOTATION timeline (top candidate location per shot), plus one
// child ANNOTATION timeline per unique location (that location's confidence
// per shot, or no annotation on shots it wasn't predicted for). Also returns
// the id of the real, flat backend timeline this was derived from, so the
// caller can hide it (client-side only) in favor of these nicer rows.
// Returns null when the plugin has never been run for this video.
export function buildGeolocationTimelineRows({ videoId, baseOrder }) {
  const data = deriveGeolocationData({ videoId });
  if (!data) return null;
  const { category, rawTimelineId, sequence } = data;

  const primaryTimelineId = `geolocation-timeline-${videoId}`;
  const timelineSegments = [];
  const annotations = [];
  const timelineSegmentAnnotations = [];
  const uniqueTags = [...new Set(sequence.flatMap(({ locations }) => locations.map((l) => l.tag)))];

  sequence.forEach(({ start, end, locations }, index) => {
    const segmentId = `geolocation-segment-${videoId}-${index}`;
    timelineSegments.push({ id: segmentId, timeline_id: primaryTimelineId, start, end, color: null });

    const top = locations[0];
    if (!top) return;

    const annotationId = `geolocation-annotation-${videoId}-${index}`;
    annotations.push({
      id: annotationId,
      name: top.tag,
      category_id: category.id,
      color: blendTowardWhite(top.color, 1 - top.confidence),
    });
    timelineSegmentAnnotations.push({
      id: `geolocation-segment-annotation-${videoId}-${index}`,
      timeline_segment_id: segmentId,
      annotation_id: annotationId,
    });
  });

  const timelines = [
    {
      id: primaryTimelineId,
      video_id: videoId,
      name: CATEGORY_NAME,
      type: "ANNOTATION",
      order: baseOrder,
      parent_id: null,
      collapse: false,
    },
  ];

  uniqueTags.forEach((tag, i) => {
    const slug = slugify(tag);
    const childTimelineId = `geolocation-child-${slug}-${videoId}`;
    const color = colorForLabel(tag);

    timelines.push({
      id: childTimelineId,
      video_id: videoId,
      name: tag,
      type: "ANNOTATION",
      order: baseOrder + i + 1,
      parent_id: primaryTimelineId,
      collapse: false,
    });

    sequence.forEach(({ start, end, locations }, index) => {
      const segmentId = `geolocation-child-segment-${slug}-${videoId}-${index}`;
      timelineSegments.push({ id: segmentId, timeline_id: childTimelineId, start, end, color: null });

      const match = locations.find((location) => location.tag === tag);
      if (!match) return;

      const annotationId = `geolocation-child-annotation-${slug}-${videoId}-${index}`;
      annotations.push({
        id: annotationId,
        name: `${Math.round(match.confidence * 100)}%`,
        category_id: category.id,
        color: blendTowardWhite(color, 1 - match.confidence),
      });
      timelineSegmentAnnotations.push({
        id: `geolocation-child-segment-annotation-${slug}-${videoId}-${index}`,
        timeline_segment_id: segmentId,
        annotation_id: annotationId,
      });
    });
  });

  derivedCache.set(videoId, {
    ...data,
    injected: {
      timelineIds: timelines.map((t) => t.id),
      timelineSegmentIds: timelineSegments.map((s) => s.id),
      timelineSegmentAnnotationIds: timelineSegmentAnnotations.map((a) => a.id),
    },
  });

  return { rawTimelineId, timelines, timelineSegments, annotations, timelineSegmentAnnotations };
}
