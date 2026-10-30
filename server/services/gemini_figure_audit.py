"""Hash and provenance audit for accepted Gemini/Paperbanana figures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from .figure_artifact_support import _sha256, _sha256_tree


Issue = Callable[[str], None]


def _resolve(root: Path, value: Any) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(str(value)).expanduser()
    candidate = candidate if candidate.is_absolute() else root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _top_level(
    item: dict[str, Any], metadata: dict[str, Any], root: Path, issue: Issue,
) -> tuple[Path | None, dict[str, Any], int, float, list[dict[str, Any]]]:
    expected = {
        "protocol": ("merak-paperbanana-v1", "missing approved Paperbanana protocol provenance"),
        "generator": ("gemini-paperbanana", "missing Gemini/Paperbanana generator provenance"),
        "generator_skill": ("paper-illustration", "missing /paper-illustration generator skill provenance"),
        "review_backend": (
            "independent-model-api-native-vision-v1",
            "Paperbanana acceptance did not use native independent API image review",
        ),
    }
    for key, (value, message) in expected.items():
        if metadata.get(key) != value:
            issue(message)
    if metadata.get("skill_invocation_verified") is not True or metadata.get("skill_invocation_verified_by") != "agent-runtime":
        issue("missing runtime-owned /paper-illustration invocation provenance")
    output = _resolve(root, item.get("output_path"))
    if not output or not output.is_file():
        issue("accepted Paperbanana output is missing")
    else:
        output_hash = _sha256(output)
        if metadata.get("output_sha256") != output_hash:
            issue("final output hash metadata is stale")
        if metadata.get("final_output_sha256") != output_hash:
            issue("explicit final output hash metadata is stale")
    source_payload = _source_manifest(item, metadata, root, issue)
    try:
        accepted_round = int(metadata.get("accepted_round"))
    except (TypeError, ValueError):
        accepted_round = 0
        issue("accepted_round is missing or invalid")
    try:
        target_score = float(metadata.get("target_score"))
    except (TypeError, ValueError):
        target_score = 0.0
    if target_score < 9:
        issue("target score is below the strict 9/10 threshold")
    rounds = [dict(value) for value in metadata.get("visual_review_rounds") or [] if isinstance(value, dict)]
    if not rounds:
        issue("no persisted independent visual-review rounds")
    if accepted_round < 1 or accepted_round > len(rounds):
        issue("accepted_round does not identify a persisted review round")
    return output, source_payload, accepted_round, target_score, rounds


def _source_manifest(
    item: dict[str, Any], metadata: dict[str, Any], root: Path, issue: Issue,
) -> dict[str, Any]:
    source = _resolve(root, item.get("source_path"))
    if not source or not source.is_file():
        issue("Paperbanana prompt/source manifest is missing")
        return {}
    source_hash = _sha256(source)
    if metadata.get("source_prompt_sha256") != source_hash:
        issue("final prompt/source hash metadata is stale")
    if metadata.get("final_source_sha256") != source_hash:
        issue("explicit final source hash metadata is stale")
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        issue("Paperbanana prompt/source manifest is invalid JSON")
        return {}
    return payload if isinstance(payload, dict) else {}


def _required_artifacts(round_number: int) -> set[str]:
    prefix = f"round_{round_number:02d}/"
    return {
        f"{prefix}{stage}_{kind}.{suffix}"
        for stage in ("layout", "style", "render", "review")
        for kind, suffix in (("prompt", "txt"), ("request", "json"), ("response", "json"))
    } | {f"{prefix}review.json"}


def _round_image(
    root: Path, paths: dict[str, Any], hashes: dict[str, Any],
    round_number: int, issue: Issue,
) -> tuple[str, Path | None]:
    prefix = f"round_{round_number:02d}/"
    names = [
        name for name in paths
        if name.startswith(prefix) and name.endswith(f"_round_{round_number:02d}.png")
    ]
    if len(names) != 1:
        issue(f"review round {round_number} must bind exactly one persisted image")
        return "", None
    image = _resolve(root, paths[names[0]])
    if not image or not image.is_file():
        issue(f"review round {round_number} image is missing")
        return "", image
    digest = _sha256(image)
    if hashes.get(names[0]) != digest:
        issue(f"review round {round_number} image protocol hash is stale")
    return digest, image


def _artifact_hashes(
    review: dict[str, Any], root: Path, paths: dict[str, Any],
    round_number: int, round_hash: str, issue: Issue,
) -> None:
    if review.get("render_sha256") != round_hash:
        issue(f"review round {round_number} render hash is stale")
    if review.get("review_image_sha256") != round_hash:
        issue(f"review round {round_number} reviewer-image hash is stale")
    prefix = f"round_{round_number:02d}/"
    for kind, field in (
        ("review_prompt.txt", "review_prompt_sha256"),
        ("review_response.json", "review_response_sha256"),
    ):
        path = _resolve(root, paths.get(prefix + kind))
        if not path or not path.is_file() or review.get(field) != _sha256(path):
            issue(f"review round {round_number} {kind.replace('_', ' ').split('.')[0]} hash is stale")


def _trace(
    review: dict[str, Any], root: Path, round_number: int,
    round_hash: str, reasoning_model: str, image_model: str, issue: Issue,
) -> None:
    identity = str(review.get("review_model_identity") or "")
    invocation = str(review.get("review_invocation_id") or "")
    if not identity or identity.rsplit("/", 1)[-1].casefold() in {reasoning_model, image_model}:
        issue(f"review round {round_number} lacks an independent API model identity")
    if not invocation.startswith("model-api:"):
        issue(f"review round {round_number} lacks a model API invocation id")
    if review.get("review_backend") != "independent-model-api-native-vision-v1":
        issue(f"review round {round_number} did not use native image attachment")
    if review.get("review_coordinator_verified") is not True:
        issue(f"review round {round_number} was not coordinator-verified")
    trace = _resolve(root, review.get("review_trace_path"))
    if not trace or not trace.is_dir():
        issue(f"review round {round_number} trace is missing")
        return
    if review.get("review_trace_sha256") != _sha256_tree(trace):
        issue(f"review round {round_number} trace hash is stale")
    try:
        metadata = json.loads((trace / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        issue(f"review round {round_number} trace metadata is invalid")
        return
    if metadata.get("transport") != "independent-model-api-native-vision-v1" or metadata.get("image_attachment_mode") != "api-native-image-content" or metadata.get("success") is not True:
        issue(f"review round {round_number} trace lacks verified native API image content")
    if round_hash not in set(map(str, dict(metadata.get("image_sha256") or {}).values())):
        issue(f"review round {round_number} trace is bound to another image")
    if metadata.get("model_identity") != identity:
        issue(f"review round {round_number} trace model identity is stale")
    if metadata.get("invocation_id") != invocation:
        issue(f"review round {round_number} trace invocation id is stale")


def _rounds(
    metadata: dict[str, Any], root: Path, rounds: list[dict[str, Any]],
    accepted_round: int, issue: Issue,
) -> dict[str, Any]:
    paths = dict(metadata.get("protocol_artifacts") or {})
    hashes = dict(metadata.get("protocol_artifact_sha256") or {})
    reasoning = str(metadata.get("reasoning_model") or "").casefold()
    image_model = str(metadata.get("image_model") or "").casefold()
    accepted: dict[str, Any] = {}
    for index, review in enumerate(rounds, 1):
        try:
            number = int(review.get("round"))
        except (TypeError, ValueError):
            number = index
            issue(f"review round {index} has an invalid round number")
        if number != index:
            issue(f"review round sequence is not contiguous at {index}")
        missing = sorted(_required_artifacts(number) - set(paths))
        if missing:
            issue(f"review round {number} lacks prompt/response provenance: " + ", ".join(missing))
        round_hash, _image = _round_image(root, paths, hashes, number, issue)
        _artifact_hashes(review, root, paths, number, round_hash, issue)
        _trace(review, root, number, round_hash, reasoning, image_model, issue)
        if number == accepted_round:
            accepted = review
    return accepted


def _accepted(
    review: dict[str, Any], metadata: dict[str, Any], output: Path | None,
    target_score: float, issue: Issue,
) -> None:
    if not review:
        return
    try:
        score = float(review.get("score"))
    except (TypeError, ValueError):
        score = 0.0
    if score < max(9.0, target_score):
        issue("accepted visual-review score is below threshold")
    try:
        manifest_score = float(metadata.get("accepted_score"))
    except (TypeError, ValueError):
        manifest_score = 0.0
    if manifest_score != score or manifest_score < 9:
        issue("top-level accepted_score is missing, low, or stale")
    if review.get("status") != "passed":
        issue("accepted visual-review round is not marked passed")
    if review.get("critical_checks_pass") is not True:
        issue("accepted visual-review round has failed critical checks")
    if review.get("model_verdict") != "accept":
        issue("accepted visual-review round has no accept verdict")
    if output and output.is_file() and review.get("render_sha256") != _sha256(output):
        issue("accepted review is stale for the final output")


def gemini_protocol_issues(item: dict[str, Any], root: Path) -> list[str]:
    figure_id = str(item.get("id") or "unknown")
    metadata = dict(item.get("metadata") or {})
    issues: list[str] = []

    def issue(message: str) -> None:
        issues.append(f"{figure_id}: {message}")

    output, source_payload, accepted_round, target_score, rounds = _top_level(
        item, metadata, root, issue,
    )
    accepted = _rounds(metadata, root, rounds, accepted_round, issue)
    _accepted(accepted, metadata, output, target_score, issue)
    if source_payload:
        if source_payload.get("status") != "accepted":
            issue("prompt/source manifest is not marked accepted")
        if source_payload.get("accepted_round") != accepted_round:
            issue("prompt/source manifest accepted_round is stale")
        if source_payload.get("accepted_score") != metadata.get("accepted_score"):
            issue("prompt/source manifest accepted_score is stale")
    return list(dict.fromkeys(issues))
