# Workflow reliability boundaries

These changes apply to all projects, not a named test directory. Quality gates
remain blocking. A running task is not an accepted scientific artifact.

## Repaired invariants

| Boundary | Runtime responsibility | Deterministic regression |
| --- | --- | --- |
| Provider → tool execution | Complete response and JSON object before any tool executes; one protocol recovery within the original request budget | `test_tool_response_protocol.py` |
| Stage → filesystem | Exact declared write targets, checked before handlers and counters; other stages and runtime records remain read-only | `test_agent_write_scope.py` |
| Integration evidence → method contract | Explicit frozen mechanism IDs; validate references before merge; finalize implemented only after deep integration checks | `test_implementation_owner_reconciliation.py` |
| Integration inputs → prior stages | Unchanged valid dependencies may be reused; changed scientific inputs require owner reconciliation before rebinding acceptance | `test_implementation_owner_reconciliation.py` |
| Blocked implementation → outer repair | Preserve stable findings and scoped targets; do not rewrite the frozen experiment plan or render previews before implementation is valid | `test_workflow_failure_boundaries.py` |
| Gate preparation → failure handling | Provider/protocol failures preserve transport checkpoints rather than requesting scientific content edits | `test_workflow_failure_boundaries.py` |
| Preview producer → output reuse | Current manifest, source, data and PDF/SVG/PNG hashes must all match; otherwise render and preserve failure gates | `test_simulation_render_reuse.py` |
| Cancellation → task lifetime | Join cancelled workers; clean phases before final cancelled status; kill and reap preview subprocesses | `test_workflow_failure_boundaries.py`, `test_simulation_render_reuse.py` |
| Producer repair → saved checkpoint | Relevant implementation, rendering and policy source changes alter checkpoint signatures | `test_revision_routing_source_signature.py` |
| Runtime → workflow controls | Reconcile terminal HTTP snapshots even when a WebSocket event is lost; reject responses from before a local state transition; show manual resume after interruption | `workflow-runtime-sync.test.cjs` |
| Packaged runtime → manual resume | Ship both Python and template source snapshots; calculate every node's revision fingerprint using the shipped interpreter before release | `build-backend.test.cjs`, `verify_resume_runtime.py` |
| Model request → progress display | Normal requests and retries share one 300-second absolute budget; streamed tool arguments emit progress without disclosing their contents | `test_model_request_budget.py`, `test_implementation_context_propagation.py` |
| Implementation model → stage validator | Typed iteration exhaustion validates joined file writes through the normal ownership/integration gate; invalid outputs remain blocked, and model failure traces remain failures | `test_implementation_iteration_handoff.py` |

## Less repeated work

- Integration findings go directly to the isolated implementation owner, not a
  broad design-model rewrite.
- A stage that resolves no finding stops its duplicate local attempt. Byte
  changes alone do not count as scientific progress.
- Accepted stage output is reused only after current dependency and integrity
  checks. Ownership/provenance are retained; timestamps do not grant acceptance.
- Valid, unchanged previews are reused per asset. Missing or modified outputs
  never satisfy the cache check.
- The preview child has a bounded 180-second render window and explicit
  cancellation cleanup. This is a cold-start allowance, not proof that every
  previous slowdown came from imports, and not an unbounded wait.

## Verification and execution

Run from `merak-ide/`:

```text
npm run test:workflow-reliability
npm run verify:local
```

These checks use temporary fixtures, fake providers and fake subprocesses.
They do not authorize a real workflow, model call, simulation, training, GPU
job or remote experiment. Real project verification still requires an explicit
execution request. Backend source changes take effect after restarting MERAK;
cancelled runs remain cancelled until explicitly resumed.

The normal agent loop retains first-response and stream-silence limits inside
the shared request budget. Incoming chunks do not extend the absolute deadline.
Progress distinguishes waiting for a response from receiving output and reports
the current attempt's remaining time separately from the shared retry budget.
An interrupted response never authorizes executing incomplete tool arguments.

Local/package smoke checks cover installation and recovery infrastructure. They
are not a completed research run with a real model, real dataset or remote GPU.
Iteration-handoff regressions use the real agent loop and stage validator with a
fake provider and temporary artifacts. Integration delegates bind transcript
reuse to current scientific inputs so a changed upstream implementation cannot
silently restore instructions from an earlier attempt.
