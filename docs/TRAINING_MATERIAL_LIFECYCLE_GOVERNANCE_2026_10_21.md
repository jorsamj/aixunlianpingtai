# GT 素材保护、训练数据单份存储及历史 Bundle 生命周期治理

> 本专项唯一需求与进度依据；更新日期：2026-10-21（Asia/Shanghai）。
> 仓库：`jorsamj/aixunlianpingtai`；唯一长期分支：`feature/external-algorithm-publishing`。
> **当前接续：第十节“训练准入诊断与素材删除治理一体化专项”（GOV-01–11），阶段A进行中。2026-10-21新增指令优先；旧MLG任务及历史记录保留，不代表已实现。图片单份存储和工作Bundle回收仍未开始，本轮不擅自扩大到生产清理。**

核验基线：2026-10-21 实际 `git fetch origin` 后，本地及远端长期分支均为 `067e60fab9c51d46434dc9309b1bd1af275adcd8`，`VERSION.txt=42.24.369`，目标工作区初始干净。原始 cwd 为另一个 `wip/42.25-codex-interrupted` 工作区，未在那里修改、切换或丢弃任何变更。

本次建立文档基线；首推CI另发现既有Chrome测试瞬态竞态，仅修复 `tests/browser/material-integrity-governance.spec.mjs` 隔离夹具同步。不修改运行时代码、数据库 Schema、前端资源或 VERSION。文档提交身份用 `git log -1 --format=%H -- docs/TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md` 查得；不得把上面的代码审计基线误作最终交付 SHA。后续开发提交和实际 CI 逐项登记于第七节。全部开发及最终验收尚未完成。

## 一、项目背景与问题

这是正式运行系统的原架构优化，不另起项目。用户反映历史成功任务、Snapshot、独立 Test 及模型引用长期阻止当前 GT/素材删除；同图同 GT 重复记录和同图不同 GT 冲突组均可能无法治理。多个任务反复复制相同图片，任务 `work/bundle` 与 Training Bundle Cache 并存，存储持续增长。历史评测又依赖冻结图片和 GT，不能简单解除全部保护后直接删除文件。

当前仓库既有治理链已经支持审计、服务端全选冻结、预览、凭证、DELETE_INDEX、Worker 重验和 GT 删除补偿；已有 Cache 生命周期文档 [TRAINING_BUNDLE_CACHE_LIFECYCLE.md](TRAINING_BUNDLE_CACHE_LIFECYCLE.md) 只描述持久缓存 TTL/LRU，不覆盖任务工作 Bundle 生命周期。它继续作为既有实现参考，不作为本专项进度源。

旧 [训练质量追踪](TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md) 的 TQ-08、旧 handoff 及 AGENTS 历史条目记录的是当时保护策略和既有验收，不能解释成本轮新需求已经实现。本专项经用户明确确认的新业务规则优先；旧的 SHA/CI 仍仅证明旧合同。

## 二、用户确认的正式需求

以下是已确认业务规则；附录 A 保存用户原始第 1–14 节全文，包含操作范围、测试矩阵和交付要求。第 15 节文档治理要求完整转为本节及第五、七、九节的约束，不依赖聊天记录。

| 编号 | 已确认需求 | 验收关键点 |
| --- | --- | --- |
| MLG-01 | 历史任务不再永久保护当前素材/GT | SUCCEEDED、历史 Snapshot、Test、模型版本均不能天然禁止当前逻辑删除；保留历史证据及引用查询 |
| MLG-02 | 排队不锁素材；启动时重核验并冻结 | 保存原精确范围，剔除失效项，不增加其他素材；10,000→删除500→实际9,500；不足则明确失败 |
| MLG-03 | 活动训练、准备、评测及必要恢复保护实际输入 | 允许逻辑删除；物理回收须等无真实消费者，不能只凭状态或过期计数 |
| MLG-04 | GT 冲突和重复素材可整组、批量及筛选全删 | 明确整组删除无需选正确GT；保留一张、指定删除、修改GT等既有流程继续可用 |
| MLG-05 | 相同 SHA256 图片尽可能只保存一份不可变内容 | 图片身份与 image_id、GT版本、Snapshot、task_id分离；不同GT不合并；其他项目/当前记录共享字节不误删 |
| MLG-06 | 训练器兼容与多 Worker 共享读取 | 复用 Ultralytics；禁止可写硬链接/越界软链接；优先安全只读视图或 CoW，受控复制兜底；远端缓存有配额、引用、核验、淘汰、恢复与真实占用 |
| MLG-07 | 完成训练后安全回收多余工作数据 | 模型、指标、Snapshot/Manifest/冻结GT、独立评测、下游依赖先核验；成功后自动回收；失败/取消按真实恢复依赖判断 |
| MLG-08 | 历史模型留证据，完整复评不永久承诺 | 分开模型可用、证据可用、冻结GT可用、原图可读、无法完整复评；归档指标不能冒充当前复验 |
| MLG-09 | 历史任务也有资格分析和安全回收 | 只读扫描、原因、预计空间、dry-run、幂等执行、审计、中断恢复；三个指定生产任务只能列候选 |
| MLG-10 | 复用原界面并统一前后端事实 | 治理显示选择/退出/当前GT/物理释放/延迟回收/历史复评影响；训练显示请求/冻结/剔除/划分/状态；存储分层实际占用和安全余量 |
| MLG-11 | 并发、迁移和完整性底线 | 冻结GT不可变、SHA划分隔离、并发租约及fencing、跨项目授权、数据库/文件非原子补偿、幂等迁移、不猜旧GT版本、外键实际检查 |
| MLG-12 | 唯一正式专项文档和准确 SHA 验收 | 每阶段真实进度/问题/测试/提交/CI；顶部双入口；最终长期分支正常推送及最终SHA核验；不写凭据 |

删除合同：逻辑删除使当前素材与当前 GT 退出可选库；物理回收是无当前保留需求、无活动使用且完成安全核验后的另一动作。历史溯源不等于活动租约。QUEUED/PENDING 不因排队保护；PREPARING/RUNNING/EVALUATING/必要活动恢复保护输入字节；SUCCEEDED 不因历史永久保护；FAILED/CANCELLED 在活动资源安全释放后解除活动保护。

冻结合同：记录创建请求数、启动有效数、剔除数、最终 Train/Val/Test 数、最终 Snapshot ID、实际图片及 GT 哈希。冻结完成后不得悄悄增减样本；同 SHA 不跨划分。老已冻结排队任务不能原地改冻结证据，须明确兼容处理。固定 Benchmark 输入缺失时不得擅自用当前同名图或额外素材替代。

报告合同：保留模型、日志、指标、Snapshot、Manifest、必要冻结GT及来源。用户给出的报告代表图建议为 12–24 张真实固定抽样缩略图，优先异常/漏检/误检/困难样本；这是建议范围，抽样策略和兼容迁移是技术设计待验证项，不能把原报告最多12个引用当作已完成缩略图归档。

授权：允许代码审计、必要前后端与兼容Schema迁移、隔离测试/Chrome、CI修复、按规范版本及文档更新、验收后正常快进推送长期分支。禁止生产DB/图片/GT/模型/Bundle/缓存删除或修改、生产部署、真实GPU训练、真实成果修改、生产外部写接口、OSS操作、强推或覆盖其他会话变更。生产历史清理需独立授权。

**分类标记：** 上述规则为“已确认需求”；第四节为“技术实现选择/候选，尚未落地”；生产容量、远端文件系统/权限、租约失联行为、历史GT完整性等为“尚待验证条件”。不要互相替代。

## 三、现有代码与架构分析

### 3.1 已核验的事实源和正式链路

| 入口/模块 | 代码审计事实 | 复用与改造边界 |
| --- | --- | --- |
| `platform_core/material_repository.py` | `materials.sqlite3` 的 materials、material_labels、material_annotation_scopes、material_meta、material_migrations、material_storage_audit；SHA为可重复索引，`get_by_content_sha256` 取一条；`_connect` 开启foreign_keys | 保留当前素材唯一Owner；SHA有索引不等于已实现不可变字节唯一存储 |
| `platform_core/annotation_repository.py` | `annotations.sqlite3`，当前schema3；annotations有version/content_digest；annotation_delete_backup、annotation_label_references、annotation_meta；当前`_connect`设置busy_timeout，未见foreign_keys=ON | GT唯一authority；version/CAS、delete prepare/finalize/restore/complete继续用；当前GT版本号不等于可遍历历史GT库 |
| `platform_core/material_batches.py` | `_historical_material_references` 汇总Task payload/input-freeze、Snapshot Test、算法/评测历史，默认纳入protected；未知历史读取失败阻止治理 | 保留审计与查询；历史引用退出逻辑删除禁止语义；活动字节资格单独核验 |
| 同上治理链 | `create_material_integrity_plan`→执行锁内复验→`prepare_batch`/`publish_prepared_batch`→MaterialBatchHandler→`_delete_index_rows`；已有DISCARD_CONFLICTS显式确认，但仍受protected及test阻断 | 不是新增整组删除器；必须同步计划、预览、提交、Worker及单张/批量/全选 |
| 同上删除执行 | `_delete_index_rows`在label/material fence内校验身份及活动引用，通过GT删除备份补偿再移除material；DELETE_INDEX不删除共享原图 | 继续复用；不可把逻辑索引删除说成实际释放磁盘；跨SQLite与文件操作不是一个原子事务 |
| `app.py`训练提交、`platform_core/remote_training_tasks.py` | 已有 TRAINING_PREPARE；`TrainingPrepareHandler._freeze_request_contract` 在material fence内解析Benchmark/duplicate review、selection/标签合同并freeze写`input-freeze.json` | 启动准备已有冻结入口；原选择失效剔除、旧已冻结任务兼容、真实消费者租约仍待审计和改造 |
| `platform_core/training_tasks.py` | `freeze_training_inputs`、`resolve_training_input_freeze`、materialize/verify/resolve_remote_training_bundle；TrainingHandler要求READY，优先读已冻结合同；旧无freeze有兼容路径 | 保留Snapshot身份、Manifest完整性、远程边界及最终逐文件SHA核验，不建立第二验证器 |
| 同上图片构建 | `_copy_verified_isolated`和`_normalize_training_image`先隔离复制，缺EOI JPEG修复到任务副本；记录source/training两个SHA及size | 规范化图必须独立不可变内容，不冒充source SHA |
| `platform_core/training_bundle_cache.py` | schema3、项目隔离、Snapshot锁、TTL/LRU/配额；恢复`_clone_bundle`用`shutil.copy2`图片/标签，明确禁止可写硬链接；schema2不准入 | 保留完整性、访问统计及维护；这不是工作Bundle自动回收，也不是单份图片实现 |
| `platform_core/task_runtime/` | TaskRepository为canonical task；已有lease_token/expiry、Worker接管、process identity、fenced repository/调度机制 | 扩展原生命周期边界；任务租约不是已有逐图片字节租约的证明 |
| 远端数据 | `remote_training_tasks.py`、`remote_training_transport.py`、`node_agent_training_runtime.py`、`remote_material_lifecycle.py` | 继续用现有Agent/传输/台账；本次未完成逐个远端读消费者及缓存淘汰审计 |
| 归档/评测/恢复 | TrainingHandler `_finalize_completed_job`依赖`work/bundle/manifest.json`构造benchmark并归档result/cache；`training_evaluation.py`、`training_recovery_tasks.py`、`training_recovery_api.py`及模型资产承担各自事实 | 删除工作图前必须解除报告/复评/恢复的真实路径依赖；不能只加finally rmtree |
| 前端 | `static/modules/material-batches.js`、`training-material-summary-runtime.js`、`training-recovery-runtime.js`、`reports.js`及现有存储入口（存储入口调用链仍须继续核对） | 复用MaterialBatch/TrainingMaterialSummary/TrainingRecovery、既有PollRegistry；无新菜单、Owner或后台轮询 |

### 3.2 第一阶段十项问题的当前答案

