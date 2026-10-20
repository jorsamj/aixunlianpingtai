# 训练重复冲突、标注工作台与素材治理闭环验收

## 2026-10-19 追加｜GT 冲突审核响应、批量安全清理及明确放弃

用户生产截图显示 GT 冲突 960 组 / 2369 张，已证实映射差异 0 组，历史/Test 保护 250 张。这是用户所见的截图数字；没有读取或改变生产数据，不能认定 2369 张全部应删除。

### 修复内容（本轮代码，需以最终 SHA CI 验收）

- GT 批量审核原前端打开、分页和详情使用全局 `document.querySelector`，可能选中隐藏旧窗口，实际可见按钮无回调。现在所有 GT/审计关键交互查找同一个可见 modal 的控件；分页和筛选请求发起时就显示状态，避免“无反应”。
- 现有 `MaterialBatchRuntime62 / PollRegistry` 是唯一审计及删除任务状态 Owner。新进度页面记录真实 Task ID、队列/Worker、phase 和已处理量，区分提交受理与执行成功，异常停留在原弹窗并显示可恢复操作；不新增第二套轮询器。
- 已有同 GT 去重继续 `SAFE_ALL` 自动保留安全身份；不同 GT 仍通过 `MANUAL_GROUPS` 显式人工选择 keeper 批量治理。支持 GT 冲突组跨页选择，再预览“放弃选中组”，或“放弃全部冲突”，由服务端完整审计范围建立 `DISCARD_CONFLICTS` 冻结计划，前端不下载成千上万图片 ID。
- **全部放弃只适用于尚未受不可变/活动任务/Test 保护的 GT 冲突索引与对应正式标注**。显式二次确认；不自动修正 GT、不删除原始共享图片、不修改原始母标签、不修改历史训练证据。不验证的异常交叠组和全保护组跳过；执行时原 Worker 再验证哈希、标注版本、引用、旧审计与当前 Revision。
- 原计划/Worker 首次支持 `keeper_image_id=''` 和 `keeper_reason=EXPLICIT_DISCARD_UNPROTECTED` 的受控整组放弃。空 keeper 仅在显式放弃场景合法，其他 keeper 缺失仍拒绝。
- API 真实执行测试覆盖无保护整组删除与受历史/Test 保护仅删除剩余项，浏览器契约覆盖多选/预检/执行原 Worker 及任务反馈。后续以最终 SHA CI 实际结果验收，未完成前不声称通过。
- 这不是物理文件、历史模型或 Benchmark 清库功能。现存生产保护的 250 张不会因为新按钮被强制清除；需要人工核查原引用，另行管理新训练输入。

本轮沿用既有 SQLite 冻结计划、现有批量任务、AnnotationRepository/MaterialRepository、ModalContentRuntime，无新数据真相源/删除线程/REST 主路径；正式 VERSION 保持 42.24.356，不部署生产。


## 2026-10-19 追加｜批量 GT 冲突分类、可视化与人工来源审核

本轮基线9e0d330；真实生产汇总由用户提供，不冒充已读取960组正式GT。根因分类、来源校验、人工确认、原冻结计划/Worker及生产边界详见唯一追踪文档本轮节。Python341、Node995通过，包含26真实组服务端全范围冻结及索引/标注删除安全验证。两个既有浏览器入口复用同一个GT差异组件，真实图片/框、来源、IoU和保护信息可见；四视口1920/1440/1366/375留图。最终 Chrome 和最终 SHA 全量 CI 记录于 `C:/Users/jorsam/.codex/visualizations/2026/10/19/gt-conflict-assisted-review/CI_FINAL_ACCEPTANCE.md`。

只读诊断合同：`GET /api/v62/projects/{project}/material-integrity/audits/{audit}/conflict-review`，支持 cursor/limit/observation/import_batch；observation 也接受 COORDINATE_ONLY、LABEL_SCOPE_COUNT_COMPOUND、SCOPE_AND_GEOMETRY 等 cohort。响应全量 cohort_counts、cohort_proven_mapping_counts、source_assisted_review_groups、individual_only_review_groups、filtered_coordinate_statistics；后者明确候选匹配口径和无法核验项。旧审计提示重新审计。单组 `POST .../material-integrity/gt-comparison` 使用实际正式GT并校验同SHA/项目及revision。

