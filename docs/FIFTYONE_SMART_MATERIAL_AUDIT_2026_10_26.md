# FiftyOne 可选智能素材分析专项

本文件是本专项唯一需求、设计、进度和接续依据。用户附件681f3943与“最高优先级：现有业务兼容性与零破坏原则”共同构成需求基线；后者优先。2026-10-26真实fetch成功，远端/本地均c88b6151797bf7a122b891f4e336697dd041802a，VERSION42.24.389，初始工作区干净。其他工作树、5944e1a5、原标注WIP和两份训练模板测试保持原样。

## 不可改变的合同

- MaterialRepository、AnnotationRepository、TaskRepository、StorageManager、原Worker及Annotorious继续拥有正式事实与操作流程；不新增任务、素材、GT或调度系统。
- 普通/批量图片、ZIP、上传恢复、素材查询/删除、SHA256/dHash/OpenCV清洗、Full Audit、GT冲突、标签治理、人工/AI标注、训练冻结与成果、资源独占、认证及项目隔离保持原语义。
- `smart_material_audit.enabled=false`为默认。关闭时不受理智能分析、不启动引擎、不加载模型；关闭不删除历史结果，不替代取消已有任务，不影响原清洗。
- 分析只读取正式素材/GT/可信评测证据，结果是可丢弃派生数据。不能自动删除、改GT、改Test或启动训练。人工修改仍使用原GT CAS及源SHA接口。
- 绝不以dHash冒充FiftyOne，不以缺预测/划分/模型/环境冒充通过，不以低置信度判定GT错误，不生成无logits的hardness分数。
- 不复制整个素材库，不将FiftyOne数据库/App嵌入主服务；独立环境、离线依赖/权重、禁止运行时下载。默认不迁移正式数据库。
- 本轮不部署、不安装生产依赖、不访问/扫描/修改生产素材、GT、数据库、模型或启动真实训练。

## A：现状审计（进行中）

| 现有能力 | 现有Owner/调用链 | 复用与真实缺口 |
|---|---|---|
| 清洗与素材批任务 | material_batches.py / BatchOperation.CLEAN、BatchSelection、cleaning_batches.py | 冻结选择、幂等任务、逐项结果、重试/取消继续复用；没有FiftyOne操作 |
| 图片分析 | cleaning.py / DurableHashIndex；cleaning_analysis_runtime.py | SHA/dHash/OpenCV及逐图超时子进程保留，不改原阈值和成功标准 |
| 完整性/重复审核 | AUDIT_MATERIAL_INTEGRITY、AUDIT_LABEL_INTEGRITY、原分页router | 原精确重复治理保留；视觉相似建议绝不能进入安全批删分组 |
| 持久执行与资源 | TaskKind.MATERIAL_BATCH、worker_registry材料角色、TaskScheduler、WorkerContext | 原lease/fence/checkpoint/资源key复用；新增能力需显式capability，旧Worker不得误领取 |
| 上传后处理 | upload-confirmation.js、UploadBatchStore、Uppy/ZIP原Runtime、唯一任务中心 | 原成功数量及清洗/标注入口复用；智能分析只可显式异步触发 |
| 标注与版本 | AnnotationRepository、annotation-workbench/annotorious-editor、原GT保存接口 | 已有CAS/源SHA及确认负样本，不新增编辑器 |
| 预测/困难样本 | evaluation_analysis.py、training_evaluation.py、hard_sample_mining.py、CandidateStore/feedback | 正式逐框证据与原候选流程复用，不重复匹配来改变正式指标 |
| 新引擎 | 本仓未找到fiftyone/smart_material_audit实现 | 需独立环境、许可清单、只读映射及真实引擎验证，再接业务 |

## 增量设计与取舍

