# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `eb76e48adaafe3c71556918d42efc98cca5d8f2f` / run `34620286461`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## 1. Purpose

This map exists to delete historical frontend overrides without changing current behavior. Preserve live semantics, not version-era wrapper count. `static/app.js` is append-only historical code; a later direct assignment can sever earlier wrappers even if those wrappers contain meaningful old logic.

## 2. Runtime ownership

```text
static/app.js current classic owner chain
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named runtimes
```

`NavigationStability` is the outer navigation coordinator. Current classic navigation semantics that must survive include startup readiness and mobile-sidebar close.

## 3. Accepted deletion batches

| Batch | Physically retired | Accepted code / run |
|---|---|---|
| A | `setupPagePolling`, `jobPollTimer` compatibility | `4cabbe84...` / `34617573070` |
| B | `set423Base`, `setBase424` | `871b1c91...` / `34618276191` |
| C | V37 duplicate `baseSetPage` sidebar wrapper | `f3eb6b36...` / `34619698115` |
| D | `oldSetV39`, `oldSet42`, `set422Base` | `eb76e48a...` / `34620286461` |

Each batch passed frontend unit + Real Chrome; temporary migration helpers/workflows were deleted after success.

## 4. Current visible owner map

| Surface | Current live owner | Required semantics | Proof |
|---|---|---|---|
| Navigation coordination | `NavigationStability` | request epoch, request-scope alignment, PollRegistry leave/enter, stale async protection | unit + Real Chrome |
| Startup readiness | `setPageReady414` | wait for startup snapshot when UI not ready | protected in static guards; future dedicated test if changed |
| Mobile sidebar close | V417 `baseSetPage417` | close sidebar/backdrop on navigation | static guard + explicit Real Chrome |
| Training submit | `TrainingSubmitRuntime` | sole `/train/start`, canonical draft/readiness | unit + Chrome |
| Training jobs request | `TrainingTaskRuntime` | focused `/jobs`, coalescing, force-fresh mutation | unit + browser performance |
| Training jobs timer | `PollRegistry(training-jobs)` | managed cadence + navigation cleanup | PollRegistry + Chrome |
| AutoLabel | `AutoLabelPollRuntime + PollRegistry` | explicit activate/deactivate | unit + Chrome |
| Video | `PollRegistry(video-frames)` | one-shot row patch | unit + Chrome |
| Sources | `PollRegistry(sources)` | managed interval | unit + Chrome |
| Data/material | `MaterialPaginationRuntime61` + current renderer | pagination/card patch/annotation stability | browser performance |
| Algorithm list | `AlgorithmListRuntime` + current renderer | expand/refresh/version rows | browser performance |

## 5. Current setPage topology

Current static scan after Batch D shows 7 `window.setPage=` assignments/bindings:

```text
A. initial function setPage → window.setPage=setPage
B. UI-state persistence direct assignment
C. v35 direct state.page/render assignment
D. v42.4 direct state.page/render assignment
E. v42.7 direct auto-label alias assignment
F. setPageReady414 async wrapper
G. baseSetPage417 sidebar-close wrapper
```

Current final classic chain after complete script load is expected to be:

```text
E v42.7 direct route owner
→ F setPageReady414
→ G baseSetPage417
→ NavigationStability module wrapper
```

because E directly overwrites `window.setPage` without invoking D.

## 6. Next bounded candidate — pre-v42.7 direct-assignment family

Potential dead source layers:

```text
B UI-state persistence direct assignment
C v35 direct state.page/render
D v42.4 direct state.page/render
```

Unlike Batch D, these are direct assignments rather than wrappers, so the write-before-delete proof must additionally check initialization-time behavior.

Required proof:

```text
1. source order B < C < D < E
2. no synchronous setPage(...) invocation between B/C/D/E requires the temporary assigned function
3. no callback/closure stores B/C/D for later use
4. any required saveUiState persistence occurs in current render/lifecycle code
5. E alias behavior remains correct
6. F/G and NavigationStability remain intact
7. deletion only removes the three dead assignments, not surrounding render/load logic
8. permanent static guard + full frontend + Real Chrome
```

If #2 or #3 fails, split the family and keep whichever temporary assignment participates in initialization.

## 7. Render-chain caution

Historical `render=function...` layers are not automatically dead when setPage layers are. Many later renderers capture prior render functions and delegate to them. Render cleanup must be audited independently by reference chain and page coverage.

## 8. Permanent navigation proof currently active

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/browser/navigation-stability.spec.mjs
```

The browser suite explicitly proves final navigation closes `sidebar.mobile-open` and `sideBackdrop.show`.

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

No `main` merge, `VERSION.txt` bump, tag/release or A800 acceptance claim is authorized by this cleanup. A800 RC remains deferred until current P0/P1 debt and zero-point scan are complete.
