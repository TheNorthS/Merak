"""Read explicit run declarations shared by implementation, audit, and scheduling."""

from __future__ import annotations

from collections.abc import Mapping
import re
from string import Formatter
from typing import Any


# Producers write the canonical top-level ``seeds`` field. Existing explicit
# run containers retain deterministic precedence; arbitrary nested seeds are
# never execution declarations (for example, augmentation RNG settings).
SEED_KEYS = ("seeds", "seed_list", "seed_lists")
PREFERRED_EXECUTION_GROUPS = (
    "decisive",
    "main",
    "primary",
    "final",
    "evaluation",
    "robustness",
    "training",
    "default",
    "pilot",
)
SCHEDULER_COMMAND_FIELDS = frozenset({"seed", "batch_size", "work_dir", "condition", "axis", "output_dir"})
DETERMINISTIC_IMPLEMENTATION_FAMILIES = frozenset({
    "formal_verification",
    "external_protocol",
})


def run_spec_requires_seeds(run_spec: Mapping[str, Any]) -> bool:
    """Return whether repeated stochastic seeds are part of this study family."""
    family = str(run_spec.get("implementation_family") or "").strip().casefold()
    if family == "machine_learning":
        return True
    if family in DETERMINISTIC_IMPLEMENTATION_FAMILIES:
        return False
    if run_spec.get("deterministic") is True or run_spec.get("stochastic") is False:
        return False
    return True


def _seed_values(value: Any) -> list[int]:
    """Normalize one explicit seed value/list and reject non-seed payloads."""
    if isinstance(value, Mapping) or value is None:
        return []
    raw_values = list(value) if isinstance(value, (list, tuple, set)) else [value]
    seeds: list[int] = []
    for item in raw_values:
        if isinstance(item, bool):
            continue
        try:
            seed = int(item)
        except (TypeError, ValueError, OverflowError):
            continue
        # Do not silently coerce fractional floats such as 1.5 to seed 1.
        if isinstance(item, float) and not item.is_integer():
            continue
        seeds.append(seed)
    return seeds


def run_spec_seed_groups(run_spec: Mapping[str, Any]) -> dict[str, list[int]]:
    """Read the first valid explicit run seed declaration without rewriting it."""
    candidates: list[Any] = [run_spec.get(key) for key in SEED_KEYS]
    matrix = run_spec.get("execution_matrix")
    if isinstance(matrix, Mapping):
        candidates.extend(matrix.get(key) for key in SEED_KEYS)
        # A few generated specs use ``execution_matrix: {runs: {seeds: …}}``.
        runs = matrix.get("runs")
        if isinstance(runs, Mapping):
            candidates.extend(runs.get(key) for key in SEED_KEYS)
    # Current model writers often group repeatability metadata under one of
    # these explicit containers (notably ``repetitions: {seeds: [...]}``).
    # Keep deterministic priority instead of recursively accepting an
    # unrelated nested seed used only by a sampler or augmentation.
    for container_name in (
        "repetitions",
        "replication",
        "replicates",
        "runs",
        "training",
        "evaluation",
        "robustness",
        # Experiment planners commonly keep repeatability settings beside
        # the other optimizer controls.  This is still an explicit run
        # contract (not an augmentation/sampler seed), so treat it as a
        # first-class seed container at every validation/scheduling boundary.
        "optimization",
        # A frozen execution budget can declare repetitions alongside epoch
        # and resource limits. It is run metadata, not an arbitrary subtree.
        "budgets",
    ):
        container = run_spec.get(container_name)
        if isinstance(container, Mapping):
            candidates.extend(container.get(key) for key in SEED_KEYS)
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, Mapping):
            groups: dict[str, list[int]] = {}
            for name, values in raw.items():
                normalized = _seed_values(values)
                if normalized:
                    groups[str(name)] = normalized
            if groups:
                return groups
            continue
        values = _seed_values(raw)
        if values:
            return {"default": values}
    return {}


def _command_entry(value: Any) -> tuple[str, bool | None]:
    if isinstance(value, Mapping):
        command = str(value.get("command") or "").strip()
        executes_training = value.get("executes_training")
        return command, executes_training if isinstance(executes_training, bool) else None
    return str(value or "").strip(), None


def run_spec_command(
    run_spec: Mapping[str, Any],
    *,
    run_experiment: bool = False,
) -> str:
    """Resolve the scientific/preflight command from every supported schema."""
    candidates: list[tuple[str, bool | None]] = []

    def add(value: Any, default_training: bool | None = None) -> None:
        command, declared_training = _command_entry(value)
        if command:
            candidates.append((
                command,
                declared_training if declared_training is not None else default_training,
            ))

    add(run_spec.get("command"), run_experiment)
    if run_experiment:
        for key in (
            "execution_command",
            "training_command",
            "run_command",
            "formal_command",
            "scientific_command",
            "evaluation_command",
            "training_command_template_for_later_stage",
        ):
            add(run_spec.get(key), True)
    else:
        add(run_spec.get("preflight_command"), False)
        add(run_spec.get("execution_command"), False)
    matrix = run_spec.get("execution_matrix")
    if isinstance(matrix, Mapping):
        for key in ("command", "execution_command", "training_command", "run_command"):
            add(matrix.get(key), run_experiment)
    for key in ("commands", "executable_commands"):
        entries = run_spec.get(key)
        if isinstance(entries, (list, tuple)):
            for entry in entries:
                add(entry)
    for command, executes_training in candidates:
        # Return dry-run commands structurally so the risk audit can report
        # the precise violation and inspect their referenced source/config.
        # The managed scheduler rejects them before execution.
        if run_experiment and executes_training is False:
            continue
        return command
    return ""


def run_spec_preflight_command(run_spec: Mapping[str, Any]) -> str:
    """Return only an explicitly declared preflight command."""
    command, _ = _command_entry(run_spec.get("preflight_command"))
    return command


def run_spec_scientific_command(run_spec: Mapping[str, Any]) -> str:
    """Return a formal command only when it is not a dry-run/preflight call."""
    command = run_spec_command(run_spec, run_experiment=True)
    if re.search(r"(?:^|\s)--dry[-_]run(?:\s|$)", command, re.IGNORECASE):
        return ""
    return command


def unresolved_command_placeholders(command: str) -> list[str]:
    """Return placeholders that the experiment scheduler cannot resolve."""
    unresolved = [
        match.group(0)
        for match in re.finditer(r"<[A-Za-z_][^<>\r\n]*>", str(command or ""))
    ]
    try:
        parsed_fields = Formatter().parse(str(command or ""))
        for _literal, field_name, _format_spec, _conversion in parsed_fields:
            if field_name and field_name.strip() not in SCHEDULER_COMMAND_FIELDS:
                unresolved.append("{" + field_name + "}")
    except ValueError:
        unresolved.append("{malformed-format-field}")
    return list(dict.fromkeys(unresolved))


def execution_seeds(run_spec: Mapping[str, Any]) -> list[int]:
    """Resolve the seed group used by the managed experiment scheduler."""
    groups = run_spec_seed_groups(run_spec)
    if not groups:
        return []
    normalized_names = {
        str(name).strip().casefold(): name for name in groups
    }
    selected_name = next(
        (
            normalized_names[name]
            for name in PREFERRED_EXECUTION_GROUPS
            if name in normalized_names
        ),
        next(iter(groups)),
    )
    seeds: list[int] = []
    for seed in groups[selected_name]:
        if seed not in seeds:
            seeds.append(seed)
    return seeds
