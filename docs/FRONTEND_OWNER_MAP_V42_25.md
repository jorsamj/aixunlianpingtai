# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `774df651c3f278c782029e64bfa3315b12622a9f` / run `34616465336`  
> Authority for debt status: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## 1. Purpose

This document is the handoff map for physically deleting historical frontend overrides without changing visible behavior. It records the current live owner, historical wrapper chain, semantics that must survive, proof required before deletion, and the next safe deletion candidate.

Do not treat a later-numbered function as automatically safe to delete. `static/app.js` is append-only historical code and later wrappers often call earlier owners.

## 2. Current top-level runtime chain

```text
static/app.js historical shell
→ final app render/setPage wrappers
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named page runtimes
```

`NavigationStability` is currently the outer live owner of navigation coordination. Its `stableSetPage` wraps whatever `window.setPage` exists after `app.js` has loaded, and owns:

```text
requestScope.navigate/alignPage
navigation epoch
PollRegistry beforeNavigate/afterNavigate
stale async-owner protection
view navigation-page marker
```

These semantics must not be lost when classic setPage layers are removed.

## 3. Static override counts at current app.js

Current audit of `static/app.js` found:

```text
window.setPage=function...   10 historical assignments
render=function...           22 historical assignments
setupPagePolling             2 historical one-line handoff definitions
```

The two `setupPagePolling` definitions no longer create or clear timers. Both are currently equivalent to:

```js
window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
```

They are therefore the first proven deletion family.

## 4. Final visible owner map

| Surface | Current live owner | Historical dependency still in chain | Required semantics | Proof before deleting predecessors |
|---|---|---|---|---|
| Navigation | `NavigationStability` wrapping final classic `window.setPage` | multiple classic setPage wrappers | page aliasing, request epoch, polling leave/enter, sidebar close, cache invalidation, persisted UI state where still used | navigation-stability unit + Real Chrome navigation regression |
| Training submit | `TrainingSubmitRuntime` | classic training UI renderers only for form presentation | sole `/train/start` owner, canonical draft, readiness | training submit unit + Chrome real submit |
| Training jobs request | `TrainingTaskRuntime` | classic training renderer DOM | focused `/jobs`, 120ms poll/manual coalescing, force-fresh mutation | training-task unit + browser performance test |
| Training jobs timer | `PollRegistry(training-jobs)` | two `setupPagePolling` handoff shells | 2000ms active / 5000ms idle, navigation cleanup | PollRegistry unit + Training PollRegistry CI guard + Chrome |
| AutoLabel timer | `AutoLabelPollRuntime + PollRegistry` | `renderOps427` presentation | managed one-shot, explicit activate/deactivate | AutoLabel unit + Chrome |
| Video timer | `PollRegistry(video-frames)` | `renderVideo424/refreshVideo424Delta` presentation | managed one-shot, row patch only | PollRegistry unit + Chrome |
| Source timer | `PollRegistry(sources)` | `renderSources422` presentation | 2500ms managed interval | PollRegistry unit + Chrome |
| Data/material page | `MaterialPaginationRuntime61` + final `renderDatasets424` wrapper chain | multiple v42.x dataset render wrappers | paged loading, source filter, card patching, annotation stability | material performance + navigation Chrome |
| Algorithm list | `AlgorithmListRuntime` + visible `renderAlgorithms423` | multiple render-era wrappers | fast expand/refresh, version rows, training entry | algorithm-list performance Chrome |
| AI annotation task page | final `window.renderOps427` v60 implementation + `AutoLabelPollRuntime` | older renderOps owner retained as clean-tab fallback | durable worker status/review, no HTTP-thread inference | AutoLabel Chrome |
| Storage config page | final outer `render` wrapper (`素材存储配置`) | calls previous render chain for all other pages | storage page routing only | navigation Chrome + storage-specific tests when changed |

## 5. Observed setPage generations and semantics

The 10 static assignments are not interchangeable. The audit has observed these semantic families:

```text
A. plain state.page = p; render()
B. localStorage/UI-state persistence
C. mobile sidebar close
D. deployment-page cache invalidation
E. v42 page-family cache invalidation
F. aliases such as 新建算法/自动迭代 → 算法列表
G. pure pass-through wrapper around previous setPage
H. direct route reset around v42.4
I. 自动标注 → 自动标注及清洗 alias
J. late mobile-sidebar wrapper around the accumulated chain
```

After `app.js`, `NavigationStability` adds the runtime coordination wrapper.

Deletion rule: preserve semantics, not wrapper count. If a wrapper only forwards with no independent state change, it is a candidate. If it aliases pages or invalidates cache, its behavior must first be moved to the final semantic router.

## 6. Observed render generations and semantics

The 22 static `render=function...` assignments include:

```text
base page map + training polling call
v28/v31/v33 compatibility render maps
v35/v37 dashboard/UI enhancement wrappers
v39 deployment routing
v42 / v42.2 / v42.3 / v42.4 page routing
v42.6 visual file-input enhancement
v42.7 AutoLabel route alias
v42.8 task-center routing
v42.9 / v42.10 algorithm+dataset routing
v42.12/v42.14 label/data-quality routing
later UI cleanup wrapper using MutationObserver
storage-page final outer wrapper
```

Current outermost classic render at the end of `app.js` is:

```text
if page === 素材存储配置
  → renderStorageSources61()
else
  → previous final render chain
```

This means deleting an inner renderer without proving callers can silently break unrelated pages. Physical deletion must proceed by owner family, not by version number.

## 7. First safe physical-deletion batch

### Batch A — setupPagePolling shells

Current state:

```text
2 function definitions
0 local timer ownership
0 jobPollTimer state compatibility
both only call replaceTrainingJobTimer()
```

Target:

```text
remove setupPagePolling definitions
replace live call sites with direct PollRegistryRuntime.replaceTrainingJobTimer()
keep TrainingTaskRuntime as request owner
keep PollRegistry as timer owner
```

Acceptance:

```text
jobPollTimer remains 0 in product runtime
setupPagePolling becomes 0 in active app.js
Training PollRegistry guard updated to reject reintroduction
PollRegistry unit PASS
TrainingTaskRuntime unit PASS
Frontend Runtime Stabilization frontend PASS
Real Chrome PASS
```

## 8. Second candidates after Batch A

Do not delete until usage proof is complete:

```text
pure pass-through set423 wrapper
version-badge-only render wrapper(s), after main.mjs build badge ownership is proven
legacy render layers fully hidden by final page router
legacy setPage wrappers whose only surviving behavior has been moved to a semantic router
```

High-risk wrappers that are not first candidates:

```text
page aliases
localStorage persistence
mobile-sidebar behavior
page cache invalidation
NavigationStability outer wrapper
```

## 9. Audit / deletion checklist for every batch

```text
1. identify final owner
2. search all direct/indirect references
3. state the independent semantics of the layer being removed
4. move semantics first if still needed
5. add/reuse deterministic regression
6. physically delete old owner
7. syntax + focused unit
8. full frontend workflow
9. Real Chrome for behavior changes
10. update TECH_DEBT_CLOSURE / CODEX_CURRENT_STATE / frontend-legacy-audit / this map
```

## 10. Release boundary

This owner-map work is frontend technical-debt closure only. It does not authorize:

```text
merge main
VERSION.txt bump
tag/release
A800 acceptance claims
```

A800 RC remains deferred until current P0/P1 debt closure and zero-point scan are complete.
