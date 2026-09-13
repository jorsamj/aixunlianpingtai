from pathlib import Path

FILES = {
    'AGENTS.md': ('### 当前产品主线 — Deployment E2E + Unified Task Progress Phase 1', '### R20n —'),
    'docs/CODEX_CURRENT_STATE.md': ('### 当前产品主线 — Deployment E2E + Unified Task Progress Phase 1', '### R20n —'),
    'docs/TECH_DEBT_CLOSURE_V42_25.md': ('## Product mainline checkpoint — Deployment E2E + Unified Task Progress Phase 1', '## 1. 永久退休 surface'),
    'docs/frontend-legacy-audit.md': ('## Product mainline checkpoint — Deployment E2E + Unified Task Progress Phase 1', '## 2. Closed owner surfaces'),
    'docs/FRONTEND_OWNER_MAP_V42_25.md': ('## Product mainline checkpoint — Deployment E2E + Unified Task Progress Phase 1', '## 2. Runtime ownership'),
}

ACCEPTED = '4f0ac51b28d3e62da183e82e01a55bedf7fc9e16'
FRONTEND_RUN = '34730512607'
ACTION_RUN = '34730512602'

PRODUCT = '''## Product mainline checkpoint — Unified Task Progress Phase 2 + Training Progress v2 CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Storage Import + Training queue truth CLOSED** — Storage Import consumes unified task truth during execution; Training `/jobs` overlays durable queue truth without a second polling request. Products `1855e2bebefe0dd7cab662cda012abba352a000d` / `7ecd56dd308f595d7cc23e921f80ef49ee8163d5`.
- **Unified Task Progress Phase 2 CLOSED — model conversion**: durable conversion overlay now exposes effective `WAITING_RESOURCE`, queue position/reason, worker/lease and progress; waiting-resource jobs remain actively polled. Product `9817f450b3fbd20256279c3c861b0938ffdcef16`, focused run `34728701060`, cleanup `d02691f47c7e72d1a7726c1fb536113ffed90a7d`.
- **Unified Task Progress Phase 2 CLOSED — AI annotation + cleaning/material batch**: existing business endpoints now expose the same Task Truth without adding a second polling request. AI annotation and `MATERIAL_BATCH(operation=CLEAN)` both surface `WAITING_RESOURCE / queue position / reason / worker / lease / progress`. Product `ff31f879b6d501a501188fed8bc78426d9eb31ea`, focused run `34729292492`, cleanup `17a52fbb8c9f83d92986da9cedb92c603ccf98d8`.
- **Existing v50 material-batching red test is not a Phase 2 regression**: independent unchanged-code baseline run `34729197821` reproduces `test_image_batch_rejects_dataset_deleted_before_commit` failing at `annotation_path.exists()`. The original test remains unchanged and must not be weakened or deleted.
- **SSE/event stream evaluation DEFERRED**: current AI/material/conversion polling is page-scoped, approximately 1.5–1.8s, and already lifecycle-managed. The repository has no EventSource/SSE replay/reconnect base; introducing it now would add more complexity than demonstrated benefit.
- **Training Progress v2 CLOSED**: existing `training-metrics.sqlite3` now persists a truthful `latest_epoch` snapshot in the same epoch SQLite transaction: epoch/total, duration, rolling-last-5 ETA, elapsed time, images/sec, numeric losses, numeric trainer metrics (including mAP when Ultralytics supplies it), and LR. The Worker publishes that snapshot into existing `job.json`; `/jobs` requires no extra metrics request and the detail API continues to expose full `runtime_metrics`. Missing metrics are omitted rather than manufactured as zero. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`, cleanup/accepted HEAD `4f0ac51b28d3e62da183e82e01a55bedf7fc9e16`, Frontend Runtime `34730512607` with Real Chrome **33/33 PASS**, Action Fencing `34730512602` PASS. Existing SQLite FD regression remained green.

**Current next product scope: ZIP 10k import scalability. Liveness audit shows the final browser `window.doImportData` still POSTs synchronously to `/api/v18/projects/{project_id}/datasets/{dataset_id}/import`, while the backend already contains the v19 background import job path with staged progress, per-project serialization and v50 buffered image commit. First priority is to prove and migrate the live UI to the existing background owner before micro-optimizing per-image loops. Do not rewrite Scheduler/GPU admission or resume broad technical-debt cleanup.**

'''

AGENTS_PRODUCT = PRODUCT.replace('## Product mainline checkpoint — Unified Task Progress Phase 2 + Training Progress v2 CLOSED', '### 当前产品主线 — Unified Task Progress Phase 2 + Training Progress v2 CLOSED')
CODEX_PRODUCT = AGENTS_PRODUCT

