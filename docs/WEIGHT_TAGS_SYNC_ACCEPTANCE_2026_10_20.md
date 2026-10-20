## 上轮最终CI归档（2026-10-20）

已读取独立验收附件weight-tags-persistence-ci-final-20261020.json：完整SHA `7a2492b24de5d6259bf792ed074f1548e66d6eda`，普通FF推送、远端一致/干净，VERSION42.24.358，Actions39/39、Checks109/109成功，失败/待运行0。属于上轮Weight tags任务最终结果，不代替后续动态字典任务CI；生产17项/7Weight补齐仍未执行。附件位置在CODEX_CURRENT_STATE及本轮动态字典专项记录的visualizations同目录。

## 2026-10-20｜Weight tags历史补齐及本地元数据（A-D通过 / E待推送CI / 生产补齐未执行）

- 已完整fetch/prune、pull --ff-only，起始0cf65c48bf6c6d0ec0df852128c2faccf4072f8e，远端一致、工作树干净；历史48/48 Actions、131/131 Checks已核验，不能借用为本轮CI。VERSION42.24.358。
- 用户只读现场证据：12版本17Weight，10确认payload含tags，7缺tags，17份canonical metadata.tags为空，版本冻结标签可解析。不能将本地空值等同于所有请求未发tags。
- 已核验现有add/edit原生JSON、旧ID补齐、UNKNOWN只读恢复及元数据差异触发原本存在。真实本地缺口：通用discover_version_artifacts未生成模型元数据，upsert整体替换metadata_json；发布临时解析与通用资产刷新不同路径，导致本地可能被覆盖。7份旧回执的最初缺失时间/生产自动发布配置尚未读取，不伪造根因。
- 计划：先RED复现；共享原可信解析合同给本地资产Owner，训练/转换本地登记独立于外部和上传配置；明确已验证元数据保留/冲突规则，禁止无条件merge。历史补齐先只读审计、原身份本地修复及既有发布Owner原Weight ID edit，提供7缺失/10对照验收。既有页面细分本地/准备/确认回执/远端读回事实。
- 不生产UPDATE、不操作OSS/S3、不调用真实新畅联写接口、不重启或部署服务；真实生产补齐另行授权。本专项与追加本地持久化合并完成，不建新队列/数据库/Owner。

### 本轮 B：真实RED与根因界限

1. 本地6项RED（四格式初始持久化、稀疏upsert保留、训练版本提交前后本地登记）→GREEN。通用资产发现未提取冻结模型信息，metadata_json整体替换会清掉发布时临时生成的tags；因此能解释“10份回执有tags但17份本地为空”，不能反过来说10份没发送。
2. PARTIAL重试时钟1项独立RED及7历史样本中的6项自动补齐失败→GREEN。ensure_publication每次更新updated_at，再判断auto_retry_due，持续将旧PARTIAL判为未到时间；现仅状态/尝试的真实patch维护重试时间，不在幂等ensure重置。
3. 原ID edit远端多候选1项RED→GREEN：已记住ID也先用已确认核心合同唯一恢复；歧义进入UNKNOWN/人工核对，不发edit/add。查询失败与已发写结果未知仍有区别。既有写前UNKNOWN、超时只读恢复保留。
4. 无发布映射本地状态1项RED→GREEN；Node1及Chrome1项RED→GREEN，原界面分开本地保存与外部回执/读回事实。
5. 7份回执最初为何省略tags：不能由目前SQLite反推发送时是否已有标签或当时运行代码；PUBLISHED样本当前源码原本会检测tags差异，生产为何未执行仍需旧HEAD/Owner运行/配置/日志对照。本轮不编造生产根因。现场7/17为用户只读证据，未连接生产重跑。

### 本轮 C：数据所有权及修改路径

