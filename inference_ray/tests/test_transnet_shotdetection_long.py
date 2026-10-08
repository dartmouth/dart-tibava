"""The streaming plugin must produce exactly the predictions of the parent's
whole-video `predict_frames`. A deterministic fake model stands in for the
TorchScript file: its output at each position depends on the frames around it,
so a windowing or padding mistake changes the result."""

import numpy as np
import pytest
import torch

from inference_ray.plugins.transnet_shotdetection import TransnetShotdetection
from inference_ray.plugins.transnet_shotdetection_long import (
    TransnetShotdetectionLong,
)


class FakeModel:
    def __call__(self, x):
        assert tuple(x.shape) == (1, 100, 27, 48, 3), x.shape
        # x: (1, 100, 27, 48, 3) uint8. Per-frame score mixes in the next
        # frame, so every output depends on neighbouring context.
        per_frame = x.float().mean(dim=(2, 3, 4))
        shifted = torch.roll(per_frame, shifts=-1, dims=1)
        out = ((per_frame + shifted) / 510.0).unsqueeze(-1)
        return out, out * 0.5


def _plugin(cls):
    plugin = cls.__new__(cls)
    plugin.model = FakeModel()
    plugin.device = "cpu"
    return plugin


def _video(n, seed=0):
    return np.random.default_rng(seed).integers(0, 255, (n, 27, 48, 3), dtype=np.uint8)


# 1 frame, shorter than a window, exact multiples of the stride, and not
@pytest.mark.parametrize("n", [1, 7, 49, 50, 51, 99, 100, 101, 149, 150, 1000, 1037])
def test_stream_matches_whole_video(n):
    video = _video(n)

    expected, _ = _plugin(TransnetShotdetection).predict_frames(video, None)
    actual = _plugin(TransnetShotdetectionLong)._predict_stream(
        iter(video), total_frames_estimate=n, callbacks=None
    )

    assert actual.shape == expected.shape == (n,)
    np.testing.assert_array_equal(actual, expected)


def test_stream_does_not_need_the_whole_video():
    # a generator that is consumed lazily is enough
    frames = (f for f in _video(300))
    out = _plugin(TransnetShotdetectionLong)._predict_stream(frames, 300, None)
    assert out.shape == (300,)


def test_decoder_yields_height_27_width_48_frames(tmp_path):
    # VideoDecoder takes [width, height]; the model wants (27, 48, 3) frames.
    imageio = pytest.importorskip("imageio.v3")
    pytest.importorskip("av")
    from tibava_utils import VideoDecoder

    path = tmp_path / "clip.mp4"
    imageio.imwrite(path, _video(20).repeat(4, axis=1).repeat(4, axis=2), plugin="pyav", fps=10)

    frame = next(iter(VideoDecoder(path=str(path), max_dimension=[48, 27])))["frame"]
    assert frame.shape == (27, 48, 3)


def test_memory_snapshot_reports_rss_and_tolerates_missing_cgroup(monkeypatch):
    import builtins

    from inference_ray.plugins import transnet_shotdetection_long as mod

    real_open = builtins.open

    def no_cgroup(path, *args, **kwargs):
        if str(path).startswith("/sys/fs/cgroup"):
            raise FileNotFoundError(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", no_cgroup)
    snap = mod.memory_snapshot()

    assert snap["rss"] > 0
    assert snap["peak_rss"] >= snap["rss"]
    assert not any(k.startswith("cgroup") for k in snap)
    assert "rss=" in mod.format_memory(snap)
    assert mod.format_memory({}) == "unavailable"


def test_top_processes_lists_this_process():
    import os

    from inference_ray.plugins.transnet_shotdetection_long import top_processes

    out = top_processes(n=1000)
    assert f"{os.getpid()}:" in out
