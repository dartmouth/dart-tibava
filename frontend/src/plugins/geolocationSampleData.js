// Sample geolocation data standing in for a not-yet-built backend plugin run.
// Shared between the standalone Geolocation.vue demo and the native timeline
// integration in VideoAnalysis.vue, so both stay in sync until the demo is removed.

import { useTimelineStore } from "@/store/timeline";
import { useTimelineSegmentStore } from "@/store/timeline_segment";

// Deliberately broad fixture for exercising marker density, map panning, and timeline rendering.
export const LOCATION_FIXTURE = [
  { tag: "Anchorage", latitude: 61.2181, longitude: -149.9003, location: "Anchorage, United States", color: "#4f46e5" },
  { tag: "Honolulu", latitude: 21.3069, longitude: -157.8583, location: "Honolulu, United States", color: "#7c3aed" },
  { tag: "Vancouver", latitude: 49.2827, longitude: -123.1207, location: "Vancouver, Canada", color: "#2563eb" },
  { tag: "San Francisco", latitude: 37.7749, longitude: -122.4194, location: "San Francisco, United States", color: "#0891b2" },
  { tag: "Mexico City", latitude: 19.4326, longitude: -99.1332, location: "Mexico City, Mexico", color: "#0f766e" },
  { tag: "New York", latitude: 40.7128, longitude: -74.006, location: "New York, United States", color: "#16a34a" },
  { tag: "Sao Paulo", latitude: -23.5505, longitude: -46.6333, location: "Sao Paulo, Brazil", color: "#65a30d" },
  { tag: "Buenos Aires", latitude: -34.6037, longitude: -58.3816, location: "Buenos Aires, Argentina", color: "#ca8a04" },
  { tag: "Reykjavik", latitude: 64.1466, longitude: -21.9426, location: "Reykjavik, Iceland", color: "#d97706" },
  { tag: "London", latitude: 51.5072, longitude: -0.1276, location: "London, United Kingdom", color: "#ea580c" },
  { tag: "Paris", latitude: 48.8566, longitude: 2.3522, location: "Paris, France", color: "#dc2626" },
  { tag: "Rome", latitude: 41.9028, longitude: 12.4964, location: "Rome, Italy", color: "#e11d48" },
  { tag: "Cairo", latitude: 30.0444, longitude: 31.2357, location: "Cairo, Egypt", color: "#db2777" },
  { tag: "Nairobi", latitude: -1.2921, longitude: 36.8219, location: "Nairobi, Kenya", color: "#9333ea" },
  { tag: "Cape Town", latitude: -33.9249, longitude: 18.4241, location: "Cape Town, South Africa", color: "#6d28d9" },
  { tag: "Moscow", latitude: 55.7558, longitude: 37.6173, location: "Moscow, Russia", color: "#4f46e5" },
  { tag: "Dubai", latitude: 25.2048, longitude: 55.2708, location: "Dubai, United Arab Emirates", color: "#2563eb" },
  { tag: "Mumbai", latitude: 19.076, longitude: 72.8777, location: "Mumbai, India", color: "#0891b2" },
  { tag: "Delhi", latitude: 28.6139, longitude: 77.209, location: "Delhi, India", color: "#0f766e" },
  { tag: "Bangkok", latitude: 13.7563, longitude: 100.5018, location: "Bangkok, Thailand", color: "#16a34a" },
  { tag: "Singapore", latitude: 1.3521, longitude: 103.8198, location: "Singapore", color: "#65a30d" },
  { tag: "Beijing", latitude: 39.9042, longitude: 116.4074, location: "Beijing, China", color: "#ca8a04" },
  { tag: "Seoul", latitude: 37.5665, longitude: 126.978, location: "Seoul, South Korea", color: "#d97706" },
  { tag: "Tokyo", latitude: 35.6762, longitude: 139.6503, location: "Tokyo, Japan", color: "#ea580c" },
  { tag: "Manila", latitude: 14.5995, longitude: 120.9842, location: "Manila, Philippines", color: "#dc2626" },
  { tag: "Jakarta", latitude: -6.2088, longitude: 106.8456, location: "Jakarta, Indonesia", color: "#e11d48" },
  { tag: "Perth", latitude: -31.9505, longitude: 115.8605, location: "Perth, Australia", color: "#db2777" },
  { tag: "Sydney", latitude: -33.8688, longitude: 151.2093, location: "Sydney, Australia", color: "#9333ea" },
  { tag: "Melbourne", latitude: -37.8136, longitude: 144.9631, location: "Melbourne, Australia", color: "#6d28d9" },
  { tag: "Auckland", latitude: -36.8485, longitude: 174.7633, location: "Auckland, New Zealand", color: "#4f46e5" },
];

export const LOCATION_BY_TAG = LOCATION_FIXTURE.reduce((locations, location) => ({ ...locations, [location.tag]: location }), {});