- `algorithm_versions.payload_json`：原冻结label_codes/label_schema、Snapshot、训练任务/血缘/实际配置继续为真值；训练条件提交额外保存规范化model_metadata（可验证YOLO/宽高、类别顺序/数量/来源等）。未知框架版本/精度等保持None，不猜值。
- `model_artifacts.metadata_json`：原ModelArtifactRepository存每个文件的tags、class_mapping、label_source、label_validation_status、label_version_id、宽高/YOLO、精度/关键conversion_params、Snapshot/任务与完整度；文件名/size_bytes/sha256、chip_code及存储身份仍用原列。仅有源SHA证据时关联source_artifact_id，不能挑第一个PT。已有best/training角色的同一已验证对象复用原Artifact，不复制original。
- 将发布层原四项可信解析函数搬到`platform_core/model_metadata.py`共享，原方法名保留兼容代理；没有第二套标签推断。版本冻结schema/codes一致优先，其次同版本hash验证Snapshot，当前项目标签/算法名称/芯片从不作为标签来源。
- upsert在原SQLite事务内保留限定模型合同字段，任务状态字段仍由其原Owner覆盖；未知/None/空tags不能擦除已知值。新旧标签冲突保留原tags、class映射/计数并记录CONFLICT与last_label_conflict；不悄悄合并类别。Artifact ID冲突或来源身份不唯一拒绝覆盖。元数据修复不改原文件/OSS/public_url/交付字段。
- 训练attach_version_if_current→原ModelArtifactService.register_version_metadata；转换完成原通知入口在外部模式判断之前登记本地事实。无需新畅联成功，也无需OSS配置/上传成功。后续ensure_uploaded和发布复用此合同；无第二数据库、队列、轮询、同步Owner。
- `external_artifact_publications`：继续保存原远端ID、compute/chip、synced_payload_json及状态，增加remote_metadata_json保存实际listByVersion读回证据。成功提交回执与远端是否返回tags分开，缺字段不冒充远端验证；UNKNOWN不反复edit/add。
- 原版本行内详情展示冻结/本地/准备/确认/远端tags、类别数、尺寸/YOLO/大小/SHA/目标及缺失/冲突原因；登记成功仍是同步成功，可选缺失不改交付结果。不新增弹窗/按钮/Owner。main缓存406，发布模块64009；app405/styles402与VERSION42.24.358不变。

### 本轮 D：限定验收证据

- 主Python6文件335 passed / 0 failed / 0 skipped，118.29s：external_algorithm_publish、external_algorithm_platform、model_artifacts、conversion_tasks、algorithm_sql_store、remote_training_results。最终日志C:/Users/jorsam/.codex/tmp/tags-complete-final.log。
- 版本兼容25 passed（test_algorithms/test_algorithm_sql_app_contract）；训练/转换传输18 passed、30 deselected；均0失败0跳过。日志tags-version-final.log、tags-transport-final.log。它们与主集合为独立用例，不将重复回归累计为新覆盖数。
- Node external-algorithm-publish + version-marker-owner：26 passed / 0 failed / 0 skipped，tags-ui-final.log；Chrome原外部发布规格3 passed / 0 failed / 0 skipped，7.6s，tags-persist-chrome.log。
- 精确7个缺失Weight ID逐一隔离重现，另10个对照按用户提供类别合同构造（完整真实10个ID未提供，不伪装为生产查询）；7个只edit原ID，10个零edit，全部本地恢复可信tags，重复运行零新增Version/Weight/上传。只读CLI按真实schema额外核验这17项候选；曾发现其provider常量误写，改为数据库实际CHANG_LIAN后复验，不隐瞒夹具/工具失败。
- 历史首轮夹具未写projects.json导致自动Owner未扫描；补真实项目索引和到期时间并断言checked=1，暴露并修复真实PARTIAL时钟缺陷。最初全回归2项兼容失败（临时payload多带溯源字段、未知标签发布语义）以隔离本地存储/准备payload修复，保留原断言，未削弱测试。
- 最终限定只读审查未发现可确认P0/P1阻断；审查未改文件/扩测/连接生产。
- CLI默认SQLite mode=ro、数据库hash不变；显式--apply-local仅调用同一ModelArtifactService，逐版本结果持久到报告，重复无变化；无外部请求/OSS写。语法、diff及原存储能力守卫通过。真实生产/第三方持久化未冒充PASS。

### 本轮 E：Git/CI

普通FF推送唯一长期分支，最终完整SHA全部实际Actions/Checks独立核验。独立验收附件：C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-tags-persistence-ci-final-20261020.json；下一受验证提交归档，避免自引用SHA产生未验证HEAD。本提交前快照不提前声称CI绿色。

### 本轮 F：生产受控验收（未执行、须另行明确授权）

