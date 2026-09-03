# AI_CONTEXT: TIBAVA geolocation + timeline + VQA year context

```yaml
authority:
  use_as: local-development handoff context
  evidence: [local workspace, current Codex conversations, added code comments]
  exclude_claims: [pre-existing platform backend, inference infrastructure, deployment]

scope:
  implemented:
    - geolocation map + timeline UI
    - mock geolocation fixtures + density/stress interaction scenarios
    - map auto-focus synchronized to video playback
    - timeline/plugin-run write-back reliability fixes
    - optional generic plugin invocation field: video_year
  non-goals/currently-not-true:
    - geolocation UI is not backed by a real geolocation inference model
    - video_year is not persisted in PluginRun history
    - video_year is not a deterministic VQA filter
    - real-model E2E and quantitative year-context evaluation are not complete

core_terms:
  mock_geolocation: local fixture; never model output
  plugin_parameters: plugin-specific parameters; do not add generic context here
  generic_invocation_context: top-level optional request data, validated centrally, passed via task kwargs
  video_year: optional generic invocation context; current consumer = BLIP VQA only
  VQA_year_effect: temporal text added to every analysed-frame prompt; soft guidance only
```

## GRAPH

```text
VideoAnalysis.vue/player.currentTime
  ├─> Geolocation.vue(variant="timeline")
  └─> Geolocation.vue(variant="map")
       invariant: map focus only when active geo segment changes

ModalPlugin.vue: Analysis Context.video_year
  -> Parameters.vue: number_field
  -> plugin_run.js: FormData[video_year] only when non-empty
  -> views/plugin_run.py: POST video_year
  -> plugin_manager.py: parse_optional_video_year + task kwargs
  -> tasks/blip_vqa.py: opt-in vqa_parameters[video_year]
  -> inference_ray/plugins/blip_embedding.py: prepend temporal context per VQA frame

plugin task timeline write-back
  -> Timeline / TimelineSegment / annotations or scalar data
  -> serializable timeline IDs in result structure
  -> PluginRunResult
  -> frontend stores / VideoAnalysis.vue
```

## FILE_MAP

```yaml
frontend/src/components/Geolocation.vue:
  owns: [mock places, mock segments, MapLibre map, OSM base map, timeline DOM interaction, current-place rendering, map focus]
  inputs: [shared playback time]
  hard_rules:
    - fixture is deliberately high-density demo/test data
    - distinguish location result vs no-location result
    - segment click seeks midpoint
    - blank-track click seeks by horizontal ratio
    - do not fly/animate map for every video frame
    - preserve bounds/world-copy protections

frontend/src/views/VideoAnalysis.vue:
  owns: [map/timeline placement, player-facing analysis view, selected video initialization]
  hard_rules:
    - plugin launch must target route/current video
    - player time is source of truth for geolocation synchronization

frontend/src/components/ModalPlugin.vue:
  owns: [all-plugin Analysis Context UI, video_year field definition]
  hard_rules:
    - visible for any selected plugin
    - keep separate from any VQA-only parameter config

frontend/src/components/Parameters.vue:
  owns: [reusable number_field rendering]

frontend/src/store/plugin_run.js:
  owns: [plugin-run FormData]
  hard_rules:
    - append top-level video_year only when non-empty
    - never inject generic context into plugin parameters array

backend/src/backend/backend/views/plugin_run.py:
  owns: [POST extraction, PluginManager invocation]

backend/src/backend/backend/utils/parser.py:
  owns: [parse_optional_video_year]
  contract:
    accepted: [null, empty, whole-number integer/string in 1888..2100]
    rejected: [boolean, fraction, nonnumeric, lower-than-1888, higher-than-2100]

backend/src/backend/backend/plugin_manager.py:
  owns: [central validation, normalized non-null context -> task kwargs]
  hard_rules:
    - validate before async dispatch
    - avoid requiring plugin-specific parsers to whitelist generic context

backend/src/backend/backend/tasks/blip_vqa.py:
  owns: [explicit BLIP VQA opt-in]
  known_todo: persist generic invocation context (e.g., PluginRun JSONField) for audit/rerun

inference_ray/src/inference_ray/plugins/blip_embedding.py:
  owns: [VQA frame prompt composition]
  contract:
    with_year: prepend temporal context to each analysed-frame question
    without_year: preserve existing question path
  known_todo: validated post-processing / structured output if year must be enforced

backend/src/backend/backend/tasks/clip_ontology.py:
  risk: [timeline IDs, annotations/scalar output, multiple results, empty shot input]

backend/src/backend/backend/tasks/place_identification.py:
  risk: [serializable result IDs, annotation timeline write-back]

backend/src/backend/backend/tests.py:
  owns: [timeline generation, multiple result records, transaction rollback regression coverage]
```

## CONTRACTS

