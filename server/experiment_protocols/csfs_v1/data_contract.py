"""Frozen, local recording contracts for CSFS-v1; no download or synthetic fallback.

The transport is an explicit channel-by-sample numeric NPY array. Legal approval
is a prior human review with hash-bound local license/provenance evidence, not an
approval inferred by this loader. The loader never authorizes scientific work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import re
from typing import Any

import numpy as np

from .protocol import CANONICAL_CHANNELS, ProtocolError, MIN_CHANNELS, WINDOW_SECONDS, PREPROCESS_BAND


class DataContractError(ProtocolError):
    """Absent data, legal evidence, identity or current hashes block CSFS inputs."""


@dataclass(frozen=True)
class Recording:
    dataset_id: str
    recording_id: str
    subject_id: str | None
    raw_id: str
    path: str
    sha256: str
    sample_rate: float
    channels: tuple[str, ...]
    canonical_channels: tuple[str, ...]
    label: int
    analysis_unit: str
    sample_count: int
    within_dataset_split: str | None = None

    @property
    def unit_id(self) -> str:
        return self.subject_id if self.subject_id is not None else self.recording_id


@dataclass(frozen=True)
class VerifiedCorpus:
    root: Path
    endpoint: str
    label_vocabulary: tuple[str, ...]
    datasets: tuple[str, ...]
    recordings: tuple[Recording, ...]
    source_hashes: tuple[tuple[str, str], ...]
    exclusions: tuple[dict[str, str], ...]

    @property
    def recording_fallback_datasets(self) -> tuple[str, ...]:
        """Only the loader's explicit no-subject dataset exceptions reach metrics."""
        return tuple(sorted({record.dataset_id for record in self.recordings if record.analysis_unit == "recording"}))

    @property
    def sha256(self) -> str:
        payload = {"sources": self.source_hashes, "endpoint": self.endpoint,
                   "labels": self.label_vocabulary, "datasets": self.datasets}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class FoldSpec:
    target_id: str
    validation_id: str
    source_ids: tuple[str, ...]
    corpus_sha256: str
    training: tuple[Recording, ...]
    validation: tuple[Recording, ...]
    target: tuple[Recording, ...]

    @property
    def sha256(self) -> str:
        payload = {"corpus": self.corpus_sha256, "target": self.target_id,
                   "validation": self.validation_id, "sources": self.source_ids}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class InDomainFold:
    dataset_id: str
    corpus_sha256: str
    training: tuple[Recording, ...]
    validation: tuple[Recording, ...]
    testing: tuple[Recording, ...]

    @property
    def sha256(self) -> str:
        payload = {"corpus": self.corpus_sha256, "dataset": self.dataset_id,
                   "train": sorted(record.recording_id for record in self.training),
                   "validation": sorted(record.recording_id for record in self.validation),
                   "test": sorted(record.recording_id for record in self.testing),
                   "scope": "isolated_target_local_secondary_reference"}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _local_bytes(root: Path, relative: str, expected: str | None = None) -> bytes:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise DataContractError("Data inputs require canonical relative project paths")
    unresolved, path = root / relative, (root / relative).resolve()
    if (not path.is_relative_to(root) or path.relative_to(root).as_posix() != relative
            or not path.is_file() or path.stat().st_nlink > 1
            or any(item.is_symlink() for item in (unresolved, *unresolved.parents) if item != root.parent)):
        raise DataContractError("Recording or provenance input is absent, linked or foreign: " + relative)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected is not None and expected != digest:
        raise DataContractError("Data/provenance input differs from its frozen hash: " + relative)
    return content


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DataContractError("Missing explicit " + name)
    return value


def _bound_document(root: Path, value: Any, sources: dict[str, str]) -> None:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise DataContractError("License/provenance requires exact file and hash evidence")
    raw = _local_bytes(root, value["path"], value["sha256"])
    if not raw.strip():
        raise DataContractError("License/provenance evidence is empty")
    sources[value["path"]] = hashlib.sha256(raw).hexdigest()


def _legal_evidence(root: Path, dataset: dict[str, Any], sources: dict[str, str]) -> None:
    _identity(dataset.get("version"), "dataset version")
    _identity(dataset.get("source_uri"), "dataset source provenance")
    for field in ("license", "provenance"):
        _bound_document(root, dataset.get(field), sources)
    review = dataset.get("legal_review")
    if (not isinstance(review, dict) or review.get("decision") != "approved_research_use"
            or not review.get("reviewer_id") or not review.get("reviewed_at")
            or review.get("license_sha256") != dataset["license"]["sha256"]
            or review.get("provenance_sha256") != dataset["provenance"]["sha256"]):
        raise DataContractError("Dataset has no source-bound prior legal-use approval")
    _bound_document(root, review.get("evidence"), sources)
    actual = json.loads(_local_bytes(root, review["evidence"]["path"]).decode("utf-8-sig"))
    required = {key: review[key] for key in ("decision", "reviewer_id", "reviewed_at", "license_sha256", "provenance_sha256")}
    if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in required.items()):
        raise DataContractError("Legal-use review artifact does not certify these current inputs")
    if any(actual.get(key) != dataset.get(key) for key in ("dataset_id", "version", "source_uri")):
        raise DataContractError("Legal review belongs to another dataset/version/source provenance")


