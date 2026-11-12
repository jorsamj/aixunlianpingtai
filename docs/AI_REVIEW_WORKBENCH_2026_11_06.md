> **42.24.553 接续**：既有原生协议、人工审核、草稿、转池和正式GT边界复用；本轮补安全推理容量/并发/乱序恢复。专项见 [双实例安全推理](WEVISONE_DUAL_GPU_INFERENCE_P0_2026_11_07.md)。真实4070仍未验证，未修改生产服务。

# AI 标注审核工作台与负样本流转 42.24.548

日期：2026-11-06。基线：9656ded4fd04f013ca60fc619d1a5bb713a9eb30 / 42.24.543。
用户授权范围：Word全部任务及六张插图。独立干净克隆开发，原 WIP / 其他worktree未改动。未访问或修改生产机器、数据库、素材和模型。

## 需求与最终设计

|需求|现有 Owner 与修改|验收依据|
|---|---|---|
|候选编辑即时保存|CandidateStore 同库 review_events、draft_revision/draft_json；原编辑器保存到服务器，CAS及请求幂等；原框单独留证|API保存后GET、旧revision409、双线程唯一赢家、真实Chrome刷新|
|有框及0框转池|原 v60 review.lock + ArtifactStore操作回执；先pending排除，再NegativePool，再transferred；失败blocked可按原ID补跑|40有框+60空框、部分失败恢复、GT冲突、无正式GT写入|
|人工确认无目标|用户显式选择算法并确认才复用原 _review_training_negative 和完整算法标签合同；未勾选只建立池关联，不新增训练资格|已有正式负样本Owner回归；完整算法确认现场UAT仍待验证|
|剩余审核准确|后端review_counts及revision；决策、迭代accepted、accept_unmentioned均排除pending/transferred/blocked/已提交，保留已拒绝|转出100张后只有11张可采用；Worker journal重放回归|
|跨页操作|显式ID或冻结筛选ID manifest；一次执行最多200，原request_id重复继续；筛选全选带排除项|服务端冻结范围、20k ID/聚合不解码全量框；跨页浏览器深度故障UAT待验证|
|审前撤销|池事务写同库幂等回执，分批恢复成员快照后恢复候选active；并发池变化/下游使用阻断|真实API和浏览器转池撤销；同库恢复回执/外部写入回归|
|失败任务详情|无产物仍返回任务阶段错误，失败图按页查看阶段/HTTP/原因/建议并导出本页JSON；原重试增加可选单图范围|无产物取消任务API、原恢复回归、单图重试不覆盖成功/草稿|
|WeVisOne|原接口已支持/wevis2/v1，不重复开发；422合同错误、200空目标/解析错误、逐图脱敏证据；前端截止190s覆盖后端180s|Provider/API单测；真实18000/18003/18002推理NOT VERIFIED|
|界面|同一个app.js Owner：左筛选、中24图分页网格、右当前图检查，底部剩余数量；转池侧栏、原深度编辑器；小屏筛选/详情折叠|真实Chrome 1920/1366/768、局部DOM身份、reduced-motion、真实API闭环|

页面用中文，未另建编辑器、请求中心、缓存或任务引擎。卡片选择与采用决定分离；勾选只选择流转对象，不代表正式GT采用。失败与未处理永不视为0框。正式GT的唯一Owner保持AnnotationRepository。

## 接口合同

沿用 `/api/v60/projects/{project_id}/annotation-tasks/{task_id}`，项目权限和已验证登录Actor复用。

- GET `/candidates?limit=24&cursor=0&filter=all`：增加summary/review_revision、草稿投影与原框证据；支持with_boxes/empty/failed/edited/transferred/blocked/rejected/low/hard。无产物返回200及task_error，不伪造图级结果。
- PUT `/candidates/{image_id}/draft`：boxes、revision、request_id；服务端校验标签、原图边界、源SHA与任务状态；返回revision/saved_at/item/summary，冲突409。
- POST `/review-selection`：filter、review_revision；返回selection_id/count/total/filter/review_revision；最大50000，ID清单在原ArtifactStore冻结。
- POST `/negative-transfer-preview`：与转移相同的范围和目标；返回总数、有框/0框、弃用框数、冲突及可用数。
- POST `/negative-transfer`：request_id，image_ids（最多200）或selection_id及excluded_image_ids，category_ids、algorithm_id、confirm_absent、review_revision。每次最多处理200；pending重复原请求继续，partial保留失败可补跑。服务端跨库步骤不冒充单一SQLite事务。
- GET `/negative-transfer/{request_id}?offset=0&limit=100`：原操作回执分页，最多200条，返回processed/total/next_cursor与目标摘要。POST其`/undo`：分批、幂等、下游/修订防护。显式确认已产生正式GT的操作不自动回滚GT，返回冲突指向正式流程。
- POST `/decisions`：旧合同兼容，新增可选review_revision/expected_remaining；单图采用/拒绝以commit=false持久化；最终提交仍走原Worker和per_image_required限制。
- POST `/retry`：旧空请求仍差量补跑；可选image_ids（1–200）限定失败/未处理项。冻结原始任务列表不改，成功及草稿不重复覆盖。