先审核代码及最终CI；本轮不部署、不重启、不改配置/密钥、不执行以下生产写步骤。修复会恢复原自动Owner的历史PARTIAL重试，因此部署/启用Owner前也须审核本清单并明确授权历史补齐，不能将“部署”当作默认生产写许可。

1. 只读预检：在选定部署目录用平台Python运行 `python scripts/audit_weight_metadata.py --data-dir /data/platform-data --project f1fb1e6fa373 --output /tmp/weight-tags-before.json`。默认不迁移/写SQLite，不连新畅联/OSS；核验所有模型文件size/SHA、冻结类别、Artifact与映射，读取原object_key/public_url/compute/chip/Weight ID和确认回执。IDENTITY_UNVERIFIED/CONFLICT/LABELS_UNKNOWN不自动处理；远端身份只标EDIT_CANDIDATE_REQUIRES_REMOTE_IDENTITY。
2. 审核17项完整清单（生产数量可能已新增，以实际只读结果为准）：预计17项本地恢复，7个缺tags回执候选edit，10个正确回执不edit。出现无法唯一定位、来源冲突或文件身份变化就停止对应项，保留审计异常。
3. 本地写须单独授权后才运行同命令加 `--apply-local --output /tmp/weight-tags-local-repair.json`；仅原canonical Owner按版本锁补元数据，无生产SQL UPDATE脚本，无上传/训练/转换。逐项结果与错误在报告；中断可用相同命令继续，原ID/对象/URL/SHA保持。
4. 外部写须明确授权后，使用既有平台发布Owner/UI（官方平台路由POST `/api/v64/external-publish/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/publish`），仅下表4个版本；不要直接调用第三方add/edit。原Owner根据差异、原核心合同和listByVersion唯一ID校验决定edit，原Version/Weight/映射不变。UNKNOWN只读恢复；远端无法唯一定位则人工核对，不能重试写来消歧。没有新增执行器。
5. 写后重新运行只读审计保存after，与before逐项比artifact_id/version_id/sha256/object_key/public_url/compute/chip/外部WeightID均不变，17本地标签正确、7回执补齐、10无编辑。再通过已有安全客户端只读查询 `/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}`；实际返回tags才是读回证据，未返回则注明“已确认提交、远端未返回tags”，不能声称第三方落库已证明。不要在命令行/报告输出密钥。

| 算法 / 版本 | 原Weight ID（只补原ID） | 应补tags |
|---|---|---|
| 明火 f4dfedadcce7 | 2110796556046307328（PT）、2110966591775707136（RK3568） | ["fire"] |
| 烟火 4ef40723d87e | 2108753027757379584（PT）、2108823477988495360（RK3568） | ["fire1","smoke1"] |
| 闯入 3ea046f276b0 | 2109230402605551616（PT）、2109232532909330432（RK3568） | ["person"] |
| 停车场 a0e1f035909b | 2110401842730110976（PT） | ["tcckongdi","tcccar"] |

对应算法ID依用户提供的ext_chang_lian_43b94d739f1bf25b、ext_chang_lian_72d63086777561b7、ext_chang_lian_92e659f3e8a7f3bd、ext_chang_lian_aa52b57d1ecbe054；生产命令仅在授权后使用实际只读清单中的身份。


## 上一轮最终CI归档（由Sophon接续核对，属于历史证据）

最终SHA 62647aeea258a26ba423f0a9db23d8f6f8ba3b1a，远端一致；Actions23/23、Checks59/59成功。Publish后端206通过、Chrome3通过；SQL中的发布115通过。VERSION42.24.358，未部署。原独立CI附件已核对；本归档关闭上一轮E/F，不代表Sophon本轮CI通过。

# 训练与转换 Weight tags 专项验收｜2026-10-20

## 2026-10-20｜训练与转换 Weight tags 专项（阶段D测试通过 / 阶段E待推送CI / 生产未验证）

