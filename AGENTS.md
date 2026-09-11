# Repository Agent Handoff

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前，先确认当前分支并读取对应交接文档，不要只根据 README 的正式版本号推断开发状态。

## 必读顺序

1. `docs/codex-handoff.md` — v42.24 及更早历史、产品约束、已知未验证事项。
2. `docs/codex-handoff-v42.25.md` — 当前 `refactor/v42.25-runtime` 增量接管状态。
3. `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md` — v42.25 第一批训练数据合同设计。
4. `docs/superpowers/specs/2026-09-11-v42.25-task-runtime-fencing-design.md` — 第二批 Task Runtime fencing 设计。
5. `docs/superpowers/specs/2026-09-11-training-resource-contract-fix.md` — 2026-09-11 真实 A800 训练暴露的 batch/cache 参数覆盖事故与修复合同。
6. `docs/superpowers/specs/2026-09-11-negative-sample-contract.md` — `confirmed_empty`、负样本 scope、YOLO 空标签、前端确认动作与训练约束。
7. `docs/superpowers/specs/2026-09-11-training-label-contract.md` — 训练任务标签选择、上一版本继承、母模型标签隔离、task-local class_id 合同。
8. `docs/superpowers/specs/2026-09-11-navigation-stability.md` — 页面 navigation epoch、过期异步渲染 fencing、页面轮询生命周期合同。
9. 对当前工作先执行 `git diff main...HEAD` / `git log main..HEAD`，不要假设 handoff 已覆盖最后一个 commit。

## 当前开发状态

- 稳定主分支：`main`
- 当前 v42.25 开发分支：`refactor/v42.25-runtime`
- v42.25 基线：`main@01636b61780361dde91c12ac2732f46d2289b6be`
- README / VERSION 仍是 `42.24.0`，因为 v42.25 尚未正式发布。
- v42.25 第一批训练数据合同已实现。
- v42.25 第二批 Task Runtime fencing 已实现，并通过定向 Linux GitHub Actions；**FULL REGRESSION NOT VERIFIED / A800 REAL TRAINING NOT VERIFIED**。
- 训练资源参数覆盖修复已通过定向 Linux CI，但修复后的 A800 实际训练仍需重新验证。
- 负样本合同已补齐并通过定向 Linux CI：`confirmed_empty` 可训练、scope 锁定、部分 scope 拒绝、空 YOLO label 落盘、0 框 UI 显式确认均已覆盖；A800 真实训练仍需回归。
- 训练任务级 Label Contract 已实现并通过定向 Linux CI：前端 7/7、Python 61/61；项目全部 active labels 不再作为算法 schema，A800 真实训练仍需确认 Ultralytics 实际 `nc/names`。
- 页面 Navigation Stability fencing 已实现并通过定向 Linux CI：页面切换采用 navigation epoch；旧页面异步任务返回后不得永久覆盖当前页面；离页时清理已知页面级轮询。
- 未完成真实环境验证前不要合并 main，也不要把 v42.25 描述成生产已验收。

## 不得回退的核心合同

