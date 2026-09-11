# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386` / run `34617573070`  
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

## 3. Override baseline and accepted Batch A

Baseline audit before physical deletion:

```text
window.setPage=function...   10 historical assignments
render=function...           22 historical assignments
setupPagePolling             2 one-line shells
```

Batch A is now **CLOSED**:

```text
setupPagePolling active references = 0
jobPollTimer active references      = 0
app.js cache                        = 42.25.49
acceptance commit                   = 4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386
Frontend Runtime run                = 34617573070
frontend                            = PASS
Real Chrome                         = PASS
```

All historical polling call sites now hand off directly to:

```js
window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
```

Permanent CI forbids `setupPagePolling` from returning.

## 4. Final visible owner map

| Surface | Current live owner | Historical dependency still in chain | Required semantics | Proof before deleting predecessors |
|---|---|---|---|---|
| Navigation | `NavigationStability` wrapping final classic `window.setPage` | multiple classic setPage wrappers | page aliasing, request epoch, polling leave/enter, sidebar close, cache invalidation, persisted UI state where still used | navigation-stability unit + Real Chrome navigation regression |
| Training submit | `TrainingSubmitRuntime` | classic training UI renderers only for form presentation | sole `/train/start` owner, canonical draft, readiness | training submit unit + Chrome real submit |
| Training jobs request | `TrainingTaskRuntime` | classic training renderer DOM | focused `/jobs`, 120ms poll/manual coalescing, force-fresh mutation | training-task unit + browser performance test |
| Training jobs timer | `PollRegistry(training-jobs)` | direct app render call sites only | 2000ms active / 5000ms idle, navigation cleanup | PollRegistry unit + Training PollRegistry CI guard + Chrome |
| AutoLabel timer | `AutoLabelPollRuntime + PollRegistry` | `renderOps427` presentation | managed one-shot, explicit activate/deactivate | AutoLabel unit + Chrome |
| Video timer | `PollRegistry(video-frames)` | `renderVideo424/refreshVideo424Delta` presentation | managed one-shot, row patch only | PollRegistry unit + Chrome |
| Source timer | `PollRegistry(sources)` | `renderSources422` presentation | 2500ms managed interval | PollRegistry unit + Chrome |
| Data/material page | `MaterialPaginationRuntime61` + final `renderDatasets424` wrapper chain | multiple v42.x dataset render wrappers | paged loading, source filter, card patching, annotation stability | material performance + navigation Chrome |
| Algorithm list | `AlgorithmListRuntime` + visible `renderAlgorithms423` | multiple render-era wrappers | fast expand/refresh, version rows, training entry | algorithm-list performance Chrome |
| AI annotation task page | final `window.renderOps427` v60 implementation + `AutoLabelPollRuntime` | older renderOps owner retained as clean-tab fallback | durable worker status/review, no HTTP-thread inference | AutoLabel Chrome |
| Storage config page | final outer `render` wrapper (`素材存储配置`) | calls previous render chain for all other pages | storage page routing only | navigation Chrome + storage-specific tests when changed |

## 5. Observed setPage generations and semantics

The baseline 10 static assignments are not interchangeable. Observed semantic families:

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

## 6. Next safe deletion candidate — v42.3/v42.4 dead setPage base family

Current read-only proof found:

```text
set423Base   → exactly one search match; declaration + call only inside pure forwarding wrapper
setBase424   → exactly one search match; declaration only; no call/use
```

Relevant code shape:

```text
v42.3:
const set423Base=window.setPage;
window.setPage=function(p){set423Base(p)};
try{setPage=window.setPage}catch(e){}

immediately followed by v42.4:
const setBase424=window.setPage;
window.setPage=function(p){state.page=p;render()};
try{setPage=window.setPage}catch(e){}
```

The v42.4 assignment does not call `setBase424`; therefore the v42.3 forwarding wrapper has no surviving semantics once execution reaches v42.4, and `setBase424` is a dead capture. Before writing, repeat these exact searches against current HEAD.

Target bounded deletion:

```text
remove v42.3 set423Base forwarding assignment
remove unused setBase424 capture
retain the v42.4 direct setPage assignment unchanged
retain all later alias/cache/sidebar wrappers unchanged
```

Required acceptance:

```text
node --check static/app.js
NavigationStability unit PASS
PollRegistry unit PASS
full frontend PASS
Real Chrome navigation PASS
no page-alias/cache/sidebar behavior regression
```

## 7. Observed render generations and semantics

The 22 baseline `render=function...` assignments include:

```text
base page map + polling handoff
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

Deleting an inner renderer without proving callers can silently break unrelated pages. Physical deletion must proceed by owner family, not by version number.

## 8. High-risk wrappers that are not first candidates

Do not delete until semantics are relocated/proven:

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
3. state independent semantics of the layer being removed
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
