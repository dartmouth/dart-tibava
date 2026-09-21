<template>
  <section class="geo-annotation pa-4">
    <div class="d-flex align-start justify-space-between mb-3">
      <div>
        <div class="text-subtitle-1 font-weight-bold">Map</div>
        <div class="text-caption grey--text text--darken-1">
          Mock data for UI demonstration — not model output
        </div>
      </div>
      <v-chip small outlined color="deep-purple">{{ timecode(currentTime) }}</v-chip>
    </div>

    <div class="map-frame">
      <div ref="mapCanvas" class="map-canvas" role="img" :aria-label="mapAriaLabel"></div>
      <div class="map-source">OpenStreetMap road data · test use</div>
      <div class="map-confidence">{{ currentSegment.tag ? `${currentSegment.tag} ·
        ${confidenceLabel(currentSegment.confidence)} confidence` : "No prediction" }}</div>
    </div>
  </section>
</template>

<script>
import { mapStores } from "pinia";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { usePlayerStore } from "@/store/player";
import { LOCATION_FIXTURE, LOCATION_BY_TAG, generateGeolocationSequence } from "@/plugins/geolocationSampleData";

// Secondary cities appear only after the street-detail zoom level is reached.
const DETAIL_LOCATION_FIXTURE = [
  { tag: "Oakland", latitude: 37.8044, longitude: -122.2712 },
  { tag: "San Jose", latitude: 37.3382, longitude: -121.8863 },
  { tag: "Brooklyn", latitude: 40.6782, longitude: -73.9442 },
  { tag: "Jersey City", latitude: 40.7178, longitude: -74.0431 },
  { tag: "Versailles", latitude: 48.8014, longitude: 2.1301 },
  { tag: "Cambridge", latitude: 52.1951, longitude: 0.1313 },
  { tag: "Alexandria", latitude: 31.2001, longitude: 29.9187 },
  { tag: "Abu Dhabi", latitude: 24.4539, longitude: 54.3773 },
  { tag: "Pune", latitude: 18.5204, longitude: 73.8567 },
  { tag: "Chiang Mai", latitude: 18.7883, longitude: 98.9853 },
  { tag: "Shenzhen", latitude: 22.5431, longitude: 114.0579 },
  { tag: "Yokohama", latitude: 35.4437, longitude: 139.638 },
  { tag: "Kyoto", latitude: 35.0116, longitude: 135.7681 },
  { tag: "Brisbane", latitude: -27.4698, longitude: 153.0251 },
  { tag: "Canberra", latitude: -35.2809, longitude: 149.13 },
  { tag: "Mombasa", latitude: -4.0435, longitude: 39.6682 },
];

const TEST_MAP_STYLE = {
  version: 8,
  sources: {
    openstreetmap: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap contributors</a>",
    },
  },
  layers: [{ id: "openstreetmap", type: "raster", source: "openstreetmap" }],
};

