# Memory-risk report: other plugins at ~30 min / ~500 MB video

## Context
transnet_shotdetection_long was OOM-killed on k8s. You asked which other plugins and
inference modules could hit memory limits on videos of similar size. An Explore agent
read the code and configs (nothing was run). These are code-reading estimates, not
measurements, and I have not independently re-checked the file:line claims.

Assumptions: 1080p RGB frame = 6.2 MB; 30 min = 45k frames at 25 fps. A 500 MB / 30 min
file is ~2.2 Mbit/s, so it may really be 720p (frame figures drop ~2.25x).

Limits (`tibava-k8s/dev/dart-tibava.yml`): inference pod request 4Gi / limit 8Gi shared by
all Ray replicas; Ray kills workers at ~7.2Gi (threshold 0.9); celery limit 2Gi; backend
unlimited. Only the two transnet apps reserve Ray memory (`inference_ray/deploy.cpu-only.yml`:
3GiB and 1.5GiB), so other apps are co-scheduled with no accounting.

## Findings (ranked)
| Risk | Plugin / path | Why |
|---|---|---|
| Certain failure | active_speaker_detection (`active_speaker_detection.py:96-103`) | `[f["frame"] for f in decoder]` at 25 fps, native res: ~280 GB; exceeds 8Gi after ~1 min of video |
| High | backend geolocation celery task (`tasks/geolocation.py:74-107`) | keeps raw full-res frames per sampled shot, resizes later; ~2-15 GB vs 2Gi celery limit (shot count assumed) |
| High | nano_ocr_video (`ocr_nano.py:73-94`) | ~3B VLM, 4-bit; risk is model + decoder inside shared 8Gi, not video length; resident size not determined |
| Medium-high | video export with `include_video` (`views/video_export.py:687`) | `f.read()` then BytesIO, getvalue, base64: ~2.5-3 GB in unlimited backend |
| Medium | transnet_shotdetection original | list + stack + concatenate copies; fine at this size (3GiB reserved), unsafe >~120k frames |
| Medium | shot_scale_and_movement | full-res float32 transforms, ~1 GB transient at 1080p, ~4 GB at 4K |
| Medium | whisper / whisper_x | ~3 GB model + 115 MB audio, no reservation |
| Low-medium | shot_angle, shot_level, places_classification | native-res batches; model reloaded per request; places writes ~3-4 GB JPEGs to disk |
| Low | audio analysers, insightface, clip/xclip, ocr_onnx, color, thumbnail, timeline sampler, video_to_audio/video | streamed or small |

## Shared helpers
- `VideoData.__call__`/`VideoIterator` (`tibava_data/plugins/video_data.py:50-77`) accept only `fps`,
  so clip, places, blip and timeline sampler always get native-res frames.
- Many plugins call `VideoDecoder` without `max_dimension`.
- `VideoDecoder`/`imageio.imiter` decode at full res before the scale filter, so decoder
  buffers cost memory even with a small `max_dimension` (plausible, unverified, contributor to
  the native growth seen on k8s).
- `VideoBatcher` doubles batch memory and drops the trailing partial batch (correctness bug).
- Unverified: whether imageio/pyav buffers the whole `ZipExtFile` (500 MB) in RAM. This would
  affect every video plugin and is the biggest open question.

## Suggested follow-ups (not started)
1. Rewrite active_speaker_detection to stream and crop/downscale per face track.
2. Resize/JPEG-encode inside geolocation `_extract_shot_frames`.
3. Stream the video export to a temp file instead of read/BytesIO/base64.
4. Add Ray memory reservations or max_replicas for whisper, nano_ocr, places.
5. Let `VideoIterator` take `max_dimension`; pass it from shot_* and clip plugins.
6. Check the `ZipExtFile` question using the memory suite output once it runs.

