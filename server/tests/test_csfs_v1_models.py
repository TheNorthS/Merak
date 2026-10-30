"""CPU artificial forward/backward checks; never an optimizer or research run."""

import math

import pytest
import torch
from torch import nn
from torch.nn import functional as F

from server.experiment_protocols.csfs_v1.baselines import (
    build_method, latent_span_mask, temporal_context_infonce, visible_temporal_context,
)
from server.experiment_protocols.csfs_v1.capacity import capacity_ledger, gradient_participation
from server.experiment_protocols.csfs_v1.models import FrozenLinearProbe
from server.experiment_protocols.csfs_v1.objectives import (
    PAIR_FAMILIES, csfs_objective, shared_private_covariance, shuffled_b_correspondence, symmetric_infonce,
)
from server.experiment_protocols.csfs_v1.protocol import METHOD_IDS, VIEW_KEYS


@pytest.fixture(autouse=True)
def single_thread_cpu():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        yield
    finally:
        torch.set_num_threads(previous)


def _batch(size=3, steps=32):
    generator = torch.Generator().manual_seed(13)
    # Deliberately artificial short signals, not 30-second research windows.
    return {**{name: torch.randn(size, 19, steps, generator=generator) for name in VIEW_KEYS},
            "a_mask": torch.ones(size, 19, dtype=torch.bool), "b_mask": torch.ones(size, 19, dtype=torch.bool),
            "labels": "must never enter SSL loss"}


def _factors():
    generator = torch.Generator().manual_seed(42)
    return {name: {"shared": torch.randn(4, 128, generator=generator, requires_grad=True),
                   "private": torch.randn(4, 64, generator=generator, requires_grad=True)} for name in VIEW_KEYS}


def test_backbone_has_the_exact_four_registered_blocks_and_independent_linear_factors():
    model = build_method("csfs")
    convolutions = [module for module in model.backbone.modules() if isinstance(module, nn.Conv1d)]
    assert [(module.in_channels, module.out_channels, module.kernel_size, module.padding) for module in convolutions] == [
        (19, 64, (15,), (7,)), (64, 128, (15,), (7,)), (128, 192, (15,), (7,)), (192, 192, (15,), (7,))]
    assert len([module for module in model.backbone.modules() if isinstance(module, nn.GELU)]) == 4
    assert [module.p for module in model.backbone.modules() if isinstance(module, nn.Dropout)] == [0.10] * 4
    assert type(model.shared_projector) is type(model.private_projector) is nn.Linear
    assert model.shared_projector.out_features == 128 and model.private_projector.out_features == 64
    assert model.shared_projector.bias is model.private_projector.bias is None


def test_model_encodes_only_four_composites_and_primary_representation_is_mean_shared_not_private_or_full():
    model, batch = build_method("csfs").eval(), _batch()
    batch["eeg"] = torch.full_like(batch["a_low"], float("nan"))
    calls = []
    hook = model.backbone.register_forward_hook(lambda *_: calls.append(True))
    output = model(batch)
    hook.remove()
    expected = torch.stack([output["views"][name]["shared"] for name in VIEW_KEYS]).mean(0)
    assert len(calls) == 4 and set(output["views"]) == set(VIEW_KEYS)
    assert output["shared_embedding"].shape == (3, 128) and torch.equal(output["shared_embedding"], expected)
    with torch.no_grad():
        model.private_projector.weight.add_(10)
    assert torch.equal(model.representation(batch), expected)


def test_unavailable_channels_cannot_be_imputed_or_leak_values_into_the_encoder():
    model, batch = build_method("csfs").eval(), _batch()
    batch["a_mask"][:, :4] = False
    batch["b_mask"][:, :4] = False
    initial = model.representation(batch)
    for key in VIEW_KEYS:
        batch[key][:, :4] = float("nan")
    assert torch.equal(model.representation(batch), initial)
    batch["a_low"][:, 4] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        model(batch)


@pytest.mark.parametrize("defect", ["missing_mask", "bad_dtype", "missing_view", "channels", "few_channels", "time_shape"])
def test_invalid_four_composite_or_mask_contract_fails_before_encoding(defect):
    batch = _batch()
    if defect == "missing_mask":
        del batch["a_mask"]
    elif defect == "bad_dtype":
        batch["a_mask"] = batch["a_mask"].float()
    elif defect == "missing_view":
        del batch["b_high"]
    elif defect == "channels":
        batch["a_low"] = batch["a_low"][:, :18]
    elif defect == "few_channels":
        batch["a_mask"][:, 3:] = False
    else:
        batch["b_high"] = batch["b_high"][:, :, :20]
    with pytest.raises(ValueError):
        build_method("csfs")(batch)