1. 图片读取发生在准备/staging/materialize/hash、Trainer数据加载、独立评测、报告图片预览及必要恢复；逐消费者精确释放时点尚未完成枚举。
2. 现有任务排队与准备子任务不同；`_ACTIVE_INPUT_STATUSES`及活动引用检查会把排队合同纳入保护，必须核对状态/阶段/所有权而非仅改状态枚举。
3. 当前GT在AnnotationRepository；Material只保存投影。冻结合同/Snapshot/Bundle隐藏Test GT是训练证据，不能随当前GT删除而重写。
4. SHA已有字段、规范化查询和重复分组索引；未见以SHA唯一约束管理全部原始字节的统一不可变存储合同。全导入及对象路径仍需追踪。
5. portable dataset和Cache恢复确实创建任务副本。正式素材所有导入通道是否重复写物理字节未完成审计；不以索引重复等同物理重复。
6. JPEG标准化会改任务副本；已安装Ultralytics的坏JPEG修复也可能原地写图片；disk cache会写npy，labels cache也需隔离。只读共享不能凭假设放行。
7. 本机`D:/python/Lib/site-packages/ultralytics`为8.4.127；`data/utils.py::img2label_paths`将images目录映射为labels；`verify_image_label`调用`check_image`，后者可原地修JPEG；`data/base.py::cache_images_to_disk`写npy。这里只完成源码审计，未完成真实YOLO Dataset加载验收，不能代表生产A800环境。
8. 历史完整复评需要原冻结图片字节、GT、类别目录、划分/benchmark绑定、可用模型及预处理合同；旧预览已有Snapshot/manifest/实际字节SHA校验。原图缺失必须明示不可完整复评，不得回退同名当前图。
9. TRAINING_COMPLETED_HISTORY、IMMUTABLE_SNAPSHOT、FROZEN_TEST_SNAPSHOT、MODEL_OR_EVALUATION_HISTORY等历史策略须改为溯源/能力影响；保留历史证据，不机械删除整个函数。
10. 活动准备/训练/评测/校准/必要恢复、多Worker、共享当前素材及清理并发仍需要保护；现有fence、delete claim和task/process fencing必须保留。未知字节依赖时拒绝物理回收，不应永久拒绝当前逻辑删除。

### 3.3 根因与审计缺口

根因是历史溯源和当前删除禁止共用protected集合，且计划/提交/Worker多点重复使用；数据冻结早于真正训练执行的兼容形态不一；图片及GT任务布局与原字节保留资格未分离；Cache回收与task work回收是不同生命周期。上述代码可证明现状，不证明本次已经修复。

剩余A：全量调用点及真实读消费者清单、DB外键运行核验、远端Task/Agent所有权接管与恢复、所有上传/导入内容身份、模型/转换/发布文件依赖、历史兼容数据形态、存储界面真实统计来源。未完成前不将A标为验收。

## 四、技术设计及取舍

以下是实施候选及约束，尚未提交运行时代码；在A完成后用真实契约细化并更新决策。不得把候选表名/字段误读为已迁移。

| 决策 | 拟采用方案和原因 | 替代方案、风险与待验证 |
| --- | --- | --- |
| TD-01 引用关系 | 在Material/Task/Snapshot原Owner中区分当前记录、活动字节租约、历史来源；不足才加最少索引；候选键含project/task/snapshot/image_id/image_sha/GT digest/split/type/state/created/released及generation | 不建第二素材库/调度器。只改historical protected集合不足以保护逻辑删除后活动源图；新增表会带来跨库一致性与修复成本，须先证明必要性 |
| TD-02 GT与Snapshot | 复用Annotation version/digest和现有input-freeze/Manifest保存不可变GT证据；source SHA与training SHA分开 | 不把image SHA当GT身份，不推造旧GT版本，不原地升级旧Snapshot；证据不全明确unknown |
| TD-03 活动租约 | 用原material fence串行化准入/逻辑删/回收claim，绑定原task lease、execution generation、消费者与物理内容；接管需旧进程停止证明后fence | 单凭TaskStatus、计数或TTL到期删除不安全；Worker断网仍可能读数据。续约、释放及失联保守保留策略须真实并发测试 |
| TD-04 排队重冻结 | 任务保存原精确ID范围；准备开始取仍有效子集，GT/SHA/标签/类别/泄漏复验并一次冻结；持久化请求/实际/剔除/划分证据 | 不重新执行宽泛筛选吸入新增图。旧冻结任务用显式派生/兼容决议而不重写原证据；固定Test/补数据协议缺项可能必须阻断 |
| TD-05 图片单份 | 优先复用现有SHA和存储Provider，建立不可变字节身份与当前记录映射；项目授权和保留关系独立；规范化图用独立内容身份 | 跨项目全局去重不是跨项目读取授权；现有对象可能可变或无可靠SHA，需要受控回退；重复导入语义不得合并不同GT |
| TD-06 训练布局 | 首选可证明Trainer不写源的轻量只读视图；实际平台支持时用reflink/CoW隔离写；其余受控复制并在任务结束回收 | 可写硬链接禁止，软链接不能绕过根目录；坏JPEG修复/npy/labels.cache写入须隔离；Windows/Linux/跨文件系统/权限不同，不能承诺零复制 |
| TD-07 远端缓存 | 复用Agent、现有传输与缓存，以内容身份核验、本机配额和活动引用管理受控副本，统计实际独占/共享字节 | 不为每任务永久保留一整份；共享索引不意味着跨机零传输；缓存淘汰与远端失联必须有fence和幂等恢复 |
| TD-08 Bundle回收 | 复用task artifacts/恢复/归档Owner，先验证best/last、正式版本/模型、指标、Snapshot/Manifest/冻结GT/评测、转换发布及下游；留轻量证据和真实抽样缩略图；失败checkpoint单独管理 | 原评测/预览仍引用work路径，先完成证据搬迁及可用性投影；直接rmtree task目录或仅SUCCEEDED判断均不可接受 |
| TD-09 物理删除状态机 | 候选→锁内重验并claim/fence→I/O→持久化审计/完成；失败或重启据claim幂等恢复；新引用必须拒绝已claim内容或重建到新generation | 可用隔离/rename机制须先核验平台与共享语义；DB提交与文件删除不能假装原子，不能无索引就猜可回收 |
| TD-10 历史/迁移 | 只读发现、缺证据拒绝物理回收；幂等schema升级及回填可信身份；不改变已有Task/版本/Snapshot事实 | 全量搬迁生产原图不在本轮授权内；旧FAILED恢复价值不能仅看文件存在；外键需逐连接实测，不能只查schema |

Schema落地前必须记录每个字段唯一Owner、唯一约束/索引、升级版本、旧数据空值语义、重复执行结果、失败补偿及兼容读取。SQLite跨materials/annotations/task库不能凭foreign_keys=ON实现跨库外键；复用既有补偿协议，实测事务边界。方案尚未满足安全前置条件时继续其他可独立任务，不能先删文件。

## 五、开发任务清单及进度

状态仅使用：**未开始、进行中、已完成待验收、已验收、阻塞**。初始“A待核验”按统一状态映射为A进行中（已有部分审计）；各阶段验收以实际测试及准确提交CI为准。

| 阶段 | 工作内容 | 状态 |
| --- | --- | --- |
| A | 当前架构及数据契约审计 | 进行中 |
| B | GT历史保护解耦与整组删除 | 未开始 |
| C | 排队任务启动时重新冻结 | 未开始 |
| D | 图片单份存储及共享读取 | 未开始 |
| E | 工作Bundle生命周期与自动回收 | 未开始 |
| F | 前后端联调、测试、CI验收 | 未开始 |

| 任务/需求 | 优先级/模块 | 状态 | 已完成 | 剩余工作 | 风险/阻塞 | Git Commit | 测试和验收证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A-01 架构、历史与活动引用/MLG-01,03,11 | P0；MaterialBatch/Repository/Task | 进行中 | 第三节已审计关键入口及历史保护根因 | 补齐全消费者和远端/恢复/fencing、DB运行契约，定稿TD-01/03 | 活动源逻辑删除后不能丢失保留资格；无外部阻塞，未完成审计 | 审计代码067e60fab9c51d46434dc9309b1bd1af275adcd8；本次文档提交见git log | T-A-01/02/03；仅旧合同基线 |
| A-02 图片/GT身份及训练器写入/MLG-05,06,11 | P0；Annotation/Snapshot/训练器/导入/Agent | 进行中 | GT version/digest、双SHA、Cache copy及本机8.4.127写入风险核验 | 全导入路径、内容存储和跨Worker契约、实际外键验证、真实加载试验 | 只读共享兼容和生产文件系统未知 | 同A-01 | T-A-03；真实YOLO加载NOT VERIFIED |
| B-01 历史解耦与统一整组/MLG-01,04 | P0；material_batches/API/原治理前端 | 未开始 | 复用点与旧保护位置已定位 | 新合同RED→改计划/预览/执行/Worker；重复/冲突/异常单批全选；历史/Test逻辑删除允许 | 必须和B-02共同闭环，不能只跳过protected | 无开发提交 | 新合同测试未执行 |
| B-02 活动字节延迟回收/MLG-03,11 | P0；Material/Task/现有生命周期fence | 未开始 | 已识别delete claim/GT补偿能力 | 实现可靠活动保留、逻辑删除和共享所有权、并发租约/失联fence | 不得根据过期任务状态物理删除 | 无开发提交 | 多消费者、失联、准入/删除竞态未验证 |
| C-01 原范围启动重冻结/MLG-02,11 | P0；TrainingPrepare/selection/freezer/恢复 | 未开始 | 已定位_freeze_request_contract及READY读取 | 保存原范围/数量，剔除失效不扩围，重新准入/划分/冻结，老队列兼容 | Benchmark/Test/补数据协议及类别不足须阻断 | 无开发提交 | 10,000→9,500、冻结前后GT、旧任务测试未执行 |
| D-01 原图不可变内容与GT分离/MLG-05 | P0；Material/导入/Provider/Snapshot | 未开始 | SHA索引和GT authority核验 | 去重字节、授权/保留映射、规范化独立身份、幂等迁移 | 历史外部对象可变；跨项目授权 | 无开发提交 | 重复导入/共享删除/规范化双SHA未做新合同验收 |
| D-02 训练共享视图及远端缓存/MLG-06 | P0；BundleCache/materialize/Agent | 未开始 | 当前复制与隔离原因明确 | 只读/CoW探测与受控复制、配额、活动淘汰/恢复、真实空间统计 | Trainer原地修JPEG、npy/cache写入；跨文件系统与权限 | 无开发提交 | reflink/权限/软硬链接/真实YOLO/多Worker未验 |
| E-01 新任务自动归档与回收/MLG-07,08 | P0；finalize/recovery/evaluation/ModelArtifact | 未开始 | 成功归档依赖work manifest已定位 | 成功/失败/取消/恢复资格，证据/缩略图、历史能力、下游依赖、幂等状态机 | 先证明模型推理/转换/发布不依赖待删文件 | 无开发提交 | 回收后推理/转换/发布/报告未验 |
| E-02 历史扫描与dry-run/MLG-09 | P0；原Task artifacts/存储治理 | 未开始 | 三候选及授权边界已登记 | 只读扫描/空间/原因、隔离回收/审计/中断恢复 | 51GB是用户历史估计，非当前测量；生产清理未授权 | 无开发提交 | 真实生产只读未执行，隔离执行器未实现 |
| F-01 前后端字段及交互/MLG-10 | P1；原治理/训练详情/存储入口 | 未开始 | 保留唯一Owner的界面方向已确定 | 实际数量、影响、占用、进度/终态/错误码；真实Chrome | 缺事实时不能展示虚假0或完成 | 无开发提交 | Node/Chrome未执行 |
| F-02 最终测试、质量及CI/MLG-11,12 | P0；相关tests/既有workflows/版本/文档 | 未开始 | 已有旧合同基线和本专项台账 | 各阶段RED/GREEN、API/文件链/Chrome、最终HEAD全部实际Actions/Jobs、最终交接 | 不降低断言、不借旧SHA绿灯；生产/GPU不在本轮内 | 无开发提交 | 第七节；完整专项验收未完成 |
| DOC-01 文档治理/MLG-12 | P0；本文件、AGENTS、CODEX_CURRENT_STATE | 已验收 | 需求全文/任务/根因/候选设计/测试/生产边界建立 | 首提交及修正已推送，949961c3 CI21/21、55/55及Chrome112/112通过；本次验收结果补记文档提交须重核自身CI，以后每阶段持续更新 | 后续不得另建同专项平行进度文档 | 首提交f632f0f2876edc3aefc796e2a17f43d3a13021e3；修正949961c3775a4349a6462f7f6647e88ef58b1f0d；补记文档提交由git log查得 | T-DOC通过；949961c3 CI通过见第七节；不冒充B–F完成 |

各任务拆分仍归属上表，不新增第二进度源；每阶段执行顺序为新合同失败用例→确认RED→原Owner最小实现→直接回归GREEN→接口/文件链和必要Chrome→复核风险→更新台账→提交→准确SHA CI。代码实现细节需在A剩余核验完成后记录，不先臆造函数/表。

## 六、问题及修复记录

