from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one match in {path}, found {text.count(old)}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Expose the exact durable discovery request that the API froze before queueing.
replace_once(
    "app.py",
    '''def _public_discovery_task(task: TaskRecord) -> dict[str, Any]:\n    public = build_public_task_payload(task)\n    progress_payload = shared_task_artifacts().read_json(task.task_id, task.progress_ref, default={})\n''',
    '''def _public_discovery_task(task: TaskRecord) -> dict[str, Any]:\n    public = build_public_task_payload(task)\n    request_payload = shared_task_artifacts().read_json(task.task_id, "request.json", default={})\n    if not isinstance(request_payload, dict):\n        request_payload = {}\n    scan_roots = [\n        str(root).strip()\n        for root in (request_payload.get("roots") or [])\n        if str(root).strip()\n    ]\n    public["discovery_scope"] = str(request_payload.get("scope") or "").strip().lower()\n    public["scan_roots"] = scan_roots\n    public["scan_root_count"] = len(scan_roots)\n    progress_payload = shared_task_artifacts().read_json(task.task_id, task.progress_ref, default={})\n''',
)

# Render durable roots, permission/cancellation guidance and friendly failure text.
replace_once(
    "static/modules/resource-discovery.js",
    '''  function progressBody(task, kind) {\n    const metrics = task.metrics || task;\n    const environment = kind === 'environment';\n    const taskStatus = status(task.status);\n    const error = task.error?.message || task.error || '';\n    return `<div class="rd-task" id="resourceDiscoveryTask" data-task-id="${escapeHtml(task.id || task.task_id || '')}">\n      <div class="rd-task-state"><span class="pill ${SUCCESS_TASK_STATUSES.has(taskStatus) ? 'ok' : taskStatus === 'FAILED' ? 'err' : 'run'}">${escapeHtml(taskStatus || 'QUEUED')}</span><b>${escapeHtml(task.stage || '等待 Worker 领取')}</b></div>\n      ${ACTIVE_TASK_STATUSES.has(taskStatus) ? '<div class="rd-indeterminate"><i></i></div>' : ''}\n      <div class="rd-task-counts"><div><span>已扫描目录</span><b>${Number(metrics.scanned_dirs) || 0}</b></div>${environment ? `<div><span>Python 候选</span><b>${Number(metrics.python_candidates) || 0}</b></div><div><span>已验证环境</span><b>${Number(metrics.validated_environments) || 0}</b></div>` : `<div><span>发现模型</span><b>${Number(metrics.models_found) || 0}</b></div>`}<div><span>权限失败</span><b>${Number(metrics.permission_errors) || 0}</b></div></div>\n      <div class="rd-current"><span>当前路径</span><code>${escapeHtml(task.current_item || metrics.current_item || '等待扫描')}</code></div>\n      ${error ? `<div class="error-box422"><b>检测失败</b><span>${escapeHtml(typeof error === 'string' ? error : JSON.stringify(error))}</span></div>` : ''}\n      <div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div>\n    </div>`;\n  }\n''',
    '''  function discoveryScopeLabel(task) {\n    const scope = String(task.discovery_scope || '').trim().toLowerCase();\n    if (scope === 'full') return '全机（仅本地文件系统）';\n    if (scope === 'directory') return '指定目录';\n    if (scope === 'fast') return '指定环境快速检测';\n    if (scope === 'auto') return '自动检测';\n    return scope || '未返回';\n  }\n\n  function discoveryFailureMessage(task) {\n    const taskStatus = status(task.status);\n    if (taskStatus === 'CANCELLED') return '任务已取消，扫描已停止；已完成的扫描计数仅用于诊断。';\n    const raw = String(task.error?.message || task.error || '').trim();\n    const normalized = raw.toLocaleLowerCase();\n    if (normalized.includes('requires at least one explicit root') || normalized.includes('no safe local scan roots')) {\n      return '当前未发现可安全扫描的本地文件系统根目录。网络盘和虚拟文件系统不会自动纳入扫描；请确认本机磁盘已正确挂载后重试。';\n    }\n    if (normalized.includes('permission') || normalized.includes('access is denied') || normalized.includes('permission denied')) {\n      return '资源检测因路径权限不足失败。请确认 Worker 对目标目录具有读取权限后重试；网络盘和虚拟文件系统不会因提权而自动纳入扫描。';\n    }\n    return '资源检测失败。请根据任务日志中的失败阶段与错误代码排查；如涉及路径访问，请确认目录存在且 Worker 具有读取权限后重试。';\n  }\n\n  function progressBody(task, kind) {\n    const metrics = task.metrics || task;\n    const environment = kind === 'environment';\n    const taskStatus = status(task.status);\n    const roots = Array.isArray(task.scan_roots) ? task.scan_roots.filter(Boolean) : [];\n    const permissionErrors = Number(metrics.permission_errors) || 0;\n    const terminalMessage = taskStatus === 'FAILED' || taskStatus === 'CANCELLED' ? discoveryFailureMessage(task) : '';\n    return `<div class="rd-task" id="resourceDiscoveryTask" data-task-id="${escapeHtml(task.id || task.task_id || '')}">\n      <div class="rd-task-state"><span class="pill ${SUCCESS_TASK_STATUSES.has(taskStatus) ? 'ok' : taskStatus === 'FAILED' ? 'err' : taskStatus === 'CANCELLED' ? 'warn' : 'run'}">${escapeHtml(taskStatus || 'QUEUED')}</span><b>${escapeHtml(task.stage || '等待 Worker 领取')}</b></div>\n      ${ACTIVE_TASK_STATUSES.has(taskStatus) ? '<div class="rd-indeterminate"><i></i></div>' : ''}\n      <div class="rd-current"><span>扫描范围</span><b>${escapeHtml(discoveryScopeLabel(task))}</b></div>\n      ${roots.length ? `<div class="rd-current"><span>实际扫描根目录（任务创建时已冻结，共 ${roots.length} 个）</span><code>${roots.map(root => escapeHtml(root)).join('<br>')}</code></div>` : ''}\n      <div class="rd-task-counts"><div><span>已扫描目录</span><b>${Number(metrics.scanned_dirs) || 0}</b></div>${environment ? `<div><span>Python 候选</span><b>${Number(metrics.python_candidates) || 0}</b></div><div><span>已验证环境</span><b>${Number(metrics.validated_environments) || 0}</b></div>` : `<div><span>发现模型</span><b>${Number(metrics.models_found) || 0}</b></div>`}<div><span>权限失败</span><b>${permissionErrors}</b></div></div>\n      <div class="rd-current"><span>当前路径</span><code>${escapeHtml(task.current_item || metrics.current_item || '等待扫描')}</code></div>\n      ${permissionErrors ? '<div class="hint">部分目录因权限不足已跳过；如果关键目录未被扫描，请为 Worker 补充只读权限后重试。</div>' : ''}\n      ${terminalMessage ? `<div class="error-box422"><b>${taskStatus === 'CANCELLED' ? '任务已取消' : '检测失败'}</b><span>${escapeHtml(terminalMessage)}</span></div>` : ''}\n      <div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div>\n    </div>`;\n  }\n''',
)

