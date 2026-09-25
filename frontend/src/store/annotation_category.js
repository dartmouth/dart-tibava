import Vue from "vue";
import axios from '../plugins/axios';
import config from '../../app.config';
import { defineStore } from 'pinia';
import { usePlayerStore } from "@/store/player";

// Keyed by resolved video id, not Pinia state, so an overlapping fetchForVideo
// call waits for the in-flight request instead of silently no-oping (see
// isLoading guard below) — plain module state, not reactive, matching the
// derivedCache pattern in plugins/geolocationRows.js.
const pendingFetchByVideoId = new Map();

export const useAnnotationCategoryStore = defineStore('annotationCategory', {
    state: () => {
        return {
            annotationCategories: {},
            isLoading: false,
        }
    },
    getters: {
        all: (state) => {
            return Object.values(state.annotationCategories);
        },
        get: (state) => (id) => {
            return state.annotationCategories[id];
        }
    },
    actions: {
        async create({ name, color, videoId = null }) {
            if (this.isLoading) {
                return
            }
            this.isLoading = true

            const params = {
                name: name,
                color: color
            }
            if (videoId) {
                params.video_id = videoId;
            }
            else {
                const playerStore = usePlayerStore();
                const videoId = playerStore.videoId;
                if (videoId) {
                    params.video_id = videoId;
                }
            }

            return axios.post(`${config.API_LOCATION}/annotation/category/create`, params)
                .then((res) => {
                    if (res.data.status === 'ok') {
                        this.addToStore([res.data.entry]);
                        return res.data.entry.id;
                    }
                })
                .finally(() => {
                    this.isLoading = false;
                })
            // .catch((error) => {
            //     const info = { date: Date(), error, origin: 'collection' };
            //     commit('error/update', info, { root: true });
            // });
        },
        async fetchForVideo({ videoId = null }) {
            const playerStore = usePlayerStore();
            const resolvedVideoId = videoId || playerStore.videoId;

            if (this.isLoading) {
                return pendingFetchByVideoId.get(resolvedVideoId);
            }
            this.isLoading = true

            let params = {}
            if (resolvedVideoId) {
                params.video_id = resolvedVideoId;
            }
            const promise = axios.get(`${config.API_LOCATION}/annotation/category/list`, { params })
                .then((res) => {
                    if (res.data.status === 'ok') {
                        this.updateStore(res.data.entries);
                    }
                })
                .finally(() => {
                    this.isLoading = false;
                    pendingFetchByVideoId.delete(resolvedVideoId);
                })
            pendingFetchByVideoId.set(resolvedVideoId, promise);
            return promise;
        },


        clearStore() {
            Object.keys(this.annotationCategories ).forEach(key => {
                Vue.delete(this.annotationCategories , key);
            });
        },
        addToStore(annotationCategories) {
            annotationCategories.forEach((e) => {
                Vue.set(this.annotationCategories, e.id, e);
            });
        },

        updateStore(annotationCategories) {
            annotationCategories.forEach((e) => {
                if (e.id in this.annotationCategories) {
                    return;
                }
                Vue.set(this.annotationCategories, e.id, e);
            });
        }
    },
})