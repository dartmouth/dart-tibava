import contextlib
import logging
import sys

import pytest

from inference_ray.plugins import transnet_shotdetection_long_experiment as exp


@pytest.mark.parametrize(
    "fps,expected",
    [(8, True), (9.0, True), ("10", True), (2, False), (None, False), ("x", False)],
)
def test_experiment_requested(fps, expected):
    assert exp.experiment_requested({"fps": fps}) is expected
    assert exp.experiment_requested(None) is False


def test_child_env_strips_switches_then_applies_overrides(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "99")
    monkeypatch.setenv(exp.MALLOC_TRIM_ENV, "1")
    env = exp.child_env({exp.DECODER_THREADS_ENV: "4"})
    assert "MALLOC_ARENA_MAX" not in env and exp.MALLOC_TRIM_ENV not in env
    assert env[exp.DECODER_THREADS_ENV] == "4"
    assert "PATH" in env  # the rest of the environment is kept


class _Ctx(contextlib.AbstractContextManager):
    def __init__(self, **attrs):
        self.__dict__.update(attrs)

    def __exit__(self, *exc):
        return False

    def open_video(self):
        return contextlib.nullcontext("/fake/video.mp4")


class _Plugin:
    model_path = "/fake/model.pt"

    def __init__(self):
        self.progress = []

    def update_callbacks(self, callbacks, progress):
        self.progress.append(progress)


class _DataManager:
    def create_data(self, name):
        return _Ctx(shots=None)


def _echo_child(video, ext, model, max_frames):
    code = (
        "import os;"
        "print('args', %r, %r, %r, %r);"
        "print('arena', os.environ.get('MALLOC_ARENA_MAX'));"
        "print('trim', os.environ.get('TRANSNET_LONG_MALLOC_TRIM'))"
    ) % (video, ext, model, max_frames)
    return [sys.executable, "-c", code]


def test_run_suite_forwards_child_output_and_isolates_env(monkeypatch, caplog):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "99")  # must not reach the baseline
    logging.getLogger("ray.serve").propagate = True
    plugin = _Plugin()
    configs = [("a", {}, 100), ("b", {"MALLOC_ARENA_MAX": "2"}, None)]
    with caplog.at_level(logging.INFO, logger="ray.serve"):
        out = exp.run_suite(
            plugin,
            {"video": _Ctx(ext="mp4")},
            _DataManager(),
            None,
            configs=configs,
            command_builder=_echo_child,
        )
    text = caplog.text
    assert "[experiment a] arena None" in text
    assert "[experiment b] arena 2" in text
    assert "[experiment a] args /fake/video.mp4 mp4 /fake/model.pt 100" in text
    assert "[experiment b] args /fake/video.mp4 mp4 /fake/model.pt None" in text
    assert text.count("exit code 0") == 2
    assert plugin.progress == [0.0, 0.5, 1.0]
    assert out["shots"].shots == []
