# Training Label Scope Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent task-specific annotation-scope failures before training creation, let users locate and explicitly supplement only reviewed labels, and preserve complete diagnostics when truth changes during Prepare.

**Architecture:** Extract one stateless compatibility rule from the existing training projection, then consume it from an orchestration service used by the picker API, submit admission, and `TrainingPrepareHandler`. Keep formal annotation writes in `AnnotationRepository`; the browser submits only selected review labels and expected identities. Extend existing frontend summary/submit/recovery runtimes instead of adding new owners or pollers.

**Tech Stack:** Python 3, FastAPI, SQLite repositories, Durable Task ArtifactStore, vanilla JavaScript ES modules, Node test runner, pytest.

---

## File map

- Create `platform_core/training_compatibility.py`: stateless orchestration for contract resolution, split truth, bounded issue collection, and artifact page serialization.
- Modify `platform_core/training_label_tasks.py`: expose the single row-level scope decision used by both projection and compatibility reporting.
- Modify `platform_core/training_material_picker_api.py`: add the task-specific compatibility endpoint and include scope in material projection.
- Modify `platform_core/remote_training_tasks.py`: run the same compatibility check before input freeze and persist issue pages on drift.
- Modify `platform_core/training_recovery_api.py`: expose persisted issue summary/pages on the existing training-task API.
- Modify `app.py`: wire algorithm lookup, pre-create admission, and explicit manual review scope submission.
- Modify `static/modules/training-material-summary-runtime.js`: own compatibility requests and issue paging alongside the existing selection summary.
- Modify `static/modules/training-submit.js`: require current compatibility truth before enabling/posting.
- Modify `static/modules/training-recovery-runtime.js`: render Prepare issue evidence through the existing task detail owner.
- Modify `static/app.js`: display reviewed/pending labels in the existing workbench, submit explicit reviewed codes, and remove excluded IDs only from the current draft.
- Modify `static/main.mjs` and `static/index.html`: pass existing dependencies and refresh asset cache keys.
- Tests: extend only directly related unit/API/frontend suites listed below.

### Task 1: Shared scope compatibility rule

**Files:**
- Modify: `platform_core/training_label_tasks.py`
- Test: `tests/unit/test_training_label_contract.py`

- [ ] **Step 1: Write failing row-level compatibility tests**

Add tests proving the wished-for API and exact missing labels:

```python
from platform_core.training_label_tasks import training_material_scope_issue


def test_scope_issue_returns_every_missing_effective_label():
    issue = training_material_scope_issue(
        {
            "id": "partial",
            "annotation_state": "annotated",
            "annotation_scope": ["helmet"],
            "boxes": [{"label": "helmet", "class_id": 0}],
        },
        {"effective_label_codes": ["helmet", "vest", "person"]},
    )
    assert issue["issue_type"] == "partial_review_scope"
    assert issue["missing_label_codes"] == ["person", "vest"]


def test_scope_issue_accepts_explicitly_complete_scope():
    assert training_material_scope_issue(
        {
            "id": "complete",
            "annotation_state": "confirmed_empty",
            "annotation_scope": ["helmet", "vest"],
            "boxes": [],
        },
        {"effective_label_codes": ["helmet", "vest"]},
    ) is None
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q tests/unit/test_training_label_contract.py -k "scope_issue"
```

Expected: import failure because `training_material_scope_issue` does not exist.

- [ ] **Step 3: Implement one shared rule and delegate projection to it**

Implement a pure function with stable fields:

```python
def training_material_scope_issue(row, contract):
    required = _unique_codes(contract.get("effective_label_codes") or [])
    state = str(row.get("annotation_state") or "unannotated")
    boxes = [dict(box) for box in row.get("boxes") or []]
    scope = _unique_codes(row.get("annotation_scope") or [])
    present = _unique_codes(
        box.get("label") or box.get("code") for box in boxes
    )
    if state not in {"annotated", "confirmed_empty"}:
        return _scope_issue(row, "missing_annotation", required, scope)
    reviewed = set(scope)
    if state == "annotated" and not reviewed:
        reviewed = set(present)
    missing = [] if "*" in reviewed else sorted(set(required) - reviewed)
    if missing:
        return _scope_issue(
            row, "partial_review_scope", required, scope,
            missing_label_codes=missing,
        )
    return None
```