整批来源审核不是标注覆盖：用户核对并显式确认来源→服务端原 dedup-plans review_basis 冻结筛选→原安全预览与二次凭证→原 DELETE_INDEX/Worker→失效旧审计→重新审计及原训练预检。没有可核验来源的组保持逐组人工，不自动求并集/选GT。412历史/Test保护继续优先；Snapshot/Test/模型和历史GT不可变。未在生产执行任何操作，未修改正式VERSION。

## 2026-10-19 追加｜远程清理 NO_OBJECTS 同步锁误保护

用户提供的真实只读证据已将五个 attempt0/无冻结、进程、结果的失败任务定位到唯一额外文件 `remote-material/staging-cleanup.json.lock`。`cleanup_task()` 在确定无对象之前获取 FileLock；Linux 可残留此锁。原历史引用扫描把它当作未知产物，错误投影 `TRAINING_FAILED_DURABLE_DEPENDENCY`。任务 ID 和重叠引用数量记录在唯一追踪文档顶部，不将各任务计数相加。

仅在原 FAILED TRAINING/no-freeze 路径中精确允许该同步锁；不删除锁，不修改远程清理流程。真实 `staging-cleanup.json` 台账、其他 `.lock`、Bundle、Checkpoint、Snapshot、Payload 内部依赖和其他任务恢复/重试关联仍保护。attempt1、进程、冻结、成功/活动训练、模型/评测、独立 Test 的规则未改；有有效冻结和实际产物的现场第六任务仍必须保护。原任务 Payload/日志/状态不变，无新 Owner、执行器、接口或前端缓存规则变化。

- RED：实际 `cleanup_task()` 返回 NO_OBJECTS 路径持有真实 FileLock 时，原函数错误保护 a/b，业务断言失败；不是手工创建同名文件。
- GREEN：真实清理与14类依赖组合，连同既有远程清理/保护单元测试46/46；GitHub同命令 `--confcutdir=tests/unit` 46/46。
- API/Worker/训练请求与上述单元组合191/191；追加训练冲突、SQLite 删除原子性与标注作用域27/27。API 在真实持锁期间建立计划，再以原凭证和 Worker 执行隔离 DELETE_INDEX，验证保留一张、共享源字节和原历史证据不变；台账及其他锁仍0可删。
- Node24完整994/994；真实Chrome最终清理夹具10/10（0失败/跳过），桌面/375px截图验证；Windows浏览器服务器产生连接断开日志但测试及后端业务断言全部通过，不屏蔽日志。最终SHA的全部Actions/Jobs结果待验收，最终准确记录见本地外部 `C:/Users/jorsam/.codex/visualizations/2026/10/19/cleanup-lock-p0/CI_FINAL_ACCEPTANCE.md`，禁止沿用上一SHA。
- 独立只读复核未发现可确认问题；复核另跑原保护单元27/27与API19/19（与上方集合重叠，不相加）。

未连接生产，不删除生产锁/素材，不改历史 Snapshot/Test，不改 VERSION=42.24.356。部署后还需重新只读审计现场保护原因和新计划；既有审计不能代表修复后的当前事实。不会将“消除一个错误保护原因”等同于“全部2531张可删除”；其他保护重叠、人工标注冲突与每组 keeper 必须保留。

## 2026-10-19 P0 追加｜素材治理与训练冲突删除统一闭环

本批从 GitHub 长期分支实际 fetch 的 `5a8d559faf20c46a4ceeca172b792920f1f86f57` 开始，正确工作树为 `C:/Users/jorsam/.codex/worktrees/external-algorithm-publishing/畅联云算法训练_v42.14.0`。下方 2026-10-18 的“保守保护全部 FAILED/no-freeze”是历史阶段，本批按可验证依赖收紧分类，不应再作为当前语义。

### 已定位的真实缺口