replace_once(
    "static/modules/resource-discovery.js",
    '''        } else if (status(task.status) === 'FAILED') {\n          notify(task.error?.message || task.error || '资源检测失败');\n        }\n''',
    '''        } else if (status(task.status) === 'FAILED') {\n          notify(discoveryFailureMessage(task), 'error');\n        } else if (status(task.status) === 'CANCELLED') {\n          notify(discoveryFailureMessage(task), 'info');\n        }\n''',
)

# Extend backend permanent contracts with Windows multi-drive and Linux/network fencing.
unit_path = Path("tests/unit/test_resource_discovery_scope_contract.py")
unit_text = unit_path.read_text(encoding="utf-8")
unit_text = unit_text.replace("from pathlib import Path\n\nimport pytest", "from pathlib import Path\nfrom types import SimpleNamespace\n\nimport pytest", 1)
unit_text = unit_text.replace(
    "from platform_core.resource_discovery import request_scope, tasks",
    "from platform_core.resource_discovery import request_scope, scanner, tasks",
    1,
)
marker = "def test_windows_local_scan_roots_include_all_visible_local_drives"
if marker in unit_text:
    raise SystemExit("resource discovery platform tests already present")
unit_text += r'''


def test_windows_local_scan_roots_include_all_visible_local_drives(monkeypatch):
    partitions = [
        SimpleNamespace(device="C:\\", mountpoint="C:/", fstype="NTFS", opts="rw"),
        SimpleNamespace(device="D:\\", mountpoint="D:/", fstype="NTFS", opts="rw"),
        SimpleNamespace(device="F:\\", mountpoint="F:/", fstype="NTFS", opts="rw"),
    ]
    monkeypatch.setattr(scanner.psutil, "disk_partitions", lambda all=False: partitions)

    roots = scanner.local_scan_roots(platform="win32")

    assert [str(root).replace("\\", "/").rstrip("/") for root in roots] == ["C:", "D:", "F:"]


def test_linux_local_scan_roots_exclude_network_and_virtual_mounts(monkeypatch):
    partitions = [
        SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4", opts="rw"),
        SimpleNamespace(device="/dev/sdb1", mountpoint="/data", fstype="xfs", opts="rw"),
        SimpleNamespace(device="server:/share", mountpoint="/mnt/nfs", fstype="nfs4", opts="rw,_netdev"),
        SimpleNamespace(device="//server/share", mountpoint="/mnt/smb", fstype="cifs", opts="rw"),
        SimpleNamespace(device="proc", mountpoint="/proc", fstype="proc", opts="rw"),
        SimpleNamespace(device="tmpfs", mountpoint="/run", fstype="tmpfs", opts="rw"),
    ]
    monkeypatch.setattr(scanner.psutil, "disk_partitions", lambda all=False: partitions)

    assert scanner.local_scan_roots(platform="linux") == [Path("/"), Path("/data")]


@pytest.mark.parametrize("fstype", ["nfs", "nfs4", "smb", "cifs", "sshfs", "proc", "sysfs", "tmpfs", "cgroup", "cgroup2"])
def test_full_scan_filesystem_fencing_keeps_network_and_virtual_types_excluded(fstype):
    assert scanner._is_excluded_filesystem("device", "/mnt/test", fstype, "rw") is True


def test_public_discovery_task_projects_frozen_request_scope_and_roots():
    source = Path("app.py").read_text(encoding="utf-8")
    assert 'read_json(task.task_id, "request.json", default={})' in source
    assert 'public["discovery_scope"]' in source
    assert 'public["scan_roots"] = scan_roots' in source
    assert 'public["scan_root_count"] = len(scan_roots)' in source
'''
unit_path.write_text(unit_text, encoding="utf-8")

