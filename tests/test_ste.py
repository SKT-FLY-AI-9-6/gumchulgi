import torch

from blazebvd.config import FlashCorrectionConfig, STEConfig
from blazebvd.ste import (
    ScaleTimeEqualization,
    compress_bright_values,
    normalized_histograms,
    scale_time_mapping,
    suppress_temporal_flashes,
    temporal_median,
)


def test_histograms_sum_to_one():
    values = torch.rand(2, 4, 1, 8, 8)
    hist = normalized_histograms(values, bins=32)
    torch.testing.assert_close(hist.sum(-1), torch.ones(2, 4))


def test_constant_video_is_unchanged_and_not_singular():
    frames = torch.full((1, 5, 3, 8, 8), 0.4)
    ste = ScaleTimeEqualization(STEConfig(bins=32, window_radius=2))
    priors = ste(frames)
    torch.testing.assert_close(priors.filtered_value, frames[:, :, :1], atol=1 / 31, rtol=0)
    assert not bool(priors.singular_frames.any())


def test_exposure_map_marks_dark_and_bright_pixels():
    frames = torch.full((1, 3, 3, 4, 4), 0.5)
    frames[..., 0, 0] = 0.0
    frames[..., 1, 1] = 1.0
    cfg = STEConfig(bins=32, dark_threshold=0.1, bright_threshold=0.9)
    priors = ScaleTimeEqualization(cfg)(frames)
    assert torch.all(priors.exposure_maps[..., 0, 0] == 1)
    assert torch.all(priors.exposure_maps[..., 1, 1] == 1)


def test_every_bright_pixel_is_compressed_regardless_of_frame_ratio():
    frames = torch.full((2, 1, 3, 10, 10), 0.4)
    frames[0, 0, :, 0, 0] = 1.0  # Only 1% of the first frame is bright.
    frames[1, 0, :, :, :] = 1.0  # 100% of the second frame is bright.
    cfg = STEConfig(
        bins=256,
        window_radius=0,
        bright_threshold=0.8,
        bright_compression_ratio=0.25,
    )

    priors = ScaleTimeEqualization(cfg)(frames)
    expected_ceiling = 0.8 + 0.25 * (1.0 - 0.8)

    assert priors.filtered_value[0, 0, 0, 0, 0] <= expected_ceiling + 1e-6
    assert torch.all(priors.filtered_value[1] <= expected_ceiling + 1e-6)
    assert priors.exposure_maps[0, 0, 0].sum() == 1
    assert torch.all(priors.exposure_maps[1] == 1)


def test_negative_bright_compression_ratio_lowers_values_below_threshold():
    original = torch.tensor([[[[[0.8, 0.9, 1.0]]]]])
    filtered = torch.ones_like(original)

    corrected = compress_bright_values(
        original,
        filtered,
        bright_threshold=0.8,
        compression_ratio=-0.25,
    )

    expected = torch.tensor([[[[[1.0, 0.775, 0.75]]]]])
    torch.testing.assert_close(corrected, expected)


def test_negative_bright_compression_ratio_is_validated():
    STEConfig(bright_compression_ratio=-0.25).validate()

    try:
        STEConfig(bright_compression_ratio=-1.01).validate()
    except ValueError as error:
        assert "[-1, 1]" in str(error)
    else:
        raise AssertionError("Ratios below -1 must be rejected")


def test_temporal_median_rejects_single_frame_flash():
    values = torch.tensor([0.2, 0.2, 0.9, 0.2, 0.2]).reshape(1, 5, 1, 1, 1)
    reference = temporal_median(values, radius=1)

    assert reference[0, 2, 0, 0, 0] == 0.2


