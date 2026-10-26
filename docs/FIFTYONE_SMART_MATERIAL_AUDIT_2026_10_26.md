# FiftyOne 可选智能素材分析专项

本文件是本专项唯一需求、设计、进度和接续依据。用户附件681f3943与“最高优先级：现有业务兼容性与零破坏原则”共同构成需求基线；后者优先。2026-10-26真实fetch成功，远端/本地均c88b6151797bf7a122b891f4e336697dd041802a，VERSION42.24.389，初始工作区干净。其他工作树、5944e1a5、原标注WIP和两份训练模板测试保持原样。

## 附件逐项补验：原生定位与标签汇总（2026-10-26）

对照原附件，补齐原生定位差异和标签区派生计数。真实 FO 控制夹具中同类框 IoU=0.6，原仅取 image mistakenness 时漏掉3张定位候选（RED）。现在只读取 Brain 写入 GT 副本的 mistakenness_loc，不另算 IoU/TP/FP/FN；3/3候选 GREEN，原生分类提示0.005、定位提示0.797，不把提示值当准确率。最多返回120条原生框信号且明确 truncated；原 GT、模型预测、评测指标均不变。[真实定位回执](evidence/fiftyone-native-location-2026-10-26.json)。

标签建议入口主动读取后，在原标签完整性区域和分析面板显示：疑似异常图片、疑似漏/多标框、类别/定位差异图片、待复核候选、人工确认或修正候选。来自派生结果 SQL 聚合及原复核回执；没有模型或历史缺字段返回 null/“未检查”。标签冲突继续由原 Full Audit 判断，既有 Full Audit 计数在原区域保留，不复制冲突判定系统。标注保存成功后的派生刷新异步执行，失败不改变原 GT 保存结果；项目变化不向新项目弹出旧保存提示。缩略图仅按当前页懒加载；来源批次只投影既有元数据，缺失显示“未记录”，不扫描全部历史上传回执或补写正式记录。

本增量最小验证：结果/复核4项 Python、相关摘要及上传入口11项 Node、面板及标签区→原GT保存2项真实Chrome通过。上传入口单测确认仅传已成功入库且已选的ID，未调用清洗/ready决策、未改变原上传回执。独立只读审查本增量无阻塞发现。未重复全仓测试，未重复之前关闭组。

**1万/10万规模边界**：[实际隔离元数据探测](evidence/fiftyone-scope-boundary-2026-10-26.json)分别使用原 Repository 写入10000/100000条真实SQLite记录，确认估算在加载ID之前以SMART_AUDIT_SCOPE_LIMIT拒绝，原库摘要不变、无任务/引擎/图片副本。只读准入耗时0.02781/0.01627秒；结束RSS相对开始+16384/-503808字节，不是峰值，也不是FiftyOne全量处理性能。当前sklearn相似比较最坏工作量随N²增长、密集重复对也会N²增长，因此不会把前2000条静默当全库结果。超过2000的完整图像/引擎扫描 **未实现、NOT VERIFIED**；需要有界全局索引/结果量方案后另验，不能通过盲目提高上限宣称已支持10万。此边界不影响原素材库或原清洗规模。

基础集成69e975db的CI仍不代表此补齐代码；下一提交按实际新SHA验收，VERSION保持本轮390。旧9162运行仅对本轮已被取代且未完成的运行安全取消，保留失败记录；其他会话/提交运行未操作。

## 首次推送与缓存守卫修正（2026-10-26）

代码 `9162a21cb1c44d7a53d227a4e967eb3b5d4d3fa2` 已正常推送，未强推。首推准确 SHA 已触发49项 Actions，早期两个 frontend check 失败，不能记为最终绿色。核验发现原版本守卫仍固定 app/main436、material-batches422410、上传 bootstrap422534；本次必要缓存已更新至437/422411/422535。仅同步既有精确缓存断言及一个原workflow grep，不删测试/不弱化断言/不扩大工作流范围。定向旧守卫 RED 后更新，24/24 GREEN，VERSION390保持不二次递增。最终以后续修正 SHA 的独立 CI 为准。

## 当前交付状态：C/D/E 已完成待最终 SHA CI（2026-10-26）

