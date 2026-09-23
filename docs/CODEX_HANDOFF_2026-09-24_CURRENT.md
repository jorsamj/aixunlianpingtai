# CODEX HANDOFF — 2026-09-24 CURRENT

> Repository: `jorsamj/aixunlianpingtai`  
> Long-lived branch: `feature/external-algorithm-publishing`  
> Code/CI cutoff before this documentation commit: `3b6187a2124ed536f63a37be6ebb2c69f7ed049c`  
> `VERSION.txt = 42.24.0` — must not change.  
> The documentation commit itself will advance HEAD. A new session MUST re-read remote HEAD before making any code change.

## 1. Non-negotiable rules

- Do not merge `main`.
- Do not tag or release.
- Do not force-push.
- Keep `VERSION.txt` exactly `42.24.0`.
- Do not delete/weaken tests to obtain green CI.
- Do not restore retired navigation/pages/owners merely to satisfy stale tests.
- Do not create a second frontend owner, second polling loop, second training truth store, or second training detail/log modal.
- Windows 11 is development; formal Linux/NVIDIA production remains the target. Do not hardcode Windows paths.
- Formal Web listener remains `127.0.0.1:8010`.
- Queued Actions are not green; completed failures must be read from real job logs before changing production code.

## 2. Training resource / scheduler work completed

The resource chain is now end-to-end and should not be redesigned.

Important commits, oldest to newest:

```text
bbf323b17152  fix: preserve GPU policy through training runtime
d624f5ec14f3  fix: budget host resources across multi-GPU training
5c8c7620b1ce  fix: persist adaptive training provenance
3e33641c90c9  ci: align external guards with current runtime owners
a87a18037f77  fix: make training precision runtime-truthful
ad06f3c9d9f1  fix: budget adaptive batch by training precision
f705287c2313  fix: respect manual GPU requests in scheduler
331863dc2e1c  fix: scale loader workers by active reservations
1be407119f61  fix: carry remote dataset memory evidence to training
6674316ad4a2  fix: wait for genuinely idle training GPUs
```

### Frontend / backend profile contract

The frontend exposes exactly three automatic profiles and sends the same durable values used by backend resource resolution:

| UI | durable value | GPU budget | worker cap | RAM-cache budget | batch cap |
| --- | --- | ---: | ---: | ---: | ---: |
| 智能推荐（推荐） | `balanced` | 70% | 8 | 35% | 128 |
| 性能优先 | `performance` | 82% | 12 | 50% | 256 |
| 稳定优先 | `stability` | 58% | 4 | 22% | 64 |

Canonical chain:

```text
training UI
→ TrainingDraft.resource.profile
→ resource_profile
→ TrainReq Literal[balanced, performance, stability]
→ durable task payload
→ local training_tasks OR remote_training_tasks
→ Agent / train_worker
→ training_metrics.resolve_resources()
```

Manual mode remains manual: user Batch/Workers/Cache values are validated, not silently replaced by the automatic profile.

### Scheduler behavior now expected

- Central scheduler owns automatic server/GPU selection.
- `device=auto` remains scheduler-owned until assignment.
- Manual `cuda:N` requests are respected and stay queued if that GPU is reserved/unavailable.
- Same physical GPU is not assigned to two platform tasks while the prior assignment is active.
- Multi-GPU hosts divide CPU/RAM/cache by actual concurrent reservations, not installed GPU count.
- A single job on a dual-GPU server does not have its Workers prematurely halved.
- External GPU load matters: highly utilized GPUs / GPUs with too little free VRAM are not treated as idle merely because the platform has no reservation on them.
- Remote Agent receives dataset-size and decoded-memory evidence so automatic RAM/disk cache selection works remotely too.
- Batch is resolved before training. Runtime does not increase Batch dynamically; bounded OOM retry may reduce Batch on the same assigned GPU.
- Shared-GPU training remains fail-closed.

### Precision truth

Pinned runtime is `ultralytics==8.4.127`.

