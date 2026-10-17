# 重复与异常素材 P0 本地验收（2026-10-17）

## 范围与权限

基线 `d031565d9d83ac60696996ba142c1b74740520a2`；沿用现有隔离工作树及本地分支 `codex/training-failure-diagnostics`，远端目标分支仍为 `feature/external-algorithm-publishing`。只允许本地修改、隔离测试和提交；没有 push、生产连接、部署或正式数据删除。`VERSION.txt=42.24.356` 保持不变。

## 现场事实与已复现代码根因

没有取得现场项目 ID、第一次/第二次 DELETE_INDEX Task ID 或原始日志，因此**不能确认现场到底删除了多少张、哪个 Worker 是否在线，也不能宣称还原了现场两次请求的唯一原因**。

基线代码和隔离执行确认：

1. `deleteMaterialIntegrity47` 在 `runMaterialBatch62` 的 estimate/create 前就关闭选择弹窗。Node RED 明确观察到 `closeModal()` 已发生；失败后选择上下文不可见。`runMaterialBatch62` 的外层 catch 只通知错误，不能把通知当作任务成功。
2. 普通 DELETE_INDEX 终态不会执行完整性审计失效，只有带 `material_integrity_plan_id` 的任务才失效。素材已经删除，审计 SQLite 仍保留原问题组，是“列表还在”的已证实路径，不代表删除未发生。
3. 重用删除前 selection revision，在第一次删除完成后再次创建，会得到 HTTP 409 / `MATERIAL_REVISION_CHANGED`。已复用现有 Python 测试证明实际索引/标注已删除、共享物理文件仍在，同时旧审计确实过期。这是一个可复现路径，不能替代现场日志归因；若第二次重新 estimate 已不存在的 ID，也可能只是零可处理数量。
4. 组详情只读取前 100 项、不消费 cursor；异常组缺少可见选择入口。旧预览在无尺寸时生成 `viewBox="0 0 1 1"`，且图片失败不隐藏 SVG。Node RED 均已捕获。
5. 通用 modal 具有堆栈语义。原治理各步骤反复调用 modal 造成多层窗口和重复控件；浏览器发现后，改为只在已有治理弹窗内替换内容。

## 实现与数据边界

- 唯一计划 Owner 仍是 `create_material_integrity_plan` / `execute_material_integrity_plan`；新增 FILTERED、SELECTED_IMAGES 和异常 SELECTED_GROUPS 范围。全筛选只传筛选/排除条件，不向浏览器下载全量 ID。组内分页每页最多 100 张，Set 保留跨页选择，全部/取消/手动排除均可见。
- 预览冻结 audit ID、material/annotation revision、SHA256、标注摘要、keeper 和删除清单；展示选中、允许删除、引用/Test 保护、需人工判断、无法核验、保留数量及已持久化标注记录数量。只返回最多 20 张真实 Content API 缩略图，完整清单留在服务端 SQLite。
- 普通异常同样走已有计划和 DELETE_INDEX Durable Task，不再绕过预览直接提交 ID。扫描未核验不删除。异常筛选遇到同属重复组的素材，会要求人工核验，不能借异常入口删空重复组或规避不同 GT 的 keeper 决策。
- 计划绑定唯一确定的 Task ID；同凭证重试及发布成功但 execution_task_id 记录中断的重试，均返回同一任务。发布前失败留下的 manifest 必须与原计划逐项一致且仍为 untouched pending 才复用；选择、keeper、hash/annotation、归属、request 或状态冲突均 409，事务回滚，不清空或放宽验证。执行、Worker 和逐项提交仍校验身份/标注/引用及 Test 保护；保留既有 annotation rollback/lifecycle fence。
- 仅删除素材索引和对应标注，不执行 DELETE_SOURCE，不删除共享原始文件、标签、训练快照或历史任务。活动/历史引用改变、标注或 keeper 改变时失败关闭，安全项可以按原有部分成功合同完成。
- 预检/提交错误保留选择和窗口；任务受理不等于删除完成。已有 MaterialBatchRuntime62 / PollRegistry 负责状态，不新增计时器或执行器。显示 Task ID、真实计数、Worker、错误样例和完整日志入口；页面重开从服务端任务列表恢复终态。
- 所有 DELETE_INDEX 终态都会刷新素材页、清理相关摘要和审计缓存。旧审计组不再作为当前列表显示，明确提供重新审计入口；后端 stale groups/items 检查防止旧分组和当前图片/框混用。
- 图片 frame 按实际宽高比显示，SVG 和图片共用区域；naturalWidth/naturalHeight 必须匹配可信元数据才显示框。无尺寸/尺寸漂移隐藏框并提示；失败立即隐藏图片与框，沿用 Content API 获取 HTTP 原因并可重载。
- 窄屏补充既有顶部与数据集工具栏换行，解决真实测出的 375px 页面撑宽；桌面表格、菜单 Owner、删除确认和权限不变。UI/UX skill 只影响选择触达面积、固定操作区、错误恢复与响应式布局，未引入新设计系统。

