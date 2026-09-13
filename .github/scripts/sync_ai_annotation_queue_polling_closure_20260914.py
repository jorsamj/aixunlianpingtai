from pathlib import Path

accepted = '2bc6f72fddd878a7e2d4802c5affd3d640f807e7'
release_run = '34788824842'
navigation_run = '34788824910'
frontend_run = '34788824849'
red_commit = '186005b428f361e88553555b3a86013d206f11b3'
red_run = '34788748122'
product_commit = 'ddb1168a8f3457fef3d875ceec79e618b75acee9'

closure = f"""## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          {red_commit}
valid RED run:             {red_run} (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            {product_commit}
accepted clean code point: {accepted}
Release Regression:        {release_run} PASS
Navigation Action Fencing: {navigation_run} PASS (Real Chrome PASS)
Frontend Runtime:          {frontend_run} PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

"""

next_old = '**Current next product scope: horizontal audit of real queue-position/progress truth across AI annotation, video, cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**'
next_new = '**Current next product scope: continue the horizontal real queue-position/progress audit across video, cleaning, storage import and deployment-test surfaces. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**'

tech = Path('docs/TECH_DEBT_CLOSURE_V42_25.md')
text = tech.read_text(encoding='utf-8')
if 'AI annotation polling queue metadata truth CLOSED' not in text:
    marker = '## 0. 接手入口\n'
    if marker not in text:
        raise SystemExit('TECH marker missing')
    text = text.replace(marker, closure + marker, 1)
import re
text = re.sub(r'> \*\*最近完整代码验收点：`[0-9a-f]{40}`\*\*', f'> **最近完整代码验收点：`{accepted}`**', text, count=1)
text = text.replace(next_old, next_new)
tech.write_text(text, encoding='utf-8')

codex = Path('docs/CODEX_CURRENT_STATE.md')
text = codex.read_text(encoding='utf-8')
text = re.sub(r'latest full code acceptance: [0-9a-f]{40}', f'latest full code acceptance: {accepted}', text, count=1)
text = re.sub(r'Frontend Runtime run:\s+\d+', f'Frontend Runtime run:        {frontend_run}', text, count=1)
if 'AI annotation polling queue metadata truth CLOSED' not in text:
    marker = '## 2. Current priority\n'
    if marker not in text:
        raise SystemExit('CODEX marker missing')
    text = text.replace(marker, closure + marker, 1)
text = text.replace(next_old, next_new)
codex.write_text(text, encoding='utf-8')

audit = Path('docs/frontend-legacy-audit.md')
text = audit.read_text(encoding='utf-8')
text = re.sub(r'commit:\s+[0-9a-f]{40}', f'commit:       {accepted}', text, count=1)
text = re.sub(r'run:\s+\d+', f'run:          {frontend_run}', text, count=1)
if 'AI annotation polling queue metadata truth CLOSED' not in text:
    marker = '## Product closure — Plain image upload whole-task progress truth CLOSED\n'
    if marker not in text:
        raise SystemExit('legacy audit marker missing')
    text = text.replace(marker, closure + marker, 1)
text = text.replace(next_old, next_new)
audit.write_text(text, encoding='utf-8')

owner = Path('docs/FRONTEND_OWNER_MAP_V42_25.md')
text = owner.read_text(encoding='utf-8')
text = re.sub(r'> Latest fully accepted code point: `[0-9a-f]{40}` / run `\d+`', f'> Latest fully accepted code point: `{accepted}` / run `{frontend_run}`', text, count=1)
if 'AI annotation polling queue metadata truth CLOSED' not in text:
    marker = '## 1. Purpose\n'
    if marker not in text:
        raise SystemExit('owner map marker missing')
    text = text.replace(marker, closure + marker, 1)
text = text.replace(next_old, next_new)
owner.write_text(text, encoding='utf-8')

for path in (tech, codex, audit, owner):
    body = path.read_text(encoding='utf-8')
    if accepted not in body or 'AI annotation polling queue metadata truth CLOSED' not in body:
        raise SystemExit(f'authority sync incomplete: {path}')
