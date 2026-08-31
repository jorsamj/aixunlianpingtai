from pathlib import Path

import cv2
import numpy as np
import pytest

from platform_core.video_tasks import (
    SamplingMode,
    VideoSampleRequest,
    extract_video,
    plan_frame_indices,
    probe_video,
)


@pytest.fixture
def real_short_video(tmp_path):
    path = tmp_path / "sample video.avi"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10.0,
        (64, 48),
    )
    assert writer.isOpened()
    for index in range(20):
        frame = np.full((48, 64, 3), index * 10, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    assert path.stat().st_size > 0
    return path


def test_fixed_count_is_exact_unique_and_includes_endpoints():
    request = VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=7)
    indices = plan_frame_indices(total_frames=20, source_fps=10, request=request)
    assert len(indices) == 7
    assert len(set(indices)) == 7
    assert indices[0] == 0
    assert indices[-1] == 19


def test_fixed_count_caps_at_available_frames():
    request = VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=9)
    assert plan_frame_indices(4, 10, request) == [0, 1, 2, 3]


def test_interval_and_fps_plans_are_deterministic():
    every_half_second = VideoSampleRequest(
        SamplingMode.INTERVAL_SECONDS,
        interval_seconds=0.5,
    )
    requested_fps = VideoSampleRequest(SamplingMode.FPS, extract_fps=2)
    assert plan_frame_indices(20, 10, every_half_second) == [0, 5, 10, 15]
    assert plan_frame_indices(20, 10, requested_fps) == [0, 5, 10, 15]


def test_request_requires_exactly_one_positive_sampling_value():
    with pytest.raises(ValueError, match="exactly one"):
        VideoSampleRequest(SamplingMode.FPS, extract_fps=2, fixed_count=3)
    with pytest.raises(ValueError, match="positive"):
        VideoSampleRequest(SamplingMode.INTERVAL_SECONDS, interval_seconds=0)


def test_real_opencv_extract_writes_nonempty_frames_and_metadata(real_short_video, tmp_path):
    probe = probe_video(real_short_video, backend="opencv")
    assert probe.total_frames == 20
    assert probe.fps == pytest.approx(10, rel=0.05)
    assert probe.duration_seconds == pytest.approx(2, rel=0.05)

    progress = []
    result = extract_video(
        real_short_video,
        tmp_path / "frames",
        VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=5),
        backend="opencv",
        progress=lambda done, total, current: progress.append((done, total, current)),
    )
    assert result.expected_frames == 5
    assert result.extracted_frames == 5
    assert [item.source_frame_index for item in result.frames][0::4] == [0, 19]
    assert all(Path(item.path).is_file() and Path(item.path).stat().st_size > 0 for item in result.frames)
    assert all(len(item.sha256) == 64 for item in result.frames)
    assert progress[-1][:2] == (5, 5)


def test_corrupt_video_fails_instead_of_creating_empty_success(tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="video"):
        extract_video(
            corrupt,
            tmp_path / "frames",
            VideoSampleRequest(SamplingMode.FIXED_COUNT, fixed_count=2),
            backend="opencv",
        )
