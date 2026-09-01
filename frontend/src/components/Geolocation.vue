<template>
  <section v-if="variant === 'map'" class="geo-annotation pa-4">
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

  <section v-else class="geo-timeline px-4 pb-4">
    <div class="d-flex align-center justify-space-between mb-2">
      <div>
        <div class="text-subtitle-1 font-weight-bold">Geolocation timeline</div>
        <div class="text-caption grey--text text--darken-1">One mock timeline · each block is a shot · colour =
          place/tag · opacity = confidence</div>
      </div>
      <div class="geo-legend">
        <span v-for="scene in sceneLegend" :key="scene.tag"><i :style="{ backgroundColor: scene.color }"></i>{{
          scene.tag }}</span>
      </div>
    </div>

    <div ref="timeline" class="geo-timeline__track" role="slider" aria-label="Mock geolocation timeline"
      @click="seekFromTimeline">
      <button v-for="segment in segments" :key="segment.id" class="geo-timeline__segment"
        :class="{ 'geo-timeline__segment--current': currentSegment.id === segment.id, 'geo-timeline__segment--unlabelled': !segment.tag }"
        :style="segmentStyle(segment)" type="button" :aria-label="segmentAriaLabel(segment)"
        @click.stop="jumpToSegment(segment)">
      </button>
      <div class="geo-timeline__playhead" :style="{ left: `${playheadPercent}%` }">
        <span></span>
      </div>
    </div>
    <div class="geo-timeline__ticks">
      <span v-for="tick in timelineTicks" :key="tick">{{ timecode(tick) }}</span>
    </div>
    <div class="text-caption mt-2">
      <template v-if="currentSegment.tag">Selected: <strong>{{ currentSegment.tag }}</strong> · {{
        currentSegment.location }} · {{ confidenceLabel(currentSegment.confidence) }} confidence</template>
      <template v-else>Selected: <strong>Unlabelled shot</strong> · no location prediction</template>
    </div>
  </section>
</template>

<script>
import { mapStores } from "pinia";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { usePlayerStore } from "@/store/player";