1. 原历史保护按任务 Payload 的 Image ID 无差别保留 FAILED/no-freeze，不能区分请求溯源与现存输入依赖；同组多个保护身份又导致整个组跳过。隔离 API RED 稳定复现 request-only 0→期望1、部分保护 0→期望2；并不证明现场1041组都属于这一原因。
2. 训练诊断没有兼容审计计划的删除桥接，API 首轮6项失败；训练弹窗缺少可见多选。新增桥接仍由同一 MaterialBatch Owner 从 TrainingCompatibility 当前事实解析范围，再调用同一计划，不把浏览器问题 ID 当成审计许可。
3. 真实 Chrome 发现结构化后端错误被公共 API 显示为 `[object Object]`、预览返回叠加弹窗拦截按钮；独立复核补齐筛选保持、人工决定 Revision、固定 Benchmark 同口径、部分失败选择与迟到响应围栏。

### 当前安全合同

- 只有终态失败、有效请求可读、无冻结/产物/恢复/重试/未知契约及其他依赖时，标记 `TRAINING_FAILED_REQUEST_ONLY`、`protected=false`。原 Payload、日志和已验证的纯诊断分页保持不变。进程/尝试/未知依赖仍 fail closed，不是一概解除 FAILED 保护。
- 成功模型、独立评测、Snapshot、冻结/当前 Test、活动训练/清洗/标注/准备任务、持久输入包和 checkpoint 继续保护；执行发布及 Worker 删除前重新核验。多个保护身份全部保留，同 GT 冗余未保护索引可治理；不同 GT 必须明确人工 keeper，且人工决定不能覆盖历史保护。
- 两个入口共用既有审计和计划 SQLite、DELETE_INDEX、Material/Annotation Repository、MaterialBatchRuntime62 和 PollRegistry。历史任务诊断只治理当前索引，不改原输入。全筛选通过服务端解析冻结，99页不逐页拉取全部ID。部分成功后复用原任务非成功 Selection 的服务端范围，重新审计/预览/人工核对，不把成功项再加入。
- 预览列出保护、人工判断、无法核验和真实计划数；0条计划服务端也拒绝创建空任务。审计分类使用同一计划的只读模式，实际已删/失败来自持久任务，旧 Revision 不显示伪实时待治理数。完整审计继续展示真实历史重复，不隐藏或修改SHA/GT。
- 正式 VERSION=42.24.356；app/main/styles入口缓存42.25.392，训练摘要422605，MaterialBatch422407。缓存与测试/工作流精确守卫同步；没有新请求包装层或第二套轮询。

### 验收证据与边界

本地 Windows/Python3.12、Node24、真实Chrome。原始日志位于 `C:/Users/jorsam/.codex/tmp/p0-*-1019.log`；最终截图、测试结果、准确提交列表和全部实际 Actions/Jobs 的原始 JSON 归档于 `C:/Users/jorsam/.codex/visualizations/2026/10/19/p0-material-governance/`。该目录仅为唯一追踪文档的验收附件，不新增问题清单或业务真相源。

- 已实测 Python/API 组合122 passed；追加原子性和最终API25 passed（与122有重叠，不相加），5条既有弃用warning；Node24全量994 passed；真实Chrome两规格10 passed，追加迟到预览围栏1 passed。均0失败、0跳过。桌面1920/1440/1366与375px手机截图已归档；手机预览为刻意注入503后仍保留选择和真实计划的状态，不是将错误隐藏。两轮独立规格/安全复核未发现剩余可确认P0/P1/P2。旧阶段及旧 SHA 的绿色不能继承为本次成功。
- 本段所在提交与后续必要CI修复仅普通FF推送；最终完整SHA、提交清单、全部实际Actions/Jobs及未触发清单，推送后写入同一证据目录 `CI_FINAL.json` 和 `CI_FINAL_ACCEPTANCE.md`，不预先将尚未运行的CI写为通过。
- 真实浏览器覆盖单张/多选/全筛选/跨99页/失败保留勾选/人工决定失效/异步返回/真实Worker成功和部分成功；2531全保护是隔离模拟，保留2531、可删0、完整审计仍报2531，绝不是生产删除。
- **生产未核验**：现场2531张、1041组的具体保护引用分布、原两次Task ID/日志、实际OSS历史对象、10万素材+海量历史任务并发、A800实机。没有只读现场证据，不能宣称1041组已清空或真实训练冲突已全面消失。
- 仍可能合理返回0：真正不可变/活动/Test依赖、GT冲突未人工复核、素材/标注/引用漂移、存储未核验。处理入口为原标注工作台核对合法当前GT，或新训练草稿调整输入；禁止强制删除和改写历史证据。
- 本轮允许普通FF推送与CI修复；不部署、不重启生产、不连接/修改生产数据库，不执行任何生产素材删除。

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