def test_all_six_registered_pairings_and_covariance_average_match_independent_formula():
    factors = _factors()
    result = csfs_objective(factors)
    for name, pairs in PAIR_FAMILIES.items():
        expected = sum(symmetric_infonce(factors[a]["shared"], factors[b]["shared"]) for a, b in pairs) / 2
        assert torch.allclose(result[name], expected)
    private = sum(shared_private_covariance(factors[name]["shared"], factors[name]["private"]) for name in VIEW_KEYS) / 4
    assert torch.allclose(result["private_loss"], private)
    expected = result["channel_loss"] + result["spectral_loss"] + result["cross_loss"] + 0.05 * private
    assert torch.allclose(result["loss"], expected) and "task_loss" not in result


def test_covariance_is_centered_shared_private_not_private_private_correlation():
    shared, private = torch.tensor([[1., 2.], [3., 6.], [8., 10.]]), torch.tensor([[2.], [5.], [7.]])
    matrix = (shared - shared.mean(0)).T @ (private - private.mean(0)) / 2
    expected = matrix.square().mean()
    assert torch.equal(shared_private_covariance(shared, private), expected)
    assert torch.allclose(shared_private_covariance(shared + 100, private - 300), expected)


@pytest.mark.parametrize("method,active", [("channel_only", "channel_loss"), ("frequency_only", "spectral_loss")])
def test_isolation_switches_disable_the_other_two_agreement_families(method, active):
    result = csfs_objective(_factors(), method)
    for name in PAIR_FAMILIES:
        assert (result[name].item() > 0) == (name == active)
    assert result["private_loss"] > 0


def test_shuffled_control_permutates_every_b_factor_once_and_never_a_or_intra_b_pairing():
    factors = _factors()
    shuffled = shuffled_b_correspondence(factors, generator=torch.Generator().manual_seed(13))
    for name in ("a_low", "a_high"):
        assert shuffled[name]["shared"] is factors[name]["shared"]
    for name in ("b_low", "b_high"):
        assert not torch.equal(shuffled[name]["shared"], factors[name]["shared"])
    original = symmetric_infonce(factors["b_low"]["shared"], factors["b_high"]["shared"])
    changed = symmetric_infonce(shuffled["b_low"]["shared"], shuffled["b_high"]["shared"])
    assert torch.allclose(original, changed)
    terms = csfs_objective(factors, "shuffled_pair", generator=torch.Generator().manual_seed(13))
    expected = sum(symmetric_infonce(shuffled[a]["shared"], shuffled[b]["shared"]) for a, b in PAIR_FAMILIES["cross_loss"]) / 2
    assert torch.allclose(terms["cross_loss"], expected)


def test_full_latent_and_no_private_are_distinct_declared_parameterizations_without_invented_effect():
    full, no_private = build_method("full_latent").eval(), build_method("no_private").eval()
    no_private.backbone.load_state_dict(full.backbone.state_dict())
    with torch.no_grad():
        no_private.shared_projector.weight.copy_(torch.cat((full.shared_projector.weight, full.private_projector.weight)))
    batch = _batch()
    assert full.private_projector is not None and no_private.private_projector is None
    assert torch.allclose(full.representation(batch), no_private.representation(batch))
    assert torch.allclose(full.ssl_loss(batch)["loss"], no_private.ssl_loss(batch)["loss"])
    assert full.ssl_loss(batch)["private_loss"] == no_private.ssl_loss(batch)["private_loss"] == 0


def test_affine_probe_freezes_encoder_and_only_head_receives_gradient_without_optimizer_updates():
    encoder = build_method("csfs")
    before = {name: tensor.detach().clone() for name, tensor in encoder.state_dict().items()}
    probe = FrozenLinearProbe(encoder, 3).train()
    assert not encoder.training and all(not parameter.requires_grad for parameter in encoder.parameters())
    logits = probe(_batch())
    F.cross_entropy(logits, torch.tensor([0, 1, 2])).backward()
    assert all(parameter.grad is None for parameter in encoder.parameters())
    assert all(parameter.grad is not None for parameter in probe.head.parameters())
    assert all(torch.equal(encoder.state_dict()[name], tensor) for name, tensor in before.items())
    assert type(probe.head) is nn.Linear and probe.head.in_features == 128
    assert probe.freeze() is probe and all(not parameter.requires_grad for parameter in probe.parameters())