## 正确性与恢复

CandidateStore只做同库增量列和索引迁移；旧记录默认active、draft_revision=0，不清理历史。负样本恢复回执位于原素材数据库，不是第二份池。池成员与候选跨库按写前回执和状态推进：任何未最终完成步骤均从最终审核排除；进程死亡后重复原请求恢复，不以Toast或HTTP200代替持久结果。

撤销对池修订变化采取保守冲突阻断；不静默重建正式GT。历史Worker提交journal对账继续包含已提交项，避免崩溃后丢失回放汇总，而人工剩余集合排除这些项。

## 验证与证据

执行数值及准确CI以最终交付记录为准。自动化使用临时项目/合成图片，真实Chrome不等于真实模型。

后端隔离性能：20000张、20次“24张首页+聚合计数+标签汇总”，P50=49.23ms，P95=56.11ms；Python tracemalloc峰值29817字节（仅该测量窗口，不是进程RSS或端到端内存峰值）。不宣称已达到生产20万素材P95。

截图位于 `docs/images/ai-review-workbench-20261106/`。原型6张已逐张阅读：原图证据、三栏、转移侧栏、深度编辑、失败队列、微动效。英文仅原型占位，正式文案中文。真实API浏览器用独立临时Uvicorn/真实SQLite与ArtifactStore，候选由夹具生成；覆盖保存→刷新→转池→数量扣除→撤销，未调用或伪造模型输出。

## 未验证与部署边界

- 仓库没有可确认4070主机地址，127.0.0.1相对于调用机器；18000/18003/18002真实图片推理、Nginx实配、生产A800/4070均未验证。
- 大任务性能是隔离测量，非生产20万素材/真实OSS/网络断线与长时多人UAT；浏览器JS堆指标不能代替整机峰值。
- 未自动运行训练、转换、发布、生产清理。没有main合并、tag/release或force push。
- 更新代码需要由部署负责人先备份业务数据目录和任务/素材SQLite及ArtifactStore，再按既有部署流程安装依赖并更新静态缓存；本轮未执行部署。旧代码回退可忽略新增列和表，不能删除迁移后审计/草稿证据；正式GT的人工确认不能通过代码回退撤销。


## 本地交付验证记录

- Node 24.21.0 全量前端：1548/1548；Python聚焦全量205/205（候选/任务/负池/WeVisOne/API，包含40有框+60空框、180跨页带排除、明确确认作用域）。
- 真实Chrome审核相关原有及新增回归31/31；最终新工作台/真实API子集复验5/5（1920/1366/768、网格/列表、键盘、reduced-motion、失败CSV、服务器草稿改框后刷新恢复）。不同命令存在重叠，不累加冒称36条独立用例。
- 扩大检查模型转换共42条时初轮有8条失败：5条审核相关已修复并复测；3条转换用例在独立只读基线克隆9656ded4原代码中同样失败，未修改转换业务代码，未冒称全仓库浏览器零失败。
- 版本文件、Python/JS语法和git diff检查；npm无单独生产构建脚本，使用原静态入口及vendor校验。
- 原工作区独有模型配额/图片同意及旧工作流改动只读审计，未覆盖、未cherry-pick；本轮只依远端9656ded4实际架构接续。
- 准确提交和远端CI在推送后核对；当前文档中的本地绿灯不代表准确SHA CI或现场验收。

## 42.24.545 准确CI回归修复

cc672d4a 首轮可查询49次运行中46成功、2次Remote Training Runtime失败、1次前端运行中。两个失败均为同一 `test_p2_reviewed_mining_preview_adoption_reuses_original_candidate_set_and_protects_test`：历史已审核难样本只读预览被新剩余候选规则过滤为空。已在本地复现RED，仅 `_reviewed_mining_candidates` 历史读取显式 `include_committed=True`，保留默认剩余过滤和正式GT隔离；不修改或放宽原回归断言。该SHA前端完整CI与三个Chrome分片随后全部success，最终47成功/2失败；新SHA需重新核对CI。

