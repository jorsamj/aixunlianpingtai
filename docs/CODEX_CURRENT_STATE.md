# Codex Current State — v42.25 Runtime

> 这是当前开发分支的**第一入口交接文件**。后续 Codex / ChatGPT / 人工开发接手时，先读本文件，再读根目录 `AGENTS.md` 中列出的专项设计。
>
> 本记录覆盖代码状态至 `ea4c08065d58ec24c233535ecb41c809b389f691`（后续若只有 handoff 文档提交，代码状态仍以该提交为基准）。接手前必须执行 `git branch --show-current`、`git rev-parse HEAD`、`git log --oneline -20`，不要只依赖本文 SHA。

## 1. 仓库与环境

- 仓库：`jorsamj/aixunlianpingtai`
- 稳定主分支：`main`
- 当前开发分支：`refactor/v42.25-runtime`
- v42.25 基线：`main@01636b61780361dde91c12ac2732f46d2289b6be`
- **不要在未明确授权时合并 main。**
- README / VERSION 仍保持正式版 `42.24.0`；当前前端开发标识显示 `v42.25.0-dev`。

生产/验收服务器：

```text
Ubuntu 22.04
16 CPU
约 32 GB RAM
NVIDIA A800-SXM4-40GB
代码目录：/data/platform/aixunlianpingtai
数据目录：/data/platform-data
Conda：mc-platform
YOLO Python：/home/vipuser/miniconda3/envs/yolo/bin/python
Torch：2.5.0+cu124
CUDA：12.4
```

Windows 仍是主要开发/普通测试环境，正式训练统一 NVIDIA Linux。代码必须跨平台，禁止写死盘符、反斜杠路径、Windows-only shell / process 调用。

---

## 2. 当前整体架构判断

当前不是经典“完全前后端工程分仓”，而是：

```text
前端逻辑分离 + 同仓部署 + 后台异步 Worker 服务化
```

目标方向：

```text
Browser
  ↓ HTTP/JSON
Web/API
  ↓
Task Runtime
  ├─ Import Worker
  ├─ Cleaning Worker
  ├─ Annotation Worker
  ├─ Video Worker
  ├─ Training Worker
  ├─ Conversion Worker
  └─ Deployment/Final Evaluation Worker
```

当前阶段**不要为了形式上的前后端分离做大重构**。优先保证训练正确性、Task Runtime 唯一执行、真实 A800 可训练、页面稳定、生产安全。

---

## 3. v42.25 已完成的核心工作

### 3.1 Training Data Contract / 防泄漏切分

核心文件：

- `platform_core/training_splits.py`
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`

核心合同：

- same SHA + same normalized GT：本次训练 canonicalize，重复素材 ID 进入 `excluded_duplicate_ids`，不删除素材库记录。
- same SHA + different normalized GT：训练前 `duplicate_annotation_conflict`，禁止 keep-first / keep-latest。
- Train/Test 如果显式选到相同 SHA，必须拒绝。
- 使用 union-find 构建不可拆分 Component，关系包括 SHA、file identity、group/video/source/near-duplicate/sequence、camera session 等。
- `camera_id` 单独不能作为长期不可拆分关系，必须与 session 组合。
- AnnotationRepository 是 Ground Truth authority，MaterialRepository 只是 searchable projection。
- Snapshot schema v3 锁定 annotation state/scope/hash、SHA、split role、duplicate audit。

设计文档：

- `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md`

### 3.2 Negative Sample Contract

语义必须严格区分：

```text
unannotated      -> 未确认 GT -> 不可训练
annotated        -> 有正式框 -> 可训练
confirmed_empty  -> 明确确认无目标 -> 合法负样本
```

核心要求：

- `confirmed_empty` 即使 `box_count=0` 仍是正式已标注素材。
- `annotation_scope` 是 Ground Truth 的一部分。
- 新 `confirmed_empty` 无显式 scope 时优先冻结当时 active label codes；历史 `['*']` 仅为兼容。
- Snapshot 必须把 `*` 解析到 locked algorithm schema。
- partial negative scope 未覆盖算法全部 locked labels 时，不得被当作全类负样本。
- portable YOLO 中合法负样本生成真实 0-byte `.txt`。
- 普通 0 框保存不能静默变成负样本；前端必须显式“确认无目标”。

相关文件：

- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`
- `static/modules/annotation.js`
- `static/modules/negative-samples.js`
- `static/main.mjs`
- `tests/unit/test_negative_sample_contract.py`

设计文档：

- `docs/superpowers/specs/2026-09-11-negative-sample-contract.md`

### 3.3 Task Runtime Execution Fencing

目标：解决 Worker lease 丢失后旧 execution 仍运行、第二个 Worker 又 claim 同任务的重复执行窗口。

已实现：