## 2026-10-19 接续增量：GT 审核与审计弹窗异步归属

本轮从远端 `6df6c8b62aab9e768fad35e2b718226171818c49` 接手，与上一记录的
`3a4a7e38760e10b25a28e1f73c136535b31b8367` 相比 fast-forward 领先 4 个提交；
当时 VERSION 为 `42.24.356`，该 SHA 的 GitHub Actions 已核验为 35/35 成功，
GitHub Checks 97/97 成功。这是上一 SHA 的证据，不自动适用于本轮修复。

已核对 `DISCARD_CONFLICTS` 仍沿用服务端冻结计划、`DELETE_INDEX`、标注仓库
和现有 Worker。审计范围由服务端展开，删除前核对索引身份、正式 GT 摘要、
历史/不可变 Snapshot、Test 身份及活动任务。未在本轮擅自删除素材、修改生产数据库
或绕过保护边界。其已有 API 和隔离 Chrome 用例随最终提交重新由 CI 复验。

新增修复提交：`4a9203dc827164784079732df6d4229a2240f7bd`。

- `static/app.js`：GT 组详情、审计结果加载、GT 批量审核错误、问题组分页/
  筛选和组内图片翻页现在验证请求原始弹窗仍可见，旧响应不能覆盖已切换弹窗。
  图片翻页显示等待、失败和重试状态；未知进度不再把 null 伪装成 0%。
- `tests/frontend/material-integrity.test.mjs`：补充异步弹窗归属和未知进度约束。
- `tests/browser/training-duplicate-conflicts.spec.mjs`：新增真实 Chrome 延迟 GT
  详情响应场景，验证用户返回批量审核后旧响应不能覆盖列表。
- `static/index.html` 与 `tests/frontend/version-marker-owner.test.mjs`：
  更新静态资源缓存参数 `42.25.395`，正式 VERSION 不变。

本轮提交后的 GitHub Actions 需按**最终 HEAD**分别核验，不得将前一提交的
成功标记沿用到最终提交。现阶段 CI 验收中；仅凭源代码审计及前一 SHA 的
全绿结果，不能承诺该新 SHA 已完成 Chrome 和全工作流验收。

**生产安全边界**：本轮只变更 GitHub 长期开发分支；未部署、不重启服务、
不修改生产数据，也不在生产真实执行 GT 放弃或远端权重发布。

### 2026-10-19 Chrome 全量回归：标签编辑状态源修复

`f6309f2c` 的 Frontend Runtime Stabilization 真实 Chrome 记录显示 106 通过、
1 失败：`material-workflows.spec.mjs` 标签管理创建后编辑，未发 PUT 即因
英文编码为空触发格式提示。原因是标签列表按 `label414Usage` 显示，
而编辑仅从 `state.labels` 查找；两个数据投影不同步时错误地打开空编辑表单。

修复编辑使用当前列表的同一标签身份与字段，并回退到正式标签集合；
找不到目标时明确报同步错误，不能悄悄当作新建弹窗。
Chrome 回归增加打开编辑窗口时英文代码 `helmet` 与中文名称 `安全帽`
的真实断言，保留最终 PUT/刷新/缓存不加载整池的原有验收，不降低校验。
静态资源版本参数更新为 `42.25.396`；正式 VERSION 仍为 `42.24.356`。
**本轮此提交必须重新经最新 SHA Actions 核验，不能沿用此前成功状态。**