Refactor `project_training_rows()` to call the function before projecting, while preserving its current `ValueError` message and all AUDIT-148 redaction behavior.

- [ ] **Step 4: Run GREEN plus existing AUDIT-148 tests**

Run:

```powershell
python -m pytest -q tests/unit/test_training_label_contract.py tests/unit/test_snapshots.py
```

Expected: all pass.

### Task 2: Bounded compatibility service and picker API

**Files:**
- Create: `platform_core/training_compatibility.py`
- Modify: `platform_core/training_material_picker_api.py`
- Modify: `app.py`
- Test: `tests/api/test_training_material_selection_summary_api.py`
- Test: `tests/api/test_training_request.py`

- [ ] **Step 1: Write failing API tests**

Add one normal and one typical error request:

```python
def test_training_compatibility_lists_all_missing_labels(client, project_with_partial_scope):
    response = client.post(
        f"/api/v62/projects/{project_with_partial_scope.id}/training-materials/compatibility",
        json={
            "algorithm_asset_id": project_with_partial_scope.algorithm_id,
            "image_ids": [project_with_partial_scope.image_id],
            "train_labels": ["helmet", "vest", "person"],
            "model": "yolo11n.pt",
            "framework": "ultralytics",
            "limit": 50,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["issue_count"] == 1
    assert body["items"][0]["missing_label_codes"] == ["person", "vest"]


def test_training_start_rejects_incompatible_scope_before_task_creation(client, project_with_partial_scope):
    before = client.get("/api/v62/tasks").json()
    response = client.post(
        f"/api/v12/projects/{project_with_partial_scope.id}/train/start",
        json=project_with_partial_scope.training_request,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    assert client.get("/api/v62/tasks").json() == before
```

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q tests/api/test_training_material_selection_summary_api.py -k compatibility
python -m pytest -q tests/api/test_training_request.py -k incompatible_scope
```

Expected: 404 for the new endpoint and existing task creation behavior for submit.

- [ ] **Step 3: Implement service and endpoint**

Implement these service interfaces:

```python
@dataclass(frozen=True)
class TrainingCompatibilityResult:
    label_contract: dict[str, Any]
    issues: tuple[dict[str, Any], ...]
    material_revision: int
    annotation_revision: int


def evaluate_training_compatibility(
    data_dir: Path,
    project: Path,
    payload: Mapping[str, Any],
    algorithm: Mapping[str, Any],
) -> TrainingCompatibilityResult:
    split = SplitRequest(
        mode=SplitMode(str(payload.get("split_mode") or "random_test_from_training_pool")),
        train_image_ids=tuple(payload.get("train_image_ids") or payload.get("image_ids") or ()),
        test_image_ids=tuple(payload.get("test_image_ids") or ()),
        experiment_percent=payload.get("experiment_percent", 20),
        validation_percent=float(payload.get("validation_percent") or 20),
    )
    selection = resolve_training_selection(project, split)
    effective_split = selection.effective_split
    contract_payload = {
        **dict(payload),
        "train_image_ids": list(effective_split.train_image_ids),
        "test_image_ids": list(effective_split.test_image_ids),
        "selected_image_ids": list(effective_split.train_image_ids),
    }
    contract = resolve_training_label_contract(
        data_dir, project, contract_payload, algorithm,
    )
    issues = tuple(
        issue
        for row in selection.effective_images
        if (issue := training_material_scope_issue(row, contract)) is not None
    )
    return TrainingCompatibilityResult(
        label_contract=contract,
        issues=issues,
        material_revision=MaterialRepository(project).current_revision(),
        annotation_revision=AnnotationRepository(project).current_revision(),
    )


