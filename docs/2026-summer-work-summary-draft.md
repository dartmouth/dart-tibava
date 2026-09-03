# Cindy Liu - Summer 2026 TIBAVA Development Contributions (Draft)

## Scope

This document is based only on the current Codex conversations, the local TIBAVA workspace, and code comments added during this development work. The project already contained a complete video-analysis platform, backend, inference services, and deployment structure when this work began. Therefore, this document does not restate the base platform's features or claim pre-existing backend or deployment capabilities as individual contributions.

The work completed during this period can be grouped into four areas:

1. Geospatial video interaction;
2. Reliability of video-analysis timelines and plugin workflows;
3. Optional LLM analysis context;
4. Testing, validation, and local delivery.

## Overview

This phase connected the map, geolocation timeline, and video playback state into an interactive demonstration experience; used high-density mock data to validate the UI under more complex conditions; fixed defects affecting timeline results and plugin startup; and added an optional video-year field so that visual question answering can receive temporal context during frame-by-frame analysis.

## Feature Structure at a Glance

- **Video-analysis interaction**
  - The video player provides the current playback time.
  - The geolocation timeline represents the active video segment, label, and confidence.
  - The map reflects the active location, supports user selection, and automatically focuses when playback enters a new location segment.

- **Plugin invocation and VQA context**
  - The Run Plugin dialog exposes an optional **Video year** in generic **Analysis Context** for every plugin.
  - The frontend sends it as a top-level optional request field; the backend validates it centrally and forwards it as task context.
  - BLIP VQA currently opts in to this context and adds it to the visual-question-answering prompt for each analysed frame.

## 1. Geospatial Video Interaction

### Geolocation UI

A Map tab and a dedicated geolocation timeline panel were added to the video-analysis view. Users can now inspect video content, the current location, and its corresponding geolocation results without leaving the analysis screen.

- Map, timeline, timestamps, place labels, confidence, legend, and current selection state are presented as one coherent interface.
- The timeline uses continuous blocks for video segments, colors for places or labels, and opacity for confidence.
- Annotated and unannotated segments are visually distinguished so that missing results are not represented as false predictions.
- Text descriptions were added for the map and timeline to improve accessibility and presentation clarity.

### Map Interaction Module

The map component uses MapLibre with OpenStreetMap data and supports interaction suitable for demonstrations and testing:

- Location markers, a highlighted current location, and a halo effect;
- Information popups after selecting a location;
- Zoom, pan, scale, and navigation controls;
- Primary and secondary locations shown at different zoom levels;
- World-copy and boundary constraints to prevent duplicated maps or unexpected panning across the international date line.

### Mock Geolocation Data and Stress Fixtures

To enable development and acceptance testing before a real geolocation model is integrated, explicitly labelled mock/demo datasets were created:

- Multiple regions, locations, coordinates, display names, colors, and confidence values;
- Dense time segments, frequent location changes, low-confidence results, and segments without a location;
- Segment ratios mapped to the real video duration so that the fixtures can be used with videos of different lengths;
- Both global locations and detailed locations that appear at higher zoom levels.

These datasets support stress and usability validation of map readability, legend density, timeline cursor behavior, location highlighting, and empty-result rendering under many markers and continuous segments. They are not model output. When the real model is integrated, its data should replace the fixtures through the same segment, location, coordinate, and confidence interface.

### Map Auto Focus and Playback Synchronization

The map and player share the same current-time state:

- When playback enters a new geolocation segment, the map smoothly focuses on the current location.
- The map moves only when the segment changes, preventing distracting animation on every frame.
- Selecting a timeline block seeks to its midpoint; selecting empty space seeks proportionally by position.
- The map highlight, timeline cursor, and player position remain synchronized.

This removes the disconnect caused by independent map, timeline, and player updates, turning the geolocation module from a static display into an explorable analysis tool.

Relevant local implementation: `frontend/src/components/Geolocation.vue`, `frontend/src/views/VideoAnalysis.vue`.

## 2. Reliability of Video-Analysis Timelines and Plugin Workflows

### Timeline Bug Fixes

The following issues were addressed around analysis-result persistence and timeline rendering:

