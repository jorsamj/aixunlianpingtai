# 训练重复冲突、标注工作台与素材治理闭环验收

日期：2026-10-18。基线：`5a28e4539b81c03b4eaa27fa4b6c718138542169`。
本地运行条件：Windows、Python 3.12.7、Node 24.19.0、本机真实 Chrome（Playwright channel=chrome，单 Worker）。
隔离工作树：`C:/Users/jorsam/.codex/worktrees/training-failure-diagnostics/畅联云算法训练_v42.14.0`。
原开发阶段仅本地开发/测试/提交。用户现已授权普通 Fast-forward 推送与 CI 修复验收；仍不部署、不连接生产、不改正式 VERSION。

## 本阶段追加：推送前独立复核

- 首轮 `edee5fb6fcd32812ee62b0197728dc7ab51d8b0f` CI 发现恢复/素材选择 Chrome build 断言与实际资源不一致，以及新接入 Hardening 守卫锁定退役的注册模块。最小修复只同步精确版本和真实 Production→CheckpointResume→Recovery 继承合同，并增强真实注册对象断言；恢复 Chrome 5/5、素材选择 Chrome 2/2、Node 982/982、两个原始 Bash 永久守卫通过。扩展 Windows 测试的 14 项长路径失败在短 basetemp 消失（19 passed/1 Linux-only skipped）；另 1 项 manual workers=8 与既有 Windows 上限4冲突，不改生产资源保护；相同未变源码的 Ubuntu 124项已实际通过。最终 SHA 仍需重新完整 CI。
- 首轮失败日志：Training Recovery Chrome Job `117553998395`、恢复永久守卫 `117553998620`、Picker Chrome `117553998540`、Hardening `117553998440`。后者实际 Python `124 passed` 后在第一个过期静态 guard 退出；修复仍要求正式 Production Handler 继承 Recovery，不绕过恢复逻辑。
- Windows 扩展首跑 `105 passed/15 failed/4 skipped`，原始日志 `p0-ci-hardening-python-20261018.log`；短路径 cache/注册复测 `19 passed/1 skipped`，日志 `p0-ci-windows-shortpath-20261018.log`。不把失败/跳过计入成功，不将该额外 Windows 组合冒充全绿。
- 完整代码提交 `5d3ad65bf7ff287521481a2ac6bfbd1f7caed52e` 的父提交与新 fetch 远端一致：`5a28e4539b81c03b4eaa27fa4b6c718138542169`，不存在分叉；42 个原变更文件属于本轮闭环。
- 发现固定 Benchmark 复用时服务端注入的 Test 身份与客户端原始 duplicate_review 角色不一致，正常排除会被拒绝，客户端伪造已注入 Test 的合同反而被接受。真实 API 先复现 3 failed/3 passed；最小修复复用既有 Benchmark resolver 与角色/revision 校验，保留原 admission_request，禁止排除固定 Test 及保留同 SHA 别名，不向公开响应暴露 Test ID。9 场景及相关 Python 109 passed。
- Release Regression 与 Training Final Validation Hardening 原来只监听旧分支；已加入长期分支，并补 Release 源码/测试路径，Node 先 RED 后 GREEN。全量 Node 981 passed。没有跳过或降低安全测试。
- 本阶段真实 Chrome 再跑训练冲突与素材治理两份规格：6 passed / 0 failed / 0 skipped，1.6 分钟；包含真实准入、GT 修改、过期 revision、全保护零删除及实际隔离 Worker 删除闭环。日志 `C:/Users/jorsam/.codex/tmp/p0-ci-chrome-final-20261018.log`。
- 本阶段最终远端 SHA、完整 Actions/Jobs、Chrome 及生产风险交接在 `C:/Users/jorsam/.codex/visualizations/2026/10/18/training-conflict-p0/CI_FINAL_HANDOFF.md`。此阶段提交前尚未运行远端 CI，必须以该报告的最终 SHA 实际结果为准。

## 根因及处理