## 隔离证据和测试

环境：Windows、Python 3.12.7、Node 24.19.0、实际 Chrome。Python conftest 和浏览器 test_server 均新建临时数据目录。浏览器 Worker helper 只允许匹配本次随机项目的 `xjalgo-browser-*` 临时目录；只对目标同项目 QUEUED 且原能力为 materials.batch 的测试 Task 设置唯一测试 capability，使用同一真实 Scheduler/Handler 执行，不领取其他用例任务。常规 materials.batch admission 由 Python 回归覆盖，测试专用路由不代表生产 Worker 在线情况；没有读取生产任务。

| 验证 | 证据 |
| --- | --- |
| 当前页/全筛选/取消/跨页 | Chrome：100 张当前页 → 下一页 26 张 → 跨页 101 张 → 全组 126 张；全筛选 UI 10000 数量由 API 返回，提交不含全量 image_ids |
| 重复安全与冲突 | Python：5→1、501 删除、120 组分页、显式人工 keeper；异常过滤不能绕过 GT/keeper（RED 曾错误纳入 2 张，GREEN 为 0 张并提示人工核验） |
| 普通异常全范围 | Python：125 张完整冻结、Test 保护 1 张、实际删除 124 张；扫描未核验的删除数为 0 |
| 排队与重复点击 | Chrome：同范围二次点击只显示原任务；Python：同凭证与丢失发布确认均返回原 Task ID；发布前失败后重试成功，篡改 manifest 则 409 且无 Task 发布 |
| 提交失败 | Chrome 注入一次明确 HTTP 503（测试故障，不是现场日志），预览和选择保留，同一凭证重试后真实服务器任务成功 |
| 过期与 Revision | Python：旧 material revision、执行前 plan revision、Worker keeper/annotation 变化均受保护；旧审计 items API 409，不混用旧问题与当前 GT |
| 历史/活动引用/Test | 现有及新增 Python 回归；受保护索引和标注保持存在 |
| 部分成功 | Python：排队后其中 1 张标注变化，成功 1 / 失败 1；变化项和历史保护项保留，失败例含真实 image_id |
| 真正删除与刷新 | Chrome 实际创建审计、计划和任务，启动现有 Scheduler/MaterialBatchHandler；成功 125、剩余 1、失败 0；刷新后从服务端恢复成功数和审计过期状态 |
| 预览几何与失败 | Chrome：16:9 / 9:16 / 4:3，图片与 SVG 实测宽高一致；HTTP 404 后框隐藏，重载恢复；Node 无尺寸不生成 SVG |
| 1000 / 10000 | 最终 JUnit 冻结耗时为 0.471 / 2.765 秒；此前并行回归观察到 10000 范围 7.208 秒。响应约 4 KB，仅 20 张预览。这里只计计划冻结，不含先前完整审计、真实 OSS I/O 或最终删除耗时，也不是生产延迟承诺 |
| 桌面/手机 | 1920×1080、1440×900、1366×768、375×812；完整页面不撑宽，勾选/预览/操作按钮可见，菜单回归保持桌面列宽与内部表格滚动 |