def _inventory_counts(dataset: dict[str, Any], rows: list) -> None:
    if dataset.get("data_origin") != "recorded_eeg" or type(dataset.get("inclusion_count")) is not int:
        raise DataContractError("Real recording provenance and inclusion count must be declared, never simulated")
    excluded = dataset.get("exclusion_ledger")
    if (dataset["inclusion_count"] != len(rows) or not isinstance(excluded, list)
            or type(dataset.get("exclusion_count")) is not int or dataset["exclusion_count"] != len(excluded)
            or any(not isinstance(item, dict) or not item.get("raw_id") or not item.get("reason") for item in excluded)):
        raise DataContractError("Dataset inclusion/exclusion inventory is incomplete or contradictory")


def load_recording(corpus: VerifiedCorpus, record: Recording) -> np.ndarray:
    """Read exactly the inventoried numeric array, never execute an adapter/source."""
    if record not in corpus.recordings:
        raise DataContractError("Recording does not belong to the verified corpus")
    raw = _local_bytes(corpus.root, record.path, record.sha256)
    try:
        values = np.load(io.BytesIO(raw), allow_pickle=False)
    except (ValueError, OSError) as error:
        raise DataContractError("Recording must be a safe numeric NPY array") from error
    if (not isinstance(values, np.ndarray) or values.ndim != 2 or values.dtype.kind not in "fiu"
            or values.shape != (len(record.channels), record.sample_count) or not np.isfinite(values).all()):
        raise DataContractError("Recording shape, channels, samples or finite numeric values violate its manifest")
    return np.asarray(values, dtype=np.float64)


def _record(root: Path, dataset: dict[str, Any], row: Any, labels: tuple[str, ...]) -> Recording:
    if not isinstance(row, dict):
        raise DataContractError("Recording inventory must contain objects")
    channels, mapping = row.get("channels"), dataset.get("channel_map")
    if (not isinstance(channels, list) or not channels or len(set(channels)) != len(channels)
            or any(not isinstance(item, str) for item in channels) or not isinstance(mapping, dict)):
        raise DataContractError("Recording has no unique explicit channel inventory/map")
    canonical = tuple(mapping.get(name, "") for name in channels)
    mapped = [name for name in canonical if name]
    if (any(name not in CANONICAL_CHANNELS for name in mapped) or len(set(mapped)) != len(mapped)
            or any(not isinstance(name, str) for name in canonical)):
        raise DataContractError("Canonical channel mapping is unknown or duplicated")
    unit = dataset.get("analysis_unit")
    subject = row.get("subject_id")
    if unit not in {"subject", "recording"} or unit == "recording" and dataset.get("subject_ids_unavailable") is not True:
        raise DataContractError("Recording-level fallback must be explicitly frozen before splitting")
    if unit == "subject":
        subject = _identity(subject, "subject identity")
    elif subject is not None:
        raise DataContractError("Recording fallback cannot silently discard a present subject identity")
    rate, count = row.get("sample_rate"), row.get("sample_count")
    if (isinstance(rate, bool) or not isinstance(rate, (int, float)) or not np.isfinite(rate) or rate <= 2 * PREPROCESS_BAND[1]
            or type(count) is not int or count < WINDOW_SECONDS * rate or row.get("label") not in labels
            or not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
            or not str(row.get("path") or "").endswith(".npy")):
        raise DataContractError("Recording lacks eligible sample rate/duration/label/hash/NPY transport")
    _local_bytes(root, row["path"], row["sha256"])
    local_split = row.get("within_dataset_split")
    if local_split is not None and local_split not in {"train", "validation", "test"}:
        raise DataContractError("Within-dataset partition must explicitly be train, validation or test")
    return Recording(dataset["dataset_id"], _identity(row.get("recording_id"), "recording identity"), subject,
                     _identity(row.get("raw_id"), "raw recording identity"), row["path"], row["sha256"], float(rate),
                     tuple(channels), canonical, labels.index(row["label"]), unit, count, local_split)


