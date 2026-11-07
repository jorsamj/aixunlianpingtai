# Evaluation Image Preview Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Restore every independently evaluated image whose frozen identity and bytes remain provable, and show exact preview failure reasons without weakening Test Split isolation.

**Architecture:** Keep the existing evaluation image endpoint and quality-workbench owner. Resolve historical records through the verified evaluation Bundle before any legacy filename fallback, retain Snapshot/SHA/path fencing, and reuse one frontend preview diagnostic contract for both thumbnail cards and the detail inspector. No new database, queue, polling owner, or evaluation engine is introduced.

**Tech Stack:** FastAPI, MaterialRepository/StorageManager, frozen Snapshot v3, evaluation Bundle manifest, vanilla JavaScript/CSS, pytest, Node tests, Playwright Chromium.

---

### Task 1: Freeze the backend recovery and media contracts

**Files:**
- Modify: `tests/api/test_evaluation_diagnostic_image.py`
- Modify: `app.py`

- [x] Add a failing test where a historical sample lacks `image_id`, its normalized Bundle name differs from Snapshot `stored_name`, and manifest plus both hashes prove its identity.
- [x] Add JPEG, PNG, WebP and BMP response tests plus corrupted bytes, access denied, temporary storage failure and arbitrary-path rejection assertions.
- [x] Run the focused pytest file and confirm the normalized historical Bundle case fails with `IMAGE_NOT_IN_SNAPSHOT` before implementation.
- [x] Extract a bounded resolver that identifies the sample through explicit Image ID, unique Snapshot stored name, or verified Bundle member; permit the last route only when manifest Snapshot ID, source SHA, evaluated SHA and safe path all match.
- [x] Return verified media with explicit safe Content-Type, dimensions and evidence-source headers; keep every response read-only and no-store.
- [x] Re-run the focused API and 20k cache tests.

### Task 2: Unify thumbnail and detail failure diagnostics

**Files:**
- Modify: `tests/browser/training-evaluation-diagnostics.spec.mjs`
- Modify: `static/app.js`

- [x] Add failing Chrome assertions that thumbnail cards show structured error reasons and retryability instead of the generic fallback.
- [x] Add stale-request/version-switch assertions and confirm failed previews never reveal GT or prediction overlays.
- [x] Replace direct thumbnail `onerror` behavior with the existing authenticated fetch/blob diagnostic path, using one AbortController scoped to the current evaluation modal.
- [x] Centralize error-code labels, recovery text and retryability so cards and details render the same contract.
- [x] Preserve 24-card paging and lazy current-page loading; abort requests when sorting, paging, closing, or switching versions.

### Task 3: Make the gallery image-first and the inspector diagnostic-first

**Files:**
- Modify: `tests/browser/training-evaluation-diagnostics.spec.mjs`
- Modify: `static/app.js`
- Modify: `static/styles.css`

- [x] Add failing assertions for format, GT/predicted labels, preview status, retry control and compact FP/FN badges.
- [x] Render larger reserved-aspect thumbnails, concise class chips, real format metadata and explicit loading/success/transient/permanent states.
- [x] Keep the existing single detail modal, zoom/reset/fullscreen/navigation and independent GT/prediction toggles; expand its evidence sidebar with source and diagnosis.
- [x] Verify overlays remain aligned at 1920×1080, 1440×900, 1366×768 and 375×812, and that failed images hide all overlays.
- [x] Respect keyboard focus, touch targets and reduced-motion behavior.

### Task 4: Regression, performance, diagnostics and delivery

**Files:**
- Modify: `tests/frontend/version-marker-owner.test.mjs`
- Modify: `static/index.html`
- Modify: `docs/EVALUATION_DIAGNOSTICS_P0_2026_10_12.md`
- Create: `scripts/diagnose_evaluation_previews.py`
- Test: `tests/unit/test_training_evaluation.py`

- [x] Add a read-only production diagnostic command that reports error-code distribution and evidence availability without outputting credentials or image bytes.
- [x] Keep `VERSION.txt` unchanged and advance only the scoped static cache marker.
- [x] Run focused Python, Node and Chrome suites, including the 20k Snapshot identity-index test.
- [x] Capture four viewport screenshots and inspect visual hierarchy, overflow, overlays and error states.
- [x] Run compile, diff and Git status checks, then create one local commit without pushing.
