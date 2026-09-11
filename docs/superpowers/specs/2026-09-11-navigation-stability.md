# v42.25 Navigation Stability Contract

## Problem

The legacy browser application is still concentrated in `static/app.js` and contains many historical override layers for `render`, `setPage`, page polling, and page-specific render functions. Several page actions are asynchronous and directly repaint `#view` after `await` without proving that the user is still on the page that started the request.

Example race:

1. User is on Training Tasks.
2. A refresh/pause/resume request begins.
3. User navigates to Datasets before the request returns.
4. The old request completes and calls the Training Tasks renderer.
5. The DOM visually jumps back even though the user selected another page.

Equivalent races exist in source collection, auto annotation, video frame extraction, and deployment pages.

## Contract

- `state.page` is the authoritative active route.
- Every navigation increments a navigation epoch.
- Asynchronous page work belongs to the epoch and page that started it.
- A stale asynchronous completion must never permanently overwrite the current page DOM.
- Leaving a page clears its known page-scoped polling timers.
- Background polling should update local rows/status only; it must not redraw the whole page unless explicitly requested.
- New asynchronous page renderers/actions must verify page ownership after `await` before repainting page-level DOM.

## Implementation

`static/modules/navigation-stability.js` installs after the legacy application and other v42.25 UI modules.

It:

- wraps final `window.setPage` and increments `NavigationEpochGuard`;
- records the current navigation epoch in UI state;
- clears page-scoped task/source/annotation/video polling when leaving those pages;
- fences known asynchronous page actions and page renderers;
- observes `#view` while stale asynchronous operations are still pending;
- repairs the authoritative current page if stale work mutates the page DOM;
- rebinds briefly after startup because the legacy `app.js` assigns some window functions through layered overrides.

The module is intentionally an isolation layer rather than another large patch inside the ~870 KB legacy `static/app.js` file.

## Tests

`tests/frontend/navigation-stability.test.mjs` covers:

- navigation epoch invalidates previous-page work;
- a stale Training Tasks completion after navigation is repaired back to the current page;
- same-page asynchronous work does not trigger unnecessary repair.

Temporary Linux GitHub Actions validation on 2026-09-11 passed together with the existing training-label frontend tests. The temporary workflow was removed after validation.

## Follow-up architecture

This is the runtime safety contract for v42.25. It does not make the large legacy `static/app.js` architecture desirable long term. A later frontend engineering batch should split routing, page renderers, API state, polling, and task views into modules/components so navigation ownership is structural rather than enforced by a compatibility fence.