- persisted execution `attempt/generation`
- lease token + generation ownership 校验
- heartbeat / bind_process / finish generation-aware
- PID + create_time + command hash 进程身份验证
- 无法确认进程身份时 fail closed
- expired live exact process 不 requeue
- recovery-hold resource fence
- GPU reservation quarantine
- lease loss 后禁止旧 execution 发布正式 artifact / finish
- process tree 终止
- FencedArtifactStore 在写入前后做 execution ownership 检查

核心文件：

- `platform_core/task_runtime/fenced_repository.py`
- `platform_core/task_runtime/process_control.py`
- `platform_core/task_runtime/worker.py`
- `platform_core/task_runtime/scheduler.py`
- `platform_core/deployment/conversion_tasks.py`
- `task_worker.py`

设计文档：

- `docs/superpowers/specs/2026-09-11-v42.25-task-runtime-fencing-design.md`

### 3.4 Training Resource Contract

真实 A800 曾出现用户配置：

```text
batch=16
workers=4
cache=false
device=0
```

但 Ultralytics 实际收到：

```text
batch=64
workers=4
cache=disk
device=0
```

根因是平台 auto resource resolver 覆盖了显式参数。

已修复 `platform_core/training_metrics.py`：

- 显式正整数 batch：Auto 只允许安全下调，禁止上调。
- `batch=-1` 才是用户明确委托自动 batch。
- `cache=false` 是硬关闭，Auto 不得改成 disk/ram。
- workers 不得被 Auto 增加，`workers=0` 必须保持 0。
- 生成 `resolved-resources.json`，记录 requested / effective / adjustment reason。
- `TrainingMetrics.on_train_start()` 对照 Ultralytics Trainer 实际值，不一致时报 `RESOURCE_RUNTIME_MISMATCH`。

设计文档：

- `docs/superpowers/specs/2026-09-11-training-resource-contract-fix.md`

### 3.5 Task-scoped Algorithm Label Contract

这是当前非常重要的业务合同。

**项目标签库 != 算法 label schema。**

首次训练：

- 可选标签只能来自本次精确已选训练素材。
- 用户必须在创建训练任务时明确选择至少一个标签。
- 母模型 / pretrained model 自带类别绝不自动继承。
- 算法 class_id 是 task/model-local，首次训练连续重排为 `0..N-1`。

例如项目标签库：

```text
fire, smoke, person, helmet, cigarette
```

本次素材包含：

```text
fire, smoke, person
```

用户只选：

```text
fire, smoke
```

则 portable `data.yaml` 必须只有：

```yaml
names:
  0: fire
  1: smoke
```

期望 Ultralytics：`nc=2`，绝不能是 5。

迭代训练：

- 自动继承上一**成功且可继续训练**版本的 `label_schema`。
- inherited labels 不可普通取消。
- 新素材里的新标签必须用户明确勾选才追加。
- 旧 class_id 不得重排，新类别只能 append。
- 历史版本缺 `label_schema` 时，只允许从旧 task `snapshot.json` 恢复；无法恢复必须 fail closed。
- 新版本持久化 `label_schema`、`label_codes`、`label_contract`。

投影约束：

- 未选类别的框可从本 task projection 里过滤。
- 但如果过滤后正样本变成 0 框，不得静默转成假负样本，必须拒绝并要求正式 `confirmed_empty`。

后端：

- `platform_core/training_label_tasks.py`
- `platform_core/worker_registry.py`

前端现有实现层：

- `static/modules/training-labels.js`
- `static/training-label-bootstrap.js`
- `static/training-label-v3-anchor.js`
- `static/main.mjs`

测试：

- `tests/unit/test_training_label_contract.py`
- `tests/frontend/training-labels.test.mjs`
- `tests/browser/training-label-selector.spec.mjs`

设计文档：

- `docs/superpowers/specs/2026-09-11-training-label-contract.md`

### 3.6 Navigation Stability / 页面乱跳

用户反馈：点击“训练任务”等页面后会莫名跳到其他页面，像重新加载。

根因：旧 `app.js` 内大量历史 override 和异步 render。典型竞态：

```text
旧页面 await 请求
→ 用户已经切到新页面
→ 旧请求返回
→ 旧 renderXxx() 无条件覆盖 #view
```

新增：

- `static/modules/navigation-stability.js`
- `tests/frontend/navigation-stability.test.mjs`

合同：

- `state.page` 是当前页面唯一权威。
- 页面切换推进 navigation epoch。
- 异步操作返回时 epoch 已变化则视为 stale，不得永久覆盖当前页面。
- 离页清理已知页面轮询。
- 后续新页面禁止 `await ...; renderXxx()` 无 ownership 校验。

设计文档：

- `docs/superpowers/specs/2026-09-11-navigation-stability.md`

