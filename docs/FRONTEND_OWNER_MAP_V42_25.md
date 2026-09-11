# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `f3eb6b360123dd688eea4dd0f29c05a9db5b4c05` / run `34619698115`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## 1. Purpose

This is the handoff map for physically deleting historical frontend overrides without changing current behavior. Preserve semantic ownership, not version-era wrapper count.

`static/app.js` is append-only historical code: later direct assignments can sever earlier wrapper chains, while later wrappers can also retain earlier render owners. Every deletion therefore requires liveness proof.

## 2. Current top-level runtime chain

```text
static/app.js historical shell
→ current classic render/setPage owner chain
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named runtimes
```

`NavigationStability` is the outer live navigation coordinator and owns request/navigation epoch alignment, PollRegistry leave/enter cleanup and stale async-owner protection.

## 3. Accepted deletion batches

### Batch A — `setupPagePolling`

```text
setupPagePolling = 0
jobPollTimer      = 0
acceptance        4cabbe84... / run 34617573070
```

Training timer owner is `PollRegistry(training-jobs)`.

### Batch B — v42.3/v42.4 pass-through family

Physically removed:

```text
set423Base
setBase424
```

Acceptance:

```text
871b1c91d919760728fd74dc0e7abf7ac25b516f
run 34618276191
frontend + Real Chrome PASS
```

### Batch C — duplicate V37 mobile-sidebar wrapper

Physically removed:

```text
const baseSetPage=window.setPage;
window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};
```

Retained live classic owner:

```text
const baseSetPage417=window.setPage;
window.setPage=function(page){
  window.toggleMobileSidebarV37?.(false);
  return baseSetPage417?.(page)
};
```

Permanent proof:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/browser/navigation-stability.spec.mjs
  final navigation owner closes the mobile sidebar and backdrop
```

Acceptance:

```text
f3eb6b360123dd688eea4dd0f29c05a9db5b4c05
run 34619698115
frontend + Real Chrome PASS
app.js cache 42.25.51
```

## 4. Current visible owner map

| Surface | Current live owner | Semantics that must survive | Regression proof |
|---|---|---|---|
| Navigation coordination | `NavigationStability` wrapping final classic `window.setPage` | request epoch, request-scope alignment, PollRegistry leave/enter, stale async protection | navigation unit + Real Chrome |
| Mobile sidebar close | V417 `baseSetPage417` wrapper | close sidebar/backdrop on navigation | static guard + explicit Chrome sidebar test |
| Startup navigation readiness | `setPageReady414` where retained in final predecessor chain | wait for startup snapshot when `uiReady` is false | startup/navigation regressions before deletion |
| Training submit | `TrainingSubmitRuntime` | sole `/train/start`, canonical draft/readiness | unit + Chrome submit |
| Training jobs request | `TrainingTaskRuntime` | focused `/jobs`, coalescing, force-fresh mutation | unit + browser perf |
| Training jobs timer | `PollRegistry(training-jobs)` | managed active/idle cadence + navigation cleanup | PollRegistry + Chrome |
| AutoLabel timer | `AutoLabelPollRuntime + PollRegistry` | explicit activate/deactivate | unit + Chrome |
| Video timer | `PollRegistry(video-frames)` | one-shot row patch | unit + Chrome |
| Source timer | `PollRegistry(sources)` | managed interval | unit + Chrome |
| Data/material page | `MaterialPaginationRuntime61` + current render chain | pagination/card patch/annotation stability | material browser perf |
| Algorithm list | `AlgorithmListRuntime` + current algorithm renderer | fast expand/refresh/version rows | algorithm browser perf |
| Storage config | final storage render wrapper | route storage page, delegate others | navigation/browser coverage |

## 5. Current setPage topology

Baseline before cleanup: 10 historical `window.setPage=function...` assignments.
After Batch B and C: current read shows 8.

Observed families include:

```text
plain state.page/render owners
UI-state persistence
V39 deploy cache invalidation
V42 page-family cache invalidation
V42.2 aliases
v42.4 direct reset
v42.7 auto-label alias/direct reset
startup readiness wrapper
V417 sidebar-close wrapper
NavigationStability outer wrapper (module)
```

The crucial distinction is **live chain vs historical source**. A direct reset that does not call the previous owner makes prior wrappers unreachable unless another reference retained them.

## 6. Next bounded candidate — pre-v42.4 dead setPage family

Current reference audit:

```text
oldSetV39  → local declaration + call inside its own wrapper only
oldSet42   → local declaration + call inside its own wrapper only
set422Base → local declaration + call inside its own wrapper only
```

Historical semantics:

```text
V39: deployment page → state.deployLoaded=false
V42: selected v42 page → state.v42.loaded=false
V42.2: 新建算法/自动迭代 alias → 算法列表
```

Later v42.4 performs a direct reset:

```js
window.setPage=function(p){state.page=p;render()};
```

and does not call the previous owner. If source-order/reference proof remains true at write time, the V39/V42/V42.2 wrappers are dead after script initialization.

### Required proof before deletion

```text
1. exact reference count for oldSetV39 / oldSet42 / set422Base
2. source order confirms v42.4 reset executes later
3. no exported callback holds those local wrappers
4. current final page navigation remains covered by existing Chrome tests
5. delete only this bounded pre-v42.4 family
6. retain v42.4 direct owner, later aliases, setPageReady414, V417 sidebar owner and NavigationStability
7. permanent static guard
8. full frontend + Real Chrome
```

Do not resurrect old cache invalidation or aliases merely because dead historical code contained them. Only current product contracts determine required behavior.

## 7. Render-chain caution

Historical `render=function...` assignments are still numerous and unlike the dead setPage wrappers may be retained through `const previousRender=render` chains. Do not delete render generations based on version number or setPage findings.

Future render cleanup must independently prove:

```text
current visible page renderer
all previous-render references
page-specific independent semantics
named runtime ownership
browser regression
```

## 8. Protected live owners

Do not include in the next batch:

```text
setPageReady414
baseSetPage417
NavigationStability
v42.4 direct setPage owner
later live alias/router wrappers
```

## 9. Per-batch checklist

```text
live HEAD
→ exact reference/liveness proof
→ deterministic regression
→ bounded physical deletion
→ permanent guard
→ syntax/focused unit
→ full frontend
→ Real Chrome
→ sync all four handoff docs
```

## 10. Release boundary

This work does not authorize `main` merge, `VERSION.txt` bump, tag/release or A800 acceptance claims. A800 RC remains deferred until current P0/P1 technical debt and zero-point scan are complete.
