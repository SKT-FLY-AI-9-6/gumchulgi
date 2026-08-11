from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import torch

from blazebvd.config import (
    AccessibilityCorrectionConfig,
    FlashCorrectionConfig,
    RedCorrectionConfig,
    STEConfig,
)
from blazebvd.ste import ScaleTimeEqualization
from blazebvd.video import read_video, ste_correct, ste_correct_video


def _make_test_video(path: Path, frame_count: int = 8) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (32, 24)
    )
    assert writer.isOpened()
    for index in range(frame_count):
        level = 30 + index * 20
        frame = np.full((24, 32, 3), level, dtype=np.uint8)
        frame[:, :8, 2] = min(255, level + 40)
        writer.write(frame)
    writer.release()


def test_streaming_ste_matches_in_memory_report(tmp_path: Path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    _make_test_video(input_path)
    cfg = STEConfig(bins=32, window_radius=2, moving_average_radius=1)
    ste = ScaleTimeEqualization(cfg)

    frames, _ = read_video(input_path)
    _, expected_report = ste_correct(frames, ste)
    actual_report, fps = ste_correct_video(
        input_path, output_path, ste, audio_source=None
    )

    assert output_path.exists()
    assert actual_report["processing_mode"] == "two_pass_streaming"
    assert actual_report["frame_count"] == frames.shape[0]
    assert actual_report["singular_frames"] == expected_report["singular_frames"]
    torch.testing.assert_close(
        torch.tensor(actual_report["kl_divergence"]),
        torch.tensor(expected_report["kl_divergence"]),
    )
    torch.testing.assert_close(
        torch.tensor(actual_report["singular_threshold"]),
        torch.tensor(expected_report["singular_threshold"]),
    )
    torch.testing.assert_close(
        torch.tensor(actual_report["exposed_pixel_ratio"]),
        torch.tensor(expected_report["exposed_pixel_ratio"]),
    )
    assert fps == 12.0

    output_frames, _ = read_video(output_path)
    assert output_frames.shape == frames.shape


def _make_flash_video(path: Path, frame_count: int = 12) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 12.0, (32, 24)
    )
    assert writer.isOpened()
    for index in range(frame_count):
        level = 200 if index in (5, 6) else 70
        frame = np.full((24, 32, 3), level, dtype=np.uint8)
        frame[:12, :16, 1] = min(255, level + 30)
        writer.write(frame)
    writer.release()


def test_streaming_report_matches_in_memory_with_flash_correction(tmp_path: Path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    _make_flash_video(input_path)
    cfg = STEConfig(bins=32, window_radius=2, moving_average_radius=1)
    correction = AccessibilityCorrectionConfig(
        flash=FlashCorrectionConfig(analysis_size=16),
        red=RedCorrectionConfig(enabled=False),
    )

    frames, fps = read_video(input_path)
    _, expected_report = ste_correct(
        frames, ScaleTimeEqualization(cfg), correction=correction, fps=fps
    )
    actual_report, _ = ste_correct_video(
        input_path,
        output_path,
        ScaleTimeEqualization(cfg),
        audio_source=None,
        correction=correction,
    )

    assert actual_report["singular_frames"] == expected_report["singular_frames"]
    torch.testing.assert_close(
        torch.tensor(actual_report["kl_divergence"]),
        torch.tensor(expected_report["kl_divergence"]),
    )
    torch.testing.assert_close(
        torch.tensor(actual_report["singular_threshold"]),
        torch.tensor(expected_report["singular_threshold"]),
    )


def test_streaming_applies_correction_stages_in_fixed_order(tmp_path: Path):
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "output.mp4"
    _make_test_video(input_path, frame_count=7)
    ste = ScaleTimeEqualization(
        STEConfig(
            bins=32,
            window_radius=0,
            temporal_flash_suppression=False,
            bright_threshold=0.99,
            bright_compression_ratio=1.0,
        )
    )
    correction = AccessibilityCorrectionConfig(
        flash=FlashCorrectionConfig(
            block_duration_seconds=0.25,
            minimum_block_frames=3,
            analysis_size=8,
        ),
        red=RedCorrectionConfig(enabled=False),
    )

    report, _ = ste_correct_video(
        input_path,
        output_path,
        ste,
        audio_source=None,
        correction=correction,
    )

    assert output_path.exists()
    assert report["correction_order"] == [
        "ste_brightness",
        "ste_temporal_flash_consolidation",
        "saturated_red_attenuation",
    ]
    assert report["flash_block_frames"] == 3
