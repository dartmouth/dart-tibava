"""TEMPORARY memory experiment suite for transnet_shotdetection_long (experiment
branch only, do not merge).

Why: replica memory grows on k8s but not locally, and changing an env var on k8s
means restarting the whole pod. So one request runs several configurations back
to back, each in a FRESH subprocess (so memory held by one config cannot leak
into the next, and glibc reads MALLOC_ARENA_MAX at process start), and forwards
each child's log lines into the replica log, prefixed with the config name.

Trigger: submit "Shot Boundary Detection (long videos)" with the fps slider at
8, 9 or 10 (see `experiment_requested`). Each value is a separate analyser cache
key, so a suite can be re-run with a different one. The plugin version is
bumped on this branch so these empty results never collide with real ones.
No shots are produced in this mode.

Child entry point: `python -m inference_ray.plugins.transnet_shotdetection_long_experiment
<zip path> <member name> <model path> <max frames or 0>`. The video lives inside a
zip, so the child opens the member itself and hands the resulting file object to
VideoDecoder, the same read path as the real plugin.
"""

import itertools
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Dict, List, Optional, Tuple

from inference_ray.plugins.transnet_shotdetection_long import (
    DECODER_THREADS_ENV,
    MALLOC_TRIM_ENV,
    TransnetShotdetectionLong,
    decoder_kwargs,
    format_memory,
    memory_snapshot,
    top_processes,
)

logger = logging.getLogger("ray.serve")

EXPERIMENT_FPS_VALUES = {8.0, 9.0, 10.0}

# Environment switches the suite controls. They are removed from the child's
# environment first, so a live edit left on the pod cannot colour a config.
PLAINFILE_ENV = "TRANSNET_EXP_PLAINFILE"  # child extracts the member to a temp file first
SWITCH_VARS = (DECODER_THREADS_ENV, MALLOC_TRIM_ENV, "MALLOC_ARENA_MAX", PLAINFILE_ENV)

# Round 2. Round 1 showed flat child memory over the first 20k frames but steady
# growth past it in a full run (anon 735MB at 20k -> 2001MB at 50k), with
# MALLOC_ARENA_MAX/decoder threads making no clear difference. Growth shows by
# ~30k frames, so 60k is enough to see the slope.
FRAMES = 60000  # about 21 minutes at the k8s decode rate

# (name, environment overrides, max frames or None for the whole video)
CONFIGS: List[Tuple[str, Dict[str, str], Optional[int]]] = [
    # malloc_trim at every periodic log: if anon still climbs, it is a real
    # leak (live native memory), not allocator fragmentation
    ("full_trim", {MALLOC_TRIM_ENV: "1"}, FRAMES),
    # video as a plain file instead of a ZipExtFile: if growth disappears, the
    # Python file-object read path is the culprit
    ("full_plainfile", {PLAINFILE_ENV: "1"}, FRAMES),
]


def experiment_requested(parameters: Optional[Dict]) -> bool:
    try:
        return float((parameters or {}).get("fps")) in EXPERIMENT_FPS_VALUES
    except (TypeError, ValueError):
        return False


def child_command(zip_path: str, member: str, model_path: str, max_frames) -> List[str]:
    return [
        sys.executable,
        "-u",
        "-m",
        __name__,
        str(zip_path),
        member,
        str(model_path),
        str(max_frames or 0),
    ]


def child_env(overrides: Dict[str, str]) -> Dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in SWITCH_VARS}
    env.update(overrides)
    return env


def run_config(name, command, env) -> int:
    """Run one child, forwarding its output lines into the replica log."""
    started = time.monotonic()
    logger.info(
        "[experiment %s] start, env overrides %s, container before: %s",
        name,
        {k: env[k] for k in SWITCH_VARS if k in env} or "none",
        format_memory(memory_snapshot()),
    )
    proc = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    for line in proc.stdout:
        logger.info("[experiment %s] %s", name, line.rstrip())
    code = proc.wait()
    logger.info(
        "[experiment %s] exit code %d after %.0fs, container after: %s",
        name,
        code,
        time.monotonic() - started,
        format_memory(memory_snapshot()),
    )
    return code


def run_suite(
    plugin: TransnetShotdetectionLong,
    inputs,
    data_manager,
    callbacks,
    configs=None,
    command_builder=child_command,
):
    configs = CONFIGS if configs is None else configs
    plugin.update_callbacks(callbacks, progress=0.0)
    with (
        inputs["video"] as input_data,
        data_manager.create_data("ShotsData") as output_data,
    ):
        zip_path = input_data.fs.path
        member = f"video.{input_data.ext}"
        logger.info(
            "[experiment] suite of %d configs on %s: %s",
            len(configs),
            member,
            [name for name, _, _ in configs],
        )
        failed = []
        for i, (name, overrides, max_frames) in enumerate(configs):
            code = run_config(
                name,
                command_builder(zip_path, member, plugin.model_path, max_frames),
                child_env(overrides),
            )
            if code != 0:
                failed.append(name)
            plugin.update_callbacks(callbacks, progress=(i + 1) / len(configs))
        logger.info("[experiment] suite done, container: %s", format_memory(memory_snapshot()))
        if failed:
            raise RuntimeError(f"experiment configs failed: {failed}")
        output_data.shots = []
        return {"shots": output_data}


def child_main(zip_path: str, member: str, model_path: str, max_frames: int) -> None:
    """One configuration: load the model, decode (optionally the first
    `max_frames` frames) and stream it through the model, logging memory the
    same way the plugin does."""
    import torch
    from tibava_utils import VideoDecoder

    logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    logger.info(
        "child env: %s",
        {k: os.environ.get(k) for k in (*SWITCH_VARS, "OMP_NUM_THREADS")},
    )

    plugin = TransnetShotdetectionLong.__new__(TransnetShotdetectionLong)
    plugin.device = "cpu"
    plugin.model = torch.jit.load(model_path, map_location=torch.device("cpu"))
    logger.info("model loaded, %s", format_memory(memory_snapshot()))

    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as zf:
        if os.environ.get(PLAINFILE_ENV) == "1":
            video_path = os.path.join(tmp, "video" + os.path.splitext(member)[1])
            with zf.open(member) as src, open(video_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            logger.info("extracted member to plain file, %s", format_memory(memory_snapshot()))
            f_video = video_path
        else:
            f_video = zf.open(member)
        try:
            decoder = VideoDecoder(
                path=f_video,
                max_dimension=[48, 27],
                extension=os.path.splitext(member)[1],
                **decoder_kwargs(),
            )
            frames = (x.get("frame") for x in decoder)
            total = max(decoder.duration() * decoder.fps(), 1)
            if max_frames:
                frames = itertools.islice(frames, max_frames)
                total = max_frames
            plugin._predict_stream(frames, total, None)
        finally:
            if not isinstance(f_video, str):
                f_video.close()
    logger.info("child done, %s", format_memory(memory_snapshot()))
    logger.info("child top processes: %s", top_processes())


if __name__ == "__main__":
    child_main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