def compatibility_page(result, *, query="", issue_type="", cursor="", limit=50):
    normalized_query = str(query or "").strip().casefold()
    normalized_type = str(issue_type or "").strip()
    filtered = [
        item for item in result.issues
        if (not normalized_type or item["issue_type"] == normalized_type)
        and (
            not normalized_query
            or normalized_query in str(item.get("image_id") or "").casefold()
            or normalized_query in str(item.get("filename") or "").casefold()
        )
    ]
    offset = max(0, int(cursor or 0))
    bounded = max(1, min(100, int(limit)))
    items = filtered[offset:offset + bounded]
    next_cursor = str(offset + len(items)) if offset + len(items) < len(filtered) else None
    return {
        "items": items,
        "filtered_count": len(filtered),
        "next_cursor": next_cursor,
    }
```

The evaluator must use `resolve_training_selection()`, `resolve_training_label_contract()`, `training_material_scope_issue()`, `MaterialRepository.get_many()` and `AnnotationRepository.get_many()` in batches no larger than 500. Enrich issues with filename, dataset identity, thumbnail/content URLs only at API projection time.

Wire the picker router with an injected `algorithm_provider(project_id, algorithm_id)`. Treat browser `effective_label_codes` as untrusted and return only server-resolved codes.

- [ ] **Step 4: Add pre-create admission using the same service**

In `_enqueue_explicit_training()`, after request normalization but before writing `payload.json` or creating either Durable task, evaluate compatibility. On issues, return a structured `PlatformError`/HTTP 409 containing code, issue count, effective labels, revisions, and the first bounded page.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
python -m pytest -q tests/api/test_training_material_selection_summary_api.py tests/api/test_training_request.py -k "compatibility or incompatible_scope or selection_summary"
```

Expected: all selected tests pass.

### Task 3: Safe ordinary save and explicit review confirmation

**Files:**
- Modify: `app.py`
- Test: `tests/api/test_annotation_flow.py`
- Test: `tests/api/test_annotation_concurrency.py`

- [ ] **Step 1: Write failing API tests for both save modes**

Add tests with an initial `annotation_scope=["helmet"]`:

```python
def test_ordinary_manual_save_preserves_existing_scope(client, annotated_image):
    response = client.post(
        annotated_image.annotation_url,
        json={
            "boxes": annotated_image.updated_boxes,
            "expected_version": annotated_image.version,
            "source_content_sha256": annotated_image.content_sha256,
        },
    )
    assert response.status_code == 200
    assert response.json()["annotation"]["annotation_scope"] == ["helmet"]


def test_explicit_review_adds_only_selected_codes(client, annotated_image):
    response = client.post(
        annotated_image.annotation_url,
        json={
            "boxes": annotated_image.updated_boxes,
            "expected_version": annotated_image.version,
            "source_content_sha256": annotated_image.content_sha256,
            "reviewed_label_codes": ["vest"],
        },
    )
    assert response.status_code == 200
    assert response.json()["annotation"]["annotation_scope"] == ["helmet", "vest"]
```

Also assert `reviewed_label_codes=["*"]`, inactive labels, stale annotation version, changed content SHA, missing/deleting material return 409/422 and never change the annotation digest.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q tests/api/test_annotation_flow.py tests/api/test_annotation_concurrency.py -k "ordinary_manual_save or explicit_review or review_scope"
```

Expected: ordinary save expands to active labels and explicit review fields are ignored/rejected.

- [ ] **Step 3: Implement request contract and one CAS write**

Extend `AnnotationSave`:

```python
class AnnotationSave(BaseModel):
    boxes: List[Dict[str, Any]]
    annotation_state: Optional[Literal["annotated", "confirmed_empty"]] = None
    expected_version: Optional[int] = None
    source_content_sha256: str
    reviewed_label_codes: List[str] = []
