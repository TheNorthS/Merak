"""One producer contract for scheduler-verified per-cell scientific provenance."""


def output_provenance_instruction() -> str:
    return (
        'Managed execution output contract: each declared provenance.json must contain '
        'result_file_sha256, a JSON object mapping project-relative or cell-relative output paths '
        'to SHA256 hex digests for every declared per_run_files artifact except provenance.json '
        'itself. Hash final on-disk bytes, including the final run log and resolved configuration. '
        'Do not substitute output_file_sha256, hashes or an unregistered field. Any later log '
        'or telemetry update must update the corresponding digest before atomic publication. '
        'Failed outputs are immutable evidence: repair the generating source and execute a new '
        'source-bound run namespace; never edit prior results or their acceptance records.'
    )
