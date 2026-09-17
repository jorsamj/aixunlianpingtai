from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image

from platform_core.cleaning_analysis_runtime import (
    CleaningAnalysisRuntime,
    CleaningAnalysisTimeout,
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
)


def test_cleaning_analysis_runtime_real_spawn_returns_metrics(tmp_path):
    image_path = tmp_path / "small.png"
    Image.new("RGB", (320, 240), "gray").save(image_path)

    with CleaningAnalysisRuntime(timeout_seconds=15, poll_seconds=0.1) as runtime:
        metrics = runtime.analyze(
            image_path,
            require_blur=False,
            content_sha256="a" * 64,
        )

    assert metrics["width"] == 320
    assert metrics["height"] == 240
    assert metrics["sha256"] == "a" * 64
    assert isinstance(metrics["dhash"], int)


class _FakeConnection:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def poll(self, timeout):
        time.sleep(min(float(timeout), 0.01))
        return False

    def recv(self):
        raise AssertionError("timeout fake must never produce a response")

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self):
        self.alive = False
        self.terminated = False
        self.killed = False
        self.exitcode = None
        self.daemon = None

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exitcode = -15

    def kill(self):
        self.killed = True
        self.alive = False
        self.exitcode = -9

    def join(self, timeout=None):
        return None


class _FakeMultiprocessingContext:
    def __init__(self):
        self.parent = None
        self.child = None
        self.process = None

    def Pipe(self, duplex=True):
        assert duplex is True
        self.parent = _FakeConnection()
        self.child = _FakeConnection()
        return self.parent, self.child

    def Process(self, *, target, args, name):
        assert callable(target)
        assert len(args) == 1
        assert name == "material-cleaning-analysis"
        self.process = _FakeProcess()
        return self.process


def test_cleaning_analysis_runtime_hard_timeout_terminates_stalled_process(tmp_path):
    fake_context = _FakeMultiprocessingContext()
    runtime = CleaningAnalysisRuntime(
        timeout_seconds=0.1,
        poll_seconds=0.02,
        multiprocessing_context=fake_context,
    )
    started = time.monotonic()
    with pytest.raises(CleaningAnalysisTimeout, match="CLEAN_ANALYSIS_TIMEOUT"):
        runtime.analyze(
            tmp_path / "never-read.png",
            require_blur=True,
            content_sha256="b" * 64,
        )
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert fake_context.process is not None
    assert fake_context.process.terminated is True
    assert fake_context.process.is_alive() is False
    assert runtime._process is None
    assert runtime._connection is None


def test_cleaning_analysis_timeout_default_is_bounded():
    assert DEFAULT_ANALYSIS_TIMEOUT_SECONDS == 30.0