```

In `save_annotation()`:

1. Read current Material and existing annotation.
2. Reject unavailable/deleting material and SHA mismatch.
3. Normalize reviewed codes; reject `*`; validate each against current active canonical labels.
4. Set `next_scope = existing_scope ∪ reviewed_label_codes`, without adding all active labels.
5. Write normalized boxes, state, and `next_scope` through the existing `write_annotation()`/AnnotationRepository expected-version CAS once.
6. Re-read Material SHA after commit; if it changed, return a conflict and leave the existing rescan review marker to keep Snapshot fail-closed.
7. Return `reviewed_label_codes_added`, resulting version/digest, and current scope as audit evidence.

- [ ] **Step 4: Run GREEN and existing annotation flow tests**

Run:

```powershell
python -m pytest -q tests/api/test_annotation_flow.py tests/api/test_annotation_concurrency.py
```

Expected: all pass.

### Task 4: Prepare drift evidence and existing task detail API

**Files:**
- Modify: `platform_core/training_compatibility.py`
- Modify: `platform_core/remote_training_tasks.py`
- Modify: `platform_core/training_recovery_api.py`
- Test: `tests/integration/test_training_task_worker.py`
- Test: `tests/api/test_training_recovery_api.py`

- [ ] **Step 1: Write failing Prepare and paging tests**

Create a training parent that passes admission, mutate an annotation scope before Prepare, run the handler, and assert:

```python
manifest = artifacts.read_json(task_id, "input-compatibility/manifest.json")
assert manifest["issue_count"] == 1
assert manifest["required_label_codes"] == ["helmet", "vest"]
page = artifacts.read_json(task_id, manifest["pages"][0]["ref"])
assert page[0]["missing_label_codes"] == ["vest"]
```

Add API assertions for `GET /api/v62/projects/{project_id}/training-tasks/{task_id}/input-issues?page=1&limit=50`, including a 404/non-training-task error.

- [ ] **Step 2: Run RED**

Run:

```powershell
python -m pytest -q tests/integration/test_training_task_worker.py -k compatibility
python -m pytest -q tests/api/test_training_recovery_api.py -k input_issues
```

Expected: missing artifact and endpoint.

- [ ] **Step 3: Persist bounded pages before raising**

Add:

```python
def persist_compatibility_issues(artifacts, task_id, result, page_size=100):
    refs = []
    for index in range(0, len(result.issues), page_size):
        ref = f"input-compatibility/pages/{index // page_size + 1:06d}.json"
        artifacts.atomic_write_json(task_id, ref, list(result.issues[index:index + page_size]))
        refs.append({"page": index // page_size + 1, "ref": ref})
    manifest = {
        "schema_version": 1,
        "issue_count": len(result.issues),
        "required_label_codes": list(
            result.label_contract.get("effective_label_codes") or []
        ),
        "material_revision": result.material_revision,
        "annotation_revision": result.annotation_revision,
        "page_size": page_size,
        "pages": refs,
    }
    artifacts.atomic_write_json(task_id, "input-compatibility/manifest.json", manifest)
    return manifest
```

In `TrainingPrepareHandler._freeze_request_contract()`, evaluate after effective split/label contract resolution and before `freeze_training_inputs()`. Persist pages then raise `TRAINING_MATERIAL_SCOPE_INCOMPATIBLE` when issues exist.

Expose manifest/page reads from `training_recovery_router`; validate page and limit bounds, task identity, and artifact refs.

- [ ] **Step 4: Run GREEN**

Run:

```powershell
python -m pytest -q tests/integration/test_training_task_worker.py tests/api/test_training_recovery_api.py -k "compatibility or input_issues"
```

Expected: all selected tests pass.

### Task 5: Existing frontend runtimes and workbench UI

**Files:**
- Modify: `static/modules/training-material-summary-runtime.js`
- Modify: `static/modules/training-submit.js`
- Modify: `static/modules/training-recovery-runtime.js`
- Modify: `static/app.js`
- Modify: `static/main.mjs`
- Modify: `static/index.html`
- Test: `tests/frontend/training-material-summary-runtime.test.mjs`
- Test: `tests/frontend/training-submit.test.mjs`
- Test: `tests/frontend/training-recovery-runtime.test.mjs`
- Test: `tests/frontend/annotation-workbench.test.mjs`

- [ ] **Step 1: Write failing frontend behavior tests**

Test these public behaviors:

```javascript
test('compatibility issues disable submit until current draft passes', () => {
  assert.deepEqual(trainingSubmitReadiness({
    draft: validDraft,
    base: {},
    compatibility: {ready: true, issue_count: 2},
  }), {ready: false, reason: 'material-compatibility'});
});

test('excluding one issue only removes it from the current training draft', () => {
  runtime.excludeFromDraft('bad-image');
  assert.deepEqual(trainingDraftRuntime.materialIds(), ['good-image']);
  assert.equal(deleteRequests.length, 0);
});
```

Add workbench source assertions/DOM behavior for reviewed tags, unchecked pending checkboxes, partial selection, explicit select-all, and request payload containing only checked `reviewed_label_codes` plus source SHA.

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test tests/frontend/training-material-summary-runtime.test.mjs tests/frontend/training-submit.test.mjs tests/frontend/training-recovery-runtime.test.mjs tests/frontend/annotation-workbench.test.mjs
```

Expected: missing compatibility API/state/actions and old save payload failures.

- [ ] **Step 3: Extend existing summary and submit runtimes**

The summary runtime must:

- build a request from the canonical TrainingDraft plus current target/model/framework;
- abort stale requests and bind responses to a draft signature including selected IDs, algorithm, labels and revisions;
- display compact counts in the create dialog;
- open the existing Modal with search/filter/page controls;
- set a temporary review context before calling the existing `openAnnotation(image_id)`;
- remove an issue only via `trainingDraftRuntime.update()` and immediately invalidate/recheck.

`trainingSubmitReadiness()` must require `compatibility.ready === true` and `issue_count === 0`; the submit function must force-refresh compatibility immediately before POST.

- [ ] **Step 4: Extend existing workbench and recovery views**

The workbench reads the temporary context, renders current scope and all missing labels unchecked, and sends only checked codes when the user chooses “保存并确认审核”. Ordinary save sends an empty review list and preserves existing scope server-side. After success it clears/reloads compatibility.

The recovery runtime consumes the new fields/endpoints through its existing task detail rendering; no interval, second task query, or independent modal owner is added.

- [ ] **Step 5: Run GREEN and syntax checks**

Run:

```powershell
node --check static/app.js
node --check static/modules/training-material-summary-runtime.js
node --check static/modules/training-submit.js
node --check static/modules/training-recovery-runtime.js
node --test tests/frontend/training-material-summary-runtime.test.mjs tests/frontend/training-submit.test.mjs tests/frontend/training-recovery-runtime.test.mjs tests/frontend/annotation-workbench.test.mjs
```

Expected: all pass.

### Task 6: Docs, version, targeted regression and delivery

**Files:**
- Modify: `VERSION.txt`
- Modify: `docs/audit-issues-2026-10-06.md`
- Modify: `docs/PROJECT_HANDOFF_CURRENT.md`
- Modify: `docs/codex-handoff.md`

- [ ] **Step 1: Increment the patch version**

Increment from `42.24.293` for each implementation commit. Do not reuse a version after a commit.

- [ ] **Step 2: Run the final targeted backend suite**

Run:

```powershell
python -m pytest -q tests/unit/test_training_label_contract.py tests/unit/test_snapshots.py tests/unit/test_annotation_repository_scope.py tests/api/test_training_material_selection_summary_api.py tests/api/test_annotation_flow.py tests/api/test_annotation_concurrency.py tests/api/test_training_request.py tests/api/test_training_recovery_api.py tests/integration/test_training_task_worker.py
```

Expected: all pass.

- [ ] **Step 3: Run the final targeted frontend suite and syntax checks**

Run the Task 5 command plus `git diff --check`.

- [ ] **Step 4: Update audit/handoff truthfully**

Record root cause, owners changed, exact targeted test counts, limitations of synthetic data, and whether task artifact/browser flows were actually verified. Do not claim real GPU, OSS, ChangLian or production-data E2E.

- [ ] **Step 5: Recheck remote, commit and push**

Run:

```powershell
git ls-remote origin refs/heads/feature/external-algorithm-publishing
git status --short
git diff --check
git push origin HEAD:feature/external-algorithm-publishing
```

Expected: remote still contains the verified base or is safely rebased before push; push is fast-forward and never forced.

- [ ] **Step 6: Inspect the exact pushed HEAD**

Wait until all GitHub Actions and check-runs for the pushed SHA are terminal. Treat queued, in_progress, cancelled, failure and missing required checks as not passing; inspect logs for failures related to this change.
