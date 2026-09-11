# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 1470bb9f0dd19e1be5d0695cd7f4de21173dd944
run:    34652823778
frontend:     PASS
Real Chrome:  PASS (12/12)
```

Current caches/builds:

```text
app.js                    42.25.55
main.mjs                  42.25.56
navigation-stability      422509
ui-state                  422500
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
auto-label-poll-runtime   422501
```

## 2. Closed owner surfaces

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired training mirrors/fallbacks stay retired.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

No classic timer or creation-wrapper ownership may return.

## 3. Accepted navigation-debt batches

```text
Batch A: setupPagePolling/jobPollTimer                  CLOSED
Batch B: set423Base + setBase424                       CLOSED
Batch C: duplicate V37 baseSetPage sidebar wrapper     CLOSED
Batch D: oldSetV39 + oldSet42 + set422Base             CLOSED
Batch E: navigation persistence moved to final runtime CLOSED
Batch F: v34/v35/v42.4 direct setPage family           CLOSED
Batch G: v42.7 direct auto-label alias owner           CLOSED
Batch H: setPageReady414 startup-readiness owner       CLOSED
```

Batch H evidence:

```text
old-owner browser baseline    0adc46fe... / 34652201043 PASS
double-owner equivalence      a618696e... / 34652478444 PASS
classic owner physically gone 1470bb9f... / 34652823778 PASS
```

`tests/browser/navigation-readiness.spec.mjs` deliberately delays `/api/v53/bootstrap/snapshot`. It proves navigation intent is registered while startup is pending, but `state.page`/render do not advance until `__v53InitPromise` resolves. After readiness, the requested page renders once and its canonical page is persisted.

## 4. Current setPage topology

The chain is now reduced to:

```text
initial function setPage(...) → window.setPage=setPage
baseSetPage417 sidebar-close wrapper
NavigationStability final module wrapper
```

### Named semantic responsibility map

```text
normalizeNavigationPage
  自动标注 → 自动标注及清洗

NavigationStability readiness hook
  request/poll navigation intent first
  waitForNavigationReady()
  startup __v53InitPromise fencing
  predecessor invocation only after readiness

NavigationStability final lifecycle
  navigation epoch
  request-scope cancellation/alignment
  PollRegistry before/after navigation
  stale async fencing
  UI-state persistence

ui-state.js
  serialize/persist page, project, dataset, imageFilter
```

### Remaining classic semantic owner

```text
baseSetPage417
  window.toggleMobileSidebarV37(false)
  → predecessor setPage
```

`toggleMobileSidebarV37(false)` removes `mobile-open` from `#sidebar` and `show` from `#sideBackdrop`. Real Chrome already asserts both are closed after navigation.

Runtime-order note: V417 wrapper is installed through `installUsability417()` later in script execution; source position alone must not be used to infer capture order.

## 5. Remaining render alias fallback

v42.7 still contains a render-level normalization:

```js
render=function(){
  if(state.page==='自动标注') state.page='自动标注及清洗';
  ...
}
```

This is no longer a `setPage` owner. Treat it as render-chain debt later; do not mix it into the sidebar migration.

## 6. Next candidate — `baseSetPage417`

Required migration sequence:

```text
1. Add/strengthen unit contract for sidebar close before predecessor invocation.
2. Keep existing Real Chrome sidebar/backdrop contract as baseline.
3. Add a named before-navigation hook to NavigationStability.
4. Double-owner equivalence: unit + Real Chrome.
5. Physically remove baseSetPage417 only after equivalence.
6. Upgrade permanent guard to forbid the numbered classic owner.
7. Leave the initial bootstrap setPage binding untouched.
```

Do not replace this with a generic global render-repair mechanism; the semantic is just navigation-side UI cleanup.

## 7. Remaining audit targets

```text
initial bootstrap setPage binding
render = ...
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

Each family must follow:

```text
live HEAD
→ exact liveness/reference proof
→ behavior contract
→ named semantic owner
→ double-owner proof
→ bounded physical deletion
→ permanent guard
→ full Real Chrome where relevant
→ docs sync
```

## 8. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. Retired training mirrors/fallbacks stay retired.
4. No mother-model class inheritance on first training.
5. Explicit false/zero training settings survive end-to-end.
6. Do not weaken duplicate-request/race/performance/browser tests.
7. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
8. AutoLabel remains PollRegistry-only.
9. Video/source/training polling direct ownership must not regress.
10. Frontend CI is not A800/CUDA acceptance.
11. Old setPage semantics may move into named runtimes only after behavior is locked.

## 9. Work order

```text
1. baseSetPage417 sidebar migration
2. initial bootstrap setPage liveness audit
3. remaining obsolete render/setPage layers
4. app.js dead code + global reload/request debt
5. cache-busting unification
6. zero-point observer/timer/fetch/render/setPage scan
7. semantic naming + deterministic tests + docs
8. technical-debt zero-point scan
9. A800 RC
```