const FALLBACK_SEGMENT_COUNT = 10;

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function shuffle(array) {
  const result = [...array];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

function pickRandomLocations(count) {
  return shuffle(LOCATION_FIXTURE).slice(0, count);
}

// Mirrors the app's existing "first ANNOTATION timeline is the shots timeline"
// convention (see store/shot.js) so the sample sequence lines up with a real
// shot-detection run when one exists for the video, and falls back to evenly
// spaced segments otherwise.
function resolveShotBoundaries({ videoId, duration }) {
  const safeDuration = duration || 0;
  const shotsTimeline = useTimelineStore()
    .forVideo(videoId)
    .find((timeline) => timeline.type === "ANNOTATION");
  const shotSegments = shotsTimeline ? useTimelineSegmentStore().forTimeline(shotsTimeline.id) : [];

  if (shotSegments.length > 1) {
    return shotSegments.map((segment) => [segment.start, segment.end]);
  }

  return Array.from({ length: FALLBACK_SEGMENT_COUNT }, (_, index) => [
    (index / FALLBACK_SEGMENT_COUNT) * safeDuration,
    ((index + 1) / FALLBACK_SEGMENT_COUNT) * safeDuration,
  ]);
}

// Generates a fresh random geolocation sequence: a random subset of locations,
// laid out over the video's real shot boundaries (or evenly spaced ones), with
// 1-3 candidate locations per shot, each at a different confidence level.
export function generateGeolocationSequence({ videoId, duration }) {
  const boundaries = resolveShotBoundaries({ videoId, duration });
  const pool = pickRandomLocations(randomInt(4, 8));

  return boundaries.map(([start, end]) => {
    const locationCount = Math.min(randomInt(1, 3), pool.length);
    const locations = shuffle(pool)
      .slice(0, locationCount)
      .map((location) => ({ tag: location.tag, confidence: 0.3 + Math.random() * 0.69 }))
      .sort((a, b) => b.confidence - a.confidence);

    return { start, end, locations };
  });
}

function slugify(tag) {
  return tag.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-+|-+$)/g, "");
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

// Shapes the sample geolocation sequence into the same Timeline/TimelineSegment/
// Annotation/PluginRunResult objects a real geolocation plugin run would produce,
// following the shot_angle plugin's parent (ANNOTATION) + per-category children
// (PLUGIN_RESULT/SCALAR_COLOR) structure.
export function buildGeolocationTimelineData({ videoId, duration, baseOrder }) {
  const safeDuration = duration || 0;
  const primaryTimelineId = `geolocation-timeline-${videoId}`;
  const categoryId = "geolocation-category";

  const annotationCategories = [{ id: categoryId, name: "Geolocation" }];

  const sequence = generateGeolocationSequence({ videoId, duration: safeDuration });

  const timelineSegments = [];
  const annotations = [];
  const timelineSegmentAnnotations = [];
  const timeSamples = [];
  const uniqueTags = [...new Set(sequence.flatMap(({ locations }) => locations.map(({ tag }) => tag)))];

  sequence.forEach(({ start, end, locations }, index) => {
    timeSamples.push((start + end) / 2);

    const segmentId = `geolocation-segment-${videoId}-${index}`;
    timelineSegments.push({
      id: segmentId,
      timeline_id: primaryTimelineId,
      start,
      end,
      color: null,
    });

    locations.forEach(({ tag, confidence }, locationIndex) => {
      const annotationId = `geolocation-annotation-${videoId}-${index}-${locationIndex}`;
      annotations.push({
        id: annotationId,
        name: tag,
        category_id: categoryId,
        color: blendTowardWhite(LOCATION_BY_TAG[tag].color, 1 - confidence),
      });
      timelineSegmentAnnotations.push({
        id: `geolocation-segment-annotation-${videoId}-${index}-${locationIndex}`,
        timeline_segment_id: segmentId,
        annotation_id: annotationId,
      });
    });
  });

  const timelines = [
    {
      id: primaryTimelineId,
      video_id: videoId,
      name: "Geolocation",
      type: "ANNOTATION",
      order: baseOrder,
      parent_id: null,
      collapse: false,
    },
  ];
  const pluginRunResults = [];

  uniqueTags.forEach((tag, i) => {
    const slug = slugify(tag);
    const resultId = `geolocation-result-${slug}-${videoId}`;

    timelines.push({
      id: `geolocation-child-${slug}-${videoId}`,
      video_id: videoId,
      name: tag,
      type: "PLUGIN_RESULT",
      visualization: "SCALAR_COLOR",
      order: baseOrder + i + 1,
      parent_id: primaryTimelineId,
      collapse: false,
      plugin_run_result_id: resultId,
    });

    pluginRunResults.push({
      id: resultId,
      data: {
        time: timeSamples,
        y: sequence.map(({ locations }) => locations.find((location) => location.tag === tag)?.confidence ?? 0),
        delta_time: safeDuration / sequence.length,
      },
    });
  });

  return {
    timelines,
    timelineSegments,
    annotations,
    annotationCategories,
    timelineSegmentAnnotations,
    pluginRunResults,
  };
}
