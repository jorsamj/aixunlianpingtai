from pathlib import Path

SECTION = '''## Product mainline checkpoint — Deployment E2E + Unified Task Progress Phase 1\n\nTechnical-debt cleanup remains paused by user request. Product productionization is now the active line:\n\n- **Deployment Artifact E2E CLOSED** — real conversion outputs refresh on terminal completion; artifacts are listed only for successful jobs with existing files. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.\n- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks`, task detail, real promote/cancel, and durable `priority / queue_rank / resource_queue_position / resource_wait_reason / worker_id / lease_expires_at / phase / progress_percent`. `WAITING_RESOURCE` is a read-only projection of persisted `QUEUED + resource_waiting`; Scheduler semantics are unchanged. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.\n- **Storage Import consumes unified task truth** during execution and returns to its business API only for the final scan result. Product `1855e2bebefe0dd7cab662cda012abba352a000d`, focused run `34727261869`, cleanup `70db2577458ae9197c36f057e714c0bbd3d7716b`.\n- **Training UI consumes durable queue truth without a second polling request** through the existing `/jobs` overlay, including waiting-resource state, resource queue position, wait reason, worker, lease and progress. Product `7ecd56dd308f595d7cc23e921f80ef49ee8163d5`, focused run `34727367920`, cleanup `4d05036398014dffde8c52a86d46fa16ca73447f`.\n\n**Next: Unified Task Progress Phase 2 — AI annotation / cleaning / model conversion first; event-stream/SSE evaluation only after those existing durable-task pages share the same truth contract. Do not rewrite Scheduler, lease recovery, or GPU admission.**\n\n'''

TARGETS = {
    'docs/TECH_DEBT_CLOSURE_V42_25.md': '## 1. 永久退休 surface\n',
    'docs/frontend-legacy-audit.md': '## 2. Closed owner surfaces\n',
    'docs/FRONTEND_OWNER_MAP_V42_25.md': '## 2. Runtime ownership\n',
}

for name, anchor in TARGETS.items():
    path = Path(name)
    text = path.read_text(encoding='utf-8')
    if 'Product mainline checkpoint — Deployment E2E + Unified Task Progress Phase 1' in text:
        continue
    if anchor not in text:
        raise SystemExit(f'{name}: anchor missing')
    text = text.replace(anchor, SECTION + anchor, 1)
    path.write_text(text, encoding='utf-8')

for name in [
    'AGENTS.md',
    'docs/TECH_DEBT_CLOSURE_V42_25.md',
    'docs/CODEX_CURRENT_STATE.md',
    'docs/frontend-legacy-audit.md',
    'docs/FRONTEND_OWNER_MAP_V42_25.md',
]:
    text = Path(name).read_text(encoding='utf-8')
    if 'Unified Task Progress Phase 1' not in text:
        raise SystemExit(f'{name}: missing phase-one handoff')
    if 'Phase 2' not in text:
        raise SystemExit(f'{name}: missing phase-two next scope')

print('all five authority handoff docs aligned')
