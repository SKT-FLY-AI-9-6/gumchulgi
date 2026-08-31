import torch

from blazebvd.flow import backward_warp


def test_backward_warp_target_to_source_convention():
    source = torch.arange(5, dtype=torch.float32).reshape(1, 1, 1, 5)
    flow = torch.zeros(1, 2, 1, 5)
    flow[:, 0] = 1  # target x samples source x+1
    warped = backward_warp(source, flow)
    torch.testing.assert_close(warped[0, 0, 0], torch.tensor([1.0, 2.0, 3.0, 4.0, 4.0]))