最终 Node：978 passed，0 failed，0 skipped。

最终 Python：41 passed，0 failed，0 skipped；包含素材治理、MaterialBatch/public truth、Content API、annotation lifecycle 和 dataset delete atomicity。5 条现有弃用提示不属于业务失败；JUnit 使用支持 record_property 的 legacy 格式记录性能，未改变测试断言。

Chrome：审查修复后的完整相关切片 21/21，包含素材治理 3 项、素材/标注工作流 10 项、分页 5 项、菜单 3 项；专项曾额外复跑 3/3，重复用例不累计数量。没有运行或声称通过全量 Python、全量 Chrome、GitHub Ubuntu、生产 OSS 或真实生产历史素材。

独立只读审查发现并复核关闭三项 Important：未发布 manifest 重试冲突、await refresh 期间跨项目污染、Chrome Worker 跨测试领取。前两项均先补稳定 RED，再最小修复到 GREEN；最终复核未发现新的明确缺陷。刷新前后及失效入口均校验项目身份，没有新增轮询 Owner。

最终真实本地证据：项目 `a7d878ebebd5`，Audit `268b7db521d541c98f47fbe6b4c70c61`，DELETE_INDEX Task `66b09f2dfab843d48661cf2a246817f0`，`SUCCEEDED / total=125 / succeeded=125 / failed=0 / remaining=1`。运行态实测 Worker 为 `integrity-browser-worker`；终态 worker_id 被租约清理后为空，UI 不再误称尚未分配 Worker。较早的其他项目审计仍为 QUEUED，证明测试 Worker 未混领。上述全部为隔离测试数据。

日志：`C:/Users/jorsam/.codex/tmp/integrity-{node,python,chrome}-20261017.log`；Python JUnit：`C:/Users/jorsam/.codex/tmp/integrity-python-20261017.xml`。

视觉与真实任务证据目录：`C:/Users/jorsam/.codex/visualizations/2026/10/17/material-integrity-p0/`：

- `selection-desktop.png`、`all-filtered-{1920,1440,1366,375}.png`
- `frozen-preview-desktop.png`、`frozen-preview-mobile.png`
- `submit-failed-selection-preserved.png`
- `delete-queued.png`、`delete-running.png`、`delete-succeeded.png`
- `isolated-delete-evidence.json`、`isolated-delete-task.log`（真实本地 API 响应与 Worker 日志）

## 修改文件与后续边界

产品：`platform_core/material_batches.py`、`static/app.js`、`static/modules/material-batches.js`、`static/styles.css`；入口缓存：`static/index.html`、`static/main.mjs`。正式 VERSION 未变，app/main/styles cache 为 `42.25.388`，MaterialBatch build/import 为 `422406`。

合同：`tests/api/test_material_integrity.py`、`tests/browser/material-integrity-governance.spec.mjs`、`tests/frontend/material-integrity.test.mjs`、`tests/frontend/material-batches-runtime.test.mjs`、`tests/frontend/version-marker-owner.test.mjs`。

既有 CI：Frontend Runtime 加入素材治理 Chrome，Release Regression 加入素材治理 Python；只增补覆盖和同步实际缓存 build 守卫，没有新增 CI、跳过测试或降低安全断言。同步 AGENTS 与四份当前 handoff 文档。

生产待核验：取得原项目的两次 DELETE_INDEX、最近 AUDIT_MATERIAL_INTEGRITY/治理任务 ID，通过已有 detail/log 接口只读比对创建时间、Worker、total/succeeded/failed、错误码及 revision；核对真实存储与引用状态。本轮证据不能代替现场任务结论。推送/远端 CI 和生产上线须后续授权；禁止将本地通过宣称为生产验收通过。