```yaml
geolocation_contract:
  current_data_source: local fixture in Geolocation.vue
  required_state_link: player_time <-> active_geo_segment <-> map_highlight/focus
  behavior:
    - playback entering new segment updates active place
    - map move only on segment transition
    - time cursor reflects player state
    - no-location segment remains explicitly unlabelled/no-result
    - marker selection/popup works under pan and zoom
  real_data_replacement_minimum_shape:
    segment: {start: number, end: number, placeId: string?, label: string?, confidence: number?}
    place: {id: string, latitude: number, longitude: number, label: string, confidence: number?}
  integration_rule: define persistence/API adapter before removing fixture; do not bind raw model response directly to view

timeline_writeback_contract:
  task_output: stable serializable IDs; never ORM objects
  data_types: [annotation timeline, scalar timeline, plugin-run result]
  invariants:
    - no-shot input creates no invalid references
    - multiple concepts/results remain individually addressable where UI expects them
    - task failure does not leave partial transactional timeline objects
    - selected video is initialized before run launch
    - frontend refreshes result/timeline state for correct video

video_year_contract:
  UI: Run Plugin > select any plugin > Analysis Context > optional Video year
  transport: FormData.top_level.video_year
  validation: central backend parser
  propagation: PluginManager kwargs -> task-specific opt-in
  current_consumer: BLIP VQA
  semantics: historically relevant disambiguation hint, not truth/eligibility/hard filter
  absent_value: omitted end-to-end; original behavior unchanged
```

## REGRESSION_MATRIX

```yaml
priority_P0_timeline_writeback:
  - task returns ORM object instead of serializable ID
  - wrong annotation/scalar timeline relationship
  - no selected/available shots
  - multiple concept/output result creation
  - exception after timeline creation => rollback required
  - opening VideoAnalysis then immediately running plugin => correct video ID
  checks:
    - inspect Timeline, TimelineSegment, PluginRunResult references
    - extend/run backend/src/backend/backend/tests.py
    - verify new run in UI; avoid relying on stale store state

priority_P1_geolocation_interaction:
  - playback crosses multiple segments
  - rapid boundary changes
  - segment click
  - blank track click
  - low-confidence/no-location segment
  - high marker density at low/high zoom
  - pan near world/date-line boundary
  expected:
    - player, playhead, active marker, map focus agree
    - focus changes once per active-segment transition
    - no invented location for no-result data
    - no duplicate-world/unbounded pan artifact

priority_P1_video_year:
  ui: [empty, valid whole number, visible with non-VQA plugin, visible with VQA]
  parser: [null, empty-string, integer, numeric-string, boolean, fraction, nonnumeric, 1888, 2100, 1887, 2101]
  dispatch: [non-null normalized int enters kwargs, omitted value does not]
  VQA: [with-year prompt includes context per frame, without-year prompt unchanged]
```

## STATE_GAPS

```yaml
real_geolocation:
  status: absent
  next_requirement: define backend storage + API + adapter for segment/place data

video_year_auditability:
  status: absent
  next_requirement: persist generic invocation context on PluginRun; define rerun semantics

video_year_enforcement:
  status: soft-prompt-only
  next_requirement: choose output schema validation, constrained generation, or post-processing before calling it hard filtering

evaluation:
  status: no recorded quantitative result
  next_requirement: labelled video/frame set + baseline-vs-year metrics + failure analysis
```

## CHANGE_PROTOCOL

```text
Before editing:
  1. Classify target: geolocation UI | timeline write-back | generic context | VQA inference.
  2. Read every file listed for that target in FILE_MAP.
  3. Identify affected contract + regression matrix rows.

When adding generic analysis context:
  UI definition -> shared control -> top-level FormData -> central parser -> manager kwargs -> explicit consumer opt-in -> persistence decision -> omitted/valid/invalid/consumer tests.

When replacing mock geolocation:
  persistent schema/API -> frontend adapter -> preserve current-time synchronization -> preserve no-result UX -> test empty/sparse/dense/overlapping/out-of-order data -> remove/gate fixture only after fallback is verified.

When changing task timeline write-back:
  determine input cardinality + output cardinality -> keep DB writes transactional -> return IDs -> update backend tests -> execute fresh UI run.

After editing:
  run targeted tests + syntax/build checks appropriate to modified layer;
  do not treat frontend build success as proof that tasks/inference work.
```

## DO_NOT_ASSUME

```text
- Mock geolocation = real geolocation inference.
- Prompt text = guaranteed LLM compliance.
- UI min/max validation = backend validation.
- A single timeline output = correct behavior for a multi-concept task.
- A successful task request = correct result persistence/reference structure.
- A successful frontend build = working background dispatch or inference.
- Existing backend/deployment/inference scaffolding = contribution of this work scope.
```

## OPEN_DECISIONS

```yaml
- canonical backend model and API for real geolocation segments/places
- PluginRun persistence schema and rerun behavior for generic context
- other LLM plugins that should opt into video_year
- meaning of video_year: hint vs eligibility filter vs source of truth
- dense-map performance target and measurement environment
- labelled evaluation set and metrics for VQA temporal context
```
