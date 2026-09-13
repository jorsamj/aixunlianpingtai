from pathlib import Path

DEPLOY_PRODUCT='b75b7d09780f691b01e4207c3107977b0500d8aa'
DEPLOY_RUN='34726749756'
DEPLOY_CLEANUP='8f3d3e394ceed73e5f522cba512622286fead7a5'
TASK_API_PRODUCT='aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc'
TASK_API_RUN='34727100684'
TASK_API_CLEANUP='6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6'
STORAGE_PRODUCT='1855e2bebefe0dd7cab662cda012abba352a000d'
STORAGE_RUN='34727261869'
STORAGE_CLEANUP='70db2577458ae9197c36f057e714c0bbd3d7716b'
TRAINING_PRODUCT='7ecd56dd308f595d7cc23e921f80ef49ee8163d5'
TRAINING_RUN='34727367920'
TRAINING_CLEANUP='4d05036398014dffde8c52a86d46fa16ca73447f'

section=f'''### 当前产品主线 — Deployment E2E + Unified Task Progress Phase 1\n\n技术债暂停后已经转入真实功能生产化。当前完成：\n\n- **Deployment Artifact E2E CLOSED**：转换任务从 `running → done` 后会立即刷新真实部署产物；部署产物页进入时重新校验服务端真值；成功 job + 真实文件才能出现在 artifacts API，失败或缺失文件不会生成假产物。product `{DEPLOY_PRODUCT}`，focused run `{DEPLOY_RUN}`，cleanup `{DEPLOY_CLEANUP}`。\n- **Unified Task Truth API Phase 1 CLOSED**：新增 `/api/v62/projects/{{project_id}}/tasks`、单任务查询、真实 promote/cancel；公开 `priority / queue_rank / resource_queue_position / resource_wait_reason / worker_id / lease_expires_at / phase / progress_percent`。`WAITING_RESOURCE` 是真实 `QUEUED + resource_waiting` 的只读投影，不改变 Scheduler 可调度语义。product `{TASK_API_PRODUCT}`，focused run `{TASK_API_RUN}`，cleanup `{TASK_API_CLEANUP}`。\n- **Storage Import 已接统一进度**：执行期间从 v62 Task Truth 读取排队、等待资源、阶段、百分比、当前项、Worker；完成后只回业务 API 读取最终扫描结果。product `{STORAGE_PRODUCT}`，focused run `{STORAGE_RUN}`，cleanup `{STORAGE_CLEANUP}`。\n- **Training durable queue truth 已接 UI**：不增加第二个请求；现有 `/jobs` durable overlay 直接带出 `WAITING_RESOURCE / resource_queue_position / wait reason / worker / lease / progress`，训练列表显示真实队列和执行节点。product `{TRAINING_PRODUCT}`，focused run `{TRAINING_RUN}`，cleanup `{TRAINING_CLEANUP}`。\n\n**下一批：Unified Task Progress Phase 2。** 优先把 AI 标注/清洗/模型转换等现有 durable task 的页面状态统一到同一 Task Truth；之后再评估 SSE/event stream。不得重写现有 Scheduler/lease/GPU admission；现有 durable queue 已是真实执行底座。\n\n'''

for path in ['AGENTS.md','docs/CODEX_CURRENT_STATE.md']:
    p=Path(path)
    text=p.read_text(encoding='utf-8')
    text=text.replace('app.js cache:                42.25.93','app.js cache:                42.25.94')
    text=text.replace('main.mjs cache:              42.25.89','main.mjs cache:              42.25.91')
    if '### 当前产品主线 — Deployment E2E + Unified Task Progress Phase 1' not in text:
        if path == 'AGENTS.md':
            anchor='### R20n — shadowed Model Config generations retirement CLOSED / 技术债主线暂停\n'
        else:
            anchor='### R20n — shadowed Model Config generations retirement CLOSED / 技术债主线暂停\n'
        if anchor not in text:
            raise SystemExit(f'{path}: product section anchor missing')
        text=text.replace(anchor,section+anchor,1)
    if path.endswith('CODEX_CURRENT_STATE.md'):
        old='''TECH-DEBT CLEANUP PAUSED BY USER REQUEST\n→ resume only for real functional/performance/data-integrity/release-blocking evidence\n→ Unified Task Progress + Durable Queue Runtime productionization (product work, when requested)\n→ Navigation Action Fencing final scan DEFERRED unless a real stale-async defect appears'''
        new='''TECH-DEBT CLEANUP PAUSED BY USER REQUEST\n→ PRODUCT MAINLINE: Deployment Artifact E2E CLOSED\n→ Unified Task Progress Phase 1 CLOSED (public truth + Storage Import + Training UI)\n→ NEXT: Unified Task Progress Phase 2 (AI annotation / cleaning / conversion), then event-stream evaluation\n→ non-blocking Navigation Action Fencing final scan remains DEFERRED'''
        if old in text:
            text=text.replace(old,new,1)
    p.write_text(text,encoding='utf-8')

print('product phase handoff synchronized')