def load_data_manifest(root: str | Path, relative: str = "data/manifests/datasets.json") -> VerifiedCorpus:
    """Require three legally reviewed common-endpoint datasets; no scientific execution."""
    root = Path(root).resolve(strict=True)
    raw = _local_bytes(root, relative)
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as error:
        raise DataContractError("Dataset manifest is not readable JSON") from error
    if not isinstance(payload, dict) or type(payload.get("schema")) is not int or payload.get("schema") != 1 or payload.get("protocol") != "CSFS-v1":
        raise DataContractError("Dataset manifest must declare current CSFS-v1 schema 1")
    endpoint = _identity(payload.get("endpoint"), "common classification endpoint")
    labels = payload.get("label_vocabulary")
    datasets = payload.get("datasets")
    if (not isinstance(labels, list) or len(labels) < 2 or len(set(labels)) != len(labels)
            or any(not isinstance(item, str) or not item.strip() for item in labels)
            or not isinstance(datasets, list)):
        raise DataContractError("Dataset manifest lacks unique common labels or dataset inventory")
    sources, records, included, excluded = {relative: hashlib.sha256(raw).hexdigest()}, [], [], []
    identities = set()
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise DataContractError("Dataset inventory must contain objects")
        identity = _identity(dataset.get("dataset_id"), "dataset identity")
        if identity in identities:
            raise DataContractError("Duplicate dataset identity")
        identities.add(identity)
        if (dataset.get("task_type") != "classification" or dataset.get("endpoint") != endpoint
                or dataset.get("label_vocabulary") != labels):
            excluded.append({"dataset_id": identity, "reason": "incompatible classification endpoint/label vocabulary"})
            continue
        _legal_evidence(root, dataset, sources)
        rows = dataset.get("recordings")
        if not isinstance(rows, list) or not rows:
            raise DataContractError("Dataset has no frozen recording inventory")
        _inventory_counts(dataset, rows)
        accepted = []
        for row in rows:
            record = _record(root, dataset, row, tuple(labels))
            if len([name for name in record.canonical_channels if name]) < MIN_CHANNELS:
                excluded.append({"dataset_id": identity, "recording_id": record.recording_id,
                                 "reason": "fewer than eight available canonical channels"})
                continue
            accepted.append(record)
            sources[record.path] = record.sha256
        if accepted:
            included.append(identity)
            records.extend(accepted)
        else:
            excluded.append({"dataset_id": identity, "reason": "no clean-eligible recordings"})
    if len(included) < 3:
        raise DataContractError("CSFS-v1 needs at least three eligible common-endpoint datasets")
    corpus = VerifiedCorpus(root, endpoint, tuple(labels), tuple(sorted(included)), tuple(records),
                            tuple(sorted(sources.items())), tuple(excluded))
    validate_recording_identities(corpus.recordings)
    for record in corpus.recordings:
        load_recording(corpus, record)
    return corpus


def validate_recording_identities(records: tuple[Recording, ...]) -> None:
    """Raw identity/content and globally declared participant identities cannot leak."""
    for field in ("recording_id", "raw_id", "sha256", "path"):
        values = [getattr(record, field) for record in records]
        if len(set(values)) != len(values):
            raise DataContractError("Duplicate raw/parent recording identity or content: " + field)
    subjects: dict[str, tuple[str, int]] = {}
    for record in records:
        if record.subject_id is not None:
            prior = subjects.setdefault(record.subject_id, (record.dataset_id, record.label))
            if prior != (record.dataset_id, record.label):
                raise DataContractError("Subject crosses datasets or has contradictory recording labels")


def verify_current_corpus(corpus: VerifiedCorpus) -> None:
    if not isinstance(corpus, VerifiedCorpus) or len(corpus.datasets) < 3:
        raise DataContractError("Inputs require a verified eligible corpus")
    for relative, digest in corpus.source_hashes:
        _local_bytes(corpus.root, relative, digest)


def build_ldo_fold(corpus: VerifiedCorpus, target_id: str, rotation: int = 0) -> FoldSpec:
    """Lexicographic target-index rotation fixes the source-validation corpus before fitting."""
    verify_current_corpus(corpus)
    if target_id not in corpus.datasets or type(rotation) is not int or rotation < 0:
        raise DataContractError("LDO needs an inventoried target and nonnegative validation rotation")
    other = [name for name in corpus.datasets if name != target_id]
    validation = other[(corpus.datasets.index(target_id) + rotation) % len(other)]
    sources = tuple(name for name in other if name != validation)
    groups = [tuple(record for record in corpus.recordings if record.dataset_id in ids)
              for ids in (sources, (validation,), (target_id,))]
    if any(not group for group in groups):
        raise DataContractError("LDO has an empty source/validation/target partition")
    validate_recording_identities(tuple(record for group in groups for record in group))
    return FoldSpec(target_id, validation, sources, corpus.sha256, *groups)


def build_in_domain_fold(corpus: VerifiedCorpus, dataset_id: str) -> InDomainFold:
    """Use predeclared target-local unit-disjoint memberships; never invent a split."""
    verify_current_corpus(corpus)
    records = tuple(record for record in corpus.recordings if record.dataset_id == dataset_id)
    if not records or any(record.within_dataset_split not in {"train", "validation", "test"} for record in records):
        raise DataContractError("In-domain C3 requires complete predeclared target-local train/validation/test memberships")
    train = tuple(record for record in records if record.within_dataset_split == "train")
    validation = tuple(record for record in records if record.within_dataset_split == "validation")
    test = tuple(record for record in records if record.within_dataset_split == "test")
    unit_groups = [{record.unit_id for record in group} for group in (train, validation, test)]
    if any(not group for group in unit_groups) or any(unit_groups[i] & unit_groups[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        raise DataContractError("In-domain C3 fitting, selection and test units must be nonempty and disjoint")
    return InDomainFold(dataset_id, corpus.sha256, train, validation, test)