# Frontend source-level guard: full actions stay explicit, UI consumes durable roots,
# raw backend ValueError is not sent directly to end users, cancellation is explicit,
# and a successful model scan still refreshes the cache.
Path("tests/frontend/resource-discovery-runtime-truth.test.mjs").write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/modules/resource-discovery.js', import.meta.url), 'utf8');

test('full discovery actions remain explicit user actions handled by the API', () => {
  assert.match(source, /deepDetectResourceEnvironment\s*=\s*\(\)\s*=>\s*runtime\.detectEnvironment\(\{scope:\s*'full'\}\)/);
  assert.match(source, /scanAllModels\s*=\s*\(\)\s*=>\s*runtime\.scanModels\(\{scope:\s*'full'\}\)/);
});

test('task detail renders durable frozen discovery roots and scope', () => {
  assert.match(source, /task\.discovery_scope/);
  assert.match(source, /task\.scan_roots/);
  assert.match(source, /实际扫描根目录（任务创建时已冻结/);
  assert.match(source, /全机（仅本地文件系统）/);
});

test('failed cancelled and permission states use actionable frontend copy', () => {
  assert.match(source, /function discoveryFailureMessage\(task\)/);
  assert.match(source, /网络盘和虚拟文件系统不会自动纳入扫描/);
  assert.match(source, /部分目录因权限不足已跳过/);
  assert.match(source, /taskStatus === 'CANCELLED'/);
  assert.doesNotMatch(source, /notify\(task\.error\?\.message \|\| task\.error \|\| '资源检测失败'\)/);
});