1. 旧训练兼容性主要核对任务标签范围，重复冲突直到构建 split 时才暴露；任务标签投影还能掩盖原始 GT 差异。现在沿用 `training_annotation_digest`，在兼容性、准入、准备和冻结入口检查原始正式 GT，同 SHA 的类别、坐标、范围及状态差异逐图分页返回；Train/Test 同 SHA 泄漏优先拒绝。
2. 用户以前只能尝试删除历史重复素材。现在同一诊断页对比真实 Content API 图片及正式标注，进入既有标注工作台人工修正，返回后重新预检；或明确确认只排除本次新训练的一条身份。排除记录保存原始 Train/Test ID、排除项及双 revision，服务端验证范围和角色；不允许通过排除掩盖原始 Train/Test 泄漏。历史证据和当前 GT 分开显示。
3. FAILED/no-freeze 的 payload 输入原本也参与保护集合，2531 张全受保护并不等于任务真的产生冻结证据。此次保留原保护集合，不批量解除 FAILED 保护；新增来源分类及 Task ID、是否记录 freeze、证据尚未复验的说明。零可删预览仍显示真实选中图片、保护数及核对入口，不生成执行删除按钮，不创建空删除任务。
4. 冻结前的 revision 检查不足以覆盖构建期间的 MaterialRepository 修改。已增加冻结结束的素材/标注 revision 复验，并在正式冻结及 artifact 发布时使用既有生命周期 fence；外部平台 HTTP 刷新不持有项目标注锁。Worker 失败留存结构化 input-preparation-error 和分页问题证据，不虚构 checkpoint 恢复。
5. 真实 Chrome 暴露素材路由内部还嵌套了一份未注入依赖的训练恢复路由，截获新诊断并返回 503。已删除嵌套挂载，app 中配置完整的唯一挂载保留；跨文件守卫先 RED 再 GREEN，并由真实 API 验证。
6. 历史 benchmark 复用任务同时记录 requested random split 和 effective independent split，诊断曾混用 ID 与 mode。已统一 requested 合同的 mode，并补稳定复现测试。
7. 重复联调发现低频的真实素材选择竞态：全选请求未返回就能确认空范围。已有素材选择 Owner 增加解析中确认锁和迟到结果归属检查；Chrome 延迟真实 bulk-selection 请求稳定 RED 后验证。不是只给测试添加等待，也没有新增选择 Owner。

## UI 与 Owner

- 现有 `TrainingMaterialSummaryRuntime` 负责训练预检、分页差异与失败诊断；`TrainingDraftRuntime` 是唯一新训练草稿；原 `TrainingSubmitRuntime` 负责最终一次提交，没有新增任务执行器、轮询器、GT 缓存 Owner。
- 标注工作台采用图片主区域、分组工具栏、右侧单一绘制类别和对象编辑；“未检查类别”默认折叠，展开不修改范围，只有显式选择并保存才写入。
- 桌面边距、移动端图片优先/检查区后置、44px 触达与 reduced-motion 沿用 UI/UX skill 的可达性和错误恢复原则。小图适应窗口最多 4 倍，大图按可用区域缩小；坐标仍按真实图片尺寸换算，100% 可恢复。
- 治理继续使用 MaterialBatch/DELETE_INDEX、原 Repository 和历史/Test 引用保护，不执行 DELETE_SOURCE。原删除失败保留选择、重复提交复用任务、删除完成审计失效、共享原始对象保留等合同继续回归。
- 正式 `VERSION.txt=42.24.356` 未改；app/main/styles 入口缓存键 `42.25.389`，涉及模块 import 与 build 同步，Recovery CI 静态守卫与实际引用一致。

## 自动化证据

完整命令和原始日志保存在 `C:/Users/jorsam/.codex/tmp/`：

