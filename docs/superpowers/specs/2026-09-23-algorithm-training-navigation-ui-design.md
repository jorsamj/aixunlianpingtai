# Algorithm, Training Task, and Advanced Navigation UI Design

## Goal

Deliver one cohesive frontend update that:

- moves `训练资源` into the formal advanced navigation;
- removes the duplicate `服务节点` menu injector;
- upgrades `算法列表` and `训练任务` to a restrained enterprise SaaS list pattern;
- preserves every existing business capability, canonical truth, cache-first path, and scoped patch path;
- adds no UI framework, parallel owner, fallback renderer, or inferred business data.

The visual hierarchy is limited to `Page → Surface → Content`. The reference images and Ant Design Pro, Arco Pro, TDesign, Semi, and Element cascader patterns are visual and interaction references only.

## Final owners and canonical truth

### Navigation

- `static/app.js::renderNav` is the only menu configuration and render owner.
- `static/modules/navigation-stability.js` remains the only stable route-normalization and `setPage` owner.
- `static/main.mjs` continues to install canonical page owners and navigation chrome.
- `ServiceNodeRuntime` remains the service-node page and business owner, but owns no navigation DOM.

Advanced-menu expansion is visibility state only. Collapsing it never changes `state.page`, persisted route, page state, or business state. A user already on `训练资源` or `服务节点` remains there; reopening the group reconstructs one formal entry and highlights it from the canonical page state.

### Algorithm list

- `AlgorithmListRuntime` becomes the only formal algorithm-list UI owner: shell, view state, filters, sorting, pagination, category-cascader presentation, row rendering, and keyed row patching.
- Historical `renderAlgorithms423` and `renderAlg412` may remain only as direct delegates to `AlgorithmListRuntime`; they contain no independent DOM, filtering, or patch logic.
- The external platform runtime remains the owner of category cache truth, external-algorithm truth, sync, and training eligibility. It exposes a read-only provider interface to the algorithm-list runtime and does not decorate or observe algorithm-list DOM.
- Existing algorithm actions remain routed to their current business owners. Reorganizing actions into direct actions and a more menu does not reimplement them.

The sole category truth is the current ChangLian category cache. An algorithm matches an applied category only through a real `external_category_id`. Local algorithms remain visible when no category filter is applied and are excluded from category-filtered results without inferred IDs, text matching, tags, industry guesses, or temporary mappings.

### Training tasks

- `TrainingTaskRuntime` owns the Durable Task snapshot, state normalization, actions, API refresh, and canonical task truth.
- `TrainingTaskVisibilityRuntime` owns only tabs, filters, sorting, pagination, transient batch selection, shell DOM, keyed row patching, and progress-cell patching.
- The visibility runtime never copies the task list, polls an API, or persists derived status counts. Every render derives counts from the current `TrainingTaskRuntime` snapshot.
- Filtering, pagination, sorting, and selection are view state only and never mutate Durable Task truth.

## Shared visual language

The existing stylesheet remains the only theme/token owner. One shared set of semantic list-page variables and primitives serves both pages:

- PageHeader with title, subtitle, primary action, and optional secondary action;
- QueryFilter as one flat surface with aligned 40-pixel controls and a conditional applied-filter row;
- text-underlined tabs/sort controls;
- horizontally divided DataTable with a 48-pixel header and 60–68-pixel rows;
- restrained StatusTag, compact progress, action links, More dropdown, skeleton, empty/error region, and pagination;
- system Chinese font stack, accessible focus styles, light gray-blue page background, white surfaces, subtle borders and shadow, and restrained brand blue.

There is no card wall, cell card, nested surface, high-saturation gradient, permanent checkbox column, or framework dependency.

## Algorithm list design

Structure:

1. PageHeader: `算法列表`, subtitle, `新建算法`, and conditional `同步畅联云`.
2. QueryFilter: name/ID search, source, industry, algorithm type, training status, category trigger, reset, and an applied-filter tag row.
3. SortBar: comprehensive, updated time, training count, and current metric.
4. DataTable: algorithm name, status, current version, real current metric label/value, training count, updated time, and actions.
5. Pagination.