- 训练任务继续按精确 `train_image_ids / test_image_ids` 工作，不恢复“数据集分组”作为训练合同。
- Windows 开发与 NVIDIA Linux 生产必须共用跨平台代码，禁止写死盘符、反斜杠路径或 Windows-only shell 流程。
- 已有素材、标注、算法版本不得因升级被清空、移动或重新编号。
- AnnotationRepository 是 Ground Truth authority；MaterialRepository 中标注字段只是 searchable projection。
- `unannotated`、`annotated`、`confirmed_empty` 是不同语义；`confirmed_empty` 是合法负样本。
- `annotation_scope` 属于 Ground Truth 与 Training Snapshot 合同，不得只保存 boxes。
- 新 `confirmed_empty` 在没有显式 scope 时优先冻结确认当时的 active label codes；历史 `*` 只作为兼容语义，Snapshot 必须解析成当前 locked schema。
- YOLO 空 `.txt` 表示“locked schema 中所有类别均不存在”；只确认了部分标签为空的样本不得作为整个多分类算法的空标签训练。
- 普通 0 框保存不得静默创建负样本；前端必须通过“确认无目标”显式确认。
- `confirmed_empty` 即使 `box_count=0` 仍属于正式已标注素材，训练素材池不得因此过滤掉。
- 项目标签库只是可用业务标签目录，**绝不等于某一个算法的 label schema**。
- 首次训练的算法标签只能来自本次精确已选素材，并由用户在创建训练任务时明确选择；母算法/预训练模型自身类别一律不继承。
- 版本迭代必须继承上一成功、可训练算法版本的 `label_schema`；本次素材中新标签只有用户明确选择后才能追加。
- 历史版本缺少 `label_schema` 时只允许从该版本训练任务的 `snapshot.json` 恢复；无法恢复必须 fail closed，禁止从项目全标签、当前素材或母模型猜测。
- 算法 `class_id` 是 task/model-local 身份：首次训练必须连续 `0..N-1`；迭代时旧 class_id 不得重排，新类别只能追加。
- 过滤掉未选择的其他类别框后，如果一张正样本没有任何本次有效框，不得静默当成负样本；必须拒绝并要求显式“确认无目标”。
- Snapshot 与 Portable `data.yaml names` 必须只包含本次有效算法 schema；项目有 5 标签而本次只选 2 标签时，Ultralytics 应得到 `nc=2`。
- same SHA + same normalized GT：训练时 canonicalize，不删除素材记录。
- same SHA + different normalized GT：必须 `duplicate_annotation_conflict`，不得 keep-first / keep-latest / 随机选择。
- Train / Validation / Test 必须按不可拆分 Component 划分，并保留最终 leakage guard。
- 有稳定 label/code 时，重复标注语义优先使用稳定 code，不把历史 class_id 当永久身份。
- Training Snapshot v3 必须保留 annotation state/scope/hash 和 duplicate exclusion audit。
- Task Runtime 的旧 execution 在 lease/generation 失效后不得继续 finish、发布正式 artifact 或与新 execution 并发占同一资源。
- 进程恢复必须用 PID + create_time + command hash 证明身份；无法证明时 fail closed。
- 显式正整数 `batch` 是 Auto 资源策略的硬上限：Auto 只可安全下调，不得上调。
- `batch=-1` 才表示用户明确委托平台自动选择 batch。
- `cache=false` 是权威关闭，Auto 不得隐式改成 disk/ram。
- Auto 不得增加用户指定的 DataLoader workers；`workers=0` 必须保持单进程加载。
- `state.page` 是浏览器当前页面唯一权威；页面切换必须推进 navigation epoch。
- 任一页面异步操作在 `await` 后如发现 navigation epoch 已变化，必须视为 stale；不得用旧页面结果永久覆盖当前 `#view`。
- 页面级轮询必须随页面生命周期清理；后台状态刷新优先更新局部 DOM，不得周期性整页重绘造成表单、滚动位置和选择状态丢失。
- 新页面不得继续通过“异步请求完成后无条件 `renderXxx()`”的方式抢占路由；需要遵守 navigation ownership。

## v42.25 主要实现位置

训练数据合同：

- `platform_core/training_splits.py`
- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`

负样本合同：

- `platform_core/annotation_repository.py`
- `platform_core/snapshots.py`
- `platform_core/training_tasks.py`
- `static/modules/annotation.js`
- `static/modules/negative-samples.js`
- `static/main.mjs`
- `tests/unit/test_negative_sample_contract.py`

训练任务标签合同：

- `platform_core/training_label_tasks.py`
- `platform_core/worker_registry.py`
- `static/modules/training-labels.js`
- `static/main.mjs`
- `tests/unit/test_training_label_contract.py`
- `tests/frontend/training-labels.test.mjs`

页面导航稳定性：

- `static/modules/navigation-stability.js`
- `static/main.mjs`
- `tests/frontend/navigation-stability.test.mjs`

Task Runtime fencing：

- `platform_core/task_runtime/fenced_repository.py`
- `platform_core/task_runtime/process_control.py`
- `platform_core/task_runtime/worker.py`
- `platform_core/task_runtime/scheduler.py`
- `platform_core/deployment/conversion_tasks.py`
- `task_worker.py`

训练资源合同：

- `platform_core/training_metrics.py`
- `tests/unit/test_training_resource_contract.py`

## 当前后续优先级

1. 用 A800 对当前训练链做真实重跑：确认 `batch=16/workers=4/cache=false` 最终仍是 `16/4/false`；选择 `fire/smoke` 时 Snapshot 和 `data.yaml` 只有 2 类、Ultralytics 日志为 `nc=2`；负样本生成真实空 `.txt`。
2. 在真实浏览器连续快速切换“训练任务 / 数据集 / 自动标注 / 素材接入”等页面，并在训练任务刷新、暂停、继续请求未返回时立即切页，确认旧请求不会再把页面盖回去；同时检查滚动位置、表单和选择状态没有被后台轮询周期性重置。
3. 完成一个真实训练版本后再次创建迭代任务，确认上一版本 `fire=0/smoke=1` 自动继承；新增标签只有用户明确勾选才追加且旧 class_id 不重排。
4. 若仍出现 `Pin memory thread exited unexpectedly`，再单独检查 kernel/cgroup OOM、`/dev/shm`、DataLoader worker/pinned memory，不得用全平台强制 `workers=0` 掩盖问题。
5. 下一大批做生产安全：`/data` 静态暴露、CORS、SSRF、训练服务器 SecretStore。

## 修改与交接要求

- 每批修改保持边界清晰，不把无关重构混入同一批。
- 代码修改同时补对应回归测试。
- 测试没有真实执行时必须明确写 `NOT VERIFIED`，不能用“测试文件已新增”代替“测试已通过”。
- 完成一批后同步更新当前 handoff；新架构决策写入 `docs/superpowers/specs/`，实施步骤可写入 `docs/superpowers/plans/`。
- 若旧测试锁定的是已经确认错误的旧语义，先更新测试合同，不要为了绿灯回退正确行为。