for filename, (start_marker, end_marker) in FILES.items():
    path = Path(filename)
    text = path.read_text(encoding='utf-8')
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f'{filename}: missing start marker')
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f'{filename}: missing end marker')
    section = PRODUCT
    if filename in {'AGENTS.md', 'docs/CODEX_CURRENT_STATE.md'}:
        section = AGENTS_PRODUCT
    text = text[:start] + section + text[end:]

    # Current accepted product checkpoint / caches.
    text = text.replace('latest full code acceptance: b83b2bf360b891265157e602f622d409d1d2332f', f'latest full code acceptance: {ACCEPTED}')
    text = text.replace('Frontend Runtime run:        34725907423', f'Frontend Runtime run:        {FRONTEND_RUN}')
    text = text.replace('latest full code acceptance: b83b2bf360b891265157e602f622d409d1d2332f', f'latest full code acceptance: {ACCEPTED}')
    text = text.replace('main.mjs cache:              42.25.91', 'main.mjs cache:              42.25.92')
    text = text.replace('`34725907423` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `34725907404` 全绿；', f'`{FRONTEND_RUN}` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `{ACTION_RUN}` 全绿；')
    text = text.replace('Run `34725907423` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after final R20n shadowed Model Config retirement. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `34725907404` is green;', f'Run `{FRONTEND_RUN}` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions after Training Progress v2. Browser navigation runs **33 tests and passed 33/33**. Permanent Action Fencing workflow `{ACTION_RUN}` is green;')

    if filename == 'docs/TECH_DEBT_CLOSURE_V42_25.md':
        text = text.replace('> **最近完整代码验收点：`b83b2bf360b891265157e602f622d409d1d2332f`**', f'> **最近完整代码验收点：`{ACCEPTED}`**')
        text = text.replace('> **Frontend Runtime Stabilization：run `34725907423`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `34725907404` 全绿；', f'> **Frontend Runtime Stabilization：run `{FRONTEND_RUN}`，frontend + Real Chrome 全绿，Real Chrome 33/33 passed；Navigation Action Fencing 永久 run `{ACTION_RUN}` 全绿；')
        text = text.replace('> **更新日期：2026-09-12**', '> **更新日期：2026-09-13**')
    if filename == 'docs/frontend-legacy-audit.md':
        text = text.replace('commit:       b83b2bf360b891265157e602f622d409d1d2332f', f'commit:       {ACCEPTED}')
        text = text.replace('run:          34725907423', f'run:          {FRONTEND_RUN}')
        text = text.replace('main.mjs                  42.25.89', 'main.mjs                  42.25.92')
        if 'training-task-runtime' not in text[text.find('Current caches/builds:'):text.find('## Product mainline checkpoint')]:
            text = text.replace('training-labels           422513\n', 'training-labels           422513\ntraining-task-runtime     training-task-runtime-422503 (cache 422505)\n')
    if filename == 'docs/FRONTEND_OWNER_MAP_V42_25.md':
        text = text.replace('> Latest fully accepted code point: `b83b2bf360b891265157e602f622d409d1d2332f` / run `34725907423`', f'> Latest fully accepted code point: `{ACCEPTED}` / run `{FRONTEND_RUN}`')
    if filename == 'docs/CODEX_CURRENT_STATE.md':
        text = text.replace('→ Unified Task Progress Phase 1 CLOSED (public truth + Storage Import + Training UI)\n→ NEXT: Unified Task Progress Phase 2 (AI annotation / cleaning / conversion), then event-stream evaluation', '→ Unified Task Progress Phase 1 + Phase 2 CLOSED\n→ Training Progress v2 CLOSED (epoch/loss/mAP/throughput/rolling ETA truth)\n→ SSE/event stream DEFERRED\n→ NEXT: ZIP 10k import scalability — migrate final live v18 XHR owner to existing v19 background import jobs')
    path.write_text(text, encoding='utf-8')

# Hard validation before CI commits docs.
for filename in FILES:
    text = Path(filename).read_text(encoding='utf-8')
    required = [
        ACCEPTED,
        'Unified Task Progress Phase 2',
        'Training Progress v2 CLOSED',
        '34730431744',
        '34730512607',
        '33/33 PASS',
        'SSE/event stream evaluation DEFERRED',
        'ZIP 10k import scalability',
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise SystemExit(f'{filename}: missing {missing}')

print('phase2 + training progress handoff synchronized')