def test_temporal_flash_suppression_limits_every_outlier_pixel():
    values = torch.full((2, 5, 1, 10, 10), 0.2)
    values[0, 2, 0, 0, 0] = 0.85  # Only 1% of this frame flashes.
    values[1, 2] = 0.85  # The whole second frame flashes.

    corrected = suppress_temporal_flashes(
        values,
        temporal_radius=1,
        contrast_threshold=0.1,
        max_temporal_deviation=0.1,
        blend_strength=1.0,
    )

    torch.testing.assert_close(
        corrected[0, 2, 0, 0, 0],
        torch.tensor(0.3),
    )
    torch.testing.assert_close(corrected[0, 2, 0, 1:, 1:], values[0, 2, 0, 1:, 1:])
    torch.testing.assert_close(corrected[1, 2], torch.full_like(corrected[1, 2], 0.3))
    torch.testing.assert_close(corrected[0, 0], values[0, 0])


def test_temporal_flash_suppression_can_be_disabled():
    frames = torch.full((1, 5, 3, 4, 4), 0.2)
    frames[:, 2] = 1.0
    cfg = STEConfig(
        bins=256,
        window_radius=0,
        bright_threshold=0.8,
        bright_compression_ratio=0.25,
        temporal_flash_suppression=False,
    )

    priors = ScaleTimeEqualization(cfg)(frames)

    torch.testing.assert_close(
        priors.filtered_value[0, 2],
        torch.full_like(priors.filtered_value[0, 2], 0.85),
    )


def test_block_flash_consolidation_is_applied_to_ste_prior():
    levels = torch.tensor([0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2])
    frames = levels.reshape(1, 7, 1, 1, 1).expand(1, 7, 3, 2, 2).clone()
    ste = ScaleTimeEqualization(
        STEConfig(
            bins=256,
            window_radius=0,
            bright_threshold=0.99,
            bright_compression_ratio=1.0,
            temporal_flash_suppression=False,
        )
    )
    flash = FlashCorrectionConfig(
        block_duration_seconds=0.3,
        minimum_block_frames=1,
        analysis_size=1,
        contrast_threshold=0.0,
        transition_width=0.0,
        strength=1.0,
        minimum_gain=0.01,
        maximum_gain=100.0,
        scene_cut_threshold=1.0,
    )

    priors = ste(frames, fps=10.0, flash_config=flash)
    expected = torch.tensor([0.2, 0.2, 0.2, 0.8, 0.8, 0.8, 0.2])
    expected = expected.reshape(1, 7, 1, 1, 1).expand_as(priors.filtered_value)

    torch.testing.assert_close(priors.filtered_value, expected, atol=2e-5, rtol=0)


def test_per_frame_mapping_matches_full_ste_mapping():
    frames = torch.rand(1, 7, 3, 8, 8)
    cfg = STEConfig(bins=32, window_radius=2)
    ste = ScaleTimeEqualization(cfg)
    priors = ste(frames)
    values = frames.max(dim=2, keepdim=True).values
    histograms = normalized_histograms(values, cfg.bins)

    reconstructed = []
    for center in range(frames.shape[1]):
        lo = max(0, center - cfg.window_radius)
        hi = min(frames.shape[1], center + cfg.window_radius + 1)
        offsets = torch.arange(lo, hi, dtype=frames.dtype) - center
        mapping = scale_time_mapping(
            histograms[:, center], histograms[:, lo:hi], offsets, cfg.gaussian_scale
        )
        value_bins = (values[:, center, 0] * (cfg.bins - 1)).round().long()
        reconstructed.append(
            torch.gather(mapping, 1, value_bins.reshape(1, -1))
            .reshape_as(value_bins)
            .div(cfg.bins - 1)
        )

    reconstructed_values = torch.stack(reconstructed, dim=1).unsqueeze(2)
    reconstructed_values = compress_bright_values(
        values,
        reconstructed_values,
        cfg.bright_threshold,
        cfg.bright_compression_ratio,
    )
    if cfg.temporal_flash_suppression:
        reconstructed_values = suppress_temporal_flashes(
            reconstructed_values,
            temporal_radius=cfg.temporal_radius,
            contrast_threshold=cfg.flash_contrast_threshold,
            max_temporal_deviation=cfg.max_temporal_deviation,
            blend_strength=cfg.flash_suppression_strength,
        )
    torch.testing.assert_close(reconstructed_values, priors.filtered_value)