The name cell shows a stable icon, name, and no more than two real descriptive tags. It never exposes UUIDs, hashes, or internal IDs. Direct actions are detail, aggregate report, and training; lower-frequency existing actions remain available through More. Expanded version details stay available without reverting to a card grid.

### Category cascader

The floating panel is 600–760 pixels wide and contains title/close, path-aware search, recent-use shortcuts, a three-pane cascade, and a fixed footer. Columns have bounded height and independent scrolling. Leaf selection is multi-select. Arbitrary real depth remains supported by shifting the three visible panes along the active path rather than flattening or fabricating hierarchy.

The picker keeps separate draft and applied selection:

- opening copies applied IDs into a draft set;
- navigation and checkboxes update only the draft set;
- confirm validates against the current category cache and applies it to AlgorithmListRuntime filters;
- cancel/close discards the draft;
- clear in the footer clears the draft until confirmed.

Search uses the real parent chain and displays full paths. Recent-use IDs are lightweight UI preference data only and never modify category or algorithm truth.

## Training task design

Structure:

1. PageHeader: `训练任务`, subtitle, `新建训练任务`.
2. Status tabs: all, running, queued, completed, failed, and stopped, with counts derived on demand from current tasks.
3. QueryFilter: task/name search, status, algorithm, priority, query, reset, and batch-mode toggle.
4. DataTable columns exactly: algorithm, task, status, priority, progress, elapsed, ETA, stage, start time, actions.
5. Pagination.

The normal table has no checkbox column. Entering temporary batch mode adds selection inside the algorithm cell and exposes only operations supported by the current task contract. Exiting batch mode clears selection. Row actions remain status-dependent; low-frequency and destructive actions are grouped without removing capabilities.

The shell is created once. Revisit uses cached task truth immediately, background jobs-only refresh patches keyed rows, and polling patches only changed cells, especially progress and clocks. Initial no-cache loading uses a filter/table-shaped skeleton; refresh errors preserve existing data and render only a regional error.

## Compatibility and anti-nesting rule

Compatibility may normalize, redirect, or delegate only. This change must not create `owner → wrapper → decorator → legacy helper → final owner`, a second category truth, a second task list, a menu dedupe layer, DOM cleanup by text, or a replacement polling path.

The repository-wide rule is one capability per final owner, one canonical truth per state, and one formal call chain. Historical nesting is reduced only where this task proves reachability and ownership; unrelated runtimes are not broadly refactored.

## Focused verification

Navigation:

- one formal `服务节点` entry across repeated expand/collapse and reload;
- `训练资源` only visible while advanced features are expanded;
- collapse on `训练资源` or `服务节点` preserves route, page, title/breadcrumb, state, and capability;
- reopen restores the entry and active highlight;
- training creation still loads training/node resources while the menu is hidden.

Algorithm list:

- first entry, revisit cache, search, source/status filters, real category cascade navigation, draft/cancel/confirm, path search, multi-select, clear, sorting, pagination, training action, and reload restoration;
- local algorithms remain unfiltered until a category is applied and are never assigned inferred categories;
- keyed patch and scoped refresh remain intact.

Training tasks:

- status counts/tabs, search, algorithm/priority filters, query/reset, pagination, conditional actions, temporary batch mode, detail/log/action flows, revisit cache, and multi-status rendering;
- polling preserves the shell and patches progress/rows rather than rerendering the page.

The already-fixed annotation P0 stays covered by its focused browser cases. Verification remains focused; the full Frontend Runtime and repository suite are out of scope.

## Screenshots and delivery

Capture four screenshots from the actual product page: algorithm default, open category cascader, task default, and task multi-status. Then update current handoff documents, verify `VERSION.txt` remains `42.24.0`, review the complete diff, commit the full batch, fetch the long-lived branch, and push only by ordinary fast-forward. No merge from main, force push, tag, release, or interim push is allowed.
