# Advanced Navigation: Training Resources and Service Node Ownership

## Goal

Move `训练资源` from the ordinary `算法生成` navigation group into `高级功能`, and remove the duplicate `服务节点` menu injector while preserving every training-resource and service-node business capability.

## Owner boundaries

- `static/app.js::renderNav` is the only navigation/menu owner. It owns group membership, advanced-menu visibility, and active menu classes.
- `static/modules/navigation-stability.js` remains the only route-normalization and stable `setPage` layer. This change adds no alias, wrapper, redirect, or second route owner.
- `static/main.mjs` continues to install the final `训练资源` page owner and navigation chrome. Existing persisted-page restoration and page-extras/cache-first behavior remain unchanged.
- `static/modules/service-node-runtime.js` remains the only service-node page/business runtime owner. It retains its API calls, cache-first snapshot, connectivity checks, node state, capabilities, polling, forms, and mutations. It no longer creates, watches, removes, deduplicates, or highlights navigation DOM.

## Long-term anti-nesting architecture constraint

The repository must preserve one final owner per capability, one canonical truth per state, and one formal call chain. Before changing a feature, contributors must identify the final owner, canonical truth, whether any wrapper remains necessary, and whether an equivalent implementation already exists.

Frontend work must not add same-purpose page-owner wrappers, wrapper runtimes, parallel old/new/fallback implementations, `window.xxx → wrapper → legacy helper → final owner` chains, duplicate shells/renderers/patchers, duplicate state truth, or unnecessary nested cards/containers. Compatibility code may only normalize, redirect, or delegate; it must not reimplement business logic. UI hierarchy should normally stop at `Page → Section/Surface → Content`.

Backend work must not add repeated API/service/adapter/helper layers for the same logic, parallel task handlers/schedulers/repositories, divergent Task/JSON/SQLite/cache truths, or new bypass writes for legacy interfaces. ModelArtifact, Annotation, Durable Task, and External Publication canonical truths must not acquire parallel stores or write paths. The preferred chain is `API → canonical domain/service → repository/runtime`, omitting layers without a clear compatibility or isolation responsibility.

Historical nesting is not authorization for a broad cleanup. First prove call reachability and fallback responsibility, then converge incrementally on the existing final owner. This project-level rule will be added to `AGENTS.md` and summarized in the current handoff documents as part of this change.

## Navigation behavior

The ordinary groups remain `总览`, `算法生成`, and `数据中心`. `算法生成` contains `算法列表` and `训练任务`; `训练资源` is added to the formal `高级功能` item list alongside the existing advanced pages. `服务节点` remains declared exactly once by the formal advanced navigation configuration.

`state.v427Advanced` is visibility state only. Collapsing advanced features rerenders the menu but does not call `setPage`, change `state.page`, write a different persisted route, dispose a page owner, or mutate business state. Therefore a user on `训练资源` or `服务节点` remains on that page with the canonical title and breadcrumb visible. Reopening advanced features immediately reconstructs the formal item and marks it active from `state.page`. Moving to an ordinary page while collapsed keeps advanced entries hidden; reopening does not navigate back.

## Business capability isolation

Training creation continues to hydrate `/api/training_options` and use `state.targets` regardless of whether `训练资源` is visible in the sidebar. Resource discovery, revisit cache, page extras, training submission, and canonical training-resource truth are unchanged. Service-node selection and runtime state likewise do not depend on the sidebar entry being present.

## Minimal implementation

1. Change only the final formal menu configuration in `static/app.js`: remove `训练资源` from `算法生成`, add it to `高级功能`, and keep `服务节点` in that same formal advanced configuration exactly once.
2. Remove `ServiceNodeRuntime`'s `decorateNavigation`, its navigation `MutationObserver`, calls made only for menu decoration, and destroy-time injected-menu removal. Do not change the runtime page owner or business methods.
3. Advance only the affected browser asset cache keys required to deliver the changed `app.js`, `main.mjs`, or service-node module source.
4. Add focused navigation browser coverage and update the existing permanent owner assertion. Do not add post-render cleanup, text-based deduplication, or compatibility wrappers.
5. Add the approved anti-nesting architecture constraint to `AGENTS.md` and the current handoff documents without refactoring unrelated historical code.

## Focused verification

- Default/collapsed navigation hides `训练资源` and contains no duplicate `服务节点` entry.
- Repeated advanced expand/collapse cycles and a page reload always produce at most one formal `服务节点` entry.
- `训练资源`: expand → enter → collapse → page/title/breadcrumb/state remain valid → expand → the restored entry is active.
- `服务节点`: enter → collapse → page/runtime remain valid → expand → the restored entry is active.
- Switch from an advanced page to an ordinary page while collapsed; reopening advanced features restores entries without changing the ordinary route.
- Open training creation while advanced features are collapsed and verify that authoritative training targets/resources are still loaded and selectable.
- Assert there is no `当前页面模块尚未就绪`, no unknown-page fallback, no page error, and exactly one registered page owner per canonical page.
- Run only the focused browser cases, the directly affected frontend owner guard, and JS syntax checks; do not run the full Frontend Runtime or repository suite.

## Non-goals

No training-resource UI redesign, API/schema changes, resource truth changes, service-node feature changes, route aliases, permissions, feature disabling, legacy deployment-page restoration, or unrelated navigation refactoring.