| 编号 | 状态 | 问题、范围与根因 | 修改/回归及关闭证据 |
| --- | --- | --- | --- |
| BUG-01 | 未开始 | 历史Task/Snapshot/Test/模型protected集合阻断当前逻辑删除，影响计划/提交/Worker | 代码位置已核验；由B-01修复，尚无新合同RED/GREEN，不写已修复 |
| BUG-02 | 未开始 | 活动输入引用与逻辑删除阻断混用；简单取消检查会丢失物理保留资格 | B-02完成字节租约/fence及并发测试后关闭 |
| BUG-03 | 未开始 | 排队原范围素材缺失的剔除/数量及旧freeze兼容未形成新合同闭环 | C-01处理；已有prepare freeze不能证明新需求通过 |
| BUG-04 | 未开始 | Cache恢复及materialize复制图片；Cache维护不处理历史task work | D/E处理；不能将cache命中或TTL清理当成单份图片或工作回收 |
| RISK-01 | 进行中 | Annotation连接未显式启用foreign_keys；需验证有无适用约束、Task库及实际连接值 | 尚未做运行核验，不称已发现外键损坏或已修复；A-02跟踪 |
| ENV-01 | 已验收 | 基线长临时目录WinError206：T-A-01为28通过14失败；同源码短目录T-A-03为41通过1软链接skip | 只改变测试目录，不改代码/断言/系统长路径设置；确认本批长路径失败可由短目录消除，不宣称平台长路径问题已修复 |
| ENV-02 | 已验收 | 首次短路径复测父目录C:/t不存在，T-A-02有24个setup error | 建立空父目录后使用全新basetemp复测；T-A-03无setup error；不掩盖失败尝试 |
| CI-01 | 已验收 | f632f0f2前端Chrome为111通过1失败：真实删除已结束，测试仍等瞬态“删除中”；原隔离Worker与浏览器轮询无同步 | 仅测试Handler在真实Scheduler认领租约后等浏览器放行；原运行中/Worker/删除125条/仅剩1条/GT及审计断言保留，新增放行前删除0条；3次重复通过，完整素材治理Chrome 8/8通过；修正SHA949961c3775a4349a6462f7f6647e88ef58b1f0d已CI21/21、55/55及Chrome112/112通过；不修改产品状态或Mock成功 |
| ENV-03 | 进行中 | 本机无法创建symlink，相关用例跳过 | CI/Linux或有能力的隔离环境需实际执行；未关闭软链接安全验收 |

新发现问题追加唯一编号，写明影响、根因证据、真实修改、回归命令、提交和关闭条件；推测与已复现Bug分开。需求变化也必须保留原因及影响：本轮2026-10-21用户明确取消历史永久保护，覆盖旧TQ-08保护语义，影响所有删除决策/队列/归档/历史复评；不是旧安全门禁被无理由移除。

## 七、测试与 CI 记录

### 7.1 实际本地测试（代码均为067e60fab9c51d46434dc9309b1bd1af275adcd8）

以下只验证既有Material/GT lifecycle、Snapshot和Cache合同，**不验证B–F新需求**。三次执行为同一组42例，不能累加成独立通过数。JUnit原始文件已产生于本会话本地证据目录；跨会话无需这些文件即可从命令、数量和测试名复验。

```powershell
python -m pytest -q --confcutdir=tests/unit tests/unit/test_material_annotation_lifecycle.py tests/unit/test_snapshots.py tests/unit/test_training_bundle_cache.py --basetemp=C:/t/mlg21b --junitxml=<独立证据目录>/mlg-a-final.xml
```

复验前创建不存在的短路径父目录；basetemp必须是**新的、仅供本次测试使用的空目录**（pytest会清理指定目录），禁止指向生产、仓库或既有用户数据。

| 编号 | 阶段/运行条件 | 通过 | 失败 | Error | 跳过 | 结果及证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T-A-01 | A基线；长basetemp `C:/Users/jorsam/.codex/tmp/mlg-a-20261021` | 28 | 14 | 0 | 0 | 退出1；WinError206及衍生文件路径错误；mlg-a-baseline.xml |
| T-A-02 | A诊断；`C:/t/mlg21a`但父目录尚不存在 | 18 | 0 | 24 | 0 | 退出1；WinError3 setup；mlg-a-shortpath.xml |
| T-A-03 | A对照；创建C:/t父目录后新`C:/t/mlg21b` | 41 | 0 | 0 | 1 | 退出0；mlg-a-final.xml；`test_cache_resolve_rejects_in_bundle_symlink_component`因本机无法创建symlink跳过 |
| T-DOC | DOC-01：9节、12需求、阶段/任务状态、原文全文/SHA、双入口、源码路径、范围、无凭据及diff检查 | 9检查组通过 | 0 | 0 | 0 | 文档校验退出0；本地git diff --check退出0；只验证文档合同，不算业务测试 |
| T-CI-01 | 隔离Chrome竞态修正：`npx playwright test tests/browser/material-integrity-governance.spec.mjs --grep 'real frozen scope' --repeat-each=3` | 3 | 0 | 0 | 0 | 同一真实文件链重复3次，不算3个不同用例；原RED为首SHA CI上述失败 |
| T-CI-02 | `npx playwright test tests/browser/material-integrity-governance.spec.mjs`（完整规格） | 8 | 0 | 0 | 0 | 本地真实Chrome；含CI-01目标场景，和重复3次存在重叠不累计独立用例 |
| T-DOC-02 | 最终修正提交前：原文完整性、九节、任务状态、双入口、精确SHA CI来源、四文件范围、Node语法和diff重验 | 通过 | 0 | 0 | 0 | 不把文档校验算业务验收；9个校验组 |
| T-B/C/D/E/F | 各阶段新需求/完整Node/新功能Chrome/GPU | 未执行 | 未执行 | 未执行 | 未执行 | 不记为0失败或已通过；真实GPU训练不在本轮授权内 |

原始本地证据目录：`C:/Users/jorsam/.codex/visualizations/2026/10/21/01a15d6e-6553-7640-9e31-04ade914aca9/`。关键夹具包括原图独立副本、防硬链接、项目隔离、冻结修订、GT生命周期互斥及TTL/LRU；symlink未实测不能计通过。后续重要验收摘要和CI链接必须持久化进仓库，不能只引用本机文件。

### 7.2 CI登记规则与本批边界

本批为文档基线及既有Chrome隔离夹具同步修正，不改工作流触发范围制造绿色。`remote-training-runtime.yml`、`training-input-integrity.yml`、`training-final-validation-hardening.yml`、`material-annotation-atomicity.yml`、`frontend-runtime-stabilization.yml`、`v42.25-release-regression.yml`等原流程是后续运行时代码的验收入口；每次根据实际改动和paths核验触发，不把未触发算通过。

| 提交 | 范围 | Actions / Jobs | 结论 |
| --- | --- | --- | --- |
| 067e60fab9c51d46434dc9309b1bd1af275adcd8 | 本轮只读代码基线 | 本次未复核该旧提交远端CI | 不借用旧绿灯 |
| f632f0f2876edc3aefc796e2a17f43d3a13021e3 | 首推三个Markdown | 实查21 Actions：20成功、1失败；55 Checks/Jobs：54成功、1失败 | Chrome 111通过1失败，CI-01；不是全绿 |
| 949961c3775a4349a6462f7f6647e88ef58b1f0d | 三个Markdown接续+隔离Chrome夹具 | 实查21/21 Actions、55/55 Checks/Jobs成功；Chrome112通过0失败0跳过 | CI-01及文档基线已验收；不代表A–F开发验收 |
| 本次验收结果补记文档提交（git log定位） | 仅三个Markdown | 须按文档自身实际HEAD重查全部push/PR Actions及Checks | 以GitHub原生绑定结果为最终证据，不继承上行绿色；如失败必须修复 |

最终SHA自引用说明：提交无法在自身内容中写入自身哈希。阶段提交SHA在下一次文档更新显式登记；最终文档提交以git对象身份为准，准确SHA的Actions/Jobs结果通过GitHub原生绑定查询核验。若验收结果补写产生新提交，新HEAD也必须重查；不得无穷借用前一次CI。最终完成交付前本节须有实际代码提交、修复提交、工作流run/job链接及成功/失败/跳过/未触发明细；本基线不宣称该最终交付已达到。


首推SHA逐工作流回执（同一SHA；pull_request触发基于已有PR全量差异，不等于本次修改了那些模块）：

| Workflow | Event | 结论 | Run |
| --- | --- | --- | --- |
| Video Frame Recovery | pull_request | success | [39566463409](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463409) |
| AI Annotation Recovery | pull_request | success | [39566463405](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463405) |
| External Algorithm Platform | pull_request | success | [39566463601](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463601) |
| ChangLian Login Auth | pull_request | success | [39566463512](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463512) |
| Node Agent Executor | pull_request | success | [39566463378](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463378) |
| External Algorithm Publish | pull_request | success | [39566463549](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463549) |
| Training Input Integrity | pull_request | success | [39566463562](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463562) |
| Storage Cache Governance | pull_request | success | [39566463616](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463616) |
| Remote Conversion Runtime | pull_request | success | [39566463521](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463521) |
| Remote Training Runtime | pull_request | success | [39566463391](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463391) |
| Remote Cleaning Runtime | pull_request | success | [39566463419](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463419) |
| Central Node Assignment | pull_request | success | [39566463446](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463446) |
| Remote RKNN Board Runtime Protocol | pull_request | success | [39566463462](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463462) |
| Portable Deployment | pull_request | success | [39566463495](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463495) |
| Resource Discovery SQLite Stability | pull_request | success | [39566463424](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463424) |
| GPU Runtime Truth | pull_request | success | [39566463428](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463428) |
| Task Runtime Truth | pull_request | success | [39566463535](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463535) |
| Remote Material Import | pull_request | success | [39566463619](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463619) |
| Online Feedback Runtime | pull_request | success | [39566463422](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463422) |
| Label Normalization Contract | pull_request | success | [39566463370](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566463370) |
| Frontend Runtime Stabilization | push | failure | [39566457772](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566457772) |

