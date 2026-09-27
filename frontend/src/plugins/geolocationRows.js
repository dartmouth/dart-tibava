// The geolocation plugin's parent + per-location child timelines are real,
// persisted Timeline rows (see backend/.../tasks/geolocation.py) like any
// other plugin's results, rendered by the app's generic annotation-timeline
// components with no special-casing needed. This module only supplies the
// "Map" tab (components/Geolocation.vue) with the per-shot/per-location data
// it needs, which isn't otherwise exposed in a single place.

import { useAnnotationCategoryStore } from "@/store/annotation_category";
import { useAnnotationStore } from "@/store/annotation";
import { useTimelineStore } from "@/store/timeline";
import { useTimelineSegmentStore } from "@/store/timeline_segment";
import { useTimelineSegmentAnnotationStore } from "@/store/timeline_segment_annotation";

const CATEGORY_NAME = "Geolocation";

function firstAnnotationOnSegment(segmentId) {
  const tsa = useTimelineSegmentAnnotationStore().forTimelineSegment(segmentId)[0];
  return tsa ? useAnnotationStore().get(tsa.annotation_id) : null;
}

// Finds the real "Geolocation" parent timeline for this video: identified by
// its segments' annotations belonging to the given AnnotationCategory (not by
// name, since a timeline's name is user-editable via rename) and by having no
// parent of its own (its child location timelines carry the same category
// too, but are themselves parented).
function findParentTimeline({ videoId, category }) {
  const timelineSegmentStore = useTimelineSegmentStore();
  const timelineSegmentAnnotationStore = useTimelineSegmentAnnotationStore();
  const annotationStore = useAnnotationStore();

  const hasCategoryAnnotation = (segment) =>
    timelineSegmentAnnotationStore
      .forTimelineSegment(segment.id)
      .some((tsa) => annotationStore.get(tsa.annotation_id)?.category_id === category.id);

  return useTimelineStore()
    .forVideo(videoId)
    .find(
      (timeline) =>
        !timeline.parent_id &&
        timelineSegmentStore.forTimeline(timeline.id).some(hasCategoryAnnotation)
    );
}

function findChildTimelines({ videoId, parentId }) {
  return useTimelineStore()
    .forVideo(videoId)
    .filter((timeline) => timeline.parent_id === parentId);
}

// Per-shot winning location for the map's active-location marker: [{ start,
// end, locations: [{ tag, location, latitude, longitude, confidence, color }] }].
// Determined purely from the child (location) timelines' own per-shot
// confidence annotations - never by matching against a name, since names are
// user-editable via rename. Returns null if geolocation has never been run
// for this video.
export function deriveGeolocationSequence({ videoId }) {
  const category = useAnnotationCategoryStore().all.find((c) => c.name === CATEGORY_NAME);
  if (!category) return null;

  const parentTimeline = findParentTimeline({ videoId, category });
  if (!parentTimeline) return null;

  const childTimelines = findChildTimelines({ videoId, parentId: parentTimeline.id });
  if (childTimelines.length === 0) return null;

  const timelineSegmentStore = useTimelineSegmentStore();

  const childShots = childTimelines.map((child) => ({
    child,
    segments: timelineSegmentStore
      .forTimeline(child.id)
      .slice()
      .sort((a, b) => a.start - b.start),
  }));

  const nShots = childShots[0].segments.length;
  const sequence = [];

  for (let i = 0; i < nShots; i++) {
    const { start, end } = childShots[0].segments[i];
    let best = null;

    for (const { child, segments } of childShots) {
      const segment = segments[i];
      if (!segment) continue;
      const annotation = firstAnnotationOnSegment(segment.id);
      if (!annotation) continue;

      const confidence = parseFloat(annotation.name) / 100;
      if (!best || confidence > best.confidence) {
        best = { child, confidence, annotation };
      }
    }

    sequence.push({
      start,
      end,
      locations: best
        ? [
            {
              tag: best.child.name,
              location: best.child.name,
              latitude: best.child.geo_point?.lat ?? null,
              longitude: best.child.geo_point?.lon ?? null,
              confidence: best.confidence,
              color: best.annotation.color,
            },
          ]
        : [],
    });
  }

  return sequence;
}

// Full set of detected locations for the map's pins: one entry per location
// (child timeline), each carrying its stored coordinates and a
// representative color. Returns null if geolocation has never been run for
// this video.
export function deriveGeolocationLocations({ videoId }) {
  const category = useAnnotationCategoryStore().all.find((c) => c.name === CATEGORY_NAME);
  if (!category) return null;

  const parentTimeline = findParentTimeline({ videoId, category });
  if (!parentTimeline) return null;

  const timelineSegmentStore = useTimelineSegmentStore();

  return findChildTimelines({ videoId, parentId: parentTimeline.id })
    .map((child) => {
      const segments = timelineSegmentStore.forTimeline(child.id);
      const annotation = segments.map((s) => firstAnnotationOnSegment(s.id)).find(Boolean);

      return {
        tag: child.name,
        location: child.name,
        latitude: child.geo_point?.lat ?? null,
        longitude: child.geo_point?.lon ?? null,
        color: annotation?.color ?? null,
      };
    })
    .filter((location) => location.latitude !== null && location.longitude !== null);
}