- A 审计已验收；B 引擎提交 `2c219ab7b51481ef984e16f1ad408858cc338e95`；C 后端提交 `9ebf89f991c3ed3294a0f0449755a04a60fd0e74`。本节优先于下面按时间保留的早期“尚未接线/待许可”记录。用户已正式允许本机隔离 PoC，生产许可另行确认。
- C/D/E 已在原素材批任务 Owner 上接通：上传后本批确认（普通图片及 ZIP 已入库后整理）、素材管理/异常 Full Audit、标签完整性区域三个入口共用一个三栏分析面板。原任务提交/轮询及原 Modal、Annotorious、GT 保存继续复用；无新任务中心、无新 API Client、无全局新轮询。仅主动打开时查询可选能力和历史，默认关闭不发智能业务请求。默认整个筛选范围，不暗中限当前页；单次上限默认1000、配置最多2000，超限拒绝并说明，不能当作全库验收。
- 当前公开合同增加仅 SMART_AUDIT 使用的 attempt/result_ready；重试清零、输入/结果摘要及 review expected_generation 一致。一次不确定提交保留原 request_id/范围并幂等重放；使用原 unknown 存储中的 smart:project 键，不阻断原 CLEAN 提交。分析失败不改变原清洗/上传回执状态。
- 派生候选 SQL 每页25条；当前图片、对比图片、只读 GT/预测图层及缩放均复用官方 Annotorious。证据过期不把旧框叠到新像素。人工复核分确认问题/无需修改/未知；“已修正”仅在原工作台真实 GT 保存成功后，再校验新 GT 版本/摘要及源 SHA。自动训练和自动删除均不存在；高级评测与困难样本跳转仍由原页面负责。窗口关闭/任务切换/代际变化立即失效旧请求并清理预览。

### 实际验收与失败记录

| 范围 | 实际结果 | 证据/边界 |
|---|---|---|
| C 原库只读、schema5、GT、缓存、幂等任务、分页与复核 | 69 passed / 0 failed / 0 skipped | 本文 C 阶段命令；非全仓 |
| C/D 审查补齐（代际、缺旧存储不迁移、删除 claim、缓存预算及公开合同） | 18 passed / 0 failed / 0 skipped | 定向 readonly/cache_budget/new API/public truth；与69重叠不累加 |
| 原上传清洗与 GT API 关闭组 | 42 passed 后遇1旧 v47用例失败 | [真实旧失败日志](evidence/fiftyone-off-legacy-failure-2026-10-26.log)；3c7b0060 中该接口已经返回410，不是本轮回归；没有修改或删除该旧测试 |
| 现行 v60 AI 候选/原 Worker 注册/训练成果计数合同 | 44 passed / 0 failed / 0 skipped | [关闭组现行合同](evidence/fiftyone-canonical-off-2026-10-26.log)，替代退役接口验证，不把 mock provider 称真实收费模型 |
| 原异常删除预览/并发 GT 与历史保护 | 2 passed / 0 failed / 0 skipped | test_material_integrity.py 两个原安全用例；隔离数据逻辑索引操作，不是生产删除 |
| Node 原批任务提交/上传确认与新范围/未知恢复 | 31 passed / 0 failed / 0 skipped | [Node 日志](evidence/fiftyone-node-2026-10-26.log) |
| Chrome 原业务关闭组 | 5 passed | 普通上传后的清洗决策、ZIP 自动确认、真实人工 GT 保存、标签 CRUD、训练创建原入口；[日志](evidence/fiftyone-chrome-off-2026-10-26.log) |
| Chrome 新面板开/关、失败、迟到响应、代际、对比图重试、原 GT 保存衔接 | 5 passed | [日志](evidence/fiftyone-chrome-integration-2026-10-26.log)。分析 API 使用明确受控夹具；Annotorious/DOM/原 GT 保存为实际平台，不冒充真实模型质量；真实 FO 由 B/C 隔离工具另验 |
| 视觉复验 | 1920×1080、1366×768 | [1920](evidence/fiftyone-smart-audit-1920.png)、[1366](evidence/fiftyone-smart-audit-1366.png)、[原工作台保存后的返回](evidence/fiftyone-smart-review-original-editor.png)；补齐 hidden 控件被原 btn display 覆盖问题，定向1项复验通过 |
| 真实取消 | CANCELLED，观察到所属 Mongo，最终所属进程0、工作目录清理、原图/GT不变 | [取消回执](evidence/fiftyone-task-cancel-2026-10-26.json)，不是仅 mock 取消 |

