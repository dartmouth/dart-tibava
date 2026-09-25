import Vue from "vue";
import axios from "../plugins/axios";
import config from "../../app.config";
import { defineStore } from "pinia";
import { useTimelineSegmentStore } from "@/store/timeline_segment";
import { useAnnotationCategoryStore } from "@/store/annotation_category";
import { useAnnotationStore } from "@/store/annotation";
import { usePlayerStore } from "@/store/player";

// Keyed by resolved video id, not Pinia state, so an overlapping fetchForVideo
// call waits for the in-flight request instead of silently no-oping (see
// isLoading guard below) — plain module state, not reactive, matching the
// derivedCache pattern in plugins/geolocationRows.js.
const pendingFetchByVideoId = new Map();

export const useTimelineSegmentAnnotationStore = defineStore(
  "timelineSegmentAnnotation",
  {
    state: () => {
      return {
        timelineSegmentAnnotations: {},
        isLoading: false,
      };
    },
    getters: {
      all: (state) => {
        return Object.values(state.timelineSegmentAnnotations);
      },
      transcriptSegments(state) {
        const annotationCatygoryStore = useAnnotationCategoryStore();
        const segmentStore = useTimelineSegmentStore();
        const annotationStore = useAnnotationStore();
        return Object.values(state.timelineSegmentAnnotations).map(
          (segment_annotation, i) => {
            let segment = null;
            let start = 0;
            let end = 0;
            if (segment_annotation.timeline_segment_id) {
              segment = segmentStore.get(segment_annotation.timeline_segment_id);
              if (segment) {
                start = segment.start;
                end = segment.end;
              }
            }
            let annotation = null;
            if (segment_annotation.annotation_id) {
              annotation = annotationStore.get(segment_annotation.annotation_id);
            }
            let cat = null;
            if (annotation) {
              cat = annotationCatygoryStore.get(annotation.category_id);
            }
            let name = '';
            if (annotation) {
              name = annotation.name;
            }
            return { id: i + 1, category: cat, name: name, start: start, end: end };
          }
        ).filter(
          (segment) => segment.category && segment.category.name === "Transcript"
        ).sort(
          (a, b) => a.start > b.start
        ).map(
          (segment, i) => {
            segment.id = i + 1;
            return segment;
          }
        );
      },
      forTimelineSegment(state) {
        return (timelineSegmentId) => {
          return Object.values(state.timelineSegmentAnnotations).filter((a) => a.timeline_segment_id == timelineSegmentId);
        };
      },
    },
    actions: {
      async create({ timelineSegmentId, annotationId }) {
        if (this.isLoading) {
          return;
        }
        this.isLoading = true;

        const params = {
          timeline_segment_id: timelineSegmentId,
          annotation_id: annotationId,
        };

        const timelineSegmentStore = useTimelineSegmentStore();

        return axios
          .post(
            `${config.API_LOCATION}/timeline/segment/annotation/create`,
            params
          )
          .then((res) => {
            if (res.data.status === "ok") {
              this.addToStore([res.data.entry]);
              timelineSegmentStore.addAnnotation([
                { timelineSegmentId, entry: res.data.entry },
              ]);
              return res.data.entry.id;
            }
          })
          .finally(() => {
            this.isLoading = false;
          });
        // .catch((error) => {
        //     const info = { date: Date(), error, origin: 'collection' };
        //     commit('error/update', info, { root: true });
        // });
      },
      async delete(id) {
        if (this.isLoading) {
          return;
        }
        this.isLoading = true;

        const params = {
          timeline_segment_annotation_id: id,
        };

        const timelineSegmentStore = useTimelineSegmentStore();

        return axios
          .post(
            `${config.API_LOCATION}/timeline/segment/annotation/delete`,
            params
          )
          .then((res) => {
            if (res.data.status === "ok") {
              [res.data.entry].forEach((id) => {
                Vue.delete(this.timelineSegmentAnnotations, id);
              });
              timelineSegmentStore.deleteAnnotation([id]);
            }
          })
          .finally(() => {
            this.isLoading = false;
          });
        // .catch((error) => {
        //     const info = { date: Date(), error, origin: 'collection' };
        //     commit('error/update', info, { root: true });
        // });
      },
      async fetchForVideo({ videoId, clear = true }) {
        const playerStore = usePlayerStore();
        const resolvedVideoId = videoId || playerStore.videoId;

        if (this.isLoading) {
          return pendingFetchByVideoId.get(resolvedVideoId);
        }
        this.isLoading = true;

        let params = {};
        if (resolvedVideoId) {
          params.video_id = resolvedVideoId;
        }
        if (clear) {
          this.clearStore();
        }
        const promise = axios
          .get(`${config.API_LOCATION}/timeline/segment/annotation/list`, {
            params,
          })
          .then((res) => {
            if (res.data.status === "ok") {
              this.updateStore(res.data.entries);
            }
          })
          .finally(() => {
            this.isLoading = false;
            pendingFetchByVideoId.delete(resolvedVideoId);
          });
        pendingFetchByVideoId.set(resolvedVideoId, promise);
        return promise;
        // .catch((error) => {
        //     const info = { date: Date(), error, origin: 'collection' };
        //     commit('error/update', info, { root: true });
        // });
      },
      clearStore() {
        Object.keys(this.timelineSegmentAnnotations).forEach(key => {
          Vue.delete(this.timelineSegmentAnnotations, key);
        });
      },
      deleteFromStore(timelineSegmentAnnotations) {
        timelineSegmentAnnotations.forEach((id) => {
          Vue.delete(this.timelineSegmentAnnotations, id);
        });
      },
      addToStore(timelineSegmentAnnotations) {
        timelineSegmentAnnotations.forEach((e) => {
          Vue.set(this.timelineSegmentAnnotations, e.id, e);
        });
      },
      updateStore(timelineSegmentAnnotations) {
        timelineSegmentAnnotations.forEach((e) => {
          if (e.id in this.timelineSegmentAnnotations) {
            return;
          }
          Vue.set(this.timelineSegmentAnnotations, e.id, e);
        });
      },
    },
  }
);