---

## 4. 当前前端标签 UI 的真实状态（重要）

### 4.1 为什么前几版“后端要求标签，但前端没地方选”

仓库旧前端是一个长期叠加 override 的经典脚本体系，`static/app.js` 很大，训练弹窗经历过多层版本覆盖：

```text
train425 / train428 / train429 / final train-v3
```

最初 `training-labels.js` 只挂到了历史训练 UI，因此后端合同已经生效，但用户在最终窗口没有选择入口。

后来增加 classic-script 层：

- `static/training-label-bootstrap.js`
- `static/training-label-v3-anchor.js`

让它直接与最终 `app.js` 训练窗口工作，而不完全依赖 ES Module 初始化链。

`static/index.html` 当前会加载：

```text
training-label-bootstrap.js
training-label-v3-anchor.js
main.mjs
```

### 4.2 最近一次“点击训练直接卡死”事故

用户反馈：点击算法“训练”按钮后，整个页面直接卡死。

根因已确认：`training-label-v3-anchor.js` 的 MutationObserver 对所有子节点变化执行 `sync()`，而 `sync()` 又无条件调用 `TrainingLabelRuntime.refresh()`；`refresh()` 重写标签面板 `innerHTML`，从而再次触发 Observer，形成自激循环。

已在代码提交 `275e0434b747b276c1bbe928774baecc52328752` / cache-bust `ea4c08065d58ec24c233535ecb41c809b389f691` 热修：

- Observer 忽略标签面板自身变化；
- 对 training panel + algorithm + selected material ids 建 signature；
- signature 未变化且标签面板仍存在时不再重复 refresh；
- 只有训练面板重建、算法变化、所选素材变化、标签面板丢失时才刷新。

**当前用户尚未对这个 hotfix 做完真实浏览器复验。**

接手者第一件前端事情：

1. 部署最新 `refactor/v42.25-runtime`；
2. 浏览器强刷 / 新标签页打开；
3. 点击算法“训练”；
4. 确认不再卡死；
5. 确认训练窗口出现“本次训练标签”；
6. 选择素材后出现素材真实标签复选框；
7. 取消某标签后发起训练，确认 `/api/v12/projects/.../train/start` 的 `train_labels` 正确。

### 4.3 不要误报浏览器测试状态

- Node/frontend 定向测试对 training label / navigation 逻辑已有通过记录。
- Python training-path 定向测试已有 61/61 通过记录。
- 有一轮真实 Chrome 证明训练窗口能出现 `#trainingLabelContractPanel` / “本次训练标签 / 请先选择训练素材”。
- 但新增 Playwright 的完整“打开最终窗口 → 真选材 → 取消标签 → 提交请求”链路**尚未稳定全绿**，因为旧 `app.js` 多层训练 UI override 在测试环境里仍存在差异。
- 所以不得写“浏览器 E2E 已完全通过”。

---

## 5. 已执行的验证证据

### Training Label / Training Path 定向 Linux CI

已完成过：

```text
frontend: 7 passed / 0 failed
Python: 61 passed
```

覆盖包括：

- training label contract
- negative sample contract
- annotation scope
- training splits/components
- snapshots
- portable dataset
- resource contract
- launcher workers
- task worker integration subset

这不是 full repo regression。

### Navigation Stability 定向前端测试

曾执行并通过 navigation stability + training-label frontend 组合测试（10 tests 全部通过）。

### 尚未完成

- **FULL REPO REGRESSION NOT VERIFIED**
- **A800 REAL TRAINING WITH CURRENT LABEL CONTRACT NOT VERIFIED**
- **CURRENT TRAINING-LABEL HOTFIX REAL BROWSER REVALIDATION NOT VERIFIED**

---

## 6. A800 下一步验收清单（P0）

不要先做大重构。当前最优先把 v42.25 训练链闭环。

用小轮数 canary，例如：

```text
device = 0
batch = 16
workers = 4
cache = false
epochs = 3~5
```

如果精确已选素材有 `fire/smoke/person`，用户只选 `fire/smoke`，必须验证：

1. `label-contract.json`：effective labels 只有 fire/smoke；
2. `snapshot.json`：label_schema 只有 fire/smoke；
3. portable `dataset/data.yaml`：names 只有 fire/smoke；
4. Ultralytics 实际日志：`nc=2`；
5. `resolved-resources.json`：batch/workers/cache 实际为 `16/4/false`；
6. Trainer 实际参数同样是 `16/4/false`；
7. confirmed_empty 在 YOLO bundle 中生成真实空 `.txt`；
8. Train/Validation/Test 没有 SHA / Component leakage；
9. 成功版本写回 `label_schema / label_codes / label_contract`；
10. 再创建迭代任务，旧标签继承且 class_id 不重排，新标签只有明确勾选后 append。