审查发现并已定向修复：旧代际详情污染、任务选择被旧轮询抢占、第二张失败图片误载第一张、只读预览消费首次 Esc。首轮浏览器夹具误把静态 JS/CSS 算智能 API 请求、把原隐藏 Modal 要求为 DOM 删除、BMP header 填充不合法、把 SVG 包装节点算两框、误要求恢复已被原 Owner 正常清空的标注队列，均按原合同纠正并保留关键真实数据/点击/身份断言；没有改原业务来迎合夹具。独立只读审查已确认修复，审查不冒充测试。

### 安装、关闭与资源边界

仅 `<data_dir>/smart_material_audit.json` 可选配置，缺省等价 `{ "enabled": false }`。隔离开发示例为 `{ "enabled": true, "python": "C:/tmp/fiftyone-audit-1221/Scripts/python.exe", "max_images": 1000, "timeout_seconds": 600 }`；不得把本机路径当作生产配置。只接受独立 venv 且非 system-site-packages；原 materials Worker 注册时获取附加 capability，旧 Worker 不会误领。启用环境须由部署方核验后按原 Worker 生命周期重启相应 materials 角色，本轮未操作生产。关闭后不再受理新分析、不启动新引擎，派生历史仍可查看；已运行任务通过原取消入口停止。

成功场景峰值进程树 RSS 622628864 字节、临时逻辑字节314835676；故障集合峰值 RSS623509504。临时 Mongo journal 导致约300MiB逻辑增长，不等于物理分配量。没有额外永久图片副本；可选 venv 约894976080字节，wheelhouse240052148字节，供后续离线验收保留，与原环境分离。真实任务成功、失败、取消会按精确归属清理各自工作目录。

**早期 PoC 清理遗留**：已核验 `C:/Users/jorsam/AppData/Local/Temp/smart-audit-poc-8lktx64b` 为首次失败隔离夹具（ownership database_name=smart_audit_bf59f7eaf2824e88a374ff445b50eeb0），无对应 Python/mongod 进程，逻辑314811347字节；带绝对路径、owner、无 reparse 校验的 Remove-Item 被自动审批安全审查拒绝。未绕过限制，该早期目录保持原样，不宣称全机PoC磁盘已清空。不是正式数据目录。

仍 NOT VERIFIED：生产许可/分发声明与 LGPL/native 义务、Linux 离线锁、NAS/OSS/S3、生产真实预测错标质量、1万/10万库规模、生产性能与物理磁盘占用。HOG/颜色192维不等于语义模型。开启组已验真实独立引擎及原 OpenCV 并行、缺环境后原 CLEAN；未将所有业务都在 Mongo 运行期间逐项全链路复测，兼容矩阵按实际证据限定。无生产部署、安装、数据库迁移、GT/素材修改或真实训练。VERSION 本轮一次递增42.24.390，最终代码及文档 SHA CI 待安全推送后独立补记。

## C 后端接线本地验收（2026-10-26，尚未完成前端及最终 CI）

B 提交 `2c219ab7b51481ef984e16f1ad408858cc338e95` 已保留。C 复用原 MATERIAL_BATCH、BatchSelection、TaskRepository、资源锁、lease/fence、取消与重试，额外 capability 隔离旧 Worker。新增专用 API，默认关闭，当前结果按 execution generation 隔离；历史结果不冒充重试结果。正式库使用原 Repository 的只读入口，schema5 不触发升级。原 StorageManager 只在分析实例关闭缓存自动 GC；128 文件/512MiB 预算在远程下载前核验，同 SHA 引用复用。

派生发现 SQL 分页，复核令牌绑定源 SHA、GT 摘要和版本；只有原标注接口真实保存了新 GT，才允许记录已修正。不会写正式 GT、自动训练或自动删除。子进程使用独立非 system-site-packages venv、私有 HOME/配置/临时目录，Mongo 随机回环端口及临时认证，进程身份与父 Worker fence 绑定。

实际定向回归 **69 passed / 0 failed / 0 skipped**，包括旧 schema5、删除 claim、GT 生命周期、源配置、缓存、任务公开合同以及新 API/幂等/分页/复核安全。未跑全仓。真实引擎通过原 Scheduler 的四个隔离场景：成功、bind 阶段 fence 丢失、部分失败后同 Task ID 重试、缺引擎后关闭增强功能继续运行原 CLEAN。对应回执见 evidence/fiftyone-task-*-2026-10-26.json。fixture 首次错误使用 public_dict、错误模拟 bind 权限异常、已修正为原 to_public_dict/真实 fence 语义；不改变原 Scheduler 状态判定。

