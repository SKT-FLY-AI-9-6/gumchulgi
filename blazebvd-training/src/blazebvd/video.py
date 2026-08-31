from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import Tensor

from .config import AccessibilityCorrectionConfig, STEConfig
from .correction import (
    attenuate_saturated_red,
    consolidate_temporal_flashes,
    flash_block_frame_count,
)
from .models.pipeline import BlazeBVD
from .ste import (
    ScaleTimeEqualization,
    compress_bright_values,
    limit_temporal_deviation,
    moving_average,
    normalized_histograms,
    rgb_value,
    scale_time_mapping,
)


def read_video(path: str | Path) -> tuple[Tensor, float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 24.0
    frames = []
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frames.append(torch.from_numpy(frame.copy()).permute(2, 0, 1))
    capture.release()
    if not frames:
        raise RuntimeError(f"No decodable frames found in: {path}")
    return torch.stack(frames).float().div(255), fps


def _write_silent_video(frames: Tensor, path: Path, fps: float) -> None:
    _, h, w = frames.shape[1:]
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h)
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not create video writer for: {path}")
    try:
        _write_tensor_frames(writer, frames)
    finally:
        writer.release()


def _write_tensor_frames(writer: cv2.VideoWriter, frames: Tensor) -> None:
    """Write a small RGB tensor batch without retaining it after the call."""
    frames_u8 = frames.detach().cpu().clamp(0, 1).mul(255).round().byte()
    for frame in frames_u8:
        bgr = cv2.cvtColor(frame.permute(1, 2, 0).numpy(), cv2.COLOR_RGB2BGR)
        writer.write(bgr)