Training UI/runtime supports:

- `auto`
- `fp16`
- `fp32`

Training BF16 is intentionally fail-closed for this pinned runtime. Do not re-add a training BF16 option unless the runtime is genuinely upgraded and tested. BF16 may legitimately appear in unrelated deployment/conversion UI such as Sophon; guards must scope to training UI, not grep the entire `static/app.js`.

## 3. Training detail / logs / error presentation work completed

The user's reported problems were:

- successful training could still show an error popup;
- details/log data was incomplete;
- open popup did not reliably refresh Epoch/Batch/progress;
- error evidence was shallow;
- popup layout was dense/legacy;
- historical renderers/owners risked technical debt.

Code-side closure is now present. Important commits:

```text
3414abe89c4c  fix: unify training detail logs and runtime truth
487de1640c64  test: guard successful training detail semantics
b6f4c484f698  fix: unify truthful training detail and live progress
a650cd714467  fix: expose structured training failure evidence
1001aeae8016  test: execute training realtime failure contract
aeadd4b7a029  refactor: retire legacy training run center owner
dc9002d41fd1  fix: return enriched read-only training detail truth
a9e742d320a6  ui: expose live training resource telemetry
be3eaccb09f8  perf: keep training detail polling read-only
da0544ad7c2e  refactor: retire legacy training detail owner
eabaa640602e  fix: reconcile terminal training detail truth
8e50195f76d0  test: guard truthful training detail refresh
```

Final owner chain:

```text
TrainingTaskRuntime
→ TrainingProgressStream (durable SSE)
→ TrainingRecoveryRuntime (single detail/log visual owner)
→ read-only canonical detail GET + log GET
→ durable Task truth + worker job truth + training metrics
```

Required semantics:

- Canonical terminal task truth wins over stale historical error/recovery metadata.
- `SUCCEEDED` must never render a stale historical error as fatal.
- `PARTIAL_SUCCESS` is completed-with-warning, not failed.
- Failure detail may expose structured `error`, `error_type`, `failure_stage`, validation/test/report errors, process/runtime/archive evidence.
- Open details receive live SSE updates.
- Terminal SSE must trigger one final canonical detail + log reconciliation before refresh stops.
- Detail GET is read-only: it must not dispatch queues, rebuild global jobs index, or archive/publish algorithm versions.
- Worker train log and durable scheduler/worker lifecycle logs are merged through the canonical log endpoint.
- Detail popup groups progress, actual resources, message/error/warnings, training config, telemetry, reproducibility evidence, lifecycle timeline, and collapsible technical log.
- Do not restore legacy training run center/detail owner or add raw `setInterval/setTimeout` polling.

Detailed design/closure: `docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`.

## 4. Current real CI state at handoff cutoff

For cutoff HEAD `3b6187a2124ed536f63a37be6ebb2c69f7ed049c`:

- total checks: **51**
- success: **41**
- failure: **10**

Therefore the branch is **not green**.

The 10 failing jobs were read from actual logs. Do not treat all ten as production regressions.

### Confirmed stale / mis-scoped checks

1. **Remote Training Runtime / permanent training guard**
   - Failure text: `BF16 must stay hidden until the pinned Ultralytics runtime truly supports it`.
   - The guard greps all of `static/app.js`.
   - Training BF16 is already removed, but unrelated Sophon deployment UI legitimately contains `<option value="bf16">`.
   - Fix the guard scope; do not remove valid deployment BF16 and do not restore training BF16.

2. **Remote Training Runtime / Windows preparation contract**
   - Two tests expect Workers 8 / 12.
   - Windows production code intentionally caps loader Workers at 4.
   - Linux behavior and Windows behavior must have OS-aware assertions. Do not remove the Windows safety cap merely to satisfy Linux-valued assertions.

3. **Label Normalization Contract / frontend contract**
   - Still expects retired exact wrapper:
     `window.createAiLabel429=function createAiLabelCanonical429(opts={})`.
   - Treat as owner/test debt unless focused reproduction proves current canonical AI label action is actually broken.