@pytest.mark.parametrize("fraction", [0.20, 0.50])
def test_seeded_contiguous_latent_masking_has_the_exact_registered_fraction_without_masking_all(fraction):
    mask = latent_span_mask(3, 64, fraction, generator=torch.Generator().manual_seed(42))
    assert mask.dtype == torch.bool and mask.shape == (3, 64)
    assert mask.sum(1).tolist() == [math.ceil(64 * fraction)] * 3
    assert torch.equal(mask, latent_span_mask(3, 64, fraction, generator=torch.Generator().manual_seed(42)))
    assert not mask.all(1).any()


def test_masked_target_values_have_no_path_into_context_and_targets_stop_gradient():
    latent = torch.randn(2, 192, 32, requires_grad=True)
    mask = latent_span_mask(2, 32, 0.50, generator=torch.Generator().manual_seed(13))
    initial = visible_temporal_context(latent, mask)
    perturbed = latent.detach().clone().masked_fill(mask.unsqueeze(1), 99999)
    assert torch.equal(visible_temporal_context(perturbed, mask), initial)
    initial.transpose(1, 2)[mask].square().mean().backward()
    assert torch.count_nonzero(latent.grad.transpose(1, 2)[mask]) == 0
    prediction = torch.randn(3, 8, 192, requires_grad=True)
    target = torch.randn(3, 8, 192, requires_grad=True)
    temporal_context_infonce(prediction, target.detach()).backward()
    assert prediction.grad is not None and target.grad is None


def test_contextual_contrast_is_per_ordinal_batch_sized_and_matches_explicit_losses():
    first, second = torch.randn(3, 5, 192), torch.randn(3, 5, 192)
    expected = torch.stack([symmetric_infonce(first[:, index], second[:, index]) for index in range(5)]).mean()
    assert torch.allclose(temporal_context_infonce(first, second), expected)


def test_all_registered_actual_ssl_parameters_have_finite_gradient_paths_and_identical_capacity():
    models = {method: build_method(method).eval() for method in METHOD_IDS}
    before = {method: {name: value.detach().clone() for name, value in model.state_dict().items()} for method, model in models.items()}
    for method, model in models.items():
        if method == "random_init":
            with pytest.raises(ValueError, match="no-SSL"):
                model.ssl_loss(_batch())
            continue
        loss = model.ssl_loss(_batch(), generator=torch.Generator().manual_seed(13))["loss"]
        assert torch.isfinite(loss)
        loss.backward()
        assert gradient_participation(model)["passed"], gradient_participation(model)
    ledger = capacity_ledger(models, require_gradients=True)
    assert len(ledger["methods"]) == 9 and ledger["capacity_matched"]
    counts = {row["raw_parameters"] for row in ledger["methods"].values()}
    assert len(counts) == 1 and ledger["optimizer_updates_verified"] is False
    assert all(torch.equal(model.state_dict()[name], value) for method, model in models.items() for name, value in before[method].items())


def test_capacity_and_gradient_ledger_rejects_ghost_parameters_and_missing_methods():
    models = {method: build_method(method) for method in METHOD_IDS}
    with pytest.raises(ValueError, match="exact registered"):
        capacity_ledger({key: value for key, value in models.items() if key != "no_private"})
    models["masked_latent"].ghost = nn.Parameter(torch.ones(30000))
    with pytest.raises(ValueError, match="more than 1%"):
        capacity_ledger(models)
    assert "ghost" in gradient_participation(models["masked_latent"])["missing_gradients"]


def test_unknown_method_or_single_example_contrast_is_never_a_fake_zero_success():
    with pytest.raises(ValueError):
        build_method("invented-reference")
    with pytest.raises(ValueError, match=">=2"):
        symmetric_infonce(torch.ones(1, 128), torch.ones(1, 128))


def test_nonfinite_private_factors_cannot_hide_behind_finite_shared_agreement():
    factors = _factors()
    factors["b_high"]["private"] = torch.full((4, 64), float("nan"))
    with pytest.raises(ValueError, match="Cross-covariance"):
        csfs_objective(factors)


@pytest.mark.parametrize("method,requires_grad", [("bendr_context", True), ("masked_latent", False)])
def test_stop_gradient_is_specific_to_registered_masked_latent_target_not_an_invented_bendr_constraint(monkeypatch, method, requires_grad):
    from server.experiment_protocols.csfs_v1 import baselines

    inspected = []
    original = baselines.temporal_context_infonce if requires_grad else baselines.F.mse_loss

    def check(prediction, target):
        inspected.append(target.requires_grad)
        return original(prediction, target)

    if requires_grad:
        monkeypatch.setattr(baselines, "temporal_context_infonce", check)
    else:
        monkeypatch.setattr(baselines.F, "mse_loss", check)
    model = build_method(method).eval()
    model.ssl_loss(_batch(), generator=torch.Generator().manual_seed(13))["loss"].backward()
    assert inspected == [requires_grad] * 4
