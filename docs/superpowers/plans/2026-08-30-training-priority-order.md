# Training Priority Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every newly created training task use a real numeric priority from 1 to 999, where 1 runs first and equal priorities use stable FIFO ordering within the same training resource.

**Architecture:** Keep the existing `queue_priority` field but version its meaning with `priority_scheme="lower_number_first"`. Centralize normalization and sorting in backend helpers, migrate only legacy queued jobs, and mirror the normalized order in the browser task list. This follows the priority-FIFO pattern used by mature batch schedulers while leaving running-task preemption to the next feature.

**Tech Stack:** FastAPI, Pydantic, JSON job persistence, vanilla JavaScript UI, pytest, Node test runner, Playwright.

---

### Task 1: Strict priority input contract

**Files:**
- Modify: `app.py:28`
- Modify: `app.py:4135`
- Modify: `app.py:4189-4190`
- Create: `tests/api/test_training_priority.py`

- [ ] **Step 1: Write the failing validation tests**

```python
import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("value", [1, 50, 999])
def test_training_priority_accepts_integer_range(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    app_module.validate_train_request(payload)
    assert payload.queue_priority == value


@pytest.mark.parametrize("value", [0, -1, 1000])
def test_training_priority_rejects_out_of_range_integer(value):
    import app as app_module

    payload = app_module.TrainReq(queue_priority=value)
    with pytest.raises(Exception, match="1~999"):
        app_module.validate_train_request(payload)


@pytest.mark.parametrize("value", [True, 1.5, "1", ""])
def test_training_priority_rejects_non_integer_input(value):
    import app as app_module

    with pytest.raises(ValidationError):
        app_module.TrainReq(queue_priority=value)
```

- [ ] **Step 2: Run the validation tests and verify RED**

Run:

```powershell
python -m pytest tests/api/test_training_priority.py -q
```

Expected: the old `0~999` validation accepts `0`, and the non-strict Pydantic integer accepts at least one coercible value.

- [ ] **Step 3: Implement the strict request field and range validation**

Change the import and field to:

```python
from pydantic import BaseModel, StrictInt


class TrainReq(BaseModel):
    # existing fields remain unchanged
    queue_priority: StrictInt = 50
```

Replace the old range check with:

```python
    if int(payload.queue_priority) < 1 or int(payload.queue_priority) > 999:
        raise HTTPException(status_code=400, detail="任务优先级必须是 1~999 的整数，1 为最高优先级")
```

- [ ] **Step 4: Run the validation tests and verify GREEN**

Run:

