"""Expose the actual scheduler contract to authoring without running any job."""

from .run_spec import SCHEDULER_COMMAND_FIELDS


def scheduler_authoring_instruction() -> str:
    fields = ", ".join("{" + name + "}" for name in sorted(SCHEDULER_COMMAND_FIELDS))
    return (
        "\n\n## Platform scheduler contract\n"
        f"The formal command supports only these scheduler fields: {fields}. "
        "Other study dimensions must be consumed from the frozen configuration inside the runner; "
        "never invent an unsupported command placeholder. "
        "For scheduled_runs, output_dir is an opaque project-relative directory allocated by the "
        "scheduler with execution and cell identity namespaces. Consume the supplied --output-dir; "
        "do not reconstruct it from condition/axis/seed, require a human-readable directory layout, "
        "or compare it to a locally guessed exact path. Reject paths escaping the declared output_root, "
        "but accept legitimate runtime-owned subdirectories beneath it. Bind condition, axis and seed "
        "from their explicit arguments into the output provenance, not by parsing directory names. "
        "Additional dimensions need distinct subdirectories and a complete declared output inventory. "
        "Every outputs.per_run_files entry must name an actual file below {output_dir}/; an integrity "
        "index does not substitute for missing metrics, prediction or provenance files. List concrete "
        "relative paths for all frozen dimension values when the runner uses child directories. "
        "Do not aggregate repeated conditions, fractions or seeds as independent scientific units."
    )