成功样本进程树峰值 RSS 622628864 字节、临时逻辑空间 314835676 字节；不是物理分配量或生产性能结论。原图/GT 摘要不变、无额外永久图片副本、已确认所属工作目录和进程清理。独立 venv 和 wheelhouse 为后续验收保留。前端三个区域、关闭组完整兼容矩阵、Node/Chrome、最终 SHA CI **未完成**；NAS/OSS/Linux/大库/真实模型错标质量仍 NOT VERIFIED。后续从原 material-batches.js 的提交/轮询 Owner 接 UI，不建第二套任务中心，不扩大存储/训练范围。

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
| A审计/回归基线 | 已验收 | 主要Owner/远端核对及增量方案已记录；原材料/清洗/上传/Worker定向24项通过，不代表完整兼容组 |
| B真实引擎隔离验证 | 已验收 | 真实相似/泄漏/uniqueness/mistakenness API、四同图退化和4项隔离场景通过；生产预测接线仍属C/D |
| C任务/清洗审核 | 已完成待验收 | 默认关闭、分页、取消/恢复、无正式数据写入及旧Worker兼容 |
| D标签/人工复核 | 已完成待验收 | 原接口/GT CAS/源SHA、审核过期与失败保护 |
| E上传后入口 | 已完成待验收 | 原批次/ZIP完成后显式异步入口、不阻塞回执 |
| F回归/审查/准确CI | 进行中 | 必须先A关闭组，再B开启组；未通过不交付 |

## 兼容性验收表

下列按实际隔离验证范围记录；生产和未执行路径不因“未改代码”推定通过。关闭组范围见顶部；开启组完整原业务全链路仍 NOT VERIFIED。

| 原模块 | 修改前行为 | 修改后必须保持 | 本专项回归 |
|---|---|---|---|
| 图片上传 | 原multipart/Uppy/批次回执 | 上传成功不等待分析 | 关闭组API与Chrome上传决策通过；开启组全链路 NOT VERIFIED |
| ZIP导入 | 原分片、标签确认、后台入库 | 原协议/恢复/GT不变 | 关闭组原Chrome自动确认通过；真实生产ZIP NOT VERIFIED |
| 素材管理 | 原分页筛选/预览/安全删除 | 不增加全库前端加载 | 原浏览器分页/标注入口及新面板范围通过；大库 NOT VERIFIED |
| 素材清洗 | SHA/dHash/OpenCV/正式结果 | 不换算法/阈值/成功含义 | 原API通过，缺引擎后同Scheduler原CLEAN成功；算法不替换 |
| 异常审核 | Full Audit/GT冲突及预检 | 智能候选不进入自动删除 | 原两个删除/GT并发保护API通过；新入口不传自动删组 |
| 标签统一 | 原映射/Full Audit | 不改正式标签及原流程 | 标签CRUD Chrome通过；完整统一流程 NOT VERIFIED |
| 人工标注 | Annotorious/GT CAS/源SHA | 仍通过原保存接口 | 原人工保存Chrome及新面板→原GT保存衔接通过 |
| AI标注 | 原provider/候选/审核 | 不依赖引擎可用性 | 现行v60原候选/API通过；真实收费模型 NOT VERIFIED |
| 训练创建 | 原准入/冻结/创建 | 不接入本分析依赖 | 原标签/提交Chrome通过；真实GPU禁止/NOT VERIFIED |
| 训练任务 | 原lease/恢复/成果 | 不改状态和副本生命周期 | 原任务公开合同与安全case通过；真实训练恢复 NOT VERIFIED |
| Worker调度 | capability/资源独占/fence | 不新增调度器或抢占 | 原注册/能力隔离、fence、重试、实际取消通过 |
| 模型成果 | 原版本/Checkpoint/可信结果 | 只读引用、不改成果 | 原成功成果计数合同通过；真实模型质量 NOT VERIFIED |

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

## 用户授权接续与真实问题（2026-10-26）

用户选择“允许隔离PoC，生产许可另行确认”，并明确原Python/Worker环境及正式数据不可修改。此前许可问题已解除本机PoC阻塞，生产安装/分发仍未授权。安装仅C:/tmp/fiftyone-audit-1221，独立venv非system-site-packages，120个wheel共240052148字节，离线pip安装成功且pip check无冲突；原requirements不改。

