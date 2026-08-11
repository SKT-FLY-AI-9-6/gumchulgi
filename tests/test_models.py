import torch

from blazebvd.config import BlazeBVDConfig, FlashCorrectionConfig
from blazebvd.flow import ZeroFlow
from blazebvd.models.gfrm import GlobalFlickerRemovalModule
from blazebvd.models.lfrm import LocalFlickerRemovalModule
from blazebvd.models.pipeline import BlazeBVD
from blazebvd.models.tcm import TemporalConsistencyModel


def test_gfrm_shape_and_range():
    model = GlobalFlickerRemovalModule(output_mode="residual")
    output = model(torch.rand(1, 3, 32, 32), torch.rand(1, 1, 32, 32))
    assert output.shape == (1, 3, 32, 32)
    assert 0 <= output.min() and output.max() <= 1


def test_lfrm_shape():
    model = LocalFlickerRemovalModule(max_positions=64)
    images = [torch.rand(1, 3, 16, 16) for _ in range(3)]
    assert model(*images).shape == images[0].shape


def test_tcm_shape():
    model = TemporalConsistencyModel(blocks=1, heads=4, window_size=4)
    video = torch.rand(1, 2, 3, 16, 16)
    flows = torch.zeros(1, 1, 2, 16, 16)
    output = model(video, flows, flows)
    assert output.shape == video.shape


def test_full_pipeline_smoke():
    cfg = BlazeBVDConfig()
    cfg.ste.bins = 32
    cfg.model.nonlocal_max_positions = 64
    cfg.model.tcm_transformer_blocks = 1
    cfg.model.tcm_window_size = 4
    cfg.flow.backend = "zero"
    model = BlazeBVD(cfg, flow_estimator=ZeroFlow())
    video = torch.rand(1, 2, 3, 32, 32)
    result = model(video)
    assert result.output.shape == video.shape
    assert result.priors.exposure_maps.shape == (1, 2, 1, 32, 32)


def _small_pipeline() -> BlazeBVD:
    cfg = BlazeBVDConfig()
    cfg.ste.bins = 32
    cfg.model.nonlocal_max_positions = 64
    cfg.model.tcm_transformer_blocks = 1
    cfg.model.tcm_window_size = 4
    cfg.flow.backend = "zero"
    return BlazeBVD(cfg, flow_estimator=ZeroFlow())


def test_pipeline_accepts_precomputed_priors():
    torch.manual_seed(0)
    model = _small_pipeline()
    video = torch.rand(1, 3, 3, 32, 32)
    priors = model.ste(
        video, fps=30.0, flash_config=model.config.correction.flash
    )
    baseline = model(video, run_tcm=False)
    precomputed = model(video, run_tcm=False, priors=priors)
    torch.testing.assert_close(precomputed.output, baseline.output)


def test_infer_clips_uses_full_video_ste_priors():
    from blazebvd.video import infer_clips

    torch.manual_seed(0)
    model = _small_pipeline()
    frames = torch.rand(9, 3, 32, 32)
    output, report = infer_clips(
        model,
        frames,
        torch.device("cpu"),
        clip_length=4,
        overlap=2,
        run_tcm=False,
    )
    assert output.shape == frames.shape
    assert report["ste_scope"] == "full_video"
    full_priors = model.ste(
        frames.unsqueeze(0), fps=30.0, flash_config=model.config.correction.flash
    )
    expected = torch.where(full_priors.singular_frames[0])[0].tolist()
    assert report["singular_frames"] == [int(index) for index in expected]


def test_full_pipeline_receives_flash_consolidated_ste_prior():
    cfg = BlazeBVDConfig()
    cfg.ste.bins = 256
    cfg.ste.window_radius = 0
    cfg.ste.bright_threshold = 0.99
    cfg.ste.bright_compression_ratio = 1.0
    cfg.model.nonlocal_max_positions = 64
    cfg.model.tcm_transformer_blocks = 1
    cfg.model.tcm_window_size = 4
    cfg.flow.backend = "zero"
    cfg.correction.flash = FlashCorrectionConfig(
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
    model = BlazeBVD(cfg, flow_estimator=ZeroFlow())
    levels = torch.tensor([0.2, 0.8, 0.2, 0.8, 0.2, 0.8, 0.2])
    video = levels.reshape(1, 7, 1, 1, 1).expand(1, 7, 3, 16, 16).clone()

    result = model(video, run_tcm=False, fps=10.0)
    expected = torch.tensor([0.2, 0.2, 0.2, 0.8, 0.8, 0.8, 0.2])
    actual = result.priors.filtered_value[:, :, :, 0, 0].flatten()

    torch.testing.assert_close(actual, expected, atol=2e-5, rtol=0)
