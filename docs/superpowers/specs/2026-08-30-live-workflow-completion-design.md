# Live Workflow Completion Design

## Goal

Make the behavior seen in the running Windows UI match the previously implemented backend capabilities, with no misleading transient states or stale cached modules.

## Findings

1. Iterative training eventually resolves the latest version, but initially renders the YOLO11n mother model for several seconds.
2. New training dialogs select every eligible image, while the required default is zero selected images.
3. The startup snapshot omits model configurations, so AI labeling says no model is configured even though `/api/v35/model-configs` contains a default Ollama model.
4. `main.mjs` imports child modules without a version query. An old cached `materials.js` can therefore prevent all `PlatformCore` helpers from loading.
5. Selecting one AI reference image rerenders up to 120 image cards and feels unresponsive.
6. At narrow widths the navigation drawer stays open after navigation and can intercept main-page clicks.
7. Vendor conversion correctly blocks without a detected official toolchain, but the empty state does not offer a direct route to deployment-resource configuration.

## Design

- Extend the startup snapshot with sanitized model configurations and apply them to frontend state.
- Open training with an empty material selection. For an algorithm with versions, lock the engine immediately using the newest client-known version and reconcile it with the authoritative latest-version API in the background. Never show a mother model during this reconciliation.
- Add a shared asset version to every ES module import so a normal reload cannot combine new `main.mjs` with an old child module.
- Render at most 40 AI reference cards initially and update only the selected card and derived label summary when toggling a reference.
- Make final navigation close the mobile drawer after every page change.
- Add a direct “配置部署资源” action to vendor-conversion empty states while keeping fail-closed behavior when ATC/RKNN/TPU-MLIR is unavailable.

## Error Handling

- AI task creation remains disabled with a clear message if no model configuration is available after refresh.
- Iterative training remains disabled while the latest version cannot be resolved; an API error is displayed rather than silently falling back to a mother model.
- Vendor conversion cannot start unless a compatible resource has passed detection.

## Verification

- API test asserts bootstrap snapshots contain sanitized model configs.
- Browser tests assert zero initial training materials, immediate locked latest-version presentation, configured AI model visibility, reference-label extraction, mobile drawer closure, and deployment-resource navigation.
- Full Python, frontend module, and browser suites run after the focused tests.