### 2026-10-20｜发布版本递增与最新审计真实浏览器回归

以已通过 GitHub Actions 的上一并行修复 SHA `64d9bb091b0066528fbfdd95dc88aab7a5f58c58` 为基线，沿用其原有 TaskRepository/Worker/ModalContentRuntime 实现，不重复叠加第二套审计或弹窗状态。正式 `VERSION.txt` 从 `42.24.356` 递增到 `42.24.357`，入口 app/main/styles 缓存参数递增到 `42.25.400`，同步静态资源守卫测试。新增 Playwright 独立项目实际创建审计、真实 Worker 运行、再写入 60 条更晚的批次，核验最近 50 个批次不含审计但最新审计接口和 UI 均准确可见。此版本未部署生产、未连接生产素材/数据库、未重启任何服务；最终是否可部署以该发布 SHA 的 CI 结果为准。

### 2026-10-20｜跨项目审计隔离与 GT 证据翻页回归

从已通过 Actions 的版本 `42.24.357` 开始，复核发现前端的素材审计过期状态仍可能从另一个项目继承。
修复时以项目 ID 和审计 Task ID 的组合判定是否可以沿用本次弹窗的过期状态；服务端真实
`groups.stale` 与当前审计关联的已执行治理任务仍具有最高优先级。不存在绕过过期审计预检
的逻辑，跨项目状态则不再污染另一项目。

另修复 GT 组图片分页只刷新图片而没有更新证据面板的问题。复用唯一的 GT 差异证据渲染和
绑定函数，第一页及后续页的标注来源、候选对比、IoU 观察只对应当前可见的图片页；
跨页选择继续保留，不改写真实 GT，不增加第二套数据源。新增 Node 契约回归及 Chrome
隔离项目端到端验证。正式 VERSION 递增为 `42.24.358`，静态 app/main/styles 参数
`42.25.401`。本次只操作 GitHub 长期开发分支，不部署生产、不删除真实素材；
本提交验收须以最终 SHA 的 GitHub Actions 为准。

## 2026-10-20｜素材完整性接续审查（本地验证，最终 SHA CI 待验收）

- 完整 fetch/pull 长期分支到 d623a2d6327143571898e778050e5d42cc5e4a4d，六个已知修复全部包含；原工作区保留，复用既有长期分支工作树。
- 仅修复三项真实复现：标签映射摘要未贯穿普通治理计划/Worker；execute 迟到成功/失败未完整校验弹窗归属；恢复复验把已成功删除项重新记作失败。沿用原计划/Task/DELETE_INDEX/AnnotationRepository/Modal/PollRegistry，无新 Owner。
- 审计已有 label_schema_digest 贯穿冻结计划、执行清单和逐项删除；标签锁先于 Material 生命周期锁。缺摘要旧计划 fail closed，需要重新审计/预检；已成功项保持历史计数，未完成项仍复验 keeper/GT/hash/Test/引用。
- 本地新回归 RED：Python 4 failed，Node 2 failed；最小修复及边界补充后聚焦 Python 6 passed，Node 全量 1021 passed。安全扩展最终 116 passed。真实 Chrome 两份规格 19 passed；最后补顶层弹窗按钮归属后聚焦 2 passed。独立复核未发现本次差异的 P0/P1；其 Python 首轮 5 setup error 为 C:/Temp 父目录不存在，换已有短目录后 6 passed，Node 35 passed。首轮新 Chrome 夹具误用 window.state 导致 2 failed，已改为仓库既有 lexical state 并保留所有业务断言。
- 正式 VERSION=42.24.358 不变；入口 app/main/styles 静态缓存 42.25.402。最终准确 SHA、全部 Actions/Checks、未触发与未验证边界记录在 C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/material-integrity-acceptance-20261020.md；不沿用基线 40/40 绿色。
- 未部署、不重启生产、不连接生产数据库、不执行真实素材删除，不自动发布模型。生产 OSS/S3、历史现场、GPU/A800、大库并发与查询 SLA 仍 NOT VERIFIED。