test('successful discovery keeps automatic cache refresh', () => {
  assert.match(source, /if \(SUCCESS_TASK_STATUSES\.has\(status\(task\.status\)\)\) \{\s*await refreshCache\(true\)/);
});
''', encoding="utf-8")

# Correct stale lifecycle documentation: trainer-writable images are copies, never hardlinks.
doc_path = Path("docs/TRAINING_BUNDLE_CACHE_LIFECYCLE.md")
doc = doc_path.read_text(encoding="utf-8")
doc = doc.replace(
    "The quota uses logical Bundle bytes. This is intentionally conservative: image\nhardlinks may initially share physical disk blocks with a task Bundle, but the\ncache can later become the remaining link after task cleanup.",
    "The quota uses logical Bundle bytes. This remains intentionally conservative even\nthough trainer-writable task images are now restored with `shutil.copy2()` and\ntherefore do not share an inode with the persistent cache.",
)
doc = doc.replace(
    "For older schema-v2 entries without `access.json`, lifecycle ordering falls back\nto `cache.json.published_at`, then the entry directory mtime.",
    "Schema-v2 entries are not admitted after the writable-image isolation fix. Cache\nschema v3 deliberately fences legacy entries because schema-v2 task restores could\nhave shared writable image inodes with persistent cache data. Lifecycle fallback\nmetadata remains relevant only to entries admitted by the current schema.",
)
doc = doc.replace(
    "After restoration, the trainer reads its own task-local `work/bundle`. Images\nmay be hardlinks to the same file object, while labels, hidden test ground truth,\nSnapshot, YAML and manifest are copied. Removing the cache pathname therefore\ndoes not remove the task-local hardlink.",
    "After restoration, the trainer reads its own task-local `work/bundle`. Every\ntrainer-writable image is copied with `shutil.copy2()` from the immutable persistent\ncache; labels, hidden test ground truth, Snapshot, YAML and manifest are copied as\nwell. The trainer can therefore repair or rewrite a JPEG without mutating the\npersistent `TrainingBundleCache` entry.",
)
doc = doc.replace(
    "- Cache payload integrity rules from schema v2 remain unchanged.",
    "- Cache schema v3 keeps the integrity gates while rejecting legacy schema-v2 entries that predate writable-image isolation.",
)
if "Images\nmay be hardlinks" in doc or "hardlinks may initially share" in doc:
    raise SystemExit("stale hardlink lifecycle wording remains")
doc_path.write_text(doc, encoding="utf-8")

handoff = Path("docs/CODEX_HANDOFF_2026-09-16_RESOURCE_DISCOVERY_JPEG_NORMALIZATION_CLOSURE.md")
handoff.write_text('''# Resource Discovery + JPEG Normalization Closure Handoff — 2026-09-16

## Baseline

- Branch: `refactor/frontend-runtime-stabilization`
- Start HEAD for this closure pass: `7cc3ea1a1d87e4c19dcec7f1431b2cd0f029e082`
- Formal `VERSION.txt`: `42.24.0` (unchanged)
- A800 RC: deferred
- Genuine 10k ZIP acceptance: deferred

## Resource Discovery contract

Current code already resolves an explicit full-machine user action in the API/task-creation layer through `local_scan_roots()` and persists those roots in the durable `RESOURCE_DISCOVERY` request payload. `ResourceDiscoveryHandler` still fails closed when a `full` or `directory` task reaches the Worker without explicit roots.

This closure pass adds runtime truth to the task projection and UI: task details show the scope plus the exact roots frozen at task creation, permission skips have actionable guidance, cancelled tasks are distinct from failures, and raw backend `ValueError` text is no longer surfaced directly to the user. Successful discovery still refreshes the model/environment cache automatically.

Permanent tests cover Windows multi-drive roots, Linux local roots, network/virtual filesystem exclusion, directory/full Worker fail-closed behavior, API durable-root wiring, frontend full-scan actions and runtime-truth rendering.

## JPEG / Training Bundle contract

The latest code before this closure pass already contains the substantive JPEG fix:

- `ultralytics_jpeg_repair_v1` is part of training Snapshot identity.
- Valid JPEGs ending in `FF D9` are not re-encoded.
- Decodable JPEGs missing EOI are normalized only in the task-derived trainer input before Ultralytics starts.
- Source material SHA/size and training-input SHA/size are recorded separately.
- Unrepairable JPEGs fail early as `TRAINING_IMAGE_INVALID`.
- Final mutation detection reports `TRAINING_BUNDLE_IMAGE_MUTATED` with image id, expected training SHA, actual SHA, source SHA and normalization policy.
- Training Bundle cache schema is v3; trainer-writable images are restored with `shutil.copy2()`, not `os.link()`.
- Legacy schema-v2 cache entries are fenced because earlier writable hardlink restores cannot be assumed immutable.

This pass does not rewrite those working mechanisms. It corrects the stale cache lifecycle documentation so future maintenance cannot treat writable task images as hardlinks again.

## Production validation boundary

Code/tests/CI completion is not production-host acceptance. A real Windows machine with multiple local volumes and a real NVIDIA Linux host should still validate actual discovered roots, permissions, filesystem mounts and representative malformed JPEG training input when production acceptance resumes. A800 RC and genuine 10k ZIP acceptance remain explicitly out of scope.

## Focused validation

The temporary closure workflow appends the exact focused pytest/Node counts here after successful execution, before committing the product patch.
''', encoding="utf-8")

# The helper is temporary and must not survive the product commit.
Path(__file__).unlink()