推荐原材料任务新增独立分析操作，保持TaskKind/原调度不变，使用额外capability与原资源key；独立Python子进程调用FiftyOne，输入仅显式冻结image_id、源SHA、GT版本与受控只读路径，输出只到任务派生工件。主服务不能import FiftyOne。新增独立分析API，旧API请求/响应/错误/分页不变；页面只增入口，原Modal/PollRegistry/任务中心复用。

替代方案：直接安装主服务会引入ASGI/Pillow等依赖冲突；嵌入FiftyOne App/MongoDB则增加第二套界面和生命周期，两者不采用。引擎的临时Mongo数据仅是可回收计算中间态，不是正式素材/GT副本；是否能够满足商业分发及部署许可，必须先核验，不能默认认可。

派生结果按任务保存，服务端分页，不全量返给浏览器；review绑定源SHA/GT摘要，过期显示需复核。正式保存成功且再次核对GT后才允许“已修正”结论，失败/冲突不标处理。无可信冻结划分标未检查；无可信预测标错标分析未检查。相似度是距离/候选证据，不是错误事实或综合评分。

## B：版本、许可与隔离验证（进行中）

官方PyPI元数据于2026-10-26查询：候选fiftyone==1.22.1，要求Python>=3.10、fiftyone-brain>=0.25,<0.26、fiftyone-db>=0.4,<2；不能直接使用最新Brain0.27替代。仅在C:/tmp新venv下载候选wheel进行依赖审计，未加入主服务requirements、未导入/启动引擎、未联网下载模型。

官方依据（在线文档可能更新，落地版本必须以下载制品为准）：