- 需求：核验冻结训练类别经原始PT/ONNX/RKNN到新畅联add/edit实际HTTP JSON；tags原生字符串数组、class_id顺序、未知省略且不阻断。上传人/身份/OSS对象标签不在范围。
- 已完整fetch/pull；分支feature/external-algorithm-publishing，起始HEAD 2cb3ba1617551f59abdc9c66115a0cde29d463f5，远端一致、工作树原始干净，VERSION42.24.358。
- 已有：冻结类别/Snapshot提取、可选扩展字段、旧ID edit、synced_payload_json与UNKNOWN恢复、转换完成唤醒。待核验：真实训练冻结格式、完整HTTP JSON、ONNX/多类/多版本与历史补齐链路；已核验没有新增业务缺口，仅补HTTP链路覆盖。
- 预计范围：既有发布/平台/转换通知测试与必要的最小修复、现有handoff；不新建Owner，不部署、不调用真实新畅联写接口、不操作生产OSS或历史数据、不运行真实训练/转换。禁止测试发散。
- 当前状态与下一步统一见 docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md；阶段变化持续持久化，最终CI须对应最终SHA。

## 阶段 A：现状核验（核验完成）

起始2cb3ba16为上一轮最终提交。上一轮最终证据归档：Actions22/22、Checks57/57成功；这是历史基线，不代表本轮CI。上一轮正确实现全部保留。已追踪training_tasks完成写入frozen_label_schema/frozen_label_codes、remote_training_tasks/remote_execution_transport同一冻结格式，以及conversion_tasks._finalize_conversion_job原通知Owner。发布层_frozen_weight_labels→discover_artifacts→ModelArtifact→_weight_metadata_payload→PublishingChangLianClient→ChangLianClient._request(json=body)链路已有且正确。上一轮DTO端测试已有原生数组证据，但未把冻结/转换通知/发布Owner贯穿到真实PreparedRequest.body。真实缺口是该层验收覆盖，不是业务功能缺失。

## 阶段 B：RED 检查（完成；未复现业务RED）

增加6项tags_wire测试，requests.Session及其JSON编码器为真实实现，仅HTTP adapter接入现有FakePublishingClient隔离后端；所有scheme装配adapter、断言changlian.example、trust_env=False，不访问网络。起点采用真实build_snapshot冻结排序与训练同用的attach_version_if_current；不声称执行了真实GPU训练。转换使用真实_finalize_conversion_job写job/通知、真实run_auto_publish_once同步。

首轮5 failed/1 passed：4项测试漏传now，另1项adapter复用Fake列表未按algoVersionId过滤，均为夹具错误，不是业务RED；修正后6 passed/109 deselected/0 failed/0 skipped。不得把该失败当业务修复证据，不为制造RED改业务。初次日志tags-wire-first-1020.log，修正tags-wire-second-1020.log。

## 阶段 C：实现（测试补全已实现待完整验收）

没有修改生产业务代码。保留上一轮字段提取、synced_payload_json、UNKNOWN恢复、原ID edit、文件SHA与芯片安全条件。仅tests/unit/test_external_algorithm_publish.py新增隔离链路验收；静态复核发现转换函数导入task_runtime需要psutil，仅在原SQL精简Job补该依赖，避免本地依赖掩盖CI遗漏；原有Fake后端复用而非伪造生产结果。无新Owner/队列/数据库/轮询/UI或身份变更。旧Weight测试额外清空旧确认回执，并在首次上传后禁止再次ensure_uploaded，确保补标签复用文件。

AGENTS.md追加永久进度规则；本专项为唯一验收文件，CODEX_CURRENT_STATE顶部为唯一接续入口。

## 阶段 D：GREEN 测试（测试通过）

- Python：`python -m pytest -q tests/unit/test_external_algorithm_publish.py tests/unit/test_external_algorithm_platform.py tests/unit/test_conversion_tasks.py --basetemp=C:/Users/jorsam/.codex/tmp/tags-final-1020`：200 passed / 0 failed / 0 skipped，69.78s，5项已有FastAPI/Starlette弃用警告。
- Node：`node --test tests/frontend/external-algorithm-publish.test.mjs`：16 passed / 0 failed / 0 skipped。
- Chrome：`npx playwright test tests/browser/external-algorithm-publish.spec.mjs`：3 passed / 0 failed / 0 skipped，11.0s。
- 复核增强转换Event.set断言后，仅重跑受影响6项：6 passed / 0 failed / 0 skipped（109 deselected），日志tags-review-1020.log。
- 新增wire回归6项均包含在上述200项内，不重复计数。既有UNKNOWN/文件身份/存储与芯片异常测试不删除、不降断言，真实转换成功/硬件待验证边界不变。
- 原始日志：C:/Users/jorsam/.codex/tmp/tags-python-final-1020.log、tags-node-final-1020.log、tags-chrome-final-1020.log，前两轮夹具调查日志同目录tags-wire-first/second-1020.log。
- 未运行无关本地全仓库测试、真实训练/转换或生产接口。