- Corrected IDs and references for annotation timelines, scalar timelines, and plugin-run results written by some tasks.
- Handled empty-shot input and multi-result output structures to prevent lost results or incorrect timeline references.
- Fixed failures caused when flows such as place identification returned objects rather than serializable IDs.
- Synchronized the selected-video state when the video-analysis page initializes, ensuring that the plugin launch control targets the correct video.
- Improved failed-plugin logs by recording the plugin, run record, video, user, and parameter context.

### Result

These changes make automated analysis results more reliable when returning to the timeline and result views. Missing shot input, multiple generated results, or different page-initialization orders no longer lead to blank results, invalid references, or plugins being launched against the wrong video.

Relevant local implementation: `backend/src/backend/backend/tasks/clip_ontology.py`, `backend/src/backend/backend/tasks/place_identification.py`, `backend/src/backend/backend/plugin_manager.py`, `frontend/src/views/VideoAnalysis.vue`.

## 3. Optional LLM Analysis Context

### Optional Video-Year Context

The optional `video_year` field lets a user enter the year of the current video when running a plugin. The field is available in **Analysis Context** for every plugin invocation rather than being hidden in a VQA-specific form.

The data flow is:

```text
User enters an optional Video year
  → Top-level video_year field in frontend FormData
  → Backend PluginRunNew endpoint
  → PluginManager(video_year=...)
  → Asynchronous task kwargs
  → BLIP VQA analyser parameters
  → Per-frame visual-question-answering prompt
```

### Design and Behavior

- `video_year` is generic plugin-invocation context and remains separate from plugin-specific `parameters`, so not every plugin parser must implement it.
- When empty, it is not sent, preserving compatibility with existing plugin invocation behavior.
- The backend accepts only integer years from 1888 to 2100 and rejects booleans, decimal values, and out-of-range values.
- BLIP VQA currently consumes the field selectively and adds it to the prompt before each frame is analysed, helping with time-sensitive semantic disambiguation.
- This is a soft prompt constraint, not a hard filter. If the year must become a business rule, output validation or constrained structured results will be needed.

The code retains two follow-up items: persist generic invocation context for auditing and repeatability, and add verifiable post-processing for the year constraint.

Relevant local implementation: `frontend/src/components/ModalPlugin.vue`, `frontend/src/components/Parameters.vue`, `frontend/src/store/plugin_run.js`, `backend/src/backend/backend/views/plugin_run.py`, `backend/src/backend/backend/plugin_manager.py`, `backend/src/backend/backend/utils/parser.py`, `backend/src/backend/backend/tasks/blip_vqa.py`, `inference_ray/src/inference_ray/plugins/blip_embedding.py`.

## 4. Testing, Validation, and Local Delivery

### Timeline Regression Coverage

Local backend tests cover representative timeline-generation and failure-recovery cases, including:

- Analysis tasks creating timeline and result references;
- Separate plugin-run results for multiple concepts or outputs;
- Transaction rollback on task failure, avoiding partially persisted timelines.

### Geolocation UI and Stress Validation

High-density mock locations and time segments were used for manual validation of:

- Synchronization among player, timeline, and map;
- Automatic focus during frequent location changes;
- Readability with many markers, multiple zoom levels, low-confidence results, and segments with no result;
- Timeline selection and map-marker interaction.

### Smoke Tests and Local Build

The following checks were completed during this development session:

- Python syntax compilation checks for the changed code;
- Smoke tests for empty and valid `video_year` conversion paths;
- JSON validation for frontend locale files;
- A frontend production build;
- Rebuilding and successfully starting the local frontend container;
- Whitespace checks for the code changes.

Work not yet completed includes integration with a real geolocation model, end-to-end regression with real LLMs and large video collections, and a quantitative evaluation of the impact of year context on model quality.

## Suggested Additions for a Final Version

- Individual role, work period, and project or course name;
- Screenshots, demo videos, or presentation links for each feature;
- Reproduction steps, before/after comparison, and impact scope for the timeline bugs;
- Size of the geolocation stress data, browser environment, and performance observations;
- Other LLM plugins that may consume the year context in the future;
- Design discussions, research, collaboration, and presentation work that are not represented in the current local code.