首批配置/输入合同6项RED→GREEN；默认无配置不建文件、不导入FiftyOne。首次真实执行中过早读取安装中的namespace失败，待安装完成后恢复；第一次完整真实引擎执行相似配对断言失败且Windows临时目录清理遇文件锁，尚未修复验收，未隐藏失败。静态核验发现FiftyOne MultiClientService按服务类型复用既有服务，且stop仅断开客户端；不能依赖此机制保证独立dbpath。改为sidecar显式启动专属mongod、回环随机端口、禁默认服务、精确进程句柄等待退出，正在真实复测。所有临时路径均属本次PoC，原图只读引用，不访问正式库。

首个视觉特征选用明确标注的hog-color-v1（HOG形状+颜色直方图192维），不加载模型、无权重许可/下载、不冒充语义模型，也不替换dHash；真实匹配/相似/泄漏/uniqueness仍调用FiftyOne Brain。任意候选都须人工复核。首版输入上限2000（默认1000）以拒绝未经验证的大库内存风险；1万/10万未实测且不声称支持，后续扩容必须给出真实索引和内存证据。

## B阶段本地验收回执（2026-10-26）

- A文档3c7b0060383781fabca394cbaa0485c441a68382自身21/21 Actions、55/55 Checks成功；不是B代码CI。
- 独立venv仅在C:/tmp，离线pip安装成功、pip check无冲突；锁文件optional-dependencies/fiftyone-windows-py312.lock.txt含120个精确版本/wheel哈希，仅Windows/CPython3.12，不加入主服务requirements。完整元数据/许可路径见evidence/fiftyone-resolved-wheels-2026-10-26.json。传递LGPL组件与MongoDB SSPL的生产分发义务仍待审核；不宣称清单等于法律许可通过。没有模型权重或GPU依赖下载。
- 真实官方接口compute_similarity、compute_near_duplicates、compute_leaky_splits、compute_uniqueness已运行，缩放JPEG与原PNG实际欧氏距离0.330387324，第三张不同图片不进入该配对。预测空缺明确未检查。compute_mistakenness以受控预测/GT夹具真实运行，copy_missing=False，3张显式空GT得到3个疑似漏标候选；这是API结构验证，不是真实训练模型质量结论。证据evidence/fiftyone-real-engine-2026-10-26.json。
- 实际失败：默认cosine后端会中心化输入，改变余弦语义并原位修改数组；改为归一化特征Euclidean及传副本，阈值与距离如实记录，不输出相似百分比。独特性不是质量分，四张全相同图片导致上游NaN；独立审查发现后改为null/not_checked，allow_nan=False，四同图真实复测通过。Brain无GT匹配时的mistakenness=-1也转换为null，不冒充有效分数。
- 默认MultiClientService存在跨dbpath服务复用及stop不等待退出的问题，未采用。只使用其固定版本single-client父进程死亡监视器，显式自有mongod、随机回环端口、独立数据库名/目录、禁默认服务及Python外网socket，finally删除精确自有数据库并等待退出；禁止任意Mongo扫描/批量终止。强制guardian停顿时，原ProcessController按PID/创建时间/命令hash升级终止已验收。
- 正常、os._exit崩溃、超时取消三项真实隔离验收通过，期间原image_metrics（含OpenCV）正常；guardian_stall第四项通过，原环境已安装包列表指纹前后一致，所有本次子进程结束。首guardian测试的监测器在进程恰好退出时遭NoSuchProcess，修正仅监测器退出竞态后复测通过；没有降低“进程零遗留”或原图SHA断言。证据evidence/fiftyone-fault-isolation-2026-10-26.json及fiftyone-guardian-stall-2026-10-26.json。
- 资源实测：整棵进程树峰值RSS最大623509504字节（约594.6MiB）；临时文件逻辑大小峰值314813143字节（约300.2MiB），MongoDB journal占主要部分，非图片集副本；已随本次自有临时根目录清除。物理分配量未测。正常冷PoC总42.953秒含启动及原OpenCV首次加载，Brain小样本分析约4–5秒；guardian故障case总71.078秒含30秒关闭截止。不能拿这些数字推断大库/生产性能。
- 保留可复用的开发环境894976080字节、离线wheelhouse240052148字节；均在本机C:/tmp且不提交二进制。没有复制正式素材，测试使用2–4张合成图片，原路径/字节不变。
- 纯主环境合同7/7通过（默认关闭无FiftyOne import、无目录创建、严格bool/输入身份、外网DNS拒绝及socket恢复）。没有重跑24项未受影响基线，也没有跑全仓或GPU。
- C/D/E尚未实现：正式任务/可信预测/GT绑定、分页审核与原标注保存联动、上传入口、关闭组完整回归、浏览器与最终准确CI；本阶段不称平台集成完成，不建议生产部署。