// Deliberately broad fixture for exercising marker density, map panning, and timeline rendering.
const LOCATION_FIXTURE = [
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

const LOCATION_BY_TAG = LOCATION_FIXTURE.reduce((locations, location) => ({ ...locations, [location.tag]: location }), {});

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

const INTENSIVE_TEST_SEQUENCE = [
  ["San Francisco", 0.98], ["Tokyo", 0.94], ["Paris", 0.89], [null, null], ["Sydney", 0.86],
  ["New York", 0.83], ["Singapore", 0.79], ["Cape Town", 0.76], ["London", 0.71], [null, null],
  ["Mexico City", 0.68], ["Mumbai", 0.64], ["Rome", 0.61], ["Auckland", 0.58], ["Cairo", 0.55],
  ["Seoul", 0.52], ["Buenos Aires", 0.49], [null, null], ["Dubai", 0.46], ["Vancouver", 0.43],
  ["Bangkok", 0.4], ["Reykjavik", 0.37], ["Nairobi", 0.34], ["Melbourne", 0.31], [null, null],
  ["Beijing", 0.28], ["Sao Paulo", 0.25], ["Anchorage", 0.22], ["Jakarta", 0.19], ["Manila", 0.16],
  ["Perth", 0.13], ["Honolulu", 0.1], ["Delhi", 0.92], [null, null], ["Moscow", 0.88],
  ["San Francisco", 0.85], ["Tokyo", 0.81], ["Paris", 0.78], ["Sydney", 0.75], ["New York", 0.72],
  ["Singapore", 0.69], [null, null], ["Cape Town", 0.66], ["London", 0.63], ["Mexico City", 0.6],
  ["Mumbai", 0.57], ["Rome", 0.54], ["Auckland", 0.51], [null, null], ["Cairo", 0.48],
  ["Seoul", 0.45], ["Buenos Aires", 0.42], ["Dubai", 0.39], ["Vancouver", 0.36], ["Bangkok", 0.33],
  ["Reykjavik", 0.3], ["Nairobi", 0.27], ["Melbourne", 0.24], ["Beijing", 0.21], ["Moscow", 0.18],
];

const SHOT_TEMPLATE = INTENSIVE_TEST_SEQUENCE.map(([tag, confidence], index) => ({
  start: index / INTENSIVE_TEST_SEQUENCE.length,
  end: (index + 1) / INTENSIVE_TEST_SEQUENCE.length,
  tag,
  confidence,
}));

export default {
  data() {
    return {
      map: null,
      mapReady: false,
    };
  },
  props: {
    variant: {
      type: String,
      default: "map",
      validator: (value) => ["map", "timeline"].includes(value),
    },
  },
  mounted() {
    if (this.variant === "map") this.$nextTick(this.initializeMap);
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
    duration() {
      return this.playerStore.videoDuration || 0;
    },
    currentTime() {
      return Math.min(Math.max(this.playerStore.currentTime || 0, 0), this.duration);
    },
    segments() {
      return SHOT_TEMPLATE.map((item, index) => ({
        ...item,
        ...(item.tag ? LOCATION_BY_TAG[item.tag] : {}),
        id: `mock-geo-${index}`,
        start: item.start * this.duration,
        end: item.end * this.duration,
      }));
    },
    currentSegment() {
      return this.segments.find((segment) => this.currentTime >= segment.start && this.currentTime < segment.end) || this.segments[this.segments.length - 1];
    },
    sceneLegend() {
      const seen = new Set();
      return this.segments
        .filter((segment) => segment.tag && !seen.has(segment.tag) && seen.add(segment.tag))
        .map((segment) => ({ tag: segment.tag, color: segment.color }));
    },
    mapLocations() {
      return LOCATION_FIXTURE;
    },
    mapAriaLabel() {
      return this.currentSegment.tag ? `Mock map annotation at ${this.currentSegment.location}` : "Mock map annotation with no location prediction for the selected shot";
    },
    playheadPercent() {
      return (this.currentTime / this.duration) * 100;
    },
    timelineTicks() {
      return [0, this.duration * 0.25, this.duration * 0.5, this.duration * 0.75, this.duration];
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
    colorFor(tag) {
      return tag ? (LOCATION_BY_TAG[tag]?.color ?? "transparent") : "transparent";
    },
    segmentStyle(segment) {
      const isLabelled = Boolean(segment.tag);
      return {
        left: `${(segment.start / this.duration) * 100}%`,
        width: `${((segment.end - segment.start) / this.duration) * 100}%`,
        backgroundColor: isLabelled ? this.colorFor(segment.tag) : "transparent",
        opacity: isLabelled ? 0.08 + segment.confidence * 0.92 : 1,
      };
    },
    segmentWidth(segment) {
      return ((segment.end - segment.start) / this.duration) * 100;
    },
    confidenceLabel(confidence) {
      return `${Math.round(confidence * 100)}%`;
    },
    timecode(seconds) {
      const minutes = Math.floor(seconds / 60);
      const remainingSeconds = Math.floor(seconds % 60);
      return `${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
    },
    segmentAriaLabel(segment) {
      const interval = `${this.timecode(segment.start)} to ${this.timecode(segment.end)}`;
      return segment.tag ? `${segment.tag}, ${this.confidenceLabel(segment.confidence)} confidence, ${interval}` : `Unlabelled shot, ${interval}`;
    },
    setTime(time) {
      const safeTime = Math.min(Math.max(time, 0), this.duration);
      this.playerStore.setCurrentTime(safeTime);
      this.playerStore.setTargetTime(safeTime);
    },
    jumpToSegment(segment) {
      this.setTime((segment.start + segment.end) / 2);
    },
    seekFromTimeline(event) {
      const bounds = this.$refs.timeline.getBoundingClientRect();
      this.setTime(((event.clientX - bounds.left) / bounds.width) * this.duration);
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

.geo-timeline {
  width: 100%;
}

.geo-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
}

.geo-legend span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.geo-legend i {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 2px;
}

.geo-timeline__track {
  position: relative;
  height: 52px;
  overflow: hidden;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #e2e8f0;
  cursor: crosshair;
}

.geo-timeline__segment {
  position: absolute;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 0;
  border-right: 2px solid rgba(255, 255, 255, 0.85);
  color: white;
  font-size: 12px;
  font-weight: 700;
  text-shadow: 0 1px 2px rgba(15, 23, 42, 0.35);
  cursor: pointer;
  transition: filter .16s ease, box-shadow .16s ease;
}

.geo-timeline__segment:hover {
  filter: brightness(1.06);
}

.geo-timeline__segment--current {
  z-index: 1;
  box-shadow: inset 0 0 0 3px #0f172a;
}

.geo-timeline__playhead {
  position: absolute;
  z-index: 3;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #0f172a;
  pointer-events: none;
}

.geo-timeline__playhead span {
  position: absolute;
  top: 0;
  left: -5px;
  width: 12px;
  height: 12px;
  background: #0f172a;
  clip-path: polygon(0 0, 100% 0, 50% 100%);
}

.geo-timeline__ticks {
  display: flex;
  justify-content: space-between;
  padding-top: 4px;
  color: #64748b;
  font-family: monospace;
  font-size: 11px;
}

</style>
