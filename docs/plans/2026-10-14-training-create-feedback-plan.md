# Training Creation Feedback Implementation Plan

> **For Codex:** Use the approved user specification as the design authority. Execute with test-driven development and verification checkpoints.

**Goal:** Add truthful, accessible training creation feedback within the existing modal and sole submit runtime.

**Architecture:** Extend `TrainingSubmitRuntime` with a pure stage projection and one DOM renderer. Keep the existing request flow and task validation unchanged. Styling remains in the canonical stylesheet and the existing modal owns lifecycle.

**Tech Stack:** Browser ES modules, CSS, Node test runner, Playwright.

---

### Task 1: Specify stage projection and UI states

- Add failing unit tests for grouped stages, indeterminate progress, explicit failure, and unknown POST result.
- Run focused Node tests and confirm the new assertions fail.
- Implement minimal pure projection helpers.

### Task 2: Integrate the feedback panel

- Add failing DOM tests for immediate button spinner, live status panel, preserved form, and no duplicate submit.
- Render inside `.train429-create`; update from existing `setSubmitStage`; keep the button mounted.
- Add restrained CSS, responsive layout, and reduced-motion handling.

### Task 3: Browser acceptance and commit

- Add focused browser coverage for slow success, failure, and unknown network outcome.
- Capture creating/success/failure screenshots.
- Run focused and related frontend/browser suites, update handoff docs, verify clean diff, and create one local commit.