## 阶段 E：Git推送与CI（待提交推送 / CI未开始）

普通FF推送唯一长期分支；当前已具备提交内容，尚不能宣称CI通过。VERSION42.24.358、静态缓存不变。

最终提交后按实际完整SHA查询所有Actions和Checks（分页完整计数），关键Publish contract/Chrome及SQL合同须核对；未触发项明确标注。最终SHA、远端HEAD、全量运行/Checks清单及结论保存在独立验收附件 `C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-tags-ci-final-20261020.json`。按用户9.4例外，最终CI附件不产生新代码SHA；下次受验证的进度提交需先归档该结果至本专项，再继续。此待验收表述是提交前记录，最终结论必须读取附件和该SHA的GitHub Checks，不借用基线绿色。

## 阶段 F：本地验收（测试通过 / CI待验收 / 生产未验证）

本地验收成立：best.pt、ONNX、RKNN通过同一可信标签来源同步；add/edit实际HTTP JSON均为字符串数组且按class_id，未知省略正常成功；旧ID安全补齐、零重复交付。真实新畅联写入、生产旧Weight、生产OSS、GPU转换与硬件加载未授权未验证。源码交付完成尚待最终SHA CI；CI通过后仅可进入另行授权的部署验收，不自动部署。

新会话接续：先读CODEX_CURRENT_STATE顶部→本文件A至F→独立最终CI附件并核对远端SHA→在下一次受验证提交归档CI；不重复开发已存在标签机制。


## 验收追溯（隔离合同，不冒充生产结果）

| 用户验收项 | 直接证据 |
|---|---|
| 训练完成best.pt标签、JSON数组与class_id顺序 | tags_wire_training_and_completed_onnx_rknn：真实Snapshot排序/条件版本提交→训练发布通知→run_auto_publish_once→真实DTO/Session JSON encoder→PreparedRequest.body |
| 转换完成RKNN/ONNX继承、两芯片一致 | 同用例实际_finalize_conversion_job提交Job与通知原Owner；4个Weight只建立1个远端Version，全部tags同冻结版本；RK3568/RK3576分开验证 |
| 单/双/三以上模型、非字母顺序 | 参数smoke；smoke/fire；helmet/fire/smoke/vest，不截断且不按代码字母重排 |
| 历史不受当前项目影响、版本迭代 | 项目标签current-only与冻结类不同；tags_wire_model_iterations单独验证两个Version各自类序 |
| 未知标签正常同步、不清空 | None参数4个Weight均PUBLISHED且无tags；旧Weight后续真实edit尺寸时仍省略tags，保留模拟后端原标签 |
| 旧ID edit及幂等、文件不重复上传 | tags_wire_old_weight清空旧确认回执，恢复可靠标签→原ID原VersionID edit；上传后ensure_uploaded设为遇调用即失败；再次发布零add/edit；原artifact_id/uploaded_at不变 |
| 真实大小/SHA/尺寸与芯片安全 | 现有完整发布/平台/转换通知三文件回归；新wire用例继续核验训练800/转换640、真实文件事实存在，异常细节沿用原覆盖 |
| UNKNOWN/超时只读恢复 | 上轮既有sync_unknown与恢复测试继续执行；不为本轮复制第二套用例/Owner |
| UI非阻断状态 | 现有Node external-algorithm-publish及Chrome单规格；本轮不改UI |

新链路不执行训练进程、真实转换、GPU或公网业务调用；Snapshot输入为隔离合成类别、Job输出为临时文件，原Worker完成写入格式另由源码与既有测试核对。新增转换通知断言包装真实Event.set并保留原调用，明确每次转换恰好发出一个信号，避免依赖run_auto自动扫描来推断通知成功。HTTP adapter响应为明确Fake后端，不能据此声称真实新畅联业务已接收。


## 只读复核

独立复核未发现tags业务P0/P1；发现1项CI P1依赖遗漏（转换函数间接顶层import psutil，SQL精简Job未安装），已按建议仅补该项。确认网络隔离、真实序列化、原ID edit/禁重复上传断言合理；转换通知增加真实信号发出断言。复核未运行额外测试。