首推Chrome失败Job：[browser-navigation](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39566457772/job/119109799023)；首推[准确SHA全部Checks](https://api.github.com/repos/jorsamj/aixunlianpingtai/commits/f632f0f2876edc3aefc796e2a17f43d3a13021e3/check-runs?per_page=100)。API分页须查至无后续页，本次21 runs/55 checks均在第一页且total_count吻合。未触发的工作流不计通过。


修正代码提交 `949961c3775a4349a6462f7f6647e88ef58b1f0d` 的实际终态回执：**21/21 Actions completed/success，55/55 Checks/Jobs success，0失败、0运行中、0跳过**；前端真实Chrome **112/112通过**（7.0m）。与首提交f632f0f2结果分别保留，不混计、不借绿灯。

| Workflow | Event | 结论 | Run |
| --- | --- | --- | --- |
| Task Runtime Truth | pull_request | success | [39568913580](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913580) |
| AI Annotation Recovery | pull_request | success | [39568913562](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913562) |
| Storage Cache Governance | pull_request | success | [39568913722](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913722) |
| Remote RKNN Board Runtime Protocol | pull_request | success | [39568913462](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913462) |
| External Algorithm Publish | pull_request | success | [39568913599](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913599) |
| GPU Runtime Truth | pull_request | success | [39568913822](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913822) |
| External Algorithm Platform | pull_request | success | [39568913671](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913671) |
| Label Normalization Contract | pull_request | success | [39568913532](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913532) |
| Resource Discovery SQLite Stability | pull_request | success | [39568913610](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913610) |
| ChangLian Login Auth | pull_request | success | [39568913768](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913768) |
| Video Frame Recovery | pull_request | success | [39568913639](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913639) |
| Online Feedback Runtime | pull_request | success | [39568913733](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913733) |
| Remote Cleaning Runtime | pull_request | success | [39568913668](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913668) |
| Central Node Assignment | pull_request | success | [39568913701](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913701) |
| Training Input Integrity | pull_request | success | [39568913864](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913864) |
| Portable Deployment | pull_request | success | [39568913692](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913692) |
| Remote Conversion Runtime | pull_request | success | [39568913746](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913746) |
| Remote Material Import | pull_request | success | [39568913648](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913648) |
| Node Agent Executor | pull_request | success | [39568913501](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913501) |
| Remote Training Runtime | pull_request | success | [39568913845](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568913845) |
| Frontend Runtime Stabilization | push | success | [39568905964](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568905964) |

修正提交[完整Checks](https://api.github.com/repos/jorsamj/aixunlianpingtai/commits/949961c3775a4349a6462f7f6647e88ef58b1f0d/check-runs?per_page=100)、[完整Chrome Job](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39568905964/job/119117874952)。本轮本地软链接skip仍未被这份摘要证明已执行，专项D/F的软链接矩阵仍待实测。

**本次补记只验收文档基线与测试夹具修正**；A仍进行中，B–F未开始，生产未操作。补记产生的文档提交必须按自身实际HEAD重查全部CI，结果原生保存在该提交Checks上；本节代码修正SHA的绿色不能替代文档新HEAD核验。后续接手可用`git log -1 --format=%H -- docs/TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md`定位文档提交并查询`/repos/jorsamj/aixunlianpingtai/actions/runs?head_sha=<该SHA>&per_page=100`及`/commits/<该SHA>/check-runs?per_page=100`，查全分页，不依赖本机回执。

### 7.3 后续测试矩阵（全部待执行）

素材：历史成功/Test引用当前GT可删、不同GT整组删、同GT保留/全删、批量/筛选全选、预览执行一致、活动字节和共享原图安全。队列：10k-500、类别/样本不足、冻结前后GT、SHA跨划分严格隔离、旧任务兼容、真实YOLO加载。存储：重复导入/多次训练独占字节不持续增长、CoW/复制兜底/权限/软硬链接/跨文件系统、回收后推理/转换/发布、报告真实性、FAILED恢复、并发引用/中断/重复回收/多Worker。前端：真实Chrome批量整组删除及进度终态、实际冻结数、历史复评能力、占用与回收状态。全部使用隔离数据，关键文件链不得用mock成功替代，不删测试、不跳断言、不降低安全门禁。

## 八、历史数据治理及生产风险

下列容量为用户提供的**2026-10-20历史估计**，非本次生产测量。约51GB合计=约31GB成功候选+约20GB失败任务；不得直接相加宣称可释放空间。

| Task ID | 历史状态/估计 | 当前判断 | 已完成代码支持/隔离验证/生产核验 |
| --- | --- | --- | --- |
| train_24766a1c81dd4392bc4216a8 | SUCCEEDED，约16GB | 后续只读资格核验候选，未证明可回收 | 新回收执行器未实现；隔离回收未验；生产未连接/未扫描/未清理 |
| train_41d78077c794484597866867 | SUCCEEDED，约15GB | 同上；须查归档与评测/下游消费者 | 同上 |
| train_2f0f0d22e2c647829e04d7a9 | FAILED，约20GB | 须先明确checkpoint、原训练恢复合同与活动Owner | 同上；不能因FAILED自动删除 |

本轮生产实际释放空间：**未执行回收，未测量释放量**。已有Cache维护代码不证明这三个work已回收。未来dry-run必须分别报告逻辑大小、物理独占字节、共享/CoW估计及无法测量值；无事实不报预计全额释放。禁止递归删除整个task_runtime/artifacts，Checkpoint与模型成果不能随图片工作集一起抹掉。

生产只读核验尚未执行；后续只读资格分析与真实清理分开。实际生产清理、部署、迁移搬运、OSS写删、真实训练及真实模型成果修改都需独立操作授权；在得到授权前仅隔离文件验证。Worker失联、未知引用、索引缺失、路径link/reparse、外项目共享、权限异常、下游活动状态不明时拒绝物理回收并显示具体原因。

## 九、后续计划及接续指令

1. 接手先读本文件、AGENTS永久约束和真实代码；`git fetch origin`、核验长期分支HEAD/工作区/并行修改，不依赖旧聊天或本地绝对证据路径。当前工作区为 `C:/Users/jorsam/.codex/worktrees/external-algorithm-publishing/畅联云算法训练_v42.14.0`，其他机器须自行定位。
2. 从 `material_batches.py::_historical_material_references`、`_assert_not_referenced_by_active_tasks`、`create_material_integrity_plan`、执行复验、MaterialBatchHandler删除路径开始，补齐A的活动消费者/字节保留合同；检查app.py直接删除与训练准入等所有调用点，不能只改单个入口。
3. 接着读 `remote_training_tasks.py::TrainingPrepareHandler._freeze_request_contract/_prepare_bundle`、`training_tasks.py::freeze_training_inputs/TrainingHandler`、task_runtime fence与generation、Annotation/Material fence。明确何时开始真实读取、失败/接管如何延续保留，并记录所需最小Schema变更。
4. A完成数据契约后按B→C→D→E实施；B的活动保护未安全闭环前不解除物理保护。D先实测YOLO实际写入、内容去重和只读/CoW可行性，不能移除现有复制隔离后直接共享可写原图；无法安全共享时保留受控复制兜底并记录局限。
5. E优先解决finalize/评测/恢复/报告对work的路径依赖，验证归档模型仍可推理、转换、发布，再做历史只读扫描和隔离执行。不要拿三个生产任务试删。F贯穿每阶段接口、Node、Chrome及实际CI。
6. 既有测试起点：`tests/unit/test_material_reference_reasons.py`、`test_material_annotation_lifecycle.py`、`test_snapshots.py`、`test_training_bundle_cache.py`、`test_portable_dataset.py`、`tests/api/test_material_integrity.py`、`test_training_conflict_governance.py`、`tests/integration/test_remote_training_prepare_task.py`、`test_training_input_integrity_chain.py`、`tests/browser/material-integrity-governance.spec.mjs`及原训练详情/报告浏览器测试。旧合同若明确与本轮需求冲突需升级为新合同，不能削弱活动/共享/身份安全断言。
7. 每完成阶段更新本文件任务行、问题关闭证据、实际Commit、测试通过/失败/error/跳过数；新需求写变更原因与影响。AGENTS和CODEX_CURRENT_STATE顶部只同步入口、阶段、结论及待办，不复制全文。禁止另起同专项计划/验收/进度MD形成第二权威。
8. 阶段提交前运行`git diff --check`、审查范围/敏感信息、再fetch避免覆盖其他会话；仅正常快进推送长期分支，不合并main、不强推、不发生产部署。按本次实际代码变更依仓库规范处理VERSION；本次文档基线保持42.24.369。
9. 全部运行时代码开发完成后：更新本文件最终完成/局限及生产边界、两个顶部入口、相关实际测试与CI；文档与代码提交推送，验证远端最终实际HEAD。追加文档产生新SHA须重新检查其CI，最终给用户GitHub专项链接。未达到时保留未完成状态，不能用“已具备回收能力”替换“生产空间已释放”。

变更日志：2026-10-21 建立唯一专项基线；现有旧保护策略与用户本轮新业务规则明确分开；A部分只读审计、T-A-01/02失败及T-A-03复测如实记录。未修改任何运行时保护，未声称开发完成。949961c3修正提交CI 21/21、55/55及Chrome112/112通过；本次补记文档提交自身仍需独立核验。首推f632f0f2 CI发现既有测试运行中瞬态竞态，按CI-01只修隔离测试同步，不将B–F标完成。

## 十、训练准入诊断与素材删除治理一体化专项（当前权威接续）

### 10.1 最新授权、基线与规则变更

最新用户指令完整留存于附录B；本节与原MLG共享唯一进度文档，不另建专项。开始已实际git fetch origin feature/external-algorithm-publishing，远端/本地均232e475521b62004ed6e68728fe562231b85130b、VERSION42.24.372、工作树干净；已查工作树和会话，旧D盘WIP及其他工作树不动，未见其他同仓库活动开发。前轮Annotorious最终21/21 Actions、55/55 Checks、Chrome175/175已验收，不替代本轮CI。

本轮正式链：准入诊断→定位真实问题→用户选择草稿排除或当前素材删除→服务端不可变预览→原后台任务执行→仅同步实际成功ID→自动完整重新预检。GOV删除规则覆盖原先永久历史/Test/活动逻辑保护：历史成功/失败请求、Snapshot、当前Test和排队均允许当前索引及当前GT退出；活动真实输入及共享字节仍保留，未知物理资格一律延期。GT冲突整组丢弃不要求Keeper；保留某张时才核验Keeper。诊断不得凭issue_count猜类型，不以算术扣数直接恢复训练。

授权必要前后端、兼容Schema及迁移代码、隔离测试/Chrome、文档与验收后正常推送长期分支。禁止生产素材/GT/Snapshot/Bundle/模型删除、项目清空、数据库迁移、部署、真实GPU训练及强推。本轮界面危险确认仅在隔离测试验证；不代表获得生产删除授权。原约51GB/31GB/20GB仅历史估计，空间未释放；本轮没有承诺Bundle回收或图片内容库改造。

### 10.2 初审事实与设计边界

现有MaterialBatch已经具有FILTERED服务端分页全选、selection.sqlite3持久冻结、DELETE_INDEX、Worker恢复/进度及GT删除补偿；完整性治理已有DISCARD_CONFLICTS但历史/Test/protected仍阻断。generic DELETE_INDEX显式选择当前仍限500；计划、提交和Worker需统一新语义。现有TrainingMaterialSummary有兼容性签名、问题分页、治理预览及单张排除；须进一步核对final Submit全部阻塞与Modal生命周期。以上仅代码初审，不作为新需求通过证据。

设计遵循原Owner：扩展原MaterialBatch计划/estimate/create/Worker，所有删除入口使用同一不可变目标与资格事实；逻辑退出与字节回收分别报告；原训练Draft/Submit/MaterialSummary统一收集阻塞，不建第二Modal/Tooltip/Loading/任务库或调度器。选择冻结须绑定project、material/GT revision、SHA/digest、操作者与确认范围，执行重验；管理员项目清空必须服务端鉴权及项目名称确认。技术接口/Schema增量在A审计完成后定稿，优先无需搬迁的兼容扩展；不为未知空间编造释放估算。

### 10.3 任务清单（本轮初始状态）

| 需求 | 优先级/模块 | 状态 | 已完成 | 剩余/风险 | Commit | 验收证据 |
|---|---|---|---|---|---|---|
| GOV-01 自动诊断 | P0 Submit/MaterialSummary/Modal | 进行中 | 附件基线与入口初读 | final阻塞/once签名/草稿恢复；加载不误报 | 未提交 | 未执行 |
| GOV-02 全部阻塞 | P0 兼容API/Submit | 进行中 | 问题类型及真实数量要求确认 | 算法/素材/GT/审核/SHA/Test/母模型/版本/资源全链审计 | 未提交 | 未执行 |
| GOV-03 单张/批量/整组 | P0 MaterialBatch/AnnotationRepo | 进行中 | DISCARD_CONFLICTS复用点定位 | Keeper只适用保留；三层资格一致 | 未提交 | 新合同未执行 |
| GOV-04 筛选全部 | P0 MaterialSelection/Batch | 进行中 | FILTERED持久全选已存在 | 全分页1000+、版本/SHA/GT冻结/恢复 | 未提交 | 新合同未执行 |
| GOV-05 全问题排除/删除 | P0 兼容API/Draft/Batch | 未开始 | 确认38张按image_id去重 | 服务端真实全问题选择及只改草稿/永久删除区分 | 未提交 | 未执行 |
| GOV-06 管理员清空 | P1 API权限/Batch/素材UI | 未开始 | 当前项目范围与名称确认需求确定 | 管理员鉴权、精确计划、GT/Test影响及恢复 | 未提交 | 未执行 |
| GOV-07 历史/Test规则 | P0 material_batches | 进行中 | 历史protected混用已定位 | 统一预览/提交/Worker和历史复评提示 | 未提交 | 新合同未执行 |
| GOV-08 活动/共享安全 | P0 Task/Material/prepare | 进行中 | DELETE_INDEX不删除共享图片已定位 | 活动消费者/queued重冻结、当前退出后引用可读、并发fence | 未提交 | 未执行 |
| GOV-09 预览与后台 | P0 Batch/Worker/审计 | 进行中 | 原selection/task/恢复可复用 | 精确影响、幂等提交、GT revision、实际成功结果/错误 | 未提交 | 未执行 |
| GOV-10 自动完整复检 | P0 Draft/MaterialSummary/Task | 未开始 | 正确流程已确定 | 只同步成功ID、部分成功、项目/草稿身份、全准入重核验 | 未提交 | 未执行 |
| GOV-11 集成验收文档 | P0 tests/既有CI/本文件 | 进行中 | 单一权威基线建立 | RED→GREEN、Python/Node/Chrome、版本、准确HEAD CI | 未提交 | 本文件及双入口已建立；不代表功能完成 |

阶段A只读审计/RED进行中，B统一资格、C扩展删除、D自动诊断、E进度复检、F端到端均未开始。每阶段更新实际文件、根因/替代方案/风险、测试通过失败跳过数及Commit。当前未运行新合同测试，不借旧合同绿灯。仅审计子代理可同时只读；实现任务按依赖顺序、代码与规范独立复核，避免共享文件并行改动。

### 10.4 本轮接续与禁止重复建设

继续从material_batches的parse_request/estimate_batch/prepare_batch、create_material_integrity_plan/执行/Worker/_delete_index_rows和Material/Annotation生命周期fence开始；训练端从training-submit、training-material-summary-runtime、training-draft-runtime/兼容性API及TrainingPrepare启动冻结开始。先完成A所有实际消费者与权限/删除入口审计，再建立RED后最小修改。保持Annotorious正式GT/CAS/SHA及旧历史证据不变。新问题即追加，最终SHA/CI未到不得写已验收。

## 附录 A：用户原始开发指令（第 1–14 节，完整留存）

以下仅为需求来源原文，实际进度始终以上面台账为准；原文中的建议与已确认业务原则按第二/四节区分。附件路径仅用于本次录入，不作为未来接续依赖。原文UTF-8（去BOM、统一LF）SHA256：`e72cf551a7d275e7c53308d4b275ab6b70374e70a3d86c562f469a9a282b3d67`；字符数10,780。


<details>
<summary>展开原始需求全文</summary>

# 畅联云算法训练平台｜GT 素材保护重构、训练数据单份存储及历史 Bundle 回收开发指令

## 一、接手项目及开发授权

你现在继续开发正式运行的畅联云算法训练平台。

**GitHub 仓库：** `jorsamj/aixunlianpingtai`

**唯一长期开发分支：** `feature/external-algorithm-publishing`

最近已知状态：

- HEAD：`067e60fab9c51d46434dc9309b1bd1af275adcd8`
- VERSION：`42.24.369`
- 核验日期：2026-10-21

上述状态仅是已知基线，必须在开始前重新 fetch 最新远端状态。

这是现有正式系统的架构优化，不允许另起项目或重建现有训练平台。

### 本轮授权

允许：

1. 拉取和审计现有代码。
2. 修改必要的前后端代码。
3. 修改必要的数据库 Schema，并提供兼容迁移。
4. 增加回归测试及浏览器测试。
5. 修复本轮改动引起的 CI 问题。
6. 按仓库现有规范更新版本及开发文档。
7. 验收通过后推送至唯一长期开发分支。

禁止：

- 修改或删除生产数据库记录。
- 删除生产图片、GT、模型、Bundle 或缓存。
- 执行生产部署。
- 擅自运行真实 GPU 训练。
- 修改真实训练成果和模型版本。
- 调用生产外部写接口。
- 操作生产 OSS。
- 强制推送、覆盖其他工作区或丢弃已有未提交变更。

本轮先完成代码层面的正式开发与隔离环境测试。真实生产历史数据清理必须作为单独授权的操作。

---

## 二、用户已经确定的最终业务原则

本次必须明确改变现有素材保护策略。

### 原有策略

当前平台存在以下问题：

1. 历史成功训练永久保护相关素材。
2. 历史 Snapshot 和独立 Test 持续保护图片。
3. GT 冲突素材即使用户明确选择整组删除，也可能无法删除。
4. 同图同标注重复记录因历史保护无法正常清理。
5. 训练期间复制大量图片，成功后长期保留 `work/bundle`。
6. 多个训练任务重复使用同一批图片，却产生多份 10–20GB 物理副本。
7. Training Bundle Cache 和任务工作 Bundle 形成额外存储占用。

用户不接受这些数据被永久锁定。

### 最终采用的新原则

**1. 历史训练不再永久保护正式素材。**

历史成功模型、历史 Snapshot、训练指标、算法版本和模型转换成果，不再默认阻止用户删除当前素材与 GT。

**2. 排队任务不保护素材。**

QUEUED / PENDING 等尚未实际开始数据准备的训练任务，不因为任务已经创建就永久锁定素材。

排队期间用户可以删除素材。

真正开始执行时，根据原任务明确选定的范围及当时有效的素材重新核验，再冻结数据。

**3. 活动训练必须保护正在使用的输入。**

实际数据准备、冻结、复制或共享视图创建、训练执行、独立评测以及必要的活动恢复期间，保护已经被使用或即将读取的物理数据。

允许用户对这些素材发起逻辑删除，但不能在活动使用期间破坏底层文件。

**4. 训练完成后释放活动保护。**

确认模型归档、评测与结果持久化完成，且没有活动消费者之后，解除训练活动保护。

历史引用只用于溯源和能力判断，不再自动转化为永久的物理删除禁止。

**5. 正式图片尽量只保存一份。**

相同图片 SHA256 对应的不可变图片内容，原则上只存储一份。

训练任务保存引用和冻结证据，而不是长期复制全量图片。

**6. GT 冲突允许整组删除。**

用户明确选择“删除整个问题组”时，可以同时删除该组全部当前图片记录和对应当前 GT，无须先判断哪一套 GT 正确。

但必须保证不破坏活动训练输入，也不能误删其他素材记录共享的底层图片。

**7. 历史完整复评不是永久承诺。**

保留模型、日志、指标、Snapshot、Manifest、必要的冻结 GT 证据和历史训练来源。

如果原始图片后续被实际删除，历史报告必须准确显示无法完整复评。

不得伪造数据可用性或重新使用当前素材冒充历史数据。

---

## 三、第一阶段：全面只读审计现有实现

修改代码之前，先完成针对性的调用链核验。

重点检查：

- `platform_core/material_batches.py`
- `platform_core/material_repository.py`
- `platform_core/training_tasks.py`
- `platform_core/training_bundle_cache.py`
- Snapshot / Manifest 构建与校验
- Training Prepare / Training Handler
- Task Runtime / Worker 调度
- 远程 Worker 数据传输
- GT 审计、重复素材审计及批量删除
- 模型归档、独立评测与历史报告
- 相关 API、前端模块及现有测试

以上只是已知入口，必须根据实际调用关系追踪，不应限定为固定文件清单。

重点回答：

1. 哪些状态下系统真正读取图片？
2. 哪些状态只是排队、等待调度？
3. 当前 GT 如何持久化？
4. 图片 SHA256 是否已经有唯一身份管理？
5. 当前图片是否存在相同内容多份物理副本？
6. 训练时哪些文件可能被修改？
7. Ultralytics 当前怎样查找图片和标签？
8. 完整历史复评具体依赖哪些图片和 GT 文件？
9. 目前有哪些历史保护判断可以取消？
10. 哪些活动读写依赖必须继续保护？

必须区分“旧业务策略造成的永久保护”和“数据一致性必需的活动保护”。

不要为了简化业务规则，直接删除所有防护代码。

---

## 四、第二阶段：重构素材引用与保护规则

### 4.1 建立统一的使用关系

优先复用现有 MaterialRepository、Snapshot、Manifest 和 Task Runtime。

如果已有数据结构能够可靠维护引用关系，应扩展原结构。

确实缺少时，可以增加最少量必要的索引表，例如：

`training_asset_references`

名称仅作示例，以仓库现有设计规范为准。

建议记录：

- project_id
- task_id
- snapshot_id
- image_id
- image_sha256
- annotation_version_id / annotation_digest
- split
- reference_type
- lifecycle_state
- created_at
- released_at

根据实际需要增加必要的唯一约束和索引。

注意区分：

- 当前素材所有权
- 活动训练使用租约
- 历史溯源记录
- 底层文件实际保留资格

历史溯源记录不等于活动租约。

历史记录存在，也不意味着必须永久保存图片字节。

不要创建第二套素材库、第二套 Snapshot 管理器或独立任务调度系统。

### 4.2 素材保护状态

实施以下业务规则：

| 状态 | 当前素材允许删除 | 底层文件保护 |
|---|---|---|
| 未被使用 | 是 | 无其他必要引用时可回收 |
| QUEUED | 是 | 不因排队任务保护 |
| PREPARING | 是，可逻辑删除 | 正在处理的数据必须保护 |
| RUNNING | 是，可逻辑删除 | 活动输入必须保护 |
| EVALUATING | 是，可逻辑删除 | 活动评测数据必须保护 |
| SUCCEEDED | 是 | 不因成功历史永久保护 |
| FAILED | 是 | 仅活动恢复、重试或其他真实依赖保护 |
| CANCELLED | 是 | 活动资源释放后解除保护 |
| 历史模型版本 | 是 | 不构成永久物理保护 |

这里的删除分为两个动作：

**逻辑删除：** 当前素材和 GT 立即退出可用素材库，不再被新任务选中。

**物理回收：** 当前素材无其他保留需求、没有活动租约且符合安全清理条件后，删除底层文件。

两者不可混淆。

对于活动任务，应支持延迟物理回收，而不是永远拒绝用户删除。

### 4.3 并发与异常保护

必须处理：

- 用户删除与训练准备同时发生。
- 用户删除与 Snapshot 冻结同时发生。
- Worker 接管任务时素材被删除。
- 多 Worker 同时引用同一张图片。
- Worker 失联但任务可能仍在运行。
- 清理任务和新训练引用同时发生。
- 数据库提交成功但文件操作失败。
- 文件回收中断后重复执行。

应利用已有任务所有权、锁和状态机制，补足必要的活动租约及 fencing。

不允许仅根据 TaskStatus 或一个可能过期的引用计数删除物理文件。

历史记录可以保留；活动租约必须能够可靠获取、续约、释放和核验。

---

## 五、第三阶段：彻底解决 GT 冲突与重复素材删除

统一使用现有的素材治理执行链路，不要建立平行删除器。

### 5.1 同图同标注

支持：

- 保留一张、删除其余重复记录。
- 删除指定图片。
- 批量删除。
- 删除整个重复组。
- 删除当前筛选结果的全部可选素材。

当多个当前记录共享同一物理图片时，删除其中一个记录不得影响其他记录。

### 5.2 同图不同标注

支持：

- 人工选择正确 GT。
- 保留指定一张。
- 修改指定 GT。
- 删除错误标注。
- 删除指定素材。
- 删除整个冲突组。
- 批量删除多个冲突组。
- 删除全部当前筛选冲突组。

**明确执行整组删除时，无须人工判断哪套 GT 正确。**

删除整组后，这些素材和对应当前 GT 均退出正式素材库。

如果底层图片还被其他当前素材记录使用，必须保留共享字节。

如果某个活动训练正在使用该图片或冻结 GT，保留其执行所需的不可变数据，直到活动结束。

### 5.3 异常素材

将单张、批量、筛选结果全部删除规则统一。

包括：

- 重复素材
- GT 冲突
- 标注异常
- 图片损坏
- 标签不一致
- 其他当前质量审计识别的异常素材

不要让用户分别进入多套不同删除逻辑。

### 5.4 去除历史永久保护

重点修改原有：

`_historical_material_references()`

以及相关规划、预览和执行前二次核验。

要求：

- 历史成功训练不再天然阻止当前素材删除。
- 历史 Snapshot 不再天然阻止当前素材删除。
- 历史 Test 基准不再天然阻止当前素材删除。
- 历史模型版本不再天然阻止当前素材删除。
- 活动任务的真实依赖仍然受到保护。
- 后端预览结果和实际执行规则必须一致。

保留原有审计证据与历史引用查询能力，但改变其删除决策语义。

不能只改前端按钮或跳过 `group_protected` 判断。

必须完整修复 API、规划、Worker 执行和执行前复验。

---

## 六、第四阶段：排队任务采用启动时重新冻结

用户确认：

排队过程中，如果素材被删除，允许任务最终使用更少的素材开始训练。

但必须满足以下要求：

1. 任务排队期间不持有长期素材活动租约。
2. 任务原始选择条件和选择范围必须保存。
3. 实际开始准备训练输入时，重新查询有效素材。
4. 仅从原任务有权使用的素材范围中剔除已删除或已失效记录，不擅自扩展到额外素材。
5. 重新执行 GT、图片 SHA256、类别映射和数据完整性核验。
6. 重新确定 Train / Validation / Test。
7. 完成最终 Snapshot 冻结后再开始训练。
8. 正式训练开始后禁止偷偷增加或减少输入样本。
9. 训练结果必须记录实际使用数据，而不是创建任务时的旧数量。

例如：

创建训练任务：10,000 张。

排队过程中：用户删除 500 张。

实际启动：符合准入条件的有效素材为 9,500 张。

系统使用 9,500 张重新冻结并训练。

同时记录：

- 创建时请求数量
- 启动时实际有效数量
- 排队期间剔除数量
- 最终 Train / Val / Test 数量
- 最终 Snapshot ID
- 实际图片和 GT 哈希

如果有效样本不足、某个类别没有足够样本，或无法满足独立测试隔离条件，应明确阻止启动，给出可理解的原因。

不得用虚假数量或自动复制样本补足。

对于老版本已冻结但仍排队的任务，必须提供安全兼容及迁移处理，不能擅自修改已有冻结证据。

---

## 七、第五阶段：建立图片单份存储及训练共享读取

本阶段是本轮核心架构改造。

### 7.1 核心目标

**同一份图片被不同训练任务使用时，不再为每个任务永久生成一整份物理副本。**

同一 SHA256 的真正相同图片，优先共享唯一的不可变物理内容。

用户希望：

- 正式素材只保留必要的一份图片。
- 训练任务引用图片而不是复制图片。
- 历史版本通过索引记录来源。
- GT 可以独立版本化。
- 任务成功后自动释放工作区临时数据。

### 7.2 不可变图片和 GT 分离

明确分离：

图片内容身份：SHA256。

当前素材记录身份：image_id。

冻结 GT 身份：annotation digest / version。

数据集身份：snapshot_id / revision。

训练任务身份：task_id。

同一图片可以拥有不同 GT 版本，不得因为图片 SHA256 相同就合并不同的标注语义。

同一图像内容不得跨 Train / Val / Test 划分，防止数据泄漏。

历史训练使用的 GT 证据不能因为用户修改或删除当前 GT 而被静默重写。

### 7.3 训练器兼容方案

继续使用现有 Ultralytics YOLO，不允许为省空间而大规模修改第三方训练框架。

先审计当前 YOLODataset、图片路径、标签路径及缓存规则。

优先研究：

1. 不可变图片的安全只读引用。
2. 与 YOLO 目录布局兼容的轻量训练视图。
3. 文件系统支持时采用 Reflink / CoW。
4. 无法安全共享时采用受控复制兜底。

要求：

- 不使用可写硬链接共享原图。
- 不允许训练器修改共享原始图片。
- 不允许软链接绕过现有路径边界。
- 不允许破坏 Manifest 的 SHA256 校验。
- 不允许跨项目越权读取图片。
- 不允许因更换存储方式而改变训练 GT。
- 必须区分原始图片、经过标准化处理的训练图片和临时派生图片。

如果训练所需图片字节与原始素材 SHA256 不一致，必须把它当作独立不可变内容，不能错误复用原图。

### 7.4 多 Worker

考虑现有 A800 和未来 A/B/C/D 分布式 Worker。

共享索引不意味着跨服务器完全零传输。

远程 Worker 可以使用共享存储或受控本地缓存，但不能为每个任务永久保留一份完整素材。

Worker 本地缓存必须具备：

- 内容身份核验
- 容量配额
- 活动引用保护
- 安全淘汰
- 异常恢复
- 实际空间统计

不得另外新建一套 Worker 调度系统。

---

## 八、第六阶段：成功与失败任务的 Bundle 生命周期

### 8.1 成功训练

SUCCEEDED 之后，必须先核验：

- best.pt / last.pt
- 正式模型版本
- 训练指标
- Snapshot
- Manifest
- GT 冻结证据
- 独立评测结果
- 下游活动引用
- 转换及发布依赖

通过后自动执行轻量归档和临时工作数据回收。

历史训练报告默认只展示少量代表性图片。

建议提供 12–24 张固定抽样的真实缩略图，优先覆盖异常、漏检、误检和困难样本。

不需要为展示历史报告永久保留成千上万张图片副本。

### 8.2 失败训练

FAILED 任务按实际情况区分：

- 仍有活动恢复流程。
- 有可恢复 Checkpoint。
- 已无恢复价值。
- 可重新从当前素材创建新任务。
- 输入已经不可用。

不能因为 FAILED 就永久保留 20GB 工作副本。

但如果用户明确需要继续原训练，且正在执行有效恢复流程，不能误删必要的数据及 Checkpoint。

建议分别管理 Checkpoint 和图片临时工作集，不要求恢复任务一定永久保留图片副本。

### 8.3 历史复评能力

至少区分：

- 模型可用。
- 训练证据可用。
- 冻结 GT 元数据可用。
- 原始图片仍可读取。
- 原始数据缺失，无法完整复评。

原图删除后仍可保留历史 mAP、指标和训练日志，但必须说明这些是已归档历史结果，并非当前重新验证的结果。

完整复评无法执行时，应明确报告原因。

---

## 九、第七阶段：历史任务存储回收

目前用户提供的历史记录：

| Task ID | 状态 | 工作 Bundle |
|---|---|---|
| train_24766a1c81dd4392bc4216a8 | SUCCEEDED | 约16GB |
| train_41d78077c794484597866867 | SUCCEEDED | 约15GB |
| train_2f0f0d22e2c647829e04d7a9 | FAILED | 约20GB |

合计约51GB。

这些是 2026-10-20 的历史数据，不代表当前生产状态。

本轮必须实现历史任务识别和回收资格分析，不得只支持新创建的训练任务。

需要提供：

- 只读扫描
- 回收资格判断
- 预计释放空间
- 阻止回收原因
- 引用关系检查
- 模型及证据校验
- Dry-run
- 幂等回收执行器
- 回收审计
- 中断恢复

**本轮只允许在隔离测试数据中验证物理回收。不得直接回收上述三个生产任务。**

两个成功任务应作为生产后续专项核验候选。

失败任务需要明确恢复资格之后才能回收。

不能直接递归删除整个 `task_runtime/artifacts`。

---

## 十、第八阶段：前端功能同步

尽量复用已有“重复与异常素材治理”及训练任务详情入口。

### 素材治理界面

操作方式统一：

- 保留一张
- 删除多余记录
- 删除整个问题组
- 批量删除
- 删除全部筛选结果
- 停止参与新训练

明确显示：

- 本次选择多少张
- 将退出素材库多少张
- 将删除多少个当前 GT
- 实际可释放多少物理存储
- 哪些图片因为活动任务暂缓物理回收
- 有多少历史训练可能失去完整复评能力

不再以“历史成功训练保护”为由一律拒绝当前素材删除。

### 训练任务界面

增加简洁的数据状态：

- 创建时素材数量
- 实际冻结素材数量
- 被删除或失效数量
- Train / Val / Test 数量
- 数据冻结状态
- 临时占用
- 可回收空间
- 回收状态

### 存储治理界面

尽量利用已有算力及存储管理入口，不新建无意义的大菜单。

展示：

- 正式图片实际占用
- GT、Snapshot、Manifest 占用
- 训练任务临时空间
- Training Bundle Cache
- Checkpoint
- 模型成果
- 可回收空间
- 共享数据实际占用
- 存储安全余量

用户应当可以明确知道：哪些数据真正占硬盘，哪些只是索引引用。

所有操作进度必须真实，不允许点击按钮后没有反馈。

前后端字段、错误码、任务状态、统计结果必须一致。

---

## 十一、安全与一致性要求

本轮必须遵守以下底线：

1. 不误删唯一共享图片。
2. 不误删其他项目引用的数据。
3. 不误删活动训练或活动评测输入。
4. 不修改已冻结任务的 GT 和数据划分。
5. 不破坏现有模型版本、推理、转换和发布能力。
6. 不允许 Train / Val / Test 出现相同 SHA256 的数据泄漏。
7. 不用历史当前素材冒充原冻结数据。
8. 不因数据库索引缺失就猜测可以物理删除。
9. 不将数据库提交与文件删除错误地当作一个原子事务。
10. 数据回收必须有恢复安全边界、审计和幂等机制。
11. 软链接、硬链接、Reflink、权限异常、跨文件系统及 Worker 失联都要单独测试。
12. 现有历史数据的迁移必须幂等，不能推断不存在的 GT 版本。
13. 不新增平行 Owner、调度器、素材仓库、审计系统或多层无意义封装。
14. 发现无法安全共享图片的情况，必须受控回退，不得牺牲正确性。

SQLite 层应检查数据库外键约束是否实际启用，并确保删除和引用修改具备事务一致性。

物理回收需要采用安全状态机或等效机制，避免扫描和删除之间新增引用造成误删。

---

## 十二、测试与验收要求

必须新增或完善以下测试：

### 素材治理

- 历史 SUCCEEDED 任务引用的当前 GT 可以删除。
- 历史 Test 引用不再永久阻止当前删除。
- 同图不同 GT 可以整组删除。
- 同图同 GT 可以保留一份或整组删除。
- 批量和筛选结果全部删除正确。
- 活动任务使用的底层文件不会误删。
- 共享文件仅在符合回收资格时释放。
- 删除前预览与执行结果一致。

### 排队与训练

- 排队 10,000 张，删除 500 张，最终使用 9,500 张。
- 素材不足时正确阻止启动。
- Snapshot 冻结后不再变化。
- GT 在冻结前变化能够被正确识别。
- GT 在冻结后变化不影响正在执行的训练。
- Train / Val / Test 按 SHA256 严格隔离。
- 不影响 YOLO 真实数据加载。

### 存储

- 同一批图片多次训练不产生永久重复工作副本。
- 重复导入同 SHA256 图片不会错误重复存储。
- Reflink、复制兜底、只读路径兼容。
- 回收后模型仍可正常推理。
- 回收后转换和发布仍可使用归档模型。
- 历史报告按实际可用性显示。
- FAILED 任务的恢复资格正确。
- 中断回收、重复回收、并发引用均安全。
- 不同 Worker 不会互相破坏缓存或素材。

### 前端

- 真实 Chrome 浏览器操作测试。
- 批量及整组删除流程。
- 删除进度与终态。
- 训练任务素材实际数量。
- 历史模型复评能力变化。
- 存储实际占用和回收状态。

所有测试必须使用隔离夹具或非生产环境。

不允许为了通过 CI 删除测试、跳过断言、降低既有安全门禁或者用 Mock 成功代替关键真实文件链路测试。

---

## 十三、开发与提交顺序

建议按依赖关系分阶段完成：

**阶段 A：现状审计与数据契约**

完成最新代码核验、活动租约定义、历史引用分类、图片及 GT 身份规则。

**阶段 B：GT 当前素材删除重构**

先实现历史保护解耦、批量整组删除、活动任务延迟物理回收。

**阶段 C：排队启动时重新冻结**

修复排队期间素材变更和正式训练开始之间的状态一致性。

**阶段 D：图片单份存储**

优先复用已有 SHA256、Snapshot 和 Repository 能力，构建安全不可变数据视图。

**阶段 E：训练工作 Bundle 自动回收**

完成成功、失败、取消和恢复任务的生命周期管理及历史归档兼容。

**阶段 F：前后端及回归验收**

完成存储状态展示、素材治理 UI、全部相关测试和 CI。

各阶段可以形成独立提交，但不要产生平行实现和长期兼容技术债。

如果某个阶段存在无法可靠证明安全的前置条件，应先完成其他可独立验收的阶段，明确记录该阻塞，不得跳过数据保护直接删除文件。

---

## 十四、GitHub 交付要求

开始前：

1. `git fetch` 最新远端。
2. 核验长期开发分支实际 HEAD。
3. 阅读 `AGENTS.md` 和相关开发约束。
4. 检查工作区及并行开发状态。
5. 不覆盖别的会话已有修改。

完成后：

1. 执行相关 Python、Node、浏览器测试。
2. 执行受影响的现有 CI。
3. 确认前后端字段一致。
4. 完成代码质量和安全复核。
5. 按仓库规范处理 VERSION。
6. 更新已有开发追踪文档。
7. 正常快进推送唯一长期开发分支。
8. 以最终 SHA 核验实际触发的 GitHub Actions 和 Jobs。

不得借用旧 SHA 的成功结果冒充本次验收。

如果存在失败，继续定位本轮相关问题，不隐瞒或绕过。

### 最终交付报告

请明确报告：

- 最终 HEAD、VERSION。
- 具体修改了哪些模块。
- 哪些历史保护规则已取消。
- GT 冲突是否已经可以整组删除。
- 排队任务是否启动时重新冻结。
- 是否真正减少训练物理图片副本。
- 训练成功是否自动回收工作数据。
- 失败任务如何保护及回收。
- 历史模型是否仍可推理、转换、发布。
- 哪些情况下历史完整复评不可用。
- 具体测试结果和 CI 状态。
- 仍存在的风险及未完成事项。
- 生产部署及历史数据回收前需要的独立操作。

**最后特别强调：用户授权的是长期开发分支的代码开发，不是生产数据清理或生产部署。**

最终目标不是简单删除 51GB，而是让平台在长期反复训练的情况下，既保证模型和数据正确性，又不再为相同图片永久保存一份又一份物理副本。

</details>


## 附录 B：最新统一开发指令（完整留存，优先于旧策略）

# 畅联云算法训练平台｜训练准入自动诊断、GT 冲突治理、素材批量删除及项目清空统一开发指令

## 一、项目背景与开发授权

继续开发已经正式运行的：

**畅联云算法训练平台**

GitHub 仓库：

`jorsamj/aixunlianpingtai`

唯一长期开发分支：

`feature/external-algorithm-publishing`

最近提供的已知 HEAD：

`4fcbcfc804748d37a07eaeb8b8ed960539d10b91`

该 HEAD 仅作为历史交接参考，不能当作当前远端最新提交。

### 1.1 开发前要求

Codex 必须先：

1. 获取远端最新代码。
2. 核验真实 HEAD 和 VERSION。
3. 阅读 `AGENTS.md`。
4. 阅读 `docs/CODEX_CURRENT_STATE.md`。
5. 阅读既有 GT 素材生命周期治理专项文档。
6. 核查当前实现及其他会话正在进行的修改。
7. 优先复用既有架构，不重复开发已有功能。

这是正式生产平台的增量开发，不是新建项目。

### 1.2 本轮授权

允许：

- 审计和修改必要的前后端代码。
- 完善已有素材删除与审计机制。
- 修改必要的数据库 Schema，并提供安全兼容迁移。
- 完善训练准入及相关 UI。
- 新增或调整自动化测试。
- 更新正式需求及进度文档。
- 完成验收后提交和推送唯一长期开发分支。

禁止：

- 擅自修改或删除生产素材。
- 擅自删除生产 GT、Snapshot、Bundle 或模型成果。
- 执行生产项目清空。
- 执行生产数据库迁移。
- 执行生产部署。
- 创建真实 GPU 训练任务。
- 强制推送或覆盖其他会话的开发成果。

**本轮只完成代码、隔离测试、CI 和开发分支交付，不执行真实生产删除操作。**

---

## 二、本轮统一需求及最终目标

本次不是两个独立专项，而是统一实施：

**训练准入诊断 → 问题素材定位 → 用户选择处理方式 → 安全删除或排除 → 后台执行 → 自动重新预检 → 恢复训练能力。**

同时将素材删除能力扩展至正常素材管理页面，支持全项目清空。

### 正式需求清单

| 编号 | 需求 | 优先级 |
|---|---|---|
| GOV-01 | 训练按钮置灰时自动弹窗诊断 | P0 |
| GOV-02 | 准确展示全部训练阻塞原因 | P0 |
| GOV-03 | 单张、批量及整组 GT 冲突删除 | P0 |
| GOV-04 | 当前筛选结果全部删除 | P0 |
| GOV-05 | 本次训练全部问题素材删除或排除 | P0 |
| GOV-06 | 管理员清空当前项目素材库 | P1 |
| GOV-07 | 历史引用及当前 Test 保护规则重构 | P0 |
| GOV-08 | 活动任务保护及共享图片安全 | P0 |
| GOV-09 | 服务端删除预览与后台任务治理 | P0 |
| GOV-10 | 删除后自动重新预检与草稿同步 | P0 |
| GOV-11 | 前后端一致性、测试和正式文档 | P0 |

全部使用现有素材治理系统实现。

不得建立两套相互独立的删除 API、任务调度器、素材索引或保护判定机制。

---

## 三、GOV-01 / GOV-02：训练开始按钮置灰时自动诊断

### 3.1 用户实际问题

用户创建香烟算法训练任务时：

“开始训练”按钮处于置灰状态。

通过 Chrome Console 才发现：

- `disabled=true`
- `reason=material-compatibility`
- `compatibility.ready=true`
- `issue_count=38`
- `lastError=''`

说明训练素材兼容性检查已经完成，存在 38 张不合格素材。

**用户不应该通过 F12 才能知道原因。**

### 3.2 自动弹窗规则

重点修改现有：

`static/modules/training-submit.js`

及相应训练兼容性运行模块。

当训练配置加载完成，且预检确定存在阻塞原因时：

**自动打开居中的训练准入诊断弹窗。**

要求：

1. 使用现有 Modal Stack。
2. 不能替换或销毁原训练创建弹窗。
3. 诊断弹窗关闭后恢复原配置及草稿。
4. 显示所有已知阻塞原因，而非只显示第一个错误码。
5. 每类问题显示实际数量及对应处理入口。
6. 加载中不能误判为检查失败。
7. 同一草稿和同一诊断版本最多主动弹出一次。
8. 用户手动关闭后，不因重复渲染再次打扰。
9. 若用户修改素材、标签、数据划分或训练配置后问题发生实质变化，应更新诊断信息，但不无意义地反复抢占焦点。
10. 按钮持续禁用期间，应保留明显的“查看不能训练的原因”入口。

注意：

自动弹窗仅针对已经确认的准入阻塞。

普通按钮提交中、后台请求尚未完成、短暂加载状态不应被当作错误弹窗。

### 3.3 诊断内容

至少覆盖：

- 算法选择异常。
- 训练素材不足。
- GT 标注冲突。
- 标签审核范围缺失。
- 同 SHA256 训练集与 Test 集交叉。
- 母模型未就绪。
- 历史迭代版本不可用。
- 固定 Test 基准异常。
- 畅联云外部算法主数据过期。
- 资源或设备准入异常（实际存在时）。
- 其他后端真实训练准入拒绝原因。

错误信息应翻译为清晰的中文。

例如：

**训练暂不可开始**

本次检测到 38 张素材不符合训练条件。

问题可能涉及：

- GT 标注冲突。
- 标签审核不完整。
- 数据集划分冲突。

具体数量应使用服务端真实诊断数据，不允许猜测。

提供：

- 查看问题素材。
- 批量处理。
- 仅从本次训练排除。
- 重新检查。
- 返回训练配置。

---

## 四、GOV-03 / GOV-04 / GOV-05 / GOV-06：统一素材删除能力

### 4.1 统一删除级别

平台正式支持以下操作：

| 操作 | 删除范围 |
|---|---|
| 删除单张 | 指定一张当前素材 |
| 删除当前勾选 | 当前勾选的若干素材 |
| 删除整个 GT 冲突组 | 同一问题组内所有当前素材 |
| 删除当前筛选结果全部 | 服务端筛选条件匹配的所有素材，包含全部分页 |
| 删除本次训练全部问题素材 | 当前训练预检识别的所有问题素材 |
| 清空当前项目素材库 | 当前项目全部素材记录和对应当前正式 GT |

同时保留非删除操作：

- 仅从本次训练排除。
- 人工核对 GT。
- 修改正式 GT。
- 保留某张并删除多余重复记录。

### 4.2 两种删除模式必须明确区分

**模式 A：仅排除本次训练**

- 只修改当前训练草稿。
- 不删除正式素材。
- 不删除正式 GT。
- 不修改历史任务。
- 后续训练仍可以重新选择该素材。
- 排除完成后重新预检。

**模式 B：从当前正式素材库删除**

- 从当前项目的可用素材索引移除指定记录。
- 对应当前正式 GT 按既有数据合同一并退出。
- 不再参与新训练选择。
- 底层物理文件按照活动引用和共享存储规则安全回收。
- 历史证据保留并准确呈现可复评能力。

这两种模式必须拥有不同的按钮文案、确认提示和执行结果。

不允许让用户误以为“排除本次训练”等于永久删除素材。

### 4.3 同图不同 GT 整组删除

用户明确要求：

**如果同一张图片存在不同 GT，而用户决定全部不要，可以直接删除整个问题组。**

例如：

图片 A：

- 记录 1：标注 `cigarette`
- 记录 2：标注 `cigarette`、`face`

用户选择：

**删除整个冲突组。**

系统应删除这两个当前素材记录和它们对应的当前 GT。

不得强迫用户：

- 先选择哪份 GT 正确。
- 先确认保留项。
- 先进入人工标注。
- 先完成 GT 修复。

保留一张并删除其余记录时，才需要用户确认保留目标或符合现有安全决策规则。

必须将“保留一张”和“整个问题组全部删除”明确区分，不能继续共享错误的强制 Keeper 校验。

### 4.4 同图同标注

支持：

- 默认保留一条有效记录。
- 删除其他重复记录。
- 删除指定记录。
- 删除整个重复组。
- 批量删除多个重复组。

如果底层图片被其他有效素材引用，删除某一记录不能删除共享图片字节。

### 4.5 异常素材统一处理

适用于：

- GT 冲突。
- 同图同标注。
- 标注异常。
- 图片损坏。
- 标签不完整。
- 数据集角色冲突。
- 其他训练准入及素材审计异常。

用户可以针对问题进行人工修复，也可以选择删除不需要的当前素材。

不同类型的问题必须保留各自真实的诊断语义，不得因为统一删除入口就将所有问题错误地标记成 GT 冲突。

### 4.6 删除当前筛选结果全部

必须覆盖服务端当前筛选结果的**所有分页**。

例如：

- 共 1,280 张匹配素材。
- 每页 50 张。
- 当前显示第 1 页。

用户选择“删除当前筛选结果全部”，应以服务端冻结的 1,280 张精确素材身份为执行目标，而不是只处理前端可见的 50 张。

要求：

- 服务端解析并冻结筛选条件。
- 返回精确的去重素材集合或不可变选择清单。
- 保存素材版本及标注版本。
- 执行前进行安全复验。
- 避免因前端分页、请求截断或筛选条件变化导致误删。
- 支持大于 500 张的操作。
- 支持中断恢复和幂等执行。

### 4.7 本次训练全部问题素材

训练预检发现的问题素材，必须支持：

- 单张删除。
- 批量勾选。
- 全选当前页。
- 全选当前筛选结果。
- 全选本次训练全部问题素材。
- 一次性预览和提交。

以这次香烟训练为例：

如果预检确认有 38 张不兼容素材，用户应可以选择全部 38 张。

处理时应按唯一 image_id 去重，不能把同一张图片在多个问题组中的出现次数重复相加。

如果这些 38 张属于 19 个同图不同 GT 冲突组，允许一次全部选择并删除，无需人工逐组判定 GT 正误。

但不能仅根据 `issue_count=38` 就假定它们全部属于同一问题类型；必须使用真实预检明细。

### 4.8 清空当前项目素材库

在现有素材管理页面增加管理员级别操作：

**清空当前项目素材库**

作用范围：

- 当前项目所有当前素材记录。
- 对应的当前正式 GT。
- 必要的当前素材关联索引及投影。

不包括：

- 其他项目素材。
- 算法定义。
- 历史训练任务。
- 已归档模型权重。
- 历史评测指标。
- 必需的审计与溯源记录。
- 不属于当前素材库的业务对象。

操作必须满足：

1. 服务端管理员权限校验。
2. 明确展示项目名称和唯一身份。
3. 提供不可误触的二次确认，建议要求输入指定项目名称。
4. 显示总素材数量及 GT 数量。
5. 展示 Test 和历史复评影响。
6. 说明是否有活动任务需延迟物理回收。
7. 先生成服务端不可变删除计划。
8. 使用已有批量任务执行机制。
9. 支持真实进度、审计和失败重试。

**清空当前素材库不等同于彻底销毁所有历史数据字节。**

如未来需要彻底清除历史归档和模型证据，应另设具有明确授权的销毁流程，不得混入普通素材删除。

---

## 五、GOV-07：历史引用与当前 Test 保护规则重构

### 5.1 当前问题

目前部分素材会显示：

- 失败任务仅保留请求溯源。
- 当前独立 Test 素材。
- 历史训练 Snapshot 引用。

但是删除时仍可能被旧保护规则阻止。

重点检查：

`platform_core/material_batches.py`

以及现有历史引用分类函数。

### 5.2 正式保护原则

| 素材关联状态 | 当前素材逻辑删除 |
|---|---|
| 历史失败任务，仅请求溯源 | 允许 |
| 历史成功训练任务 | 允许 |
| 历史 Snapshot | 允许 |
| 历史 Test 引用 | 允许，但需提示复评影响 |
| 当前 Test 素材 | 允许，但需提示当前测试集变化 |
| 排队中的训练任务 | 允许 |
| 正在使用素材的活动训练 | 允许逻辑删除，底层文件延迟回收 |
| 正在使用素材的独立评测 | 允许逻辑删除，底层文件延迟回收 |
| 共享底层图片存在其他有效引用 | 仅移除指定记录，保留共享内容 |

历史训练、模型版本和 Test 角色不再天然构成当前素材永久删除禁令。

### 5.3 历史记录与当前使用分离

必须区分：

1. 历史溯源引用。
2. 活动数据使用租约。
3. 当前素材所有权。
4. 底层物理文件保留资格。
5. 训练或评测的完整复现能力。

历史索引应当能够继续记录：

- 训练任务 ID。
- Snapshot ID。
- 图片身份及 SHA256。
- 冻结 GT 摘要。
- 数据划分。
- 模型版本及训练结果。

但保留这些历史索引不等于必须永久保留当前素材记录和图片副本。

不得在删除后假装原始图片仍然存在。

---

## 六、GOV-08：活动任务和共享文件安全

用户明确允许删除历史素材，但不能破坏真实运行中的任务。

### 6.1 活动数据保护

需要保护：

- 正在执行训练准备的数据。
- 已冻结并被活动训练读取的数据。
- 正在运行的独立评测输入。
- 正在使用的有效 Checkpoint 恢复输入。
- 其他经实际核验仍在使用底层文件的任务。

用户执行删除时：

**当前素材可以先从新任务可选库中退出。**

但实际运行任务需要的底层图片与冻结 GT 必须继续保持可用，直到活动依赖安全释放。

### 6.2 排队任务

排队任务不永久锁定素材。

如果训练任务排队期间，部分素材被删除：

- 保留原训练请求范围与条件。
- 正式开始训练准备时重新核验有效素材。
- 不得擅自扩展至用户原本未选择的图片。
- 重新冻结最终输入。
- 重新核验 Train / Val / Test。
- 数据不足时明确拒绝启动。

已经完成最终冻结的活动任务不允许偷偷修改其训练输入。

### 6.3 共享图片

相同 SHA256 的图片内容可能对应多个素材记录。

必须保证：

- 删除一条索引不误删其他有效记录的底层文件。
- 不破坏跨任务共享的不可变输入。
- 物理删除前再次核对活动租约及真实引用。
- 避免扫描结束后新增引用造成竞态。
- 不把目录级删除当作素材级安全删除。
- 清理失败后能够安全重试。

如果无法证明物理回收安全，可以先完成当前素材逻辑删除并延期回收，不得为了释放空间强行删除共享字节。

---

## 七、GOV-09：统一删除计划、预览和执行链路

必须复用已有：

- 素材审计。
- 训练兼容性诊断。
- 服务端选择冻结。
- MaterialRepository。
- `DELETE_INDEX`。
- 批量任务队列。
- Worker 执行。
- 任务状态和进度。
- 审计日志。

不得再建第二套删除系统。

### 7.1 删除前预览

所有删除模式必须返回真实预览：

| 指标 | 要求 |
|---|---|
| 实际选中素材 | 精确去重数量 |
| 可逻辑删除素材 | 精确数量 |
| 当前 GT 影响 | 将移除的记录数量 |
| GT 冲突组 | 涉及组数 |
| 当前 Test | 受影响数量 |
| 活动保护 | 延迟物理回收数量 |
| 共享图片 | 不可直接释放的内容数量 |
| 历史复评 | 可能失去完整复评的任务或版本 |
| 预计释放空间 | 基于实际物理存储估算 |
| 暂不可执行 | 具体原因及可处理范围 |

必须让用户清楚知道删除的是当前素材记录，还是底层物理内容。

### 7.2 服务端冻结选择范围

删除提交时保存：

- 项目身份。
- 操作类型。
- 精确选择清单或可验证的冻结选择引用。
- 筛选条件。
- 素材 Revision。
- GT Revision。
- 必要的 SHA256 / Annotation Digest。
- 操作者身份。
- 操作审计信息。

如果正式执行前数据发生变化，应返回具体冲突结果，并根据现有事务合同要求重新预览或对安全的剩余集合进行明确处理。

不得扩大原先确认的删除范围。

### 7.3 三层保护校验统一

重点修改：

`platform_core/material_batches.py`

涉及：

1. 删除计划生成。
2. 删除提交前复验。
3. Worker 实际执行前校验。

三层必须使用同一套业务资格语义。

不能出现：

- 预览允许但执行无故拒绝。
- 预览拒绝但 Worker 可直接删除。
- 当前 Test 在其中一层仍被永久保护。
- GT 整组删除在其中一层仍强制要求 Keeper。
- 失败任务仅请求溯源却仍被算作真实活动保护。

同时保留必要的数据完整性、并发保护和项目隔离检查。

### 7.4 后台任务执行

支持：

- 大批量排队执行。
- 真实进度。
- 已完成数量。
- 总数量。
- 失败数量。
- 跳过数量。
- 明确失败原因。
- 幂等重试。
- 服务重启后恢复。
- 中断安全。
- 审计记录。

禁止点击删除后长时间无响应。

必须区分：

**素材索引已移除** 和 **底层空间已释放**。

不能将两者统计混为一谈。

---

## 八、GOV-10：删除后自动重新预检训练

用户删除或排除问题素材之后，系统需要自动重新判断能否开始训练。

### 8.1 正确流程

1. 等待后台处理返回明确的有效结果。
2. 获取实际处理成功的 image_id 集合。
3. 从当前训练草稿中移除已经失效的素材。
4. 保留其他正常素材。
5. 更新训练素材实际数量。
6. 重新检查标签与 GT。
7. 重新检查 Train / Val / Test 隔离。
8. 重新检查母模型、算法版本及其他准入条件。
9. 更新当前诊断。
10. 根据真实结果决定是否恢复训练按钮。

### 8.2 恢复按钮的条件

只有全部必要条件通过时：

“开始训练”按钮才恢复可点击状态。

例如：

原训练素材 2,142 张。

预检发现 38 张问题素材。

用户删除或排除成功后：

系统应根据实际结果重新核验剩余素材，而不能仅仅计算 `2142 - 38` 就直接认定可以训练。

还需要处理：

- 待标注素材。
- GT 范围是否满足本次训练要求。
- 类别是否有效。
- 数据划分是否合理。
- Train / Val / Test 是否泄漏。
- 独立 Test 是否足够。
- 其他训练准入条件。

如果仍存在阻塞：

继续禁用按钮，并展示最新原因。

### 8.3 失败和部分成功

如果批量操作部分成功：

- 只能移除实际成功处理的素材。
- 失败素材仍需保留在当前诊断。
- 不能错误显示“38 张已经全部处理”。
- 不能错误恢复训练按钮。
- 可以允许用户重新处理剩余问题。

所有统计必须来自服务器真实结果。

---

## 九、统一前端 UI 设计

本轮使用现有中文 Modal、Loading 和 Tooltip 体系。

### 9.1 训练阻塞弹窗

标题：

**训练暂不可开始**

显示：

- 当前算法名称。
- 本次选择的素材数量。
- 不兼容素材数量。
- 阻塞原因分类。
- 每类影响数量。
- 可以采取的解决方式。

提供：

- 查看全部问题。
- 逐张修复。
- 批量排除本次训练。
- 批量删除正式素材。
- 重新预检。
- 返回训练配置。

诊断窗口保持合理尺寸，不能出现近似全屏工作台布局。

### 9.2 问题素材列表

每项展示：

- 真实缩略图。
- 文件名。
- 标签。
- GT 状态。
- 问题类型。
- 当前 Train / Val / Test 角色。
- 必要的历史关联信息。
- 操作入口。

支持：

- 当前页全选。
- 当前筛选结果全选。
- 本次所有问题全选。
- 删除选中。
- 排除选中。
- 整组删除。
- 单张编辑 GT。

用户明确选择整组删除时，不需要首先选择正确 GT。

### 9.3 素材管理界面

增加或完善：

- 删除当前选中。
- 删除当前筛选全部。
- 管理员清空当前项目素材库。

危险操作应放在清晰、合理的位置，不与普通查看按钮混淆。

对“清空项目”使用明显的危险提示和二次确认。

### 9.4 加载和反馈

必须支持：

- 预检 Loading。
- 删除预览 Loading。
- 删除后台任务进度。
- 删除成功反馈。
- 部分成功反馈。
- 失败原因及重试。
- 自动重新预检反馈。

已知真实数据不应因为后台重新预检而全部清空。

---

## 十、开发范围与代码质量要求

重点检查：

- `static/modules/training-submit.js`
- `static/modules/training-material-summary-runtime.js`
- `static/modules/training-draft-runtime.js`
- `platform_core/material_batches.py`
- 训练兼容性 API
- 当前素材管理 API
- MaterialRepository
- AnnotationRepository
- TaskRepository
- 删除任务 Worker
- 历史引用及活动租约实现
- 前端相关 Modal 和素材列表

以上仅为入口，实际修改范围以代码调用链为准。

要求：

1. 前后端一致。
2. 逻辑尽可能扁平。
3. 不新增平行存储和任务调度体系。
4. 不在旧逻辑外叠加多个永久兼容补丁。
5. 不降低权限和审计约束。
6. 不改写历史模型。
7. 不误删共享文件。
8. 不伪造 GT 或训练成功状态。
9. 不用跳过测试来获取 CI 通过。
10. 不引入难以退役的技术债。

---

## 十一、测试与验收标准

必须使用隔离数据，不操作生产素材。

### 11.1 训练诊断测试

- 香烟训练模拟 38 张不兼容素材，按钮置灰并自动诊断。
- 检查未完成时不误弹错误。
- 同一问题不重复弹窗。
- 多类阻塞原因同时展示。
- 手动关闭后草稿保留。
- 母模型或版本异常正确说明。
- 项目切换后诊断不串数据。

### 11.2 GT 冲突测试

- 同图不同 GT 删除一张。
- 同图不同 GT 删除整个组。
- 整组删除不需要保留项。
- 同图同标注保留一张。
- 同图同标注整组删除。
- 跨多个问题组去重。
- 19 组、38 张全部删除。
- 删除后当前 GT 状态正确。

### 11.3 大批量及项目清空测试

- 删除选中素材。
- 删除当前筛选全部。
- 1,000 张以上跨分页删除。
- 超过原 500 张请求限制。
- 全项目清空。
- 项目管理员权限不足时拒绝。
- 清空确认不完整时拒绝。
- 项目间数据严格隔离。
- 中断和重试后结果一致。

### 11.4 引用与文件安全测试

- 历史成功任务引用。
- 历史失败任务仅请求溯源。
- 当前独立 Test。
- 历史 Snapshot。
- 排队任务素材被删除。
- 运行中任务素材被删除。
- 评测中素材被删除。
- 共享 SHA256 图片引用。
- 延迟物理回收。
- 物理回收前出现新活动引用。
- 不修改历史模型与评测结果。

### 11.5 删除后训练恢复

- 38 张问题素材全部排除后重新预检。
- 38 张问题素材全部删除后重新预检。
- 全部成功后恢复训练按钮。
- 部分成功时继续显示剩余问题。
- 删除后可用样本不足时继续禁用。
- 删除后 Test 不足时继续禁用。
- 不允许不经重新核验就启动训练。

### 11.6 真实浏览器测试

使用 Chrome / Playwright 验证：

- 自动诊断弹窗。
- 各种删除范围。
- 服务端跨分页全选。
- 删除预览。
- 危险操作确认。
- 任务进度。
- 删除后重新检查。
- 无多余 Modal 和遮罩。
- 错误提示与恢复。
- 按钮状态正确。

必须建立 RED→GREEN 证据。

不得只使用静态源码断言。

---

## 十二、需求与开发进度文档

本轮继续使用已有正式专项：

`docs/TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md`

本次两组原始需求统一记录为：

**训练准入诊断与素材删除治理一体化专项**

文档必须包含：

1. 用户确认的统一需求。
2. 当前实现与根因。
3. GT 冲突、重复素材和 Test 的正式删除规则。
4. 训练诊断的触发与展示合同。
5. 删除预览和活动保护设计。
6. 大批量删除及项目清空方案。
7. 开发任务清单及当前进度。
8. 实际修改代码。
9. 已完成与未完成事项。
10. RED→GREEN 测试。
11. 浏览器交互证据。
12. 关联 Commit。
13. 最终 SHA 的 CI。
14. 生产数据清理前置条件。
15. 下一会话接续指令。

训练弹窗 UI 变化，在现有综合前端专项文档中添加简短引用：

`docs/FRONTEND_STARTUP_REPORT_UX_GOVERNANCE_2026_10_21.md`

同时更新：

`docs/CODEX_CURRENT_STATE.md`

不得创建多份互相矛盾的需求和进度记录。

每完成一个开发阶段及时更新，不要全部做完才补文档。

---

## 十三、建议开发顺序

### 阶段 A：现有代码审计

确认训练按钮置灰、38 张问题素材、GT 冲突删除、当前 Test 保护及后台任务的真实调用链。

核查既有实现，建立 RED 测试。

### 阶段 B：统一删除资格与历史保护

优先解决：

- GT 整组删除。
- 历史引用解耦。
- 当前 Test 逻辑删除。
- 活动输入保护。
- 删除计划与 Worker 一致性。

### 阶段 C：三级及扩展删除功能

实现：

- 选中删除。
- 整组删除。
- 当前筛选全部删除。
- 本次全部问题素材删除。
- 管理员项目清空。
- 服务端冻结选择和安全预览。

### 阶段 D：训练准入自动诊断

实现全部阻塞原因收集、一次性自动提醒、处理入口及训练草稿恢复。

### 阶段 E：后台进度与自动重新预检

完成删除任务、状态反馈、草稿更新及重新计算训练准入。

### 阶段 F：端到端验收

执行 Python、Node、Playwright 及受影响的全部回归。

更新正式专项进度文档，正常提交和推送长期开发分支。

按最终 SHA 核验 CI。

---

## 十四、最终交付要求

完成后向用户明确报告：

- 最终 HEAD / VERSION。
- 训练按钮置灰是否能自动说明原因。
- 是否展示全部已知阻塞项。
- 38 张问题素材是否支持一次性处理。
- GT 冲突是否支持整组直接删除。
- 是否支持跨分页删除全部筛选结果。
- 是否支持管理员清空当前项目素材库。
- 历史成功、失败、Test 和 Snapshot 是否还会错误阻止当前素材删除。
- 活动训练和共享图片是否受到保护。
- 删除进度是否真实。
- 删除后是否自动重新预检。
- 训练按钮是否依据实际准入状态恢复。
- 实际测试结果及数量。
- GitHub Actions / Checks 是否通过。
- 正式需求与进度文档地址。
- 未完成事项和生产部署前核验要求。

**本轮最终目标：用户知道为什么不能训练，也能直接处理不需要的素材；用户明确选择整组、批量、筛选结果全部或清空当前项目时，系统必须能够在不破坏活动任务与共享数据的前提下，安全、完整、可审计地执行，而不是被历史 GT、Test 和失败任务永久锁死。**

本轮不执行生产部署，不删除任何真实生产素材。