4. **Broad browser navigation suite**
   - Several failures explicitly expect retired `工作台` while current canonical route is `总览`.
   - One failure is an exact stale build marker (`training-draft-runtime-422516` vs current `422517`).
   - Do not restore `工作台` as a product page.

### Must be focused-reproduced before classification

- External Algorithm Publish Real Chrome: preflight element not visible.
- Storage Source Real Chrome: expected element not visible.
- Model/RKNN Agent Real Chrome: locator click timeout; test mentions retired deployment resource editor semantics.
- External Algorithm Platform Real Chrome: stale algorithm blocked-state element not visible.
- Remote Material permanent guard: API contract was green; only the grep/guard step failed. Read exact guard line before production changes.
- Frontend Runtime “retired legacy poll timer compatibility guard”: preceding owner guards were green; isolate the exact grep before changing runtime.
- Broad browser suite has 14 failed / 58 passed; besides known stale navigation/build-key assertions it also contains ambiguous selector and request-count failures. Each must be isolated individually.

## 5. Current user priority after this handoff

The newest user priority remains the training task experience, but code-side detail/log consolidation has already landed. The next session should **verify before redesigning**.

Priority order:

1. Re-read current remote HEAD / VERSION / recent commits / check-runs.
2. Read this file and `docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`.
3. Resolve current completed CI failures by real logs, starting with confirmed stale guards/tests.
4. Focused browser verification of training task:
   - successful task never shows failure;
   - live progress/Epoch/Batch updates in open detail;
   - log grows without remounting the popup;
   - failure shows useful structured evidence;
   - terminal state performs final reconciliation;
   - layout remains readable and does not spawn another modal owner.
5. Real Linux/NVIDIA and remote Agent verification when available.
6. Only after focused evidence, make further UI improvements.

## 6. Real deployment verification still OPEN

Code/unit/browser mocks are not equal to production GPU evidence.

Still verify on Linux/NVIDIA:

- two training jobs on two GPUs receive distinct devices;
- automatic profile resolves expected Batch/Workers/Cache;
- single job on dual GPU host is not artificially worker-throttled;
- RAM cache activates only with safe memory headroom;
- busy external GPU stays unassigned until acceptable;
- FP16/FP32 actual precision truth matches requested precision;
- CUDA OOM reduction is bounded and recorded;
- detail popup reflects live Epoch/Batch/progress/telemetry;
- terminal popup reconciles final success/failure;
- best/last artifacts and logs are present.

Remote Agent should be checked against the same contracts.

## 7. What NOT to redo

Do not reopen these as architecture projects:

- TrainingTaskRuntime canonical list owner.
- TrainingProgressStream SSE owner.
- TrainingRecoveryRuntime single detail/log owner.
- central node/GPU scheduler ownership.
- GPU reservation identity.
- auto/manual resource strategy split.
- three profile contract.
- GPU policy propagation.
- adaptive resource provenance.
- multi-GPU concurrency budgeting.
- precision truth contract.
- remote dataset memory evidence.
- retired deployment center / retired standalone test-publish route.
- retired `工作台` canonical navigation.

If a test asks for a retired owner/page, migrate the test unless production behavior is independently proven broken.

## 8. Suggested next-session execution sequence

```text
A. Re-read live branch HEAD, VERSION.txt, latest 20 commits, all completed checks.
B. Compare live state against this cutoff; do not assume 3b6187a is still HEAD.
C. Clear confirmed stale CI:
   1) training BF16 guard scope
   2) Windows Workers expectations
   3) retired AI label wrapper assertion
   4) obvious 工作台 / exact build-marker browser debt
D. For every remaining failure, run/inspect one focused test and classify before editing production.
E. Re-run focused training-detail contracts.
F. If focused training detail is green, do not redesign it; move to real Linux GPU / Agent validation.
G. Keep VERSION 42.24.0; no merge/tag/release/force-push.
```