| 范围 | 结果/日志 |
|---|---|
| Node 24 全量 frontend | 980 passed；`conflict-node-final-20261018.log` |
| Python 冲突、split、标签、恢复、分页、准备、训练 Worker | 131 passed；`conflict-backend-final-20261018.log` |
| Python 训练 API、挂载、治理、批量任务、Content、标注原子性与引用保护 | 115 passed；`conflict-api-final-20261018.log` |
| 准备集成：schema 3/4 真 Scheduler、外部刷新锁外/Benchmark/选择/冻结锁内 | 14 passed（计入上述131）；`conflict-backend-final-20261018.log` |
| 真实 Chrome 五份规格 | 24 passed，0 failed/0 skipped；`conflict-chrome-final-20261018.log` |

新增训练冲突闭环和全保护零删除用例使用独立临时后端仓库、正式 API 与真实 Content 字节；资源发现采用明确的 CPU 夹具。冲突闭环的新训练最终 POST 不被 mock，母模型为隔离生成的有效随机 YOLO `.pt`，只验证准入/持久任务，不声称已训练或 GPU 验证。没有下载预训练权重。既有布局、创建反馈和进度样式用例仍使用其明确的 API mock，不作为真实后台执行证据；真实删除完成由实际隔离 Scheduler/MaterialBatchHandler 用例和 API 测试证明。

覆盖映射：

- 原始 GT 相同与类别/坐标/范围/状态差异、跨角色 SHA、投影掩盖、畸形排除合同：`tests/unit/test_training_duplicate_conflicts.py`。
- 当前 GT 修改后重新预检、显式排除及持久 payload、revision 漂移拒绝、历史不回填：上述单元测试、`tests/api/test_training_request.py` 与 `tests/browser/training-duplicate-conflicts.spec.mjs`。
- 历史多引用、FAILED 有/无 freeze、活动任务、成功任务、模型/快照/Test：`tests/unit/test_material_reference_reasons.py` 和既有完整性/删除原子性测试。
- 全选/全筛选/跨页、组内 >100、排队再次提交、失败保留选择、成功失效审计、共享内容不删、非 4:3 与失败藏框：`tests/browser/material-integrity-governance.spec.mjs` 及 API 安全测试。
- 四视口 1920×1080、1440×900、1366×768、375×812；单一类别选择器、默认折叠、手动保存/切图/关闭、迟到响应、创建防重：`material-workflows`、`training-create-first-open`、`training-label-selector` Chrome 规格。

真实 SQLite/AnnotationRepository 批量写入后调用 canonical preflight，不再只测合成响应：最终一轮 100/1000/10000 张本地首次预检分别约 0.038/0.184/1.349 秒，第一页 24 条约 17.2KB（JSON 字符长度；夹具为 ASCII）。计时包含读取与计算，不含造数、不含 HTTP/TLS 或原图传输。该数字不是生产服务器 SLA，也不是浏览器渲染 10000 张图片；缓存页切换另有既有性能合同。

独立只读复核指出历史 split 与长锁两项 P2，缩锁后的进一步复核又发现 Benchmark GT 校验到 selection revision 捕获之间的 P1 窗口。现将 Benchmark、expected revision、选择解析至冻结发布置于同一把锁，外部 HTTP 仍在锁外；真实 Scheduler 回归断言三处锁边界，先 RED 后 GREEN。实际测试失败没有跳过或降低业务断言：修正保存状态确切文案、零删除弹窗标题、有效母模型与两类正样本、正式标注每批 500 上限的夹具；真实产品缺陷另作代码修复。

## 截图

实际截图目录：`C:/Users/jorsam/.codex/visualizations/2026/10/18/training-conflict-p0/`。

- `training-duplicate-conflic-fa170-d-rechecks-before-admission-comparison-desktop.png` / `comparison-mobile.png`：同 SHA 两份真实 GT。
- `training-duplicate-conflic-fa170-d-rechecks-before-admission-annotation-before.png` / `annotation-after.png` / `precheck-resolved.png`：修复闭环。
- `material-workflows-image-f-193ab-ed-review-at-every-viewport-annotation-workspace-1366.png` / `annotation-workspace-375.png`：工作台。
- `material-integrity-governa-79579-nd-preserves-shared-content-protected-zero-delete-desktop.png` / `protected-zero-delete-mobile.png`：全部保护、0 删除及入口。
- `material-integrity-evidence-delete-queued.png` / `delete-running.png` / `delete-succeeded.png`：持久删除真实 Worker。

