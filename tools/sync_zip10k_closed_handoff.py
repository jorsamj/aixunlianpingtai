from pathlib import Path
import re

ACCEPTED = '60305921402204e77b8e7ed4ec8e576d9f857c4b'
PRODUCT = 'b4875ada5ff084fd4e21d7c5f026f5b09128033b'
FOCUSED_RUN = '34731027723'
CLEANUP = 'e819a35c71f6aa20f7739281ddfc75e8502104ce'
UNIT_GUARD = '27654cba1fb3406567a40754904531c2b53aa53f'
CHROME_GUARD = '60305921402204e77b8e7ed4ec8e576d9f857c4b'
FRONTEND_RUN = '34733035739'
ACTION_RUN = '34733035761'

PRODUCT_SECTION = f'''## Product mainline checkpoint — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{{project_id}}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `{PRODUCT}`, focused run `{FOCUSED_RUN}`, cleanup `{CLEANUP}`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`{UNIT_GUARD}`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`{CHROME_GUARD}`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `{FRONTEND_RUN}` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `{ACTION_RUN}` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Current next product scope: ZIP 10k processing-phase scalability audit. The UI/background-state amplification is closed, but this does not yet prove that importing 10,000 valid images with annotations is fast enough. Benchmark the real worker path and inspect per-image image decode/copy, AnnotationRepository writes, progress cadence, v50 buffered material commit, label/project writes and finalization. Optimize only measured hotspots; preserve YOLO/COCO/VOC semantics, project serialization, data integrity and cross-platform behavior.**

'''

FILES = {
    'AGENTS.md': ('### 当前产品主线 — ', '### R20n —'),
    'docs/CODEX_CURRENT_STATE.md': ('### 当前产品主线 — ', '### R20n —'),
    'docs/TECH_DEBT_CLOSURE_V42_25.md': ('## Product mainline checkpoint — ', '## 1. 永久退休 surface'),
    'docs/frontend-legacy-audit.md': ('## Product mainline checkpoint — ', '## 2. Closed owner surfaces'),
    'docs/FRONTEND_OWNER_MAP_V42_25.md': ('## Product mainline checkpoint — ', '## 2. Runtime ownership'),
}

for filename, (start_marker, end_marker) in FILES.items():
    path = Path(filename)
    text = path.read_text(encoding='utf-8')
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f'{filename}: product section start not found')
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f'{filename}: product section end not found')
    section = PRODUCT_SECTION
    if filename in {'AGENTS.md', 'docs/CODEX_CURRENT_STATE.md'}:
        section = PRODUCT_SECTION.replace('## Product mainline checkpoint — ZIP 10k import scalability CLOSED', '### 当前产品主线 — ZIP 10k import scalability CLOSED', 1)
    text = text[:start] + section + text[end:]

    text = re.sub(r'latest full code acceptance:\s*[0-9a-f]{40}', f'latest full code acceptance: {ACCEPTED}', text)
    text = re.sub(r'Frontend Runtime run:\s*\d+', f'Frontend Runtime run:        {FRONTEND_RUN}', text)
    text = re.sub(r'app\.js cache:\s*[0-9.]+', 'app.js cache:                42.25.95', text)
    text = re.sub(r'main\.mjs cache:\s*[0-9.]+', 'main.mjs cache:              42.25.92', text)

    if filename == 'docs/CODEX_CURRENT_STATE.md':
        priority_start = text.find('## 2. Current priority')
        priority_end = text.find('\n```', text.find('```text', priority_start) + 7)
        if priority_start < 0 or priority_end < 0:
            raise SystemExit('CODEX priority block not found')
        block_start = text.find('```text', priority_start)
        replacement = '''```text\nTECH-DEBT CLEANUP PAUSED BY USER REQUEST\n→ PRODUCT MAINLINE: Deployment Artifact E2E CLOSED\n→ Unified Task Progress Phase 1 + Phase 2 CLOSED\n→ Training Progress v2 CLOSED\n→ ZIP 10k import scalability CLOSED (live v19 + cold candidate manifest)\n→ NEXT: ZIP 10k processing-phase benchmark and measured worker-hotspot optimization\n→ SSE/event stream evaluation DEFERRED\n→ non-blocking Navigation Action Fencing final scan remains DEFERRED\n→ Resource Lifecycle production soak / non-SQLite resource classes\n→ backend regression / A800 RC only when explicitly resumed\n```'''
        text = text[:block_start] + replacement + text[priority_end + 4:]
        old_run_sentence = re.search(r'Run `\d+` passed syntax,[^\n]+', text)
        if old_run_sentence:
            new_sentence = f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after ZIP 10k owner/manifest migration. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `{ACTION_RUN}` is green; permanent Resource Discovery SQLite workflow `34700900542` remains green on Ubuntu and Windows. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.'
            text = text[:old_run_sentence.start()] + new_sentence + text[old_run_sentence.end():]

    if filename == 'docs/TECH_DEBT_CLOSURE_V42_25.md':
        text = re.sub(r'> \*\*最近完整代码验收点：`[0-9a-f]{40}`\*\*', f'> **最近完整代码验收点：`{ACCEPTED}`**', text)
        text = re.sub(r'> \*\*Frontend Runtime Stabilization：run `\d+`，frontend \+ Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `\d+` 全绿；', f'> **Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；', text)
        text = text.replace('> **更新日期：2026-09-12**', '> **更新日期：2026-09-13**')

    if filename == 'docs/frontend-legacy-audit.md':
        text = re.sub(r'commit:\s+[0-9a-f]{40}', f'commit:       {ACCEPTED}', text, count=1)
        text = re.sub(r'run:\s+\d+', f'run:          {FRONTEND_RUN}', text, count=1)
        text = re.sub(r'app\.js\s+42\.25\.\d+', 'app.js                  42.25.95', text, count=1)
        text = re.sub(r'main\.mjs\s+42\.25\.\d+', 'main.mjs                  42.25.92', text, count=1)

    if filename == 'docs/FRONTEND_OWNER_MAP_V42_25.md':
        text = re.sub(r'> Latest fully accepted code point: `[0-9a-f]{40}` / run `\d+`', f'> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`', text)

    path.write_text(text, encoding='utf-8')

required = [
    ACCEPTED,
    PRODUCT,
    FOCUSED_RUN,
    '1,370,177 bytes',
    '10,000 image members',
    '33/33 PASS (53.9s)',
    ACTION_RUN,
    'ZIP 10k processing-phase scalability audit',
    '42.24.0',
    '42.25.95',
]
for filename in FILES:
    text = Path(filename).read_text(encoding='utf-8')
    missing = [value for value in required if value not in text]
    if missing:
        raise SystemExit(f'{filename}: missing {missing}')

print('ZIP 10k CLOSED handoff synchronized')
