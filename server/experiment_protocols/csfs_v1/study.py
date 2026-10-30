"""Full registered study graph, run only after explicit CLI/config authorization.

This coordinates actual producers; it cannot turn structural previews, code
checks or old scientific CSVs into execution evidence. Every new attempt is
isolated; anchors are locked from source validation before target scoring.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

from .data import prepare_fold, prepare_in_domain_fold
from .data_contract import build_ldo_fold, build_in_domain_fold, load_data_manifest, verify_current_corpus
from .evaluation import EvaluationBindings, evaluate_frozen_probe, label_vocabulary_hash
from .execution_io import AttemptWriter, content_hash, serializable, source_inventory
from .perturbations import c3_evaluation_inventory
from .protocol import METHOD_IDS, PROTOCOL_ID, SEEDS, require_execution_authorization
from .statistics import AnchorChoice, EligibilityRecord, ScoreRecord, evaluate_claims
from .training import fixed_batches, seed_runtime, train_condition


def evaluation_bindings(corpus, fold, prepared, method, seed, config_hash, source_hash,
                         encoder_hash, probe_hash, *, in_domain=False, selection=False):
    target = fold.dataset_id if in_domain else fold.target_id
    validation = target if in_domain else fold.validation_id
    role = ("target_local_validation" if selection else "target_local_test") if in_domain else (
        "source_validation" if selection else "target_test")
    return EvaluationBindings(method, target, seed, (target,) if in_domain else tuple(fold.source_ids),
        validation, validation if selection else target,
        "target_local_training" if in_domain else "source_training", role,
        encoder_hash, probe_hash, config_hash, source_hash, corpus.sha256, fold.sha256,
        prepared.normalizer.sha256, label_vocabulary_hash(corpus.label_vocabulary))


def _score(trained, corpus, bindings, segments, seed, resources):
    from .training import memory_guard

    trained.probe.to(resources.device)
    result = evaluate_frozen_probe(trained.probe,
        fixed_batches(segments, seed, resources.device), bindings=bindings,
        label_vocabulary=corpus.label_vocabulary,
        expected_segment_ids=[segment.segment_id for segment in segments],
        recording_fallback_datasets=corpus.recording_fallback_datasets,
        on_batch=lambda: (trained.anomaly.check_time(), memory_guard(resources)))
    trained.probe.to("cpu")
    return result


def _train_one(root, corpus, fold, prepared, method, seed, resources, config_hash, source_hash,
               *, in_domain=False, resume_request=None):
    from .baselines import build_method

    seed_runtime(seed, resources.device)
    writer = AttemptWriter(root, {"protocol_id": PROTOCOL_ID, "method_id": method,
        "target_id": fold.dataset_id if in_domain else fold.target_id, "seed": seed,
        "fit_role": "target_local_training" if in_domain else "source_training",
        "config_sha256": config_hash, "source_sha256": source_hash,
        "corpus_sha256": corpus.sha256, "split_sha256": fold.sha256})
    model = build_method(method)

    def evaluate(probe, encoder_hash, probe_hash):
        bindings = evaluation_bindings(corpus, fold, prepared, method, seed, config_hash, source_hash,
                                       encoder_hash, probe_hash, in_domain=in_domain, selection=True)
        result = evaluate_frozen_probe(probe, fixed_batches(prepared.validation, seed, resources.device),
            bindings=bindings, label_vocabulary=corpus.label_vocabulary,
            expected_segment_ids=[item.segment_id for item in prepared.validation],
            recording_fallback_datasets=corpus.recording_fallback_datasets)
        return result["metrics"]["macro_f1"]

    try:
        trained = train_condition(model, corpus, fold, prepared, seed=seed, resources=resources,
                                  writer=writer, evaluate_selection=evaluate, resume_request=resume_request)
    except (ValueError, RuntimeError, OSError) as error:
        writer.finish(success=False, outputs={}, failure=f"{type(error).__name__}: {error}")
        raise
    writer.json("normalization.json", prepared.normalizer.to_dict())
    trained.model.to("cpu")
    trained.probe.to("cpu")
    return trained, writer


def _eligibility(corpus, target, seed, condition, segments, inventory):
    eligible = set(inventory["clean_pair_ids"])
    chosen = [segment for segment in segments if segment.segment_id in eligible]
    return EligibilityRecord(target_id=target, seed=seed, condition=condition,
        all_clean_segment_ids=tuple(sorted(segment.segment_id for segment in segments)),
        clean_segment_ids=tuple(sorted(eligible)), unit_ids=tuple(sorted({item.unit_id for item in chosen})),
        available_channels=tuple(sorted((item.segment_id, int(item.channel_mask.sum())) for item in chosen)),
        ineligible_segments=tuple(sorted((item["segment_id"], item["reason"]) for item in inventory["ineligible"])),
        corpus_manifest_sha256=corpus.sha256, declared_before_scoring=True)


def _perturb_scores(corpus, fold, prepared, trained, seed, resources, config_hash, source_hash, anchor):
    targets = prepared.target
    records, cleans, eligibility = {}, {}, []
    for condition in ("random_deletion_25", "random_deletion_50", "bandstop_8_13", "bandpass_1_8", "region_deletion"):
        inventory = c3_evaluation_inventory(targets, condition, seed)
        ledger = _eligibility(corpus, fold.target_id, seed, condition, targets, inventory)
        eligibility.append(ledger)
        records[condition], cleans[condition] = [], []
        paired = set(inventory["clean_pair_ids"])
        if not paired:
            continue
        clean = tuple(item for item in targets if item.segment_id in paired)
        for method in ("csfs", anchor.method_id):
            fitted, _writer = trained[method]
            bindings = evaluation_bindings(corpus, fold, prepared, method, seed, config_hash, source_hash,
                                           fitted.checkpoint_sha256, fitted.probe_sha256)
            for destination, segments in ((cleans, clean), (records, inventory["perturbed"])):
                result = _score(fitted, corpus, bindings, segments, seed, resources)
                score = result["score_record"]
                score = replace(score, bindings={**score.bindings, "eligibility_sha256": ledger.sha256})
                result["score_record"] = score
                destination[condition].append(score)
                _writer.json(f"{condition}-{'clean' if destination is cleans else 'shifted'}.json", result)
    return records, cleans, eligibility


def run_study(root: Path, config: dict, *, allow_execution: bool) -> dict[str, Any]:
    """Authorize BEFORE data reads, model construction, jobs or result persistence."""
    resources = require_execution_authorization(config, allow_execution=allow_execution)
    corpus = load_data_manifest(root)
    # Require every prospective secondary split before consuming primary compute.
    folds = {target: build_ldo_fold(corpus, target) for target in corpus.datasets}
    in_domain_folds = {target: build_in_domain_fold(corpus, target) for target in corpus.datasets}
    from .baselines import build_method
    from .capacity import capacity_ledger

    capacity = capacity_ledger({method: build_method(method) for method in METHOD_IDS})
    config_hash, source_hash = content_hash(config), content_hash(source_inventory(Path(__file__).parent))
    overall = AttemptWriter(root, {"protocol_id": PROTOCOL_ID, "scope": "complete_registered_study",
                                   "config_sha256": config_hash, "source_sha256": source_hash})
    outcomes, anchors, shifted, cleans, eligible, domains = [], [], {}, {}, [], []
    overall.json("matching_ledger.json", capacity)
    try:
        for target, fold in folds.items():
            prepared = prepare_fold(corpus, fold)
            for seed in SEEDS:
                trained = {method: _train_one(root, corpus, fold, prepared, method, seed, resources,
                    config_hash, source_hash) for method in METHOD_IDS}
                anchor = _lock_anchor(target, fold, seed, trained, overall)
                anchors.append(anchor)
                for method, (fitted, writer) in trained.items():
                    bindings = evaluation_bindings(corpus, fold, prepared, method, seed, config_hash, source_hash,
                                                   fitted.checkpoint_sha256, fitted.probe_sha256)
                    result = _score(fitted, corpus, bindings, prepared.target, seed, resources)
                    writer.json("target_evaluation.json", result)
                    outcomes.append(result["score_record"])
                changes, baseline, ledger = _perturb_scores(corpus, fold, prepared, trained, seed, resources,
                                                           config_hash, source_hash, anchor)
                _append_conditions(shifted, changes)
                _append_conditions(cleans, baseline)
                eligible.extend(ledger)
                for fitted, writer in trained.values():
                    writer.finish(success=True, outputs={"checkpoint_sha256": fitted.checkpoint_sha256,
                        "probe_sha256": fitted.probe_sha256, "budget": fitted.budget})
            domains.extend(_in_domain(root, corpus, in_domain_folds[target], resources, config_hash, source_hash))
            verify_current_corpus(corpus)
        c3 = {"condition_records": shifted, "clean_subset_records": cleans, "anchor_choices": anchors,
              "in_domain_records": domains, "eligibility_records": eligible}
        report = evaluate_claims(outcomes, tuple(corpus.datasets), c3_inputs=c3)
        digest = overall.json("registered_claim_decisions.json", report)
        overall.finish(success=True, outputs={"decision_report_sha256": digest})
    except (ValueError, RuntimeError, OSError) as error:
        overall.finish(success=False, outputs={}, failure=f"{type(error).__name__}: {error}")
        raise
    return report


def _lock_anchor(target, fold, seed, trained, writer):
    scores = {method: trained[method][0].selection_score for method in ("bendr_context", "masked_latent")}
    method = max(("bendr_context", "masked_latent"), key=lambda identity: scores[identity])
    digest = writer.json(f"anchor-{content_hash(target)[:16]}-{seed}.json", {"scores": scores, "method": method,
        "source_validation_id": fold.validation_id, "target_scoring_started": False,
        "selected_checkpoints": {key: trained[key][0].checkpoint_sha256 for key in scores}})
    return AnchorChoice(target, seed, method, scores, fold.validation_id, True, digest)


def _append_conditions(destination, current):
    for condition, rows in current.items():
        destination.setdefault(condition, []).extend(rows)


def _in_domain(root, corpus, fold, resources, config_hash, source_hash):
    prepared = prepare_in_domain_fold(corpus, fold)
    rows = []
    for seed in SEEDS:
        for method in ("csfs", "random_init"):
            fitted, writer = _train_one(root, corpus, fold, prepared, method, seed, resources,
                                       config_hash, source_hash, in_domain=True)
            bindings = evaluation_bindings(corpus, fold, prepared, method, seed, config_hash, source_hash,
                                           fitted.checkpoint_sha256, fitted.probe_sha256, in_domain=True)
            result = _score(fitted, corpus, bindings, prepared.target, seed, resources)
            writer.json("in_domain_evaluation.json", result)
            writer.finish(success=True, outputs={"checkpoint_sha256": fitted.checkpoint_sha256,
                "probe_sha256": fitted.probe_sha256, "budget": fitted.budget})
            rows.append(result["score_record"])
    return rows


def resume_condition(root: Path, config: dict, request: dict, *, allow_execution: bool):
    """Resume one exact source-bound condition, never silently resume a whole study."""
    resources = require_execution_authorization(config, allow_execution=allow_execution)
    corpus = load_data_manifest(root)
    if request["method"] not in METHOD_IDS or request["seed"] not in SEEDS or request["target"] not in corpus.datasets:
        raise ValueError("Resume condition is outside the registered target/method/seed family")
    path = Path(request["path"])
    executed = (root / "experiments/results/executed").resolve()
    if path.resolve().parent.parent != executed:
        raise ValueError("Resume cannot load a checkpoint outside this project's actual execution attempts")
    fold = build_ldo_fold(corpus, request["target"])
    prepared = prepare_fold(corpus, fold)
    config_hash, source_hash = content_hash(config), content_hash(source_inventory(Path(__file__).parent))
    fitted, writer = _train_one(root, corpus, fold, prepared, request["method"], request["seed"],
        resources, config_hash, source_hash,
        resume_request={"path": path, "sha256": request["sha256"], "attempt_root": path.parent})
    bindings = evaluation_bindings(corpus, fold, prepared, request["method"], request["seed"], config_hash,
                                   source_hash, fitted.checkpoint_sha256, fitted.probe_sha256)
    result = _score(fitted, corpus, bindings, prepared.target, request["seed"], resources)
    writer.json("target_evaluation.json", result)
    writer.finish(success=True, outputs={"budget": fitted.budget})
    return {"status": "condition_completed", "study_claims_accepted": False, "result": serializable(result)}
