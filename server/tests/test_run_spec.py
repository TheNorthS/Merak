from server.services.run_spec import (
    execution_seeds,
    run_spec_command,
    run_spec_preflight_command,
    run_spec_requires_seeds,
    run_spec_scientific_command,
    run_spec_seed_groups,
    unresolved_command_placeholders,
)
from server.workflows.engine import WorkflowEngine


def test_execution_seeds_prefers_decisive_named_group() -> None:
    run_spec = {
        "seed_lists": {
            "pilot": [101, 202],
            "decisive": [101, "202", 303, 404, 505],
        }
    }

    assert set(run_spec_seed_groups(run_spec)) == {"pilot", "decisive"}
    assert execution_seeds(run_spec) == [101, 202, 303, 404, 505]


def test_repetition_container_seed_list_is_supported() -> None:
    run_spec = {"repetitions": {"seeds": [13, 42, 73]}}

    assert run_spec_seed_groups(run_spec) == {"default": [13, 42, 73]}
    assert execution_seeds(run_spec) == [13, 42, 73]


def test_optimization_seed_list_is_supported() -> None:
    """Planner output may nest the frozen repetitions under optimization."""
    run_spec = {
        "optimization": {
            "seeds": [13, 42, 73],
            "seed_list_is_frozen_and_must_be_executed_in_full": True,
        }
    }

    assert run_spec_seed_groups(run_spec) == {"default": [13, 42, 73]}
    assert execution_seeds(run_spec) == [13, 42, 73]


def test_windows_python_launcher_is_literal_regex_replacement() -> None:
    executable = r"E:\PyCharmAndAn\Python311\python.exe"

    command = WorkflowEngine._replace_local_python_launcher(
        "python experiments/src/train.py --seed {seed}",
        executable,
    )

    assert command.startswith(executable)
    assert command.endswith("experiments/src/train.py --seed {seed}")


def test_structured_execution_matrix_and_execution_command_are_supported() -> None:
    run_spec = {
        "execution_command": "python experiments/src/train.py",
        "execution_matrix": {"seeds": [13, "42", 73]},
    }
    assert run_spec_command(run_spec).startswith("python experiments/src/train.py")
    assert execution_seeds(run_spec) == [13, 42, 73]


def test_invalid_seed_payload_cannot_pass_contract_and_fall_back_silently() -> None:
    assert run_spec_seed_groups({"seeds": "not-a-seed"}) == {}
    assert run_spec_seed_groups({"seed_lists": {"main": {"seeds": [1, 2]}}}) == {}
    assert execution_seeds({"optimization": {"seeds": [True, 1.5, "bad"]}}) == []


def test_seed_groups_preserve_duplicates_for_audit_but_execution_deduplicates() -> None:
    run_spec = {"optimization": {"seeds": [13, "13", 42]}}

    assert run_spec_seed_groups(run_spec) == {"default": [13, 13, 42]}
    assert execution_seeds(run_spec) == [13, 42]


def test_deterministic_research_families_do_not_require_stochastic_seeds() -> None:
    assert run_spec_requires_seeds({"implementation_family": "machine_learning"})
    assert run_spec_requires_seeds({
        "implementation_family": "machine_learning",
        "deterministic": True,
    })
    assert run_spec_requires_seeds({"implementation_family": "computational_general"})
    assert not run_spec_requires_seeds(
        {"implementation_family": "formal_verification"}
    )
    assert not run_spec_requires_seeds(
        {"implementation_family": "external_protocol"}
    )


def test_preflight_command_is_never_promoted_to_scientific_execution() -> None:
    run_spec = {
        "preflight_command": "python experiments/src/train.py --dry-run",
        "seeds": [13, 42, 73],
    }

    assert run_spec_command(run_spec, run_experiment=True) == ""
    assert run_spec_command(run_spec, run_experiment=False).endswith("--dry-run")
    assert run_spec_preflight_command(run_spec).endswith("--dry-run")

    legacy_dry_run = {"command": run_spec["preflight_command"]}
    assert run_spec_command(legacy_dry_run, run_experiment=True).endswith("--dry-run")
    assert run_spec_scientific_command(legacy_dry_run) == ""


def test_structured_command_metadata_is_shared_by_gate_and_scheduler() -> None:
    run_spec = {
        "execution_command": {
            "command": "python experiments/src/train.py --seed {seed}",
            "executes_training": True,
        },
        "optimization": {"seeds": [13, "42", 73]},
    }

    assert run_spec_command(run_spec, run_experiment=True).endswith("--seed {seed}")
    assert execution_seeds(run_spec) == [13, 42, 73]


def test_only_scheduler_owned_command_placeholders_are_accepted() -> None:
    command = (
        "python experiments/src/train.py --seed {seed} "
        "--out {work_dir} --held-out <manifest_selected_subject_ids> "
        "--unknown {dataset_path}"
    )

    assert unresolved_command_placeholders(command) == [
        "<manifest_selected_subject_ids>",
        "{dataset_path}",
    ]
    assert unresolved_command_placeholders(
        "python train.py --seed {seed:04d} --root {work_dir!s}"
    ) == []
