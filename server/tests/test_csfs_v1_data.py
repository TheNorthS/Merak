"""Artificial temporary signal fixtures only: no EEG corpus, model or optimization."""

from dataclasses import replace
import hashlib
import json

import numpy as np
import pytest

from server.experiment_protocols.csfs_v1.data_contract import (
    DataContractError, build_ldo_fold, load_data_manifest, load_recording,
    build_in_domain_fold,
)
from server.experiment_protocols.csfs_v1.preprocessing import (
    Segment, fit_source_normalizer, prepare_recording, segment_recording,
)
from server.experiment_protocols.csfs_v1.data import (BalancedSourceSampler, channel_subsets, four_composites,
                                                   stack_composites, prepare_fold, prepare_in_domain_fold)
from server.experiment_protocols.csfs_v1.perturbations import (
    c3_evaluation_inventory, random_deletion, region_deletion, spectral_perturbation,
)
from server.experiment_protocols.csfs_v1.protocol import CANONICAL_CHANNELS, STRIDE_SAMPLES, WINDOW_SAMPLES


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _binding(root, relative, contents):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return {"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _fixture(root, *, channel_count=19, rate=256, duration=45, dataset_count=4, subjects=2):
    """Mimic a reviewed manifest purely to test parsing; these signals are not research data."""
    datasets = []
    for index in range(dataset_count):
        identity = f"fixture-dataset-{index}"
        license_file = _binding(root, f"data/legal/{identity}-license.txt", "Artificial fixture license text, not a real dataset approval.")
        provenance = _binding(root, f"data/legal/{identity}-provenance.txt", "Temporary generated sinusoid fixture; never scientific evidence.")
        review = {"decision": "approved_research_use", "reviewer_id": "fixture-human-reviewer", "reviewed_at": "fixture-date",
                  "license_sha256": license_file["sha256"], "provenance_sha256": provenance["sha256"]}
        review_path = f"data/legal/{identity}-review.json"
        _json(root / review_path, {**review, "dataset_id": identity, "version": "fixture-v1", "source_uri": "fixture://artificial"})
        rows = []
        for subject in range(subjects):
            relative = f"data/recordings/{identity}-subject-{subject}.npy"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            time = np.arange(int(rate * duration)) / rate
            values = np.array([np.sin(2 * np.pi * (5 + channel / 3) * time + index + subject / 3)
                + 0.2 * np.sin(2 * np.pi * 35 * time) + index + subject + 0.001 * time
                for channel in range(channel_count)], dtype=np.float32)
            np.save(path, values, allow_pickle=False)
            rows.append({"recording_id": f"recording-{index}-{subject}", "subject_id": f"global-person-{index}-{subject}",
                         "raw_id": f"raw-{index}-{subject}", "path": relative,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "sample_rate": rate,
                         "sample_count": values.shape[1], "channels": list(CANONICAL_CHANNELS[:channel_count]), "label": "negative"})
        datasets.append({"dataset_id": identity, "version": "fixture-v1", "source_uri": "fixture://artificial",
            "task_type": "classification", "endpoint": "registered_fixture_class", "label_vocabulary": ["negative", "positive"],
            "analysis_unit": "subject", "data_origin": "recorded_eeg", "inclusion_count": len(rows),
            "exclusion_count": 0, "exclusion_ledger": [], "channel_map": {name: name for name in CANONICAL_CHANNELS},
            "license": license_file, "provenance": provenance,
            "legal_review": {**review, "evidence": {"path": review_path,
                "sha256": hashlib.sha256((root / review_path).read_bytes()).hexdigest()}}, "recordings": rows})
    payload = {"schema": 1, "protocol": "CSFS-v1", "endpoint": "registered_fixture_class",
               "label_vocabulary": ["negative", "positive"], "datasets": datasets}
    _json(root / "data/manifests/datasets.json", payload)
    return payload


def _segment(channels=19, identity="toy-parent", subject="toy-person"):
    raw_hash = hashlib.sha256(identity.encode()).hexdigest()
    mask = np.zeros(19, dtype=bool)
    mask[:channels] = True
    time = np.arange(WINDOW_SAMPLES) / 256
    values = np.zeros((19, WINDOW_SAMPLES), dtype=np.float32)
    values[mask] = np.sin(2 * np.pi * 4 * time) + np.sin(2 * np.pi * 20 * time)
    parent = hashlib.sha256(f"{identity}:{raw_hash}:0:{WINDOW_SAMPLES}".encode()).hexdigest()
    return Segment(values, mask, "toy-dataset", subject, identity, parent, identity, raw_hash, 0, 0, "toy-source-normalizer")


@pytest.mark.parametrize("missing", ["manifest", "legal_review", "recording", "label", "endpoint", "origin", "count", "mapping", "task"])
def test_absent_unverified_or_incompatible_recordings_fail_without_fallback(tmp_path, missing):
    payload = _fixture(tmp_path, dataset_count=3)
    dataset = payload["datasets"][0]
    if missing == "manifest":
        (tmp_path / "data/manifests/datasets.json").unlink()
    elif missing == "recording":
        (tmp_path / dataset["recordings"][0]["path"]).unlink()
    else:
        if missing == "legal_review":
            dataset["legal_review"]["decision"] = "unverified"
        elif missing == "label":
            dataset["recordings"][0]["label"] = "foreign-label"
        elif missing == "endpoint":
            dataset["endpoint"] = "different-endpoint"
        elif missing == "origin":
            dataset["data_origin"] = "simulation"
        elif missing == "count":
            dataset["inclusion_count"] += 1
        elif missing == "mapping":
            dataset["channel_map"]["Fp2"] = "Fp1"
        else:
            dataset["task_type"] = "regression"
        _json(tmp_path / "data/manifests/datasets.json", payload)
    with pytest.raises((DataContractError, ValueError)):
        load_data_manifest(tmp_path)


@pytest.mark.parametrize("field", ["raw_id", "recording_id", "subject_id", "sha256"])
def test_forbidden_raw_subject_parent_and_content_duplicates_are_rejected(tmp_path, field):
    payload = _fixture(tmp_path)
    first, second = payload["datasets"][0]["recordings"][0], payload["datasets"][1]["recordings"][0]
    if field == "sha256":
        (tmp_path / second["path"]).write_bytes((tmp_path / first["path"]).read_bytes())
    second[field] = first[field]
    _json(tmp_path / "data/manifests/datasets.json", payload)
    with pytest.raises(DataContractError, match="Duplicate|Subject crosses"):
        load_data_manifest(tmp_path)


def test_source_only_normalization_and_registered_windows_keep_target_excluded(tmp_path):
    _fixture(tmp_path, rate=128)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    assert set(fold.source_ids).isdisjoint({fold.target_id, fold.validation_id})
    normalizer = fit_source_normalizer(corpus, fold)
    assert set(dict(normalizer.source_recordings)) == {record.recording_id for record in fold.training}
    assert set(dict(normalizer.source_recordings)).isdisjoint({record.recording_id for record in (*fold.validation, *fold.target)})
    assert set(normalizer.counts) == {len(fold.training) * 45 * 256}
    values, mask = prepare_recording(corpus, fold.target[0])
    assert values.shape == (19, 45 * 256) and mask.all()
    segments = segment_recording(corpus, fold, fold.target[0], normalizer)
    assert len(segments) == 2 and [item.start_sample for item in segments] == [0, STRIDE_SAMPLES]
    assert all(item.signal.shape == (19, WINDOW_SAMPLES) and item.recording_id == fold.target[0].recording_id for item in segments)
    expected = (values[:, :WINDOW_SAMPLES] - np.array(normalizer.means)[:, None]) / np.array(normalizer.standard_deviations)[:, None]
    np.testing.assert_allclose(segments[0].signal, expected, rtol=1e-6, atol=1e-6)
    with pytest.raises(DataContractError, match="source-training"):
        fit_source_normalizer(corpus, replace(fold, training=fold.training + fold.target))
    with pytest.raises(DataContractError, match="foreign, stale"):
        segment_recording(corpus, fold, fold.target[0], replace(normalizer, source_recordings=()))


def test_recording_fallback_must_be_explicit_and_current_legal_hashes_cannot_drift(tmp_path):
    payload = _fixture(tmp_path)
    dataset = payload["datasets"][0]
    dataset.update(analysis_unit="recording", subject_ids_unavailable=True)
    for row in dataset["recordings"]:
        row["subject_id"] = None
    _json(tmp_path / "data/manifests/datasets.json", payload)
    corpus = load_data_manifest(tmp_path)
    assert corpus.recordings[0].unit_id == corpus.recordings[0].recording_id
    assert corpus.recording_fallback_datasets == (dataset["dataset_id"],)
    path = tmp_path / dataset["license"]["path"]
    path.write_text("Changed legal input.")
    with pytest.raises(DataContractError, match="frozen hash"):
        build_ldo_fold(corpus, corpus.datasets[-1])


@pytest.mark.parametrize("count", range(8, 20))
def test_every_registered_clean_channel_count_has_exact_overlapping_m1_four_spectral_views(count):
    segment = _segment(count)
    a, b = channel_subsets(segment, 13)
    k = max(4, count // 2)
    assert a.sum() == b.sum() == k and np.count_nonzero(a & b) == (k + 1) // 2
    assert not np.any((a | b) & ~segment.channel_mask)
    again = channel_subsets(segment, 13)
    assert np.array_equal(a, again[0]) and np.array_equal(b, again[1])
    views = four_composites(segment, 13)
    assert np.array_equal(views["a_mask"], a) and np.array_equal(views["b_mask"], b)
    for key, mask in (("a_low", a), ("a_high", a), ("b_low", b), ("b_high", b)):
        assert views[key].shape == (19, WINDOW_SAMPLES) and np.isfinite(views[key]).all()
        assert not np.any(views[key][~mask]) and views["composite_parent_ids"][key] == segment.segment_id
    assert not np.allclose(views["a_low"][a], views["a_high"][a])
    shared = a & b
    np.testing.assert_array_equal(views["a_low"][shared], views["b_low"][shared])
    np.testing.assert_array_equal(views["a_high"][shared], views["b_high"][shared])


def test_unavailable_channels_are_masked_not_imputed_or_normalized(tmp_path):
    _fixture(tmp_path, channel_count=8)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    norm = fit_source_normalizer(corpus, fold)
    segment = segment_recording(corpus, fold, fold.target[0], norm)[0]
    assert np.count_nonzero(segment.channel_mask) == 8 and not np.any(segment.signal[~segment.channel_mask])
    assert all(value == 0 for value in norm.counts[8:])
    with pytest.raises(DataContractError):
        four_composites(replace(segment, channel_mask=np.zeros(19, dtype=bool)), 13)


def test_balanced_sampler_excludes_source_validation_target_and_uses_replacement(tmp_path):
    _fixture(tmp_path)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    norm = fit_source_normalizer(corpus, fold)
    segments = tuple(item for record in fold.training for item in segment_recording(corpus, fold, record, norm))
    sample = BalancedSourceSampler(corpus, fold, segments, 13, 2000)
    ids = [item.segment_id for item in sample]
    assert ids == [item.segment_id for item in sample] and len(ids) == 2000 and len(set(ids)) <= len(segments)
    chosen = list(sample)
    counts = {dataset: sum(item.dataset_id == dataset for item in chosen) for dataset in fold.source_ids}
    assert all(850 < count < 1150 for count in counts.values())
    subjects = {unit: sum(item.unit_id == unit for item in chosen) for unit in {item.unit_id for item in segments}}
    assert all(350 < count < 650 for count in subjects.values())
    outsider = segment_recording(corpus, fold, fold.validation[0], norm)[0]
    with pytest.raises(DataContractError, match="validation/target"):
        BalancedSourceSampler(corpus, fold, (*segments, outsider), 13, 10)
    with pytest.raises(DataContractError, match="every eligible"):
        BalancedSourceSampler(corpus, fold, segments[:-2], 13, 10)


def test_c3_requires_exact_evaluable_subset_pair_ids_and_eligibility_ledgers():
    sixteen, fifteen = _segment(16, "eligible"), _segment(15, "ineligible")
    quarter, half = random_deletion(sixteen, 13, 25), random_deletion(sixteen, 13, 50)
    assert quarter.eligible and half.eligible and len(quarter.removed_channels) == 4 and len(half.removed_channels) == 8
    assert set(quarter.removed_channels) <= set(half.removed_channels)
    assert half.segment.channel_mask.sum() == 8 and half.pair_id == sixteen.segment_id
    assert not random_deletion(fifteen, 13, 25).eligible
    ledger = c3_evaluation_inventory([sixteen, fifteen], "random_deletion_50", 13)
    assert ledger["clean_pair_ids"] == (sixteen.segment_id,) and len(ledger["ineligible"]) == 1
    assert ledger["paired_recomputation_required"] and ledger["perturbed"][0].segment_id == sixteen.segment_id
    assert not region_deletion(_segment(8)).eligible
    regional = region_deletion(_segment(19))
    assert regional.eligible and regional.condition == "region_deletion_frontal" and len(regional.removed_channels) == 7
    spectral = c3_evaluation_inventory([sixteen, fifteen], "bandstop_8_13", 13)
    assert set(spectral["clean_pair_ids"]) == {sixteen.segment_id, fifteen.segment_id} and spectral["ineligible"] == ()
    low = spectral_perturbation(sixteen, "bandpass_1_8")
    assert low.segment.channel_mask.sum() == sixteen.channel_mask.sum() and not np.allclose(low.segment.signal, sixteen.signal)


def test_stacking_never_loses_parent_identity_or_omits_masks():
    values = [four_composites(_segment(19, "one"), 13), four_composites(_segment(19, "two"), 13)]
    batch = stack_composites(values)
    assert batch["a_low"].shape == (2, 19, WINDOW_SAMPLES) and batch["b_mask"].shape == (2, 19)
    assert [row["segment_id"] for row in batch["metadata"]] == batch["composite_parent_ids"]["a_low"]
    with pytest.raises(DataContractError):
        stack_composites([{**values[0], "a_mask": None}])


def test_in_domain_requires_declared_unit_disjoint_split_and_never_reuses_ldo_normalization(tmp_path):
    payload = _fixture(tmp_path, subjects=3)
    corpus = load_data_manifest(tmp_path)
    target = corpus.datasets[-1]
    with pytest.raises(DataContractError, match="predeclared"):
        build_in_domain_fold(corpus, target)
    for dataset in payload["datasets"]:
        for index, record in enumerate(dataset["recordings"]):
            record["within_dataset_split"] = ("train", "validation", "test")[index]
    _json(tmp_path / "data/manifests/datasets.json", payload)
    corpus = load_data_manifest(tmp_path)
    fold = build_in_domain_fold(corpus, target)
    prepared = prepare_in_domain_fold(corpus, fold)
    assert {item.dataset_id for item in (*prepared.training, *prepared.validation, *prepared.testing)} == {target}
    assert set(dict(prepared.normalizer.source_recordings)) == {item.recording_id for item in fold.training}
    assert {item.unit_id for item in prepared.training}.isdisjoint({item.unit_id for item in prepared.testing})
    assert {item.unit_id for item in prepared.training}.isdisjoint({item.unit_id for item in prepared.validation})
    sampler = BalancedSourceSampler(corpus, fold, prepared.training, 13, 20)
    assert all(item.dataset_id == target and item.unit_id in {value.unit_id for value in fold.training} for item in sampler)
    with pytest.raises(DataContractError, match="validation/target"):
        BalancedSourceSampler(corpus, fold, (*prepared.training, prepared.validation[0]), 13, 10)
    ldo = build_ldo_fold(corpus, target)
    ldo_normalizer = fit_source_normalizer(corpus, ldo)
    with pytest.raises(DataContractError, match="foreign, stale"):
        segment_recording(corpus, fold, fold.testing[0], ldo_normalizer)
    with pytest.raises(DataContractError, match="target-local training"):
        fit_source_normalizer(corpus, replace(fold, training=(*fold.training, *fold.testing)))
    with pytest.raises(DataContractError, match="target-local training"):
        fit_source_normalizer(corpus, replace(fold, training=(*fold.training, *fold.validation)))


def test_prepare_fold_bounds_global_hashing_per_stage_not_per_record(tmp_path, monkeypatch):
    from server.experiment_protocols.csfs_v1 import data_contract

    _fixture(tmp_path)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    original = data_contract._local_bytes
    counts = {}

    def observed(root, relative, expected=None):
        counts[relative] = counts.get(relative, 0) + 1
        return original(root, relative, expected)

    monkeypatch.setattr(data_contract, "_local_bytes", observed)
    prepared = prepare_fold(corpus, fold)
    assert prepared.training and prepared.validation and prepared.target
    # Each input is checked at stage boundaries, and each recording at its actual read.
    assert max(counts.values()) <= 5


def test_foreign_numeric_values_and_unverified_pickle_are_not_recording_inputs(tmp_path):
    payload = _fixture(tmp_path)
    row = payload["datasets"][0]["recordings"][0]
    path = tmp_path / row["path"]
    np.save(path, np.array([{"unsafe": "pickle"}], dtype=object), allow_pickle=True)
    row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    _json(tmp_path / "data/manifests/datasets.json", payload)
    with pytest.raises(DataContractError, match="safe numeric"):
        load_data_manifest(tmp_path)


def test_source_sampler_cannot_subtract_one_window_or_mix_foreign_fitted_state(tmp_path):
    _fixture(tmp_path)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    prepared = prepare_fold(corpus, fold)
    with pytest.raises(DataContractError, match="every registered window"):
        BalancedSourceSampler(corpus, fold, prepared.training[1:], 13, 10)
    foreign = replace(prepared.training[0], normalization_sha256="Different source-only state")
    with pytest.raises(DataContractError, match="foreign fitted"):
        BalancedSourceSampler(corpus, fold, (foreign, *prepared.training[1:]), 13, 10)


def test_recording_short_channels_are_excluded_before_ldo_not_silently_imputed(tmp_path):
    payload = _fixture(tmp_path, dataset_count=4)
    row = payload["datasets"][0]["recordings"][0]
    path = tmp_path / row["path"]
    array = np.load(path, allow_pickle=False)[:7]
    np.save(path, array, allow_pickle=False)
    row.update(channels=list(CANONICAL_CHANNELS[:7]), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    _json(tmp_path / "data/manifests/datasets.json", payload)
    corpus = load_data_manifest(tmp_path)
    assert row["recording_id"] not in {record.recording_id for record in corpus.recordings}
    assert any(item.get("recording_id") == row["recording_id"] and "fewer than eight" in item["reason"] for item in corpus.exclusions)


def test_probe_draw_budget_is_distinct_from_pretraining_without_changing_source_boundaries(tmp_path):
    from server.experiment_protocols.csfs_v1.protocol import FINAL_PROBE_UPDATES, BATCH_SIZE

    _fixture(tmp_path)
    corpus = load_data_manifest(tmp_path)
    fold = build_ldo_fold(corpus, corpus.datasets[-1])
    prepared = prepare_fold(corpus, fold)
    with pytest.raises(DataContractError, match="bounded registered window budget"):
        BalancedSourceSampler(corpus, fold, prepared.training, 13, 101_000)
    maximum = FINAL_PROBE_UPDATES * BATCH_SIZE
    sampler = BalancedSourceSampler(corpus, fold, prepared.training, 13, maximum, sampling_role="probe")
    assert sampler.window_budget == 320_000 and sampler.sampling_role == "probe"
    iterator = iter(sampler)
    assert all(next(iterator).dataset_id in fold.source_ids for _ in range(20))
    with pytest.raises(DataContractError, match="bounded registered window budget"):
        BalancedSourceSampler(corpus, fold, prepared.training, 13, maximum + 1, sampling_role="probe")
    with pytest.raises(DataContractError, match="validation/target"):
        BalancedSourceSampler(corpus, fold, (*prepared.training, prepared.target[0]), 13, maximum, sampling_role="probe")


def test_make_batch_cpu_tensor_interface_preserves_four_views_masks_labels_and_parents():
    import torch
    from server.experiment_protocols.csfs_v1.data import make_batch

    segments = [_segment(19, "parent-one"), _segment(16, "parent-two")]
    batch = make_batch(segments, 13)
    for key in ("a_low", "a_high", "b_low", "b_high"):
        assert batch[key].device.type == "cpu" and batch[key].dtype == torch.float32
        assert batch[key].shape == (2, 19, WINDOW_SAMPLES) and not batch[key].requires_grad
        assert batch["composite_parent_ids"][key] == [item.segment_id for item in segments]
    assert batch["a_mask"].dtype == batch["b_mask"].dtype == torch.bool
    assert batch["a_mask"].shape == batch["b_mask"].shape == (2, 19)
    assert batch["labels"].dtype == torch.long and batch["labels"].tolist() == [0, 0]
    assert [row["segment_id"] for row in batch["metadata"]] == [item.segment_id for item in segments]
    assert "shuffled_b_indices" not in batch