export default {
  data() {
    return {
      map: null,
      mapReady: false,
    };
  },
  mounted() {
    this.$nextTick(this.initializeMap);
  },
  beforeDestroy() {
    if (this.map) this.map.remove();
  },
  watch: {
    "currentSegment.id"() {
      // Playback updates currentTime continuously. Watching the segment ID means
      // the map only moves when playback enters a new geolocation interval.
      this.updateActiveLocation({ flyToLocation: true });
    },
  },
  computed: {
    videoId() {
      return this.playerStore.videoId;
    },
    duration() {
      return this.playerStore.videoDuration || 0;
    },
    currentTime() {
      return Math.min(Math.max(this.playerStore.currentTime || 0, 0), this.duration);
    },
    shotTemplate() {
      return generateGeolocationSequence({ videoId: this.videoId, duration: this.duration }).map((segment) => {
        const top = segment.locations[0] || null;
        return {
          start: segment.start,
          end: segment.end,
          tag: top?.tag ?? null,
          confidence: top?.confidence ?? null,
        };
      });
    },
    segments() {
      return this.shotTemplate.map((item, index) => ({
        ...item,
        ...(item.tag ? LOCATION_BY_TAG[item.tag] : {}),
        id: `mock-geo-${index}`,
      }));
    },
    currentSegment() {
      return this.segments.find((segment) => this.currentTime >= segment.start && this.currentTime < segment.end) || this.segments[this.segments.length - 1];
    },
    mapLocations() {
      return LOCATION_FIXTURE;
    },
    mapAriaLabel() {
      return this.currentSegment.tag ? `Mock map annotation at ${this.currentSegment.location}` : "Mock map annotation with no location prediction for the selected shot";
    },
    ...mapStores(usePlayerStore),
  },
  methods: {
    toFeatureCollection(locations) {
      return {
        type: "FeatureCollection",
        features: locations.map((location) => ({
          type: "Feature",
          geometry: { type: "Point", coordinates: [location.longitude, location.latitude] },
          properties: {
            tag: location.tag,
            location: location.location || location.tag,
            color: location.color || "#5e6d75",
          },
        })),
      };
    },
    initializeMap() {
      if (this.map || !this.$refs.mapCanvas) return;
      this.map = new maplibregl.Map({
        container: this.$refs.mapCanvas,
        style: TEST_MAP_STYLE,
        center: [this.currentSegment.longitude || 0, this.currentSegment.latitude || 0],
        zoom: 3.5,
        minZoom: 1,
        maxZoom: 15,
        // Keep one continuous world: don't repeat tiles beyond the dateline,
        // and stop panning once the Web Mercator world edge is reached.
        renderWorldCopies: false,
        maxBounds: [[-180, -85.051129], [180, 85.051129]],
        attributionControl: true,
      });
      this.map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-left");
      this.map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-right");
      this.map.on("load", () => {
        this.map.addSource("geo-locations", { type: "geojson", data: this.toFeatureCollection(this.mapLocations) });
        this.map.addLayer({
          id: "geo-location-points",
          type: "circle",
          source: "geo-locations",
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 1, 3, 4, 5, 8, 8],
            "circle-color": ["get", "color"],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.5,
            "circle-opacity": 0.92,
          },
        });
        this.map.addSource("geo-detail-locations", { type: "geojson", data: this.toFeatureCollection(DETAIL_LOCATION_FIXTURE) });
        this.map.addLayer({
          id: "geo-detail-location-points",
          type: "circle",
          source: "geo-detail-locations",
          minzoom: 5,
          paint: { "circle-radius": 3, "circle-color": "#566d77", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 },
        });
        this.map.addSource("geo-active-location", { type: "geojson", data: this.toFeatureCollection([]) });
        this.map.addLayer({
          id: "geo-active-halo",
          type: "circle",
          source: "geo-active-location",
          paint: { "circle-radius": 16, "circle-color": ["get", "color"], "circle-opacity": 0.2 },
        });
        this.map.addLayer({
          id: "geo-active-point",
          type: "circle",
          source: "geo-active-location",
          paint: { "circle-radius": 7, "circle-color": "#ffffff", "circle-stroke-color": ["get", "color"], "circle-stroke-width": 4 },
        });
        this.map.on("mouseenter", "geo-location-points", () => { this.map.getCanvas().style.cursor = "pointer"; });
        this.map.on("mouseleave", "geo-location-points", () => { this.map.getCanvas().style.cursor = ""; });
        this.map.on("click", "geo-location-points", (event) => this.openLocationPopup(event));
        this.mapReady = true;
        this.updateActiveLocation();
      });
    },
    updateActiveLocation({ flyToLocation = false } = {}) {
      if (!this.mapReady || !this.map || !this.map.getSource("geo-active-location")) return;
      this.map.getSource("geo-active-location").setData(
        this.currentSegment.tag ? this.toFeatureCollection([this.currentSegment]) : this.toFeatureCollection([]),
      );
      if (flyToLocation && this.currentSegment.tag) {
        this.map.flyTo({
          center: [this.currentSegment.longitude, this.currentSegment.latitude],
          zoom: Math.max(this.map.getZoom(), 5),
          duration: 700,
          essential: true,
        });
      }
    },
    openLocationPopup(event) {
      const feature = event.features && event.features[0];
      if (!feature) return;
      const coordinates = feature.geometry.coordinates.slice();
      const { tag, location } = feature.properties;
      new maplibregl.Popup({ offset: 10, closeButton: false })
        .setLngLat(coordinates)
        .setHTML(`<strong>${tag}</strong><br>${location}`)
        .addTo(this.map);
      this.map.flyTo({ center: coordinates, zoom: Math.max(this.map.getZoom(), 5), essential: true });
    },
    confidenceLabel(confidence) {
      return `${Math.round(confidence * 100)}%`;
    },
    timecode(seconds) {
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = Math.floor(seconds % 60);
      return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
    },
  },
};
</script>

<style scoped>
.geo-annotation {
  height: 100%;
  overflow: hidden;
}

.map-frame {
  position: relative;
  height: calc(100% - 48px);
  min-height: 310px;
  overflow: hidden;
  border: 1px solid #c8d8df;
  border-radius: 12px;
  background: #c6e2f1;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .68), 0 6px 18px rgba(15, 49, 71, .08);
}

.map-canvas {
  width: 100%;
  height: 100%;
}

.map-source {
  position: absolute;
  z-index: 3;
  right: 10px;
  bottom: 10px;
  padding: 4px 7px;
  border-radius: 5px;
  background: rgba(255, 255, 255, .86);
  color: #38505b;
  font-size: 10px;
  backdrop-filter: blur(3px);
}

.map-confidence {
  position: absolute;
  padding: 5px 8px;
  border-radius: 5px;
  background: rgba(15, 23, 42, 0.78);
  color: white;
  font-size: 12px;
  backdrop-filter: blur(3px);
}

.map-confidence {
  right: 10px;
  top: 10px;
}
</style>