- [FiftyOne Apache-2.0](https://github.com/voxel51/fiftyone/blob/develop/LICENSE)、[Brain许可](https://github.com/voxel51/fiftyone-brain/blob/main/LICENSE)
- [Brain API输入及默认模型行为](https://docs.voxel51.com/api/fiftyone.brain.html)
- [FiftyOne配置/禁遥测](https://docs.voxel51.com/user_guide/config.html)
- [MongoDB SSPL及服务场景解释](https://www.mongodb.com/legal/licensing/server-side-public-license/faq)
- [候选CLIP项目MIT许可](https://github.com/openai/CLIP/blob/main/LICENSE)，不是已核验权重制品清单

重大许可边界：FiftyOne/Brain的Apache-2.0不覆盖MongoDB服务端SSPL，不覆盖任意模型权重，不解决现有Ultralytics AGPL/企业许可。现阶段不引入MongoDB生产依赖或声称可无条件闭源分发；依赖/二进制及权重逐项核验未完成。

| 官方能力 | 必要输入/限制 | 当前状态 |
|---|---|---|
| compute_similarity / compute_near_duplicates | 明确提供离线embedding/模型；不能省略而触发默认下载；image_id映射及距离/阈值记录 | 未验证 |
| compute_leaky_splits | 同上，且可信冻结Train/Val/Test映射 | 未验证；无证据必须未检查 |
| compute_uniqueness | embedding；分数仅独特性，不代表标签质量 | 未验证 |
| compute_mistakenness | 同类别合同正式GT与可信检测预测，copy_missing=False；候选不改正式指标 | 未验证 |
| hardness | 分类logits等必要输入；当前检测场景不伪造 | 不计划新增；复用已有可靠困难样本候选 |

## 阶段与验收

| 阶段 | 状态 | 完成证据/剩余事项 |
|---|---|---|
| A审计/回归基线 | 已完成待验收 | 主要Owner/远端核对及增量方案已记录；原材料/清洗/上传/Worker定向24项通过，不代表完整兼容组 |
| B真实引擎隔离验证 | 阻塞 | 已提出本机临时MongoDB隔离PoC许可选择，等待用户答复；未安装/运行服务、未选定权重 |
| C任务/清洗审核 | 未开始 | 默认关闭、分页、取消/恢复、无正式数据写入及旧Worker兼容 |
| D标签/人工复核 | 未开始 | 原接口/GT CAS/源SHA、审核过期与失败保护 |
| E上传后入口 | 未开始 | 原批次/ZIP完成后显式异步入口、不阻塞回执 |
| F回归/审查/准确CI | 未开始 | 必须先A关闭组，再B开启组；未通过不交付 |

## 兼容性验收表

下列是待执行的验收，不是以未改代码代替通过。当前没有业务修改，没有测试/Commit/CI可以认作本专项完成。

| 原模块 | 修改前行为 | 修改后必须保持 | 本专项回归 |
|---|---|---|---|
| 图片上传 | 原multipart/Uppy/批次回执 | 上传成功不等待分析 | NOT VERIFIED |
| ZIP导入 | 原分片、标签确认、后台入库 | 原协议/恢复/GT不变 | NOT VERIFIED |
| 素材管理 | 原分页筛选/预览/安全删除 | 不增加全库前端加载 | NOT VERIFIED |
| 素材清洗 | SHA/dHash/OpenCV/正式结果 | 不换算法/阈值/成功含义 | NOT VERIFIED |
| 异常审核 | Full Audit/GT冲突及预检 | 智能候选不进入自动删除 | NOT VERIFIED |
| 标签统一 | 原映射/Full Audit | 不改正式标签及原流程 | NOT VERIFIED |
| 人工标注 | Annotorious/GT CAS/源SHA | 仍通过原保存接口 | NOT VERIFIED |
| AI标注 | 原provider/候选/审核 | 不依赖引擎可用性 | NOT VERIFIED |
| 训练创建 | 原准入/冻结/创建 | 不接入本分析依赖 | NOT VERIFIED |
| 训练任务 | 原lease/恢复/成果 | 不改状态和副本生命周期 | NOT VERIFIED |
| Worker调度 | capability/资源独占/fence | 不新增调度器或抢占 | NOT VERIFIED |
| 模型成果 | 原版本/Checkpoint/可信结果 | 只读引用、不改成果 | NOT VERIFIED |

大库1万/10万、真实NAS/OSS/S3、生产性能、GPU、生产商业许可及部署全部NOT VERIFIED。每阶段仅运行受影响必要测试，不重复全仓测试。不自动部署。

## 实施计划与执行门槛

按原授权内联顺序执行，计划记录在本唯一文档，不另建重复专项。

1. B先只在临时wheelhouse核对fiftyone==1.22.1及兼容Brain0.25.0/db1.4.1的精确制品、SHA及传递许可；主requirements不变。MongoDB SSPL风险已向用户明确说明，并询问是否允许本机临时MongoDB隔离PoC；答复前不安装/运行该服务、不执行依赖它的业务接入。仅预选版本，下载完成和许可清单不冒充已验收。
2. B通过后新增可选引擎桥接模块及隔离测试：强制显式离线embedding，阻止默认zoo下载，使用临时且有task/project前缀的计算集合，finally清理，禁遥测；先验证真实Brain相似/泄漏/uniqueness和检测mistakenness的image_id回映。没有模型/预测/划分时返回明确未检查。全真引擎测试和模拟异常单测分别记录，不混称。
3. C新增独立smart-material-audit接口与原MATERIAL_BATCH下独立操作；在prepare之前判定开关；额外capability阻止旧Worker领取。复用BatchSelection/原resource_key/checkpoint/lease fencing及取消，不新增调度；子进程必须纳入原进程控制。派生结果放原ArtifactStore，每页25/50且SQL LIMIT/OFFSET，结果库仅是工件，不存原图或正式GT。先测试开关关闭/缺环境拒绝、新旧任务并存、跨项目/重复受理/取消恢复及正式数据不变，再接UI。
4. D由原异常审核结果入口打开Annotorious，传image_id、疑似原因及只读预测。GT更改仍走原接口；review提交再次核对源SHA和GT摘要，过期或保存失败不标已修正；不得向精确重复批删接口传智能分组。原标签Full Audit区域仅增加派生计数/入口。
5. E在upload-confirmation及ZIP已入库任务的原页面增加可选异步入口，保持原回执、任务中心与成功数。关闭开关不拉分析列表或创建分析任务；不新增全局轮询。
6. F先跑A关闭组，任何关键失败先修复不交付。再B开启组，覆盖真实引擎、项目隔离、失败/取消/重试、GT保存冲突及浏览器核心操作。基线通过且未受新改动影响的不重复执行。最终版本/缓存按真实用户可见交付一次递增，正常推送前fetch并核对远端，准确SHA独立CI。

### 本次实际检查记录

- `git fetch origin feature/external-algorithm-publishing`经本机代理成功，远端c88b6151；无工作区业务修改，其他worktree不操作。
- `python -m pytest tests/unit/test_cleaning_analysis_runtime.py tests/unit/test_upload_batches.py tests/unit/test_material_batch_public_truth.py tests/unit/task_runtime/test_worker_runtime_truth.py -q --disable-warnings --maxfail=1`：24 passed / 0 failed / 0 skipped，5 warnings，3.25秒。覆盖真实spawn图像指标、超时终止、上传幂等/顺序、原任务公开状态及持久Worker状态；不是图片上传/ZIP/GT/训练全链路验收。
- 官方API明确默认embedding行为；适配必须禁止隐式默认模型。现有evaluation_analysis.analyze_evaluation_trust已拥有可信冻结划分/SHA泄漏合同，缺证据保持未知；不能直接用当前material.split冒充历史划分。
- 当前尚无本专项业务代码、真实FiftyOne执行或CI结论，不能宣称已集成、零回归或具备部署条件。

### 候选制品实际许可检查

已直接检查pip下载的wheel ZIP（没有import包或执行mongod），而不只依赖网页许可证标签：

| 制品 | 精确版本 | wheel SHA256 | 检查 |
|---|---|---|---|
| fiftyone | 1.22.1 | a5a216ac6aea97fccee95e583d85ffe0de228c7dcd480bd295d3c8c637d13b3e | 内含Apache LICENSE；requires_dist包含独立Brain/db及ASGI依赖 |
| fiftyone-brain | 0.25.0 | b9d3037f2a829cb8da3d02e4786262b6b5af78bc8fa00fc740f14f9011d5a17d | 内含LICENSE，官方项目Apache-2.0；不是直接升级到0.27 |
| fiftyone-db | 1.4.1 Windows | 8840f6c46761e20970cc3f47ee6002233417c6588b9885776e1dde06bdced9e4 | 实际打包mongod.exe；Python封装元数据写Apache并不能覆盖该服务端SSPL |

db wheel只列自身dist-info/licenses/LICENSE，不能据此宣称bundled mongod已经完成商业分发合规。MongoDB具体二进制版本、第三方声明和分发要求仍需独立核验。传递依赖及模型权重清单尚未完成，不提供“所有依赖允许闭源商用”结论。独立环境下载本身不是生产安装；正式项目requirements保持原样。

完整wheelhouse首次下载在scipy-1.18.1（36.7MB）传输中发生files.pythonhosted.org读取超时，pip退出1；不是依赖冲突或引擎执行失败，未安装任何候选包。不能宣称离线安装包已齐备或真实引擎已通过。已读取的三份核心wheel元数据/摘要见[制品初查回执](evidence/fiftyone-wheel-initial-audit-2026-10-26.json)。后续获得运行许可后使用已缓存制品重试下载，不重跑已通过的24项基线。

**阻塞及下一步**：用户附件第八节明确“有许可证风险时要明确列出，不能擅自引入”。已说明SSPL问题，并通过问题卡请求选择是否允许仅在本机隔离PoC运行临时MongoDB，生产安装/分发另行确认。答复前不推进实际引擎运行及依赖它的业务集成。获得允许后先完成B真实执行及制品许可清单，随后按C→D→E→F接续，不能跳过关闭组回归或称为已完成集成。此限制来自用户原始要求，不是引入额外的管理员/部署审批流程。