```powershell
python -m pytest tests/api/test_training_priority.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 5: Commit the strict contract**

```powershell
git add -- app.py tests/api/test_training_priority.py
git commit -m "feat: validate numeric training priority"
```

### Task 2: Normalize legacy queued jobs and sort priority-FIFO

**Files:**
- Modify: `app.py:5727-5753`
- Modify: `app.py:5949-5976`
- Test: `tests/api/test_training_priority.py`

- [ ] **Step 1: Add failing policy and scheduler tests**

Append:

```python
def test_new_priority_sort_key_uses_lower_number_then_fifo():
    import app as app_module

    jobs = [
        {"id": "late-high", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:01:00"},
        {"id": "normal", "queue_priority": 50, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T09:00:00"},
        {"id": "early-high", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:00:00"},
        {"id": "medium", "queue_priority": 2, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T08:00:00"},
    ]

    ordered = sorted(jobs, key=app_module._v56_training_queue_sort_key)

    assert [job["id"] for job in ordered] == ["early-high", "late-high", "medium", "normal"]


@pytest.mark.parametrize(("legacy", "normalized"), [(100, 1), (80, 20), (50, 50)])
def test_legacy_active_priority_mapping_preserves_old_levels(legacy, normalized):
    import app as app_module

    assert app_module._v56_normalize_priority({"status": "queued", "queue_priority": legacy}) == normalized


def test_dispatch_selects_highest_priority_per_resource(tmp_path, monkeypatch):
    import app as app_module

    job_files = []
    for job in [
        {"id": "local-low", "status": "queued", "resource_key": "local:default", "queue_priority": 50, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T09:00:00"},
        {"id": "local-high", "status": "queued", "resource_key": "local:default", "queue_priority": 1, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T10:00:00"},
        {"id": "remote", "status": "queued", "resource_key": "remote:a", "queue_priority": 20, "priority_scheme": "lower_number_first", "queued_at": "2026-08-30T08:00:00"},
    ]:
        job_dir = tmp_path / job["id"]
        job_dir.mkdir()
        job_file = job_dir / "job.json"
        app_module.write_json(job_file, job)
        job_files.append(job_file)
    launched = []
    monkeypatch.setattr(app_module, "_v48_all_job_files", lambda _project_id: job_files)
    monkeypatch.setattr(app_module, "_v48_launch_saved_job", lambda _project_id, job: launched.append(job["id"]))

    app_module._v48_dispatch_training_queues("project")

    assert launched == ["local-high", "remote"]
```

- [ ] **Step 2: Run the scheduler tests and verify RED**

Run:

```powershell
python -m pytest tests/api/test_training_priority.py -q
```

Expected: helper functions are missing and the scheduler still selects larger numbers first.

- [ ] **Step 3: Implement one centralized priority policy**

Add before `_v48_dispatch_training_queues`:

```python
V56_PRIORITY_SCHEME = "lower_number_first"
V56_LEGACY_PRIORITY_MAP = {100: 1, 80: 20, 50: 50}


def _v56_normalize_priority(job: Dict[str, Any]) -> int:
    try:
        raw = int(job.get("queue_priority", 50))
    except (TypeError, ValueError):
        raw = 50
    if job.get("priority_scheme") == V56_PRIORITY_SCHEME:
        return max(1, min(999, raw))
    return V56_LEGACY_PRIORITY_MAP.get(raw, max(1, min(999, 101 - raw)))


def _v56_training_queue_sort_key(job: Dict[str, Any]):
    return (
        _v56_normalize_priority(job),
        int(job.get("priority_tiebreaker") or 0),
        str(job.get("queued_at") or job.get("created_at") or ""),
        str(job.get("id") or ""),
    )


def _v56_migrate_queued_priority(job_file: Path, job: Dict[str, Any]) -> Dict[str, Any]:
    if job.get("status") != "queued" or job.get("priority_scheme") == V56_PRIORITY_SCHEME:
        return job
    migrated = dict(job)
    migrated["legacy_queue_priority"] = job.get("queue_priority", 50)
    migrated["queue_priority"] = _v56_normalize_priority(job)
    migrated["priority_scheme"] = V56_PRIORITY_SCHEME
    migrated["priority_migrated_at"] = now_iso()
    try:
        write_json(job_file, migrated)
    except Exception as exc:
        print(f"[priority-migration] {job_file}: {exc}")
    return migrated
```

When creating a job, persist:

```python
        "queue_priority": int(payload.queue_priority),
        "priority_scheme": V56_PRIORITY_SCHEME,
```

Change dispatch to migrate queued jobs and sort with `_v56_training_queue_sort_key`. Keep one running or paused task per `resource_key`.

- [ ] **Step 4: Keep the existing queued-task promote endpoint directionally safe**

Replace the old `max + 1` behavior with:

```python
    queued_peers = [
        item for item in peers
        if item.get("status") == "queued" and _v48_resource_key(item) == _v48_resource_key(job)
    ]
    minimum = min([_v56_normalize_priority(item) for item in queued_peers] or [50])
    job["queue_priority"] = max(1, minimum - 1)
    job["priority_scheme"] = V56_PRIORITY_SCHEME
    if minimum == 1:
        job["priority_tiebreaker"] = min([int(item.get("priority_tiebreaker") or 0) for item in queued_peers] or [0]) - 1
```

This only prevents the existing button from moving a task backwards. Running-task preemption remains out of scope.

- [ ] **Step 5: Run the backend priority tests and verify GREEN**

Run:

```powershell
python -m pytest tests/api/test_training_priority.py tests/api/test_training_request.py -q
```

Expected: all selected backend tests pass.

- [ ] **Step 6: Commit the scheduler policy**

```powershell
git add -- app.py tests/api/test_training_priority.py tests/api/test_training_request.py
git commit -m "feat: schedule lower numeric priority first"
```

### Task 3: Numeric priority input and visible queue order

**Files:**
- Modify: `static/app.js:2989`
- Modify: `static/app.js:3005-3014`
- Modify: `static/app.js:3119-3132`
- Modify: `static/app.js:3712-3713`
- Modify: `tests/browser/training-quality-reports.spec.mjs`
- Modify: `tests/browser/core-actions.spec.mjs`

- [ ] **Step 1: Add failing browser assertions for the creation form**

In the existing training dialog test, add:

```javascript
  const priority = trainingDialog.locator('#tr429Priority');
  await expect(priority).toHaveAttribute('type', 'number');
  await expect(priority).toHaveAttribute('min', '1');
  await expect(priority).toHaveAttribute('max', '999');
  await expect(priority).toHaveValue('50');
  await expect(trainingDialog.getByText('1 最高，数字越大优先级越低')).toBeVisible();
```

In the submit test, fill and assert:

```javascript
  await dialog.locator('#tr429Priority').fill('7');
  // after submit
  expect(submitted.queue_priority).toBe(7);
```

- [ ] **Step 2: Run the browser test and verify RED**

Run:

```powershell
npx playwright test tests/browser/training-quality-reports.spec.mjs --reporter=line
```

Expected: `#tr429Priority` is still a select and does not expose numeric range attributes.

- [ ] **Step 3: Replace every active training priority select with one numeric field**

Use this markup in both maintained training dialog variants:

```html
<div class="field">
  <label>任务优先级</label>
  <input id="tr429Priority" class="input" type="number" min="1" max="999" step="1" value="50">
  <small>1 最高，数字越大优先级越低；相同数字按进入队列时间排序。</small>
</div>
```

Keep the legacy `tr428Priority` variant consistent with the same attributes and wording. Before building either request payload, validate:

```javascript
const priority = Number(document.getElementById('tr429Priority')?.value || 50);
if (!Number.isInteger(priority) || priority < 1 || priority > 999) {
  return toast('任务优先级必须是 1~999 的整数，1 为最高优先级');
}
```

Send `queue_priority: priority` in the request.

- [ ] **Step 4: Add failing task-list assertions**

Add a browser test that routes the active project response with two queued jobs on one resource:

```javascript
const queuedJobs = [
  {id: 'job-50', status: 'queued', resource_key: 'local:default', queue_priority: 50, priority_scheme: 'lower_number_first', queued_at: '2026-08-30T10:00:00'},
  {id: 'job-1', status: 'queued', resource_key: 'local:default', queue_priority: 1, priority_scheme: 'lower_number_first', queued_at: '2026-08-30T11:00:00'},
];
```

After navigating to “训练任务”, assert the `job-1` row contains `优先级 1` and `队列第 1 位`, while the `job-50` row contains `优先级 50` and `队列第 2 位`.

- [ ] **Step 5: Implement normalized display and ascending queue positions**

Add:

```javascript
function priorityValue428(job){
  const raw=Number(job?.queue_priority ?? 50);
  if(job?.priority_scheme==='lower_number_first')return Math.max(1,Math.min(999,Number.isFinite(raw)?raw:50));
  return ({100:1,80:20,50:50})[raw] ?? Math.max(1,Math.min(999,101-raw));
}
```

Use `priorityValue428` in `queuePosition428`, sorting ascending and then by `queued_at`, `created_at`, and ID. Add `<small class="queuepriority428">优先级 ${priorityValue428(j)}</small>` beside the status for active and historical rows.

- [ ] **Step 6: Run browser tests and verify GREEN**

Run:

```powershell
npx playwright test tests/browser/training-quality-reports.spec.mjs tests/browser/core-actions.spec.mjs --reporter=line
```

Expected: all selected browser tests pass.

- [ ] **Step 7: Commit the UI**

```powershell
git add -- static/app.js tests/browser/training-quality-reports.spec.mjs tests/browser/core-actions.spec.mjs
git commit -m "feat: expose numeric training priority"
```

### Task 4: Version, full regression, and Windows live verification

**Files:**
- Modify: `VERSION.txt`
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/main.mjs` only if module imports change

- [ ] **Step 1: Bump visible and cache versions together**

Set the release version to `42.19.0` in `VERSION.txt`, the page badge, script and stylesheet query strings, and the final runtime badge override in `static/app.js`.

- [ ] **Step 2: Run syntax and diff checks**

Run:

```powershell
node --check static/app.js
node --check static/main.mjs
git diff --check
```

Expected: all commands exit with code 0.

- [ ] **Step 3: Run every automated suite**

Run:

```powershell
python -m pytest -q
npm test
npm run test:browser -- --reporter=line
```

Expected: zero failures. The single hardware-dependent skip remains acceptable only if it reports the same missing external vendor environment as before.

- [ ] **Step 4: Restart only the verified Windows service on port 8012**

Resolve the listener, verify its command line contains `uvicorn app:app --host 127.0.0.1 --port 8012`, stop that exact process, and start the server from the `windows-p0` worktree.

- [ ] **Step 5: Verify the live page**

On `http://127.0.0.1:8012/`:

1. Open an algorithm’s training dialog.
2. Confirm priority defaults to `50`, accepts `1`, and shows the lower-number-first help text.
3. Submit an invalid `0` and confirm no request is sent.
4. Create or inspect queued tasks with priorities `1` and `50` on the same resource.
5. Confirm the priority-1 task displays queue position 1 without interrupting a running task.

- [ ] **Step 6: Commit the release metadata**

```powershell
git add -- VERSION.txt static/index.html static/app.js static/main.mjs
git commit -m "chore: release training priority ordering"
```

## External design references

- Kubernetes separates scheduling priority from preemption policy, including a non-preempting priority mode suitable for data-science workloads: <https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/>
- AWS Deadline Cloud documents strict priority-FIFO ordering and does not interrupt already-running tasks when the scheduling configuration changes: <https://docs.aws.amazon.com/deadline-cloud/latest/developerguide/build-jobs-scheduling.html>
- Slurm uses priority, submit time, and job ID as successive scheduling criteria: <https://slurm.schedmd.com/priority_multifactor.html>
- AWS Batch keeps scheduling resource-aware so a high-priority job is still started only on a compatible resource: <https://docs.aws.amazon.com/batch/latest/userguide/resource-aware-scheduling.html>