def _copy_or_mux_audio(
    silent_video: Path,
    output_path: Path,
    audio_source: str | Path | None,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if audio_source is None or ffmpeg is None:
        shutil.copy2(silent_video, output_path)
        return
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(silent_video),
        "-i",
        str(audio_source),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def write_video(
    frames: Tensor,
    output_path: str | Path,
    fps: float,
    audio_source: str | Path | None = None,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="blazebvd-") as temp_dir:
        silent = Path(temp_dir) / "silent.mp4"
        _write_silent_video(frames, silent, fps)
        _copy_or_mux_audio(silent, output_path, audio_source)


def ste_correct(
    frames: Tensor,
    ste: ScaleTimeEqualization,
    correction: AccessibilityCorrectionConfig | None = None,
    fps: float = 30.0,
) -> tuple[Tensor, dict]:
    batch = frames.unsqueeze(0)
    priors = ste(
        batch,
        fps=fps,
        flash_config=correction.flash if correction is not None else None,
    )
    value = rgb_value(batch)
    # Preserve hue/chroma by scaling RGB with V_filtered / V, rather than
    # independently matching the three color channels.
    scale = priors.filtered_value / value.clamp_min(1e-6)
    corrected = (batch * scale).clamp(0, 1)[0]
    if correction is not None:
        # Flash consolidation has already updated the STE filtered-value prior.
        corrected = attenuate_saturated_red(corrected, correction.red)
    report = {
        "frame_count": int(frames.shape[0]),
        "singular_frames": torch.where(priors.singular_frames[0])[0].cpu().tolist(),
        "kl_divergence": priors.kl_divergence[0].cpu().tolist(),
        "singular_threshold": priors.singular_threshold[0].cpu().tolist(),
        "exposed_pixel_ratio": priors.exposure_maps[0].mean(dim=(1, 2, 3)).cpu().tolist(),
    }
    if correction is not None:
        report["correction_order"] = [
            "ste_brightness",
            "ste_temporal_flash_consolidation",
            "saturated_red_attenuation",
        ]
    return corrected, report


def _rgb_tensor(frame_bgr: np.ndarray) -> Tensor:
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    return torch.from_numpy(frame_rgb.copy()).permute(2, 0, 1).float().div(255)


def _collect_histograms(
    input_path: str | Path,
    histogram_path: Path,
    bins: int,
) -> tuple[int, float, tuple[int, int]]:
    """First pass: persist only per-frame value histograms to a temporary file."""
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 24.0
    frame_count = 0
    frame_size: tuple[int, int] | None = None
    try:
        with histogram_path.open("wb") as stream:
            while True:
                ok, frame_bgr = capture.read()
                if not ok:
                    break
                height, width = frame_bgr.shape[:2]
                if frame_size is None:
                    frame_size = (width, height)
                elif frame_size != (width, height):
                    raise RuntimeError("Video frame size changed during decoding")
                frame = _rgb_tensor(frame_bgr)
                value = frame.max(dim=0, keepdim=True).values[None, None]
                histogram = normalized_histograms(value, bins)[0, 0]
                stream.write(histogram.numpy().astype(np.float32, copy=False).tobytes())
                frame_count += 1
    finally:
        capture.release()
    if frame_count == 0 or frame_size is None:
        raise RuntimeError(f"No decodable frames found in: {input_path}")
    return frame_count, fps, frame_size


def _filter_ste_frame(
    frame_bgr: np.ndarray,
    frame_index: int,
    histogram_data: np.ndarray,
    frame_count: int,
    cfg: STEConfig,
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    """Compute STE and highlight compression before temporal flash limiting."""
    lo = max(0, frame_index - cfg.window_radius)
    hi = min(frame_count, frame_index + cfg.window_radius + 1)
    # memmap slices are read-only; copy the small local histogram window before
    # exposing it to PyTorch.
    histogram_window = torch.from_numpy(np.array(histogram_data[lo:hi]))
    source_histogram = histogram_window[frame_index - lo][None]
    offsets = torch.arange(lo, hi, dtype=source_histogram.dtype) - frame_index
    mapping = scale_time_mapping(
        source_histogram,
        histogram_window[None],
        offsets,
        cfg.gaussian_scale,
    )[0]

    frame = _rgb_tensor(frame_bgr)
    value = frame.max(dim=0, keepdim=True).values
    value_bins = (value[0] * (cfg.bins - 1)).round().long()
    filtered_value = mapping[value_bins].div(cfg.bins - 1)[None]
    filtered_value = compress_bright_values(
        value,
        filtered_value,
        cfg.bright_threshold,
        cfg.bright_compression_ratio,
    )
    return frame, value, filtered_value, source_histogram[0]


def _limit_buffered_temporal_flash(
    center: int,
    buffered: dict[int, tuple[Tensor, Tensor, Tensor, Tensor]],
    frame_count: int,
    cfg: STEConfig,
) -> Tensor:
    """Limit one frame using only a radius-sized decoded-frame buffer."""
    filtered_value = buffered[center][2]
    if not cfg.temporal_flash_suppression or cfg.temporal_radius == 0:
        return filtered_value

    indices = [
        min(frame_count - 1, max(0, index))
        for index in range(
            center - cfg.temporal_radius,
            center + cfg.temporal_radius + 1,
        )
    ]
    temporal_values = torch.stack([buffered[index][2] for index in indices])
    reference = temporal_values.median(dim=0).values
    return limit_temporal_deviation(
        filtered_value,
        reference,
        cfg.flash_contrast_threshold,
        cfg.max_temporal_deviation,
        cfg.flash_suppression_strength,
    )


@torch.inference_mode()
def ste_correct_video(
    input_path: str | Path,
    output_path: str | Path,
    ste: ScaleTimeEqualization,
    audio_source: str | Path | None = None,
    correction: AccessibilityCorrectionConfig | None = None,
) -> tuple[dict, float]:
    """Apply STE with two video passes and constant-size pixel working memory.

    The first pass writes one small histogram per frame to a temporary on-disk
    array. The second pass keeps only the local temporal frame window required
    by the centered brightness limiter plus one flash-consolidation block, then
    writes corrected frames in order.
    """
    cfg = ste.config
    if correction is not None:
        correction.validate()
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        tempfile.TemporaryDirectory(prefix="blazebvd-ste-") as temp_dir,
        ExitStack() as cleanup,
    ):
        temp_root = Path(temp_dir)
        histogram_path = temp_root / "histograms.f32"
        silent_path = temp_root / "silent.mp4"
        frame_count, fps, frame_size = _collect_histograms(
            input_path, histogram_path, cfg.bins
        )
        histogram_data = np.memmap(
            histogram_path,
            mode="r",
            dtype=np.float32,
            shape=(frame_count, cfg.bins),
        )
        # On Windows an open memory map prevents TemporaryDirectory cleanup.
        # Register it before the second pass so error paths close it as well.
        cleanup.callback(histogram_data._mmap.close)

        capture = cv2.VideoCapture(str(input_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not reopen video for correction: {input_path}")
        writer = cv2.VideoWriter(
            str(silent_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, frame_size
        )
        if not writer.isOpened():
            capture.release()
            raise RuntimeError(f"Could not create video writer for: {silent_path}")

        kl_values: list[float] = []
        exposed_ratios: list[float] = []
        buffered: dict[int, tuple[Tensor, Tensor, Tensor, Tensor]] = {}
        correction_buffer: list[tuple[Tensor, Tensor, Tensor]] = []
        frame_index = 0
        next_center = 0

        correction_block_frames = 1
        if correction is not None and correction.flash.enabled:
            correction_block_frames = flash_block_frame_count(fps, correction.flash)

        def flush_correction_buffer() -> None:
            if not correction_buffer:
                return
            corrected_frames = torch.stack(
                [corrected for corrected, _, _ in correction_buffer]
            )
            kl_source = torch.stack(
                [filtered_value for _, filtered_value, _ in correction_buffer]
            )
            original_histograms = torch.stack(
                [histogram for _, _, histogram in correction_buffer]
            )
            if correction is not None:
                # The streaming path builds STE one frame at a time, so its
                # block flash pass is performed here before the optional red
                # stage. This buffer is still part of the STE output path.
                corrected_frames = consolidate_temporal_flashes(
                    corrected_frames,
                    fps,
                    correction.flash,
                )
                if correction.flash.enabled:
                    # The KL statistic describes the final STE prior, which
                    # includes flash consolidation but not red attenuation —
                    # the same definition as the in-memory path.
                    kl_source = rgb_value(corrected_frames[None])[0]
                corrected_frames = attenuate_saturated_red(
                    corrected_frames,
                    correction.red,
                )
            filtered_histograms = normalized_histograms(kl_source[None], cfg.bins)[0]
            eps = torch.finfo(filtered_histograms.dtype).eps
            kl = (
                filtered_histograms.clamp_min(eps)
                * (
                    filtered_histograms.clamp_min(eps).log()
                    - original_histograms.clamp_min(eps).log()
                )
            ).sum(dim=-1)
            kl_values.extend(float(value) for value in kl)
            corrected_u8 = (
                corrected_frames.clamp(0, 1)
                .mul(255)
                .round()
                .byte()
                .permute(0, 2, 3, 1)
                .numpy()
            )
            for corrected_rgb in corrected_u8:
                writer.write(cv2.cvtColor(corrected_rgb, cv2.COLOR_RGB2BGR))
            correction_buffer.clear()

        def emit(center: int) -> None:
            frame, value, _, original_histogram = buffered[center]
            filtered_value = _limit_buffered_temporal_flash(
                center,
                buffered,
                frame_count,
                cfg,
            )
            scale = filtered_value / value.clamp_min(1e-6)
            corrected = (frame * scale).clamp(0, 1)

            exposed = (
                (value < cfg.dark_threshold)
                | (value > cfg.bright_threshold)
            ).float().mean()
            exposed_ratios.append(float(exposed))

            correction_buffer.append((corrected, filtered_value, original_histogram))
            if len(correction_buffer) >= correction_block_frames:
                flush_correction_buffer()

        try:
            while True:
                ok, frame_bgr = capture.read()
                if not ok:
                    break
                if frame_index >= frame_count:
                    raise RuntimeError("Video produced more frames on the second decoding pass")
                buffered[frame_index] = _filter_ste_frame(
                    frame_bgr,
                    frame_index,
                    histogram_data,
                    frame_count,
                    cfg,
                )

                # A centered temporal median needs `radius` future frames.
                while next_center + cfg.temporal_radius <= frame_index:
                    emit(next_center)
                    next_center += 1
                    oldest_needed = max(0, next_center - cfg.temporal_radius)
                    for old_index in [index for index in buffered if index < oldest_needed]:
                        del buffered[old_index]
                frame_index += 1

            if frame_index != frame_count:
                raise RuntimeError(
                    "Video frame count changed between passes: "
                    f"{frame_count} then {frame_index}"
                )

            # Replicate the last real frame for right-boundary windows.
            while next_center < frame_count:
                emit(next_center)
                next_center += 1
                oldest_needed = max(0, next_center - cfg.temporal_radius)
                for old_index in [index for index in buffered if index < oldest_needed]:
                    del buffered[old_index]
            flush_correction_buffer()
        finally:
            capture.release()
            writer.release()

        kl_tensor = torch.tensor(kl_values, dtype=torch.float32)[None]
        threshold = moving_average(kl_tensor, cfg.moving_average_radius)[0]
        singular = torch.where(kl_tensor[0] > threshold)[0].tolist()
        report = {
            "frame_count": frame_count,
            "singular_frames": singular,
            "kl_divergence": kl_values,
            "singular_threshold": threshold.tolist(),
            "exposed_pixel_ratio": exposed_ratios,
            "processing_mode": "two_pass_streaming",
            "temporal_buffer_radius": cfg.temporal_radius,
        }
        if correction is not None:
            report.update(
                {
                    "correction_order": [
                        "ste_brightness",
                        "ste_temporal_flash_consolidation",
                        "saturated_red_attenuation",
                    ],
                    "flash_block_frames": correction_block_frames,
                }
            )
        _copy_or_mux_audio(silent_path, output_path, audio_source)
    return report, fps


@torch.inference_mode()
def infer_clips(
    model: BlazeBVD,
    frames: Tensor,
    device: torch.device,
    clip_length: int = 16,
    overlap: int = 4,
    run_tcm: bool = True,
    fps: float = 30.0,
) -> tuple[Tensor, dict]:
    if clip_length <= overlap:
        raise ValueError("clip_length must be greater than overlap")
    t = frames.shape[0]
    if t == 1:
        clip_length, overlap = 1, 0
    step = max(1, clip_length - overlap)
    accumulator = torch.zeros_like(frames, dtype=torch.float32)
    weights = torch.zeros(t, 1, 1, 1)
    # STE is histogram-domain and cheap, so run it once over the full video.
    # Sliced priors then feed every clip, keeping temporal histogram windows,
    # flash blocks, and the singular moving average identical to whole-video
    # processing instead of truncating them at clip boundaries.
    full_priors = model.ste(
        frames.unsqueeze(0),
        fps=fps,
        flash_config=model.config.correction.flash,
    )
    for start in range(0, t, step):
        end = min(t, start + clip_length)
        clip = frames[start:end].unsqueeze(0).to(device)
        result = model(
            clip,
            run_tcm=run_tcm,
            fps=fps,
            priors=full_priors.slice_time(start, end).to(device),
        )
        output = result.output[0].cpu()
        local_weights = torch.ones(end - start, 1, 1, 1)
        if overlap > 0 and start > 0:
            n = min(overlap, end - start)
            local_weights[:n] = torch.linspace(0, 1, n + 2)[1:-1, None, None, None]
        if overlap > 0 and end < t:
            n = min(overlap, end - start)
            local_weights[-n:] = torch.minimum(
                local_weights[-n:], torch.linspace(1, 0, n + 2)[1:-1, None, None, None]
            )
        accumulator[start:end] += output * local_weights
        weights[start:end] += local_weights
        if end == t:
            break
    singular = torch.where(full_priors.singular_frames[0])[0].cpu().tolist()
    return accumulator / weights.clamp_min(1e-6), {
        "frame_count": t,
        "clip_length": clip_length,
        "overlap": overlap,
        "ste_scope": "full_video",
        "singular_frames": [int(index) for index in singular],
    }


def _read_stream_frames(
    capture: cv2.VideoCapture,
    count: int,
    expected_size: tuple[int, int] | None,
) -> tuple[Tensor | None, tuple[int, int] | None]:
    """Decode at most ``count`` RGB frames without retaining earlier frames."""
    frames: list[Tensor] = []
    frame_size = expected_size
    for _ in range(count):
        ok, frame_bgr = capture.read()
        if not ok:
            break
        height, width = frame_bgr.shape[:2]
        if frame_size is None:
            frame_size = (width, height)
        elif frame_size != (width, height):
            raise RuntimeError("Video frame size changed during decoding")
        frames.append(_rgb_tensor(frame_bgr))
    if not frames:
        return None, frame_size
    return torch.stack(frames), frame_size


@torch.inference_mode()
def infer_video_streaming(
    model: BlazeBVD,
    input_path: str | Path,
    output_path: str | Path,
    device: torch.device,
    clip_length: int = 16,
    overlap: int = 4,
    run_tcm: bool = True,
    audio_source: str | Path | None = None,
) -> tuple[dict, float]:
    """Run neural correction with bounded host memory.

    Only one input clip, one output clip, and the overlap carried into the next
    clip are resident at a time. Unlike :func:`infer_clips`, STE priors are
    evaluated per overlapping clip because a full-resolution, full-video prior
    tensor would defeat bounded-memory inference.
    """
    if clip_length <= overlap:
        raise ValueError("clip_length must be greater than overlap")
    if overlap > 0 and clip_length < 2 * overlap:
        raise ValueError(
            "Streaming inference requires clip_length >= 2 * overlap"
        )

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {input_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 24.0
    declared_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = clip_length - overlap
    frame_size: tuple[int, int] | None = None
    decoded_count = 0
    emitted_count = 0
    clip_count = 0
    singular_frames: set[int] = set()

    def correct_clip(frames: Tensor, start: int) -> Tensor:
        nonlocal clip_count
        priors = model.ste(
            frames.unsqueeze(0),
            fps=fps,
            flash_config=model.config.correction.flash,
        )
        local_singular = torch.where(priors.singular_frames[0])[0].cpu().tolist()
        singular_frames.update(start + int(index) for index in local_singular)

        clip = frames.unsqueeze(0).to(device)
        device_priors = priors.to(device)
        result = model(
            clip,
            run_tcm=run_tcm,
            fps=fps,
            priors=device_priors,
        )
        output = result.output[0].detach().cpu()
        output = attenuate_saturated_red(output, model.config.correction.red)
        clip_count += 1
        del result, device_priors, priors, clip
        return output

    with tempfile.TemporaryDirectory(prefix="blazebvd-neural-stream-") as temp_dir:
        silent_path = Path(temp_dir) / "silent.mp4"
        writer: cv2.VideoWriter | None = None
        try:
            frames, frame_size = _read_stream_frames(
                capture,
                clip_length,
                frame_size,
            )
            if frames is None or frame_size is None:
                raise RuntimeError(f"No decodable frames found in: {input_path}")
            decoded_count += int(frames.shape[0])
            writer = cv2.VideoWriter(
                str(silent_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps,
                frame_size,
            )
            if not writer.isOpened():
                raise RuntimeError(f"Could not create video writer for: {silent_path}")

            clip_start = 0
            previous_tail: Tensor | None = None
            while True:
                output = correct_clip(frames, clip_start)
                next_frames, frame_size = _read_stream_frames(
                    capture,
                    step,
                    frame_size,
                )
                no_more_frames = next_frames is None
                if next_frames is not None:
                    decoded_count += int(next_frames.shape[0])

                if overlap == 0:
                    _write_tensor_frames(writer, output)
                    emitted_count += int(output.shape[0])
                elif previous_tail is None:
                    if no_more_frames:
                        _write_tensor_frames(writer, output)
                        emitted_count += int(output.shape[0])
                    else:
                        _write_tensor_frames(writer, output[:-overlap])
                        emitted_count += int(output.shape[0] - overlap)
                        previous_tail = output[-overlap:].clone()
                else:
                    n = min(overlap, previous_tail.shape[0], output.shape[0])
                    fade_in = torch.linspace(
                        0,
                        1,
                        n + 2,
                        dtype=output.dtype,
                    )[1:-1, None, None, None]
                    blended = previous_tail[-n:] * (1 - fade_in) + output[:n] * fade_in
                    _write_tensor_frames(writer, blended)
                    emitted_count += n

                    if no_more_frames:
                        _write_tensor_frames(writer, output[n:])
                        emitted_count += int(output.shape[0] - n)
                        previous_tail = None
                    else:
                        middle_end = output.shape[0] - overlap
                        if middle_end > n:
                            _write_tensor_frames(writer, output[n:middle_end])
                            emitted_count += int(middle_end - n)
                        previous_tail = output[-overlap:].clone()

                if clip_count == 1 or clip_count % 25 == 0 or no_more_frames:
                    total = str(declared_frame_count) if declared_frame_count > 0 else "?"
                    print(
                        f"[blazebvd] decoded {decoded_count}/{total} frames; "
                        f"wrote {emitted_count}",
                        flush=True,
                    )

                if no_more_frames:
                    break

                if overlap > 0:
                    frames = torch.cat((frames[-overlap:], next_frames), dim=0)
                else:
                    frames = next_frames
                clip_start += step
                del output
        finally:
            capture.release()
            if writer is not None:
                writer.release()

        if emitted_count != decoded_count:
            raise RuntimeError(
                "Streaming frame accounting mismatch: "
                f"decoded {decoded_count}, wrote {emitted_count}"
            )
        _copy_or_mux_audio(silent_path, output_path, audio_source)

    return {
        "frame_count": emitted_count,
        "declared_frame_count": declared_frame_count,
        "clip_length": clip_length,
        "overlap": overlap,
        "clip_count": clip_count,
        "processing_mode": "neural_clip_streaming",
        "ste_scope": "per_clip_with_overlap",
        "singular_frames": sorted(singular_frames),
    }, fps


def save_report(report: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")