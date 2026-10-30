# Remote Experiment Runtime

MERAK uses one durable experiment lifecycle for local, SSH, Vast.ai, and Modal
execution. Provider code is infrastructure control code; it does not authorize
scientific code or configuration changes.

## Lifecycle

```text
PRECHECK -> SNAPSHOT -> SYNC/HASH VERIFY -> LAUNCH -> MONITOR -> COLLECT
                                                        |
                                                        v
                                                    ANOMALY
                                                        |
                                                        v
                                      SAFE STOP -> DIAGNOSE -> APPROVAL
                                                        |
                                                        v
                                                NEW ATTEMPT
```

Every run is stored under:

```text
<project>/.merak/experiments/<run_id>/
  run.json
  snapshot.json
  events.jsonl
  attempt-01/
  attempt-02/
  proposals/<proposal_id>.json
```

An attempt records the source snapshot hash, command hash, approved adjustment
ID, remote process metadata, transfer manifests, metrics, anomalies, result
paths, logs, and diagnosis. A later attempt never overwrites an earlier one.

## Provider Paths

### SSH

1. Require a previously verified and host-key-pinned SSH target.
2. Check Bash, Python, disk space, and NVIDIA GPU availability.
3. Upload only the immutable source snapshot over SFTP.
4. Verify each uploaded file with SHA-256.
5. Launch the wrapper with `nohup setsid`, preserving the training exit code.
6. Tail the remote log by byte offset and poll `nvidia-smi` telemetry.
7. Stop the whole process group with TERM, then KILL after a grace period.
8. Download results and logs into attempt-specific directories and verify hashes.

### Vast.ai

1. Require a verified Vast.ai integration and API key.
2. Select only verified, rentable offers that satisfy GPU RAM, reliability,
   hourly-price, and worst-case run-budget limits.
3. Provision the instance and wait for SSH readiness.
4. Register an ephemeral SSH target and reuse the complete SSH lifecycle.
5. Destroy the instance after completion, controlled failure, anomaly stop, or
   operator stop when `auto_destroy` is enabled.
6. Preserve an instance only when MERAK itself detaches unexpectedly and a later
   reattachment remains possible.

### Modal

1. Require a verified Modal integration, CLI, and token pair.
2. Materialize the immutable snapshot into a Modal image.
3. Execute inside a named app with a persistent Modal Volume.
4. Stream training output plus periodic GPU utilization, memory, and temperature.
5. Commit logs, status, and generated experiment artifacts to the Volume.
6. Recover the Volume after success, failure, timeout, anomaly, or operator stop.
7. Reattach by app name and Volume metadata after an MERAK restart.

## Synchronization Boundary

Snapshots exclude credentials, local databases, VCS metadata, virtual
environments, build output, previous logs/results/checkpoints, and datasets by
default. Dataset transfer must be explicitly enabled. Large files are bounded
by policy. Upload and download hash mismatches fail the transfer; a process exit
code of zero is not accepted as a successful scientific run when result
collection cannot be verified.

## Monitoring And Intervention

The health monitor parses structured JSON metrics and common text logs. It
tracks loss history, log heartbeat, and GPU utilization. Critical findings
include:

- CUDA/device OOM
- NaN or infinite loss
- consecutive near-zero loss collapse
- loss divergence
- fatal runtime errors
- stalled logs combined with repeated idle GPU observations

Warnings include a loss plateau or a stalled log without enough idle-GPU
evidence. Critical findings can trigger a safe stop. Logs, status, partial
results, metrics, and the exact finding evidence are collected before the
attempt is finalized.

The workflow monitor exposes these operator actions:

- safe stop
- open diagnosis
- create an adjustment proposal
- approve or reject the proposal
- queue a new attempt from one approved, unused proposal

The workflow WebSocket reconnects with bounded exponential backoff. After a
reconnect it reads the durable manifest and resumes the local log mirror from
the last recovered byte offset, so a transient UI connection loss does not
erase the experiment record.

An adjustment proposal is immutable and records its rationale, expected command
hash, batch size, and source snapshot hash. Approval is rejected as stale if
the command, batch size, or source changes after proposal creation. A source
change after approval also blocks retry. Code edits remain subject to the Chat
diff approval path; the experiment panel never edits source automatically.

## Verification Levels

The repository test suite validates lifecycle behavior with local processes and
mocked SSH, SFTP, Vast.ai, and Modal control planes. This verifies orchestration,
state transitions, cleanup policy, and evidence preservation without spending
cloud resources.

Provider readiness is a separate level. A target is selectable only after its
connection test succeeds. A real end-to-end provider claim additionally
requires a small, budget-capped smoke experiment using the user's own account,
image availability, SSH key, quotas, network, and billing configuration. MERAK
must not report a provider as externally validated based only on mocked tests.