如果仍出现：

```text
Pin memory thread exited unexpectedly
```

再检查：

- kernel/cgroup OOM
- `/dev/shm`
- DataLoader worker crash
- pinned memory / RAM

`workers=0` 只可作为诊断手段，不能成为全平台永久默认修复。

---

## 7. 当前生产部署方式

用户当前明确采用**原部署目录直接更新**，不是 worktree 并行验收。

代码：

```text
/data/platform/aixunlianpingtai
```

数据：

```text
/data/platform-data
```

更新开发分支：

```bash
cd /data/platform/aixunlianpingtai
git fetch origin
git switch refactor/v42.25-runtime
git reset --hard origin/refactor/v42.25-runtime
```

前端修改后通常只需重启 Web；Task Runtime / Python worker 代码变化时 Web + Worker 都重启。

Web：

```bash
conda activate mc-platform
export MC_TRAIN_DATA_DIR=/data/platform-data
export MC_DATA_DIR=/data/platform-data
nohup python -m uvicorn app:app --host 0.0.0.0 --port 8010 \
  > /data/platform-data/logs/web.log 2>&1 &
```

Worker：

```bash
nohup python task_worker.py \
  --data-dir /data/platform-data \
  --roles all \
  --worker-id "$(hostname)-prod-all-default" \
  > /data/platform-data/logs/worker.log 2>&1 &
```

注意：不要同时运行旧 Worker 与新 Worker 指向同一个 `/data/platform-data`。

---

## 8. 当前已知未收口事项

P0/P1：

- 当前 training-label hotfix 需要用户真实浏览器复验。
- A800 label contract + resource contract + negative samples 需要真实训练闭环。
- 全仓 pytest / Playwright 还没有做完整回归。
- `AnnotationSave` API model 尚未把 `annotation_state / scope` 做成完全显式的新 API 合同；目前部分行为依赖 repository/default 与前端保护。
- YOLO import 的空 TXT scope 目前按项目 active labels 冻结，不一定等同外部数据集精确 label mapping；安全但语义仍可进一步收紧。
- 正样本 annotated image 的 scope 仍主要来自实际 boxes；尚未要求每张正样本显式证明“其他类不存在”。不要宣称已解决所有 multi-class absence verification。

后续大批：

- 生产安全：移除广泛 `/data` 静态暴露、CORS 收紧、SSRF 防护、SecretStore、受控 artifact/download API、基础认证权限。
- Worker 真正独立部署：API server 与 GPU Training Worker 可分机。
- algorithms/version persistence 逐步 SQLite 化。
- 前端工程化：停止继续把版本 override 堆进巨型 `static/app.js`；v42.25 稳定后再拆 router/store/service/page modules，之后再评估 Vue/React/Vite，不要现在大重写。

---

## 9. 不得回退的开发规则

- 不得为了旧测试绿灯回退已经确认的正确业务语义。
- 不得把项目标签库重新等同算法 schema。
- 不得让母模型类别混进首次训练 schema。
- 不得让 `confirmed_empty` 再被当成未标注。
- 不得在过滤未选标签后把正样本静默变成负样本。
- 不得让旧 Worker / stale execution 在 lease 丢失后 finish 或发布 artifact。
- 不得让 Auto resource strategy 增大显式 batch/workers 或打开显式关闭的 cache。
- 不得让 stale async render 抢占当前页面。
- 不得继续用无限 MutationObserver + 无条件 innerHTML 重绘的方式做训练 UI 挂载。
- 不得在未真实验证时写“生产已验收 / E2E 已通过 / A800 已通过”。
- 未经用户明确指令，不得合并 `main`。

---

## 10. 接手动作

Codex 接手后先执行：

```bash
git branch --show-current
git rev-parse HEAD
git status
git log --oneline -20
git diff main...HEAD --stat
```

然后按顺序阅读：

1. `docs/CODEX_CURRENT_STATE.md`（本文件）
2. `AGENTS.md`
3. `docs/codex-handoff-v42.25.md`
4. 与当前任务相关的 `docs/superpowers/specs/*.md`

如果当前任务涉及训练 UI，先阅读：

- `static/app.js` 最终 train-v3 override 段
- `static/training-label-bootstrap.js`
- `static/training-label-v3-anchor.js`
- `static/modules/training-labels.js`
- `static/modules/navigation-stability.js`

如果涉及训练 Worker，先阅读：

- `platform_core/training_label_tasks.py`
- `platform_core/training_metrics.py`
- `platform_core/training_splits.py`
- `platform_core/snapshots.py`
- `platform_core/task_runtime/*`
- `platform_core/worker_registry.py`

最后原则：**先验证当前合同，再修改；每批改动都更新本文件或新增对应 spec，不能让交接再次依赖聊天记录。**