同时补充一次RED/GREEN范围回归：转池或编辑后返回当前可审核标签汇总，最终请求移除只属于已排除候选的旧映射，避免剩余集合被过期映射误阻断；服务端未知映射校验继续严格保留。用户确认4070在无法访问的内网，本轮不再请求现场访问，真实三路推理保留NOT VERIFIED。Remote Training Runtime原精确CI命令本地132/132通过。

545提交前复验：聚焦Python含难样本历史210/210，Remote Training Runtime原命令132/132，前端全量1549/1549，真实API/原审核轮询Chrome3/3。两万任务元数据、24张当前页的浏览器采样：输入至下一帧P50 16.6ms/P95 16.9ms，采样窗口JS堆观察峰值7539990字节，0个>50ms长任务，DOM身份保留；详见 `images/ai-review-workbench-20261106/browser-interaction-baseline.json`。这是隔离合成夹具的观测，非真实模型/生产端到端或整机内存峰值。

## 42.24.546 审核计数语义

最终视觉复核移除页头旧的“本页已选择（默认采用数）”，只保留服务端筛选分页数量；底栏“选中N”专属于实际转池勾选，卡片选中边框也只依checkbox真值。未修改后端数据合同或训练资格。新增RED/GREEN前端回归，最新截图及准确SHA CI独立核对。

546前端全量1550/1550；服务器草稿改框刷新、转池/撤销、全失败CSV及三视口网格/列表/键盘/reduced-motion复验5/5。后端同545，已验210/210与远程训练API132/132。

## 42.24.547 大批故障与回执修订

546 / 7f84d2bd43f401b70b07d962cb600acba4d6ff54准确CI **41/41 success**。补充超过200张的全失败RED复现发现初批失败项会被优先重复选中，后页饥饿；改为先处理未尝试图片，冻结集全部尝试后返回partial停止自动循环，用户明确重试时才补跑失败项。240张测试验证200失败→后40失败并停止→显式重试200成功→剩40成功，成功项不重复执行。

另一个RED复现发现完成回执重复请求会刷新pool_revision，从而让之后发生的池修改绕过撤销冲突；现完成重放立即返回原回执，不更新任何操作修订，外部池变化后撤销严格409，新增分类仍保留。两项仅改原转移API，不改变GT/训练/模型合同，生产未动。

547聚焦后端212/212（保留原断言），真实API浏览器草稿/转池/撤销/失败CSV复验1/1；前端代码同546，已验1550/1550。版本真值回归11/11，Python编译与diff检查通过；准确547 SHA CI待推送核对。

## 42.24.548 大批回执与安全撤销

547 / 0104d2bb8259836c778a5c276f75d1c196fe06d5准确CI **47/47 success**。补测发现逐图重写整单JSON造成二次方写放大；逐图状态改写现有CandidateStore同库review_transfer_receipts，操作metadata只在批次边界写入。每次最多200条，不解码全量候选框；GET回执分页，并从已转出图片检查栏重新查看和撤销。旧JSON回执首次恢复时原样归档后导入同库，不删除审计证据。

撤销仅允许起始池修订加本操作成功数等于结束修订，跨批其他修改或不确定的恢复写入均409，避免覆盖其他人的池关联；旧回执没有起始修订也明确阻断自动撤销。池恢复与池幂等回执仍在原素材库同事务；候选active恢复与其undone回执在CandidateStore同事务，使用原操作ID/固定200图撤销批次恢复。对SQL中断、池提交后候选恢复前中断均有回归。负样本算法关联新增material_id索引，EXPLAIN验证SEARCH，兼容没有算法关联表的旧项目池。

新增240张跨批外部修改、每批整单JSON写入次数有界、旧回执归档迁移、分页及崩溃重入、事务回滚测试。真实4070三路推理因内网不可达继续NOT VERIFIED。最终本地数值及准确548 SHA CI见交付记录，不借用547绿灯。

548提交前实测：Python聚焦218/218，Node 24前端全量1550/1550，Chrome关键流9/9（含真实API、三视口、768触屏勾选、键盘、reduced-motion、20k元数据局部交互、诊断及轮询）。Python编译、JS语法、git diff检查通过；Annotorious 16项、Uppy 87项本地依赖及声明校验通过。npm原静态架构没有独立构建脚本。准确548提交CI需推送后单独核验。
