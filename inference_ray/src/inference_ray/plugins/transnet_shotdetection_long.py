from inference_ray.plugin import AnalyserPluginManager
from inference_ray.plugins.transnet_shotdetection import (
    TransnetShotdetection,
    default_parameters,
    provides,
    requires,
)

from tibava_utils import VideoDecoder
from tibava_data import Shot
from tibava_data import DataManager, Data

from typing import Callable, Dict

import logging
import time

import numpy as np

# "ray.serve" is configured by Serve to write to the replica log file; the root
# logger would drop INFO.
logger = logging.getLogger("ray.serve")

default_config = {
    "data_dir": "/data/",
    "host": "localhost",
    "port": 6379,
    "model_name": "transnet",
    "model_device": "cpu",
    "model_file": "/models/transnet_shotdetection/transnet.pt",
}

# Window geometry of the TransNet model, mirrored from
# TransnetShotdetection.predict_frames: 100-frame windows, stride 50, of which
# the 50 center frames are kept (25 frames of context on either side).
WINDOW = 100
STRIDE = 50
CONTEXT = 25

# Log memory every this many model windows (~10k frames).
LOG_EVERY_WINDOWS = 200

MB = 1024 * 1024


def _read_kv(path):
    """Parse a `key value` per line file such as /proc/self/status or memory.stat."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                parts = line.replace(":", " ").split()
                if len(parts) >= 2 and parts[1].isdigit():
                    # /proc/self/status reports kB, cgroup files bytes
                    out[parts[0]] = int(parts[1]) * (1024 if len(parts) > 2 else 1)
    except OSError:
        pass
    return out


def _read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def memory_snapshot() -> Dict[str, int]:
    """Memory figures in bytes, for diagnosing OOMs. Never raises; figures that
    are unavailable (non-Linux, other cgroup layout) are omitted.

    rss / peak_rss: this process. cgroup_*: the whole container, which is what
    the Ray memory monitor compares against its threshold; cgroup_file is page
    cache, cgroup_anon is heap/native allocations."""
    snap = {}
    status = _read_kv("/proc/self/status")
    if "VmRSS" in status:
        snap["rss"] = status["VmRSS"]
    if "VmHWM" in status:
        snap["peak_rss"] = status["VmHWM"]

    # cgroup v2, then v1
    used = _read_int("/sys/fs/cgroup/memory.current")
    if used is not None:
        stat = _read_kv("/sys/fs/cgroup/memory.stat")
        names = {"anon": "cgroup_anon", "file": "cgroup_file"}
        stat_path = "/sys/fs/cgroup/memory.stat"
    else:
        used = _read_int("/sys/fs/cgroup/memory/memory.usage_in_bytes")
        stat_path = "/sys/fs/cgroup/memory/memory.stat"
        names = {"rss": "cgroup_anon", "cache": "cgroup_file"}
    if used is not None:
        snap["cgroup_used"] = used
        stat = _read_kv(stat_path)
        for key, name in names.items():
            if key in stat:
                snap[name] = stat[key]
    return snap


def top_processes(n: int = 6) -> str:
    """The n processes with the largest RSS in this container, one line, for
    finding what else is using memory (e.g. other Ray replicas). Never raises."""
    import os

    procs = []
    try:
        pids = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return "unavailable"
    for pid in pids:
        try:
            rss = _read_kv(f"/proc/{pid}/status").get("VmRSS")
            if rss is None:
                continue
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
            procs.append((rss, pid, cmd[:60]))
        except OSError:
            continue  # process exited while scanning
    procs.sort(reverse=True)
    return "; ".join(f"{pid}:{rss / MB:.0f}MB {cmd}" for rss, pid, cmd in procs[:n]) or "unavailable"


def format_memory(snap: Dict[str, int]) -> str:
    return " ".join(f"{k}={v / MB:.0f}MB" for k, v in snap.items()) or "unavailable"


@AnalyserPluginManager.export("transnet_shotdetection_long")
class TransnetShotdetectionLong(
    TransnetShotdetection,
    config=default_config,
    parameters=default_parameters,
    version="0.1",
    requires=requires,
    provides=provides,
):
    """Same model and output as `transnet_shotdetection`, but the video is
    decoded and fed to the model window by window, so memory use stays flat
    regardless of video length instead of holding (several copies of) every
    frame.

    Only `call` differs from the parent. Keep the windowing and padding in
    `_predict_stream` in sync with `TransnetShotdetection.predict_frames`.
    """

    def _predict_window(self, window: np.ndarray) -> np.ndarray:
        import torch

        with torch.no_grad(), torch.autocast(
            device_type=self.device, enabled=(self.device == "cuda")
        ):
            raw_result = self.model(torch.from_numpy(window[np.newaxis]).to(self.device))
        return raw_result[0].cpu().detach().numpy()[0, CONTEXT : CONTEXT + STRIDE, 0]

    def _predict_stream(self, frames, total_frames_estimate, callbacks):
        """Equivalent to predict_frames(np.stack(frames)) without materializing
        the whole video. `frames` is any iterator over (27, 48, 3) frames."""
        buffer = []
        predictions = []
        n_frames = 0
        last_frame = None
        start = time.monotonic()
        logger.info(
            "[transnet_shotdetection_long] stream start, ~%d frames expected, %s",
            total_frames_estimate,
            format_memory(memory_snapshot()),
        )
        logger.info("[transnet_shotdetection_long] top processes: %s", top_processes())

        def drain():
            # Run the model on every full window currently in the buffer.
            while len(buffer) >= WINDOW:
                predictions.append(self._predict_window(np.stack(buffer[:WINDOW])))
                del buffer[:STRIDE]
                progress = min(len(predictions) * STRIDE / total_frames_estimate, 0.99)
                self.update_callbacks(callbacks, progress=progress)
                if len(predictions) % LOG_EVERY_WINDOWS == 0:
                    elapsed = time.monotonic() - start
                    logger.info(
                        "[transnet_shotdetection_long] frames=%d windows=%d "
                        "elapsed=%.0fs (%.1f frames/s) %s",
                        n_frames,
                        len(predictions),
                        elapsed,
                        n_frames / max(elapsed, 1e-9),
                        format_memory(memory_snapshot()),
                    )
                    logger.info(
                        "[transnet_shotdetection_long] top processes: %s", top_processes()
                    )

        for frame in frames:
            if n_frames == 0:
                # start padding: copies of the first frame
                buffer.extend([frame] * CONTEXT)
            buffer.append(frame)
            last_frame = frame
            n_frames += 1
            drain()

        if n_frames == 0:
            return np.zeros(0, dtype=np.float32)

        # end padding: copies of the last frame, 25 - 74 of them so that the
        # padded length is a whole number of strides
        no_padded_frames_end = CONTEXT + STRIDE - (n_frames % STRIDE or STRIDE)
        buffer.extend([last_frame] * no_padded_frames_end)
        drain()

        elapsed = time.monotonic() - start
        logger.info(
            "[transnet_shotdetection_long] stream done, frames=%d windows=%d "
            "elapsed=%.0fs %s",
            n_frames,
            len(predictions),
            elapsed,
            format_memory(memory_snapshot()),
        )
        logger.info("[transnet_shotdetection_long] top processes: %s", top_processes())
        return np.concatenate(predictions)[:n_frames]

    def call(
        self,
        inputs: Dict[str, Data],
        data_manager: DataManager,
        parameters: Dict = None,
        callbacks: Callable = None,
    ) -> Dict[str, Data]:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"

        if self.model is None:
            self.model = torch.jit.load(
                self.model_path, map_location=torch.device(device)
            )
            self.device = device
            logger.info(
                "[transnet_shotdetection_long] model loaded on %s, %s",
                device,
                format_memory(memory_snapshot()),
            )

        self.update_callbacks(callbacks, progress=0.0)
        with (
            inputs["video"] as input_data,
            data_manager.create_data("ShotsData") as output_data,
        ):
            with input_data.open_video() as f_video:
                # VideoDecoder takes [width, height]. TransNetV2 expects 48 wide x
                # 27 high frames, i.e. (27, 48, 3) arrays, so no reshape is needed.
                # The parent plugin passes [27, 48] and then reshapes the
                # resulting (48, 27, 3) frames to (27, 48, 3), which scrambles
                # each frame. This plugin deliberately uses the canonical
                # preprocessing, so its shots can differ slightly from the parent's.
                video_decoder = VideoDecoder(
                    path=f_video,
                    max_dimension=[48, 27],
                    extension=f".{input_data.ext}",
                )
                total_frames_estimate = max(
                    video_decoder.duration() * video_decoder.fps(), 1
                )
                logger.info(
                    "[transnet_shotdetection_long] video %sx%s fps=%.3f duration=%.0fs, %s",
                    *video_decoder._size,
                    video_decoder.fps(),
                    video_decoder.duration(),
                    format_memory(memory_snapshot()),
                )

                prediction = self._predict_stream(
                    (x.get("frame") for x in video_decoder),
                    total_frames_estimate,
                    callbacks,
                )

                shot_list = self.predictions_to_scenes(
                    prediction, parameters.get("threshold")
                )

                output_data.shots = [
                    Shot(
                        start=x[0].item() / video_decoder.fps(),
                        end=x[1].item() / video_decoder.fps(),
                    )
                    for x in shot_list
                ]

                self.update_callbacks(callbacks, progress=1.0)

                return {"shots": output_data}