## 生产边界及只读验收

最终独立复核确认 Benchmark/选择/冻结并发窗口关闭，素材选择 busy/归属补丁未发现 P0/P1 风险。本地必要回归全部通过；这不是对全仓库所有测试、生产数据或远端 CI 的通过声明。

未连接生产；现场 2531 张/1041 组及 SHA `0dcb43b6fa1c0678d1c4094c93403678aae9cbaac28419c2fbf4cfd9120c5e9e`、图片 `57512edb455f4b16` / `11916bbdb5c64595` 的具体历史 Task、GT 与物理对象尚未核验，不能宣称已修复生产数据或证实两次现场删除数量。

取得单独授权后，先只读：获取现场 project/task ID；查询既有 material-batches 详情/日志、audit groups/items、训练 input-diagnosis、annotation 与 Content API；记录 payload/input-freeze/Snapshot/Test/模型评测引用来源及 revision/SHA，区分当前 GT 和冻结证据。先验证只读图像/诊断，再由用户决定是否修改合法当前 GT 或新训练选择。不得再次删除生产素材来“复现”，不得清空 FAILED 记录解锁删除。

本轮 GitHub Actions/Linux、真实生产 OSS/S3 历史对象、GPU/A800 训练、实际大库并发与外部平台网络仍为 NOT VERIFIED。现有 Frontend/Release 工作流已接入新增测试，尚未推送或执行，不能沿用旧 SHA CI。是否推送和生产部署均等待用户分别授权。

## 实际修改文件

- `.github/workflows/frontend-runtime-stabilization.yml`
- `.github/workflows/training-recovery-guard.yml`
- `.github/workflows/v42.25-release-regression.yml`
- `AGENTS.md`
- `app.py`
- `docs/CODEX_CURRENT_STATE.md`
- `docs/FRONTEND_OWNER_MAP_V42_25.md`
- `docs/TECH_DEBT_CLOSURE_V42_25.md`
- `docs/frontend-legacy-audit.md`
- `platform_core/material_batches.py`
- `platform_core/remote_training_tasks.py`
- `platform_core/training_compatibility.py`
- `platform_core/training_recovery_api.py`
- `platform_core/training_splits.py`
- `platform_core/training_tasks.py`
- `static/app.js`
- `static/index.html`
- `static/main.mjs`
- `static/modules/training-draft-runtime.js`
- `static/modules/training-draft.js`
- `static/modules/training-material-summary-runtime.js`
- `static/modules/training-material-picker-runtime.js`
- `static/modules/training-recovery-runtime.js`
- `static/modules/training-submit.js`
- `static/styles.css`
- `tests/api/test_material_integrity.py`
- `tests/api/test_runtime_router_app_mount.py`
- `tests/api/test_training_ground_truth_gate.py`
- `tests/api/test_training_request.py`
- `tests/browser/material-integrity-governance.spec.mjs`
- `tests/browser/material-workflows.spec.mjs`
- `tests/browser/training-label-selector.spec.mjs`
- `tests/frontend/annotation-action-owner-retirement.test.mjs`
- `tests/frontend/training-draft.test.mjs`
- `tests/frontend/training-material-summary-runtime.test.mjs`
- `tests/frontend/version-marker-owner.test.mjs`
- `tests/integration/test_remote_training_prepare_task.py`
- `docs/TRAINING_CONFLICT_GOVERNANCE_ACCEPTANCE_2026_10_18.md`
- `docs/superpowers/plans/2026-10-17-training-conflict-governance.md`
- `tests/browser/training-duplicate-conflicts.spec.mjs`
- `tests/unit/test_material_reference_reasons.py`
- `tests/unit/test_training_duplicate_conflicts.py`
