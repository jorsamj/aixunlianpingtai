# 业务文件访问与外部同步删除安全专项（2026-10-26）

本文件为本轮唯一需求、设计、进度、故障及验收依据。用户附件80541c09已授权实际开发、隔离测试、普通提交推送长期分支，不部署、不轮换生产密钥、不执行生产删除/扫描/迁移。开始HEAD60dd80d8c6f18a3f93550e2c6028c59ffa07bc9a，VERSION42.24.387；fetch远端0/0，当前隔离工作树干净。原标注4本地提交/WIP、5944与两份模板测试保留，其他工作树不改。

## 2026-10-26 最终代码验收及接续（生产未部署）

代码最终 **da4de46736a782aa8b11ad55784b3478cbd1ef19 / VERSION42.24.388**，已推送唯一长期分支，准确 **22/22 Actions、59/59 Checks全部成功**。本轮两个已复现漏洞已完成代码与隔离验收：取消整库静态暴露；异常/缺失产品不会触发破坏清理。可信产品删除事件尚无服务商正式契约，生产自动确认默认关闭；用户提供的版本remove接口不等于产品删除，不调用生产。真实生产代理、既往暴露、NAS/OSS与Worker退出仍NOT VERIFIED。下文开发初期“未修复/未提交/待CI”为历史过程，当前结论以本节及末尾回执为准。文档提交自身最终HEAD须交付前独立核验Checks，不借用代码SHA绿色。

## 需求基线

P0-01：取消DATA_DIR静态映射；保留正式静态资源。素材原图/缩略图、训练/推理图片、PT/ONNX/转换成果、ZIP及历史地址必须经登录、项目访问范围、可信业务记录及文件归属校验。禁止任意path下载、路径穿越、越界链接、敏感内部文件、未登记文件和错误绝对路径泄露。生产不能仅因测试多项目标志而绕过登录。提供独立授权的密钥轮换、访问日志核验和重新登录影响说明，代码不自动轮换。

P0-02：外部列表必须区分合法空、格式/业务/HTTP错误、不完整分页、重复或缺失ID；无法证明全集则不得当删除证据。正常训练产品status=1、分析analysisType=1/status=1保持。疑似不能停任务/删除文件；可靠确认后逻辑隔离，再原Durable Task/Worker幂等安全清理，保留发布版本锁、活动引用与共享素材保护。主记录/清理意图先持久提交，再跨系统执行；OSS失败不报成功，失败/重启/重复同步可恢复。8/12/15调度不改。

前端显示真实同步、疑似、确认与清理状态，真实计数、详情、重新核实和安全重试；不提供绕过确认硬删按钮、不伪造进度、不重复Toast，异常/超时结束Loading。

## 已确认根因与实现选择

- app.py仍mount('/data', StaticFiles(DATA_DIR))；登录保护不等于业务对象授权。现有StorageManager内容/缩略图及评测证据接口继续复用；其他业务产物经已有任务/算法版本/manifest记录解析。历史/data兼容只作受控路由，不恢复静态目录。仅封禁文件名或允许模型目录任意扩展名均不能满足登记授权，不采用。
- 登录test bypass仅判断MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS。将限制为显式隔离测试启动条件，生产误设单一标志不得关闭认证；不新增RBAC/用户表。当前生产固定空间是访问范围基线，无法证明可访问的其他项目拒绝文件读取。
- 同步products(status='')不能证明状态全集，缺失项现进入LocalPurger，且破坏操作在缓存/算法镜像提交前。保留原Repository/锁/Worker，先严格解析和缺失保护；官方删除证据不明时只疑似。确认后的持久清理意图和步骤审计是唯一执行依据；不再由同步HTTP流程直接purge。
- 备选“异常空列表拒绝、其余照删”不能处理截断/状态过滤；备选直接禁用全部最终清理丢业务。采用完整性证据+确认+持久任务安全清理。跨DB/文件/OSS不宣称全局事务，失败只能靠原持久状态和幂等恢复。

## 执行计划与进度

| 阶段 | 具体修改及证据 | 状态 |
|---|---|---|
| A | 原文件/同步/清理Owner及官方合同定向审计，版本删除与产品删除区分 | 已验收 |
| B | 受控文件及旧地址兼容，真实API/Chrome和独立安全复核，Linux安全50/50无跳过 | 已验收 |
| C | 严格产品合同及疑似保留，错误/缺失/不完整输入无破坏 | 已验收 |
| D | 原Worker持久清理、租约/消费者/Checkpoint/OSS备份和恢复，真实Provider契约默认关闭 | 已验收 |
| E | 原前端七态/计数/分页/同ID重试/有界Loading与ABA隔离 | 已验收 |
| F | VERSION388、安全快进推送、代码SHA22/22 Actions及59/59 Checks；文档自身HEAD另核 | 已验收 |

每阶段先复现再修复。文件安全API复用tests/conftest.py隔离目录与TestClient；认证另构造真实SignedSessionManager cookie，未经登录必须失败。同步故障复用tests/unit/test_external_algorithm_platform.py与原fake HTTP，不调用真实Provider/OSS。浏览器沿原external-algorithm-platform/质量/素材用例做必要冒烟，不跑真实训练，不新增第二测试框架。

## 验收和风险（开发开始）

当前两个P0均未修复，尚无本轮GREEN/提交/CI；不能沿用VERSION387的绿色代替。本地文件业务登记、旧模型扫描兼容、项目隔离、生产test开关、产品全集/详情删除证明和原清理任务扩展均需以真实代码审计补充。生产访问日志、既有密钥暴露范围、真实NAS/OSS软删除/版本恢复和停机退出仍NOT VERIFIED。

生产步骤仅文档交付：备份auth、任务/算法/产物/发布/存储索引及所需恢复数据；先关闭通用静态暴露并验证正常业务；核验旧/data内部路径访问日志（保留证据但不打印密钥）；部署人员确认后停写/备份旧签名密钥、生成替换并重启认证进程，告知全部会话需重新登录。具体可执行命令和回滚限制将在代码确定后补齐，当前不执行。


## 2026-10-26 阶段A/B真实证据（持续更新）

- 官方产品schema只读取得：[list分页](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837722e0.md)、[listAll](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837723e0.md)、[getInfo](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837724e0.md)。产品status1上架、2下架（不同于分析方式status1/0）；list分页pageNum/pageSize必填，listAll无分页参数且status无默认定义；data/total未声明必填，详情无明确不存在/删除业务码，delFlag无取值解释。不能据省略status、空详情、404或两次列表缺失自动确认删除。
- 用户补充版本删除schema：GET /internal/algorithm/algorithm-version/remove/{algoVersionIds}，int64数组，版本删除级联全部权重，RInteger只有字段类型。此为版本级危险写接口，不是产品已删除证据，也不能用作存在探测。本轮不调用生产；PRODUCT_DELETED与VERSION_DELETED必须区分。
- P0-01首批API RED：4项隔离敏感文件可被登录用户读取（会话key/模拟SQLite/内部storage/Worker）及未登记模型可下载，5失败。取消通用静态映射后内部4项通过，旧模型下载需同resolver补齐。真实已登记素材/缩略图保留，跨项目存在素材拒绝通过。
- 认证测试新增5项先RED（隔离校验函数缺失），补齐显式test build+显式OS临时数据根+原flag共同条件。生产仅误设多项目flag不会关闭认证。现有认证测试曾1失败/25通过：Windows撤销数据库因原SQLite上下文不关闭连接导致unlink失败；将原3处连接明确closing且保留事务，认证20/20通过，未跳过此安全断言。
- 新业务文件resolver单测17通过、1 Windows无symlink创建权限跳过；链接/越界用例将由原登录安全Linux CI真实执行，不能以Windows跳过视为验收。原登录工作流仅加入新安全文件及定向API测试，已迁移的test flag源码守卫指向原auth Owner，另校验app调用新隔离检查；不删守卫、不新建CI。
- 当前仍无本轮最终提交/CI结果；完整业务兼容及P0-02仍进行中。所有访问为隔离测试目录和公开API文档，没有生产素材/GT/OSS/会话密钥操作。


## P0-01业务兼容与定向验收（未提交、独立复核中）

已取消通用/data静态mount，原静态/static不变。新增BusinessFileService为唯一业务文件解析器，API和历史/data兼容同项目/记录/路径/SHA校验。原素材StorageManager、source lease、正式AlgorithmSqlStore/ModelArtifact、TaskRecord/ArtifactStore为权威，不建平行素材/模型库。旧JSON不能复活已删除SQL版本；转换ZIP只打包登记outputs，不附邻接日志/配置。

新预测输入/结果沿原.evidence.json记录SHA；ONNX登记原job/SQL version.exported_models；模型ZIP扩展原model_meta.zip_sha256。没有来源登记的历史独立模型/ONNX继续拒绝，列表URL为空并说明恢复来源，不以目录存在视为授权；历史有可信来源的图片/模型/导出保持兼容。

实际测试命令与结果（重叠不重复累计）：

- 六文件：test_business_files、test_controlled_business_files、test_material_content、test_deployment_test_runtime、test_deployment_artifact_visibility、test_online_feedback：63 passed / 1 Windows symlink skip。
- 随后新增HTTP与权限/脱敏，仅受影响test_controlled_business_files：29 passed / 1 Windows symlink skip。
- test_material_content + test_training_material_picker_api：16 passed；test_label_mapping_samples + test_zip_class_samples_v19：8 passed。
- test_changlian_login_auth：20 passed；父P002疑似发布保护新增6先RED，连原正常发布1共7 passed。
- 真实Chrome：material-thumbnail、quality-detection-workbench及model-and-conversion的RKNN converted_unverified三项3/3；原auth config两项2/2。均隔离接口/模拟执行，没有真实GPU/生产访问。
- P002前端纯状态和真实计数2项先RED，原external platform Node文件20/20通过；完整UI仍开发中。

当前P001等待独立只读安全复核，P002后端/原UI并行实现但尚未验收；所有工作未推送，无本轮CI结论。不得把以上定向通过当作两个P0全部完成。

## 生产部署、备份与签名密钥轮换手册（仅供另行授权执行）

1. 部署前由运维确认反向代理没有直接把DATA_DIR（包括/data/platform-data）用alias、容器静态服务或对象公开列表暴露；仓库未发现nginx/compose配置，生产代理仍NOT VERIFIED。/data历史业务路径应交给本应用的受控兼容路由。
2. 停止全部Web与Worker写入后，备份auth目录、projects元数据、algorithms.sqlite3、任务/模型产物/发布/存储索引及清理outbox/回执；SQLite用离线一致副本或其backup API，不在写入时直接复制单个WAL主文件。原图/GT不迁移、不重建。
3. 先保存生产访问日志，只检索/data/auth、task_runtime、storage、secure/secrets及数据库后缀访问的状态/时间/来源。不要把响应体、cookie、密钥或URL中的敏感查询参数粘进仓库。没有访问记录不能证明从未暴露，应按潜在泄露安排轮换。
4. 代码更新本身不换key；会话保持。运维确认轮换会使全部既有cookie失效并需要重新登录。确认进程已停止且有安全备份后，以下Linux离线步骤才可执行；本轮没有执行：

```bash
python - <<'PY'
import os, secrets, time
from pathlib import Path
root = Path('/data/platform-data/auth')
key = root / 'changlian-session.key'
if root.is_symlink() or key.is_symlink() or not key.is_file():
    raise SystemExit('auth path is not an ordinary offline file')
backup = root / ('changlian-session.key.backup-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()))
with backup.open('xb') as out:
    os.chmod(backup, 0o600)
    out.write(key.read_bytes()); out.flush(); os.fsync(out.fileno())
replacement = root / 'changlian-session.key.rotate-pending'
with replacement.open('xb') as out:
    os.chmod(replacement, 0o600)
    out.write(secrets.token_bytes(48)); out.flush(); os.fsync(out.fileno())
os.replace(replacement, key)
os.chmod(key, 0o600)
print('Key rotated offline; restart services and require login. No key printed.')
PY
```

5. 先验未登录受控API401/旧资源登录跳转，登录后正常原图/缩略图/PT/转换/ZIP/历史结果；敏感、未登记、越界/跨项目地址失败，错误不返回绝对路径；最后核验后台同步与原调度。真实NAS/OSS、生产历史完整性和实际训练停机仍需授权环境验收。
6. 回滚不得恢复旧/data整目录静态映射，也不应恢复可能已暴露的旧签名key。新增安全元数据保持兼容、outbox/回执必须保留；清理中的旧程序不识别新保护状态，回退前停止同步/Worker并评估恢复副本，不能简单运行旧“缺失即purge”代码。物理清理恢复需要按逐项回执与SHA恢复，不能宣称数据库事务能复原OSS。


### P0-01独立审查及阶段提交

独立只读审查复现P1兼容回归：正式Paddle outputs中的infer_cfg.yml被文件类型过滤，ZIP还拍平目录。新增API test_conversion_package_preserves_registered_inference_config_and_directory_layout先RED。修复仅允许可信outputs的正式json/yml/yaml配置，保持经过路径检查的原相对层级；未登记邻接配置仍拒绝。相关API+resolver+原deployment_artifact_visibility共52 passed / 2 Windows symlink skip。审查者独立重验新增案例1 passed，当前P001无已证实阻塞。

P001将独立本地提交（完整SHA见本文件下一阶段记录/提交历史），暂不单独部署。P002当前WIP不加入该提交。VERSION按本轮一次递增留待最终集成，当前阶段仍387；不代表生产已升级。准确SHA CI待最终正常push后核验，不能把本地定向通过写成远端全绿。


## P0-02核心后端验收与独立复核（本地、CI待验）

P001独立提交 **ee9750ab10090dce6291a3786ba52e625e6af512** 已保留；当前P002未推送。严格产品snapshot解析保留官方code/data、字段、唯一ID/total契约；未知、混合坏行、分页截断、HTTP/业务失败不能变空数组。合法空/产品缺失只进入SUSPECTED_DELETED，不调用同步purger；恢复出现解除疑似，正常上架/分析方式资格仍原合同。所有缺失都被保护，不用不可验证的数量阈值授权删除，空集或大幅骤减也不能越过确认；有效存在产品仍可更新。

删除确认仅服务器可信适配器调用CleanupRepository(..., contracts=(VerifiedDeletionContract(...),)).confirm_deleted(..., DeletionEvidence(...scope='PRODUCT_DELETED'))，contracts默认空。没有HTTP确认/force入口。适配器必须先校验真实服务商契约、事件签名及身份，普通404、空详情、连续缺失和用户提供的版本remove文档均不构成产品删除证据。生产自动确认仍关闭，需服务商补充权威产品删除契约；不能宣称本轮已验证真实Provider删除事件。

算法隔离与outbox在原algorithms.sqlite3同事务提交，新的TaskKind.EXTERNAL_ALGORITHM_CLEANUP由原storage Worker/Scheduler处理；原heartbeat仅派送已提交意图，不新建调度器。每个删除cycle稳定operation/task ID；旧lease/旧cycle不能触碰新代。先收集归属及引用、原版本锁、请求安全取消并通过Worker heartbeat有界等待退出，再按持久计划及回执执行。失败同ID重试，主记录最后移除，outbox/audit保留。

OSS专属key、源/版本/文件SHA及共享引用验证；硬删前保留并验证恢复副本，删除后读回，失败不报成功。跨DB/文件/OSS没有假全局事务。正常位置移除但恢复副本明确recovery_retained=true，不能宣称物理磁盘已全部释放。历史目录含symlink/junction当前保守阻断，需要原Owner核验；不强删共享目标。

独立复核发现并关闭P1：其他任务合法label_contract.base_model_reference冻结Checkpoint、其他历史版本只有stored_path且无ModelArtifact时，原新增guard漏检。两例先RED后GREEN，补全全项目Task payload/checkpoint/result及正式引用、所有隔离root/source与其他版本路径检查，在任何cancel/OSS/rename前及原version fence下即时复验；计划后插入消费者也阻断。审查者独立4项通过（冻结训练、历史版本、跨项目、迟到消费者），无已证实残留阻塞。旧LocalPurger.purge破坏执行体已退役，直接拒绝，实际清理只有原Durable handler。

原conversion request新增冻结algorithm_id/version_id/source_id，来源于服务端解析的source/source_trace；原portable用例先RED后20/20通过。清理API与原外部发布/同步router复用同项目范围校验；实际跨项目cleanup状态请求先RED，再连原相关6项共7/7通过。疑似仅阻该算法新发布，父发布保护新增6先RED，连原正常发布共7/7通过。

实际后端测试：

- external platform/cleanup/auto_sync/model_artifacts/algorithm_sql_store/worker_registry六文件短临时路径：262 passed / 1 Windows symlink skip，0失败。
- 首次原模型4项因Windows长路径WinError3失败，改短basetemp定向4/4验证，再上述全组通过；未降低断言。
- 补审后的cleanup文件40 passed / 1同类skip，覆盖OSS失败/备份、对象共享/归属、最终SQL失败、中途退出/重启、重复/并发、旧lease与cycle、活跃安全退出、冻结与跨项目引用、迟到consumer。
- 最近核实时间新增1项RED→GREEN：first时间保持、checked_at随成功观察推进，无重复state history或业务revision；相关5项定向通过。
- 原两份受影响CI源码守卫已迁移：从“缺失必硬删/同步purge锁”改为缺失保留、不调用purger、确认marker、原Worker kind及version fence；动态安全断言全部保留。原guard脚本本地实际退出auth=0、external=0。新增cleanup测试只接原external工作流及必要标准依赖，不新建CI。

前端正在最终集成：Node38/38、原Browser2+新增P0三项分批5/5；新增绘制异常2个独立RED后GREEN，相关Chrome2/2和最后1/1，保持原按钮/Modal/轮询Owner。VERSION最终统一388/cache436，版本Owner10/10通过；尚无远端CI结论。


## P002阶段提交、前端最终本地验收及推送状态

核心后端本地提交 **06ce390d660b21677f575b4547c5ab618e47a8a4**，接在P001 ee9750ab之后，未覆盖其他工作树。疑似发布6+正常发布1、conversion portable20及实际项目隔离7通过；共享问题修复后独立4项复验通过，后端没有已证实残留阻塞。Windows softlink能力限制待Linux CI，不标验收。

前端沿原external platform/algorithm list Runtime、原Modal及单一poll promise完成：真实七态、同步/清理数量、25行分页、同步记录/技术详情、疑似核实、失败同task重试、刷新恢复、活跃训练与待核实同时显示。只疑似承诺现有任务继续；确认后说明安全停止和等待，不把失败/恢复副本当训练仍继续。不新增确认或强制硬删入口。

真实前端异常发现与修复：

- 首次绘制在try外导致后续点击无POST、finally绘制失败遗留disabled/aria-busy，两独立Chrome先RED后GREEN；finally先恢复原按钮，再执行可能失败的面板渲染，异常仍上报。
- 独立审查再复现A→B→A旧GET覆盖成功新A且误锁，新增Node覆盖ABA/同项目旧GET/旧错误/旧POST/HTTP200坏JSON共5个RED后GREEN。GET成功和错误均校验scope generation+read ordinal，POST首次回执即校验submission epoch；200坏JSON抛明确ParseError，保留原running供重新查询。
- 最后相关Node43/43；Chrome原2+P0三项合计5/5，之后绘制fault case两处注入及既有HTTP场景定向2/2、最终fault1/1；项目迟到/分页1/1，HTTP/永挂/坏JSON查询1/1。独立审查5项复验确认ABA关闭。重叠不重复累计，不冒充单次全仓通过。
- VERSION本轮一次387→388；app/main/styles缓存436，external63023、algorithm-list4226389。版本Owner10/10，原auth/external全部永久守卫实际退出0；主业务不重跑无变更全组。

Git网络出现TLS握手失败，HTTP代理/OpenSSL/SOCKS和直连均未成功；GitHub连接器与GitHub API仍可读，已新核验远端仍60dd80d8，无其他提交被覆盖。本地阶段成果全部保留。若Git传输持续失败，将采用GitHub Git Data API上传同一对象/仅快进更新，不强推、不使用第三方代理托管凭据；最终准确远端SHA及CI必须另核验，当前尚未推送，不宣称CI通过。

## 首轮远端 CI 及最小兼容修正

阶段提交 ee9750ab、06ce390d、ab40a9fb 已经通过 GitHub Git Data API 原对象上传及 force=false 快进推送，返回 SHA 与本地逐一完全相同；未改写共享历史。首轮最终 ab40a9fbcd9dcdb2c3811acbabe365761ab55525 实际 49 Actions：30成功/19失败；132 Checks：109成功/23失败，不能作为验收通过。

失败根因与修改：新增 auth 测试的整包导入触发精简环境缺少 filelock，改复用既有 importlib AUTH；旧外部发布产品夹具补充真实必验 productType/status；严格解析兼容原客户端既有业务成功码0和200，仍拒绝布尔码、错误码、不完整字段与总量；素材选择器源码守卫迁移至更严格的项目授权回调，并断言仍复用 get_project/list_projects；一项字典 HTTP 测试在 monkeypatch DATA_DIR 后不再满足隔离绕过，现使用真实签名登录 Cookie，不放宽生产认证。多工作流共享上述测试而产生重复失败，不是19个独立缺陷。

修正后最小本地证据：auth/audit/router三文件29通过；产品及原发布相关24通过；不可信产品快照13通过；字典真实登录HTTP1通过。首次新增成功码200测试的审计预期仍写0造成失败，已同步为实际参数后上述29通过。VERSION保持388，不重复递增；无删除测试、降低安全断言或扩张CI依赖。修正提交及其准确SHA的全部CI仍待后续核验。

修正代码5eea5b0d9b73bc965e5d2066c845b5317cb41005已正常快进推送。新CI发现一项未改动的旧ZIP测试时序：只等两次setImmediate就读取尚未完成内容指纹/会话rekey的行，1342项Node中1341通过、此项undefined progress失败。原ZIP业务本轮无diff；测试改为有2秒截止地等待真实XHR分片已派发，再注入进度并执行原有不倒退断言，新增必须确有分片的断言，不降低业务验证。该文件8/8通过；不改上传控制器或协议。最终新SHA仍须重新核验CI，5eea失败不当作绿色。


## 最终代码回执、兼容性与发布边界

- 最终代码：[da4de46736a782aa8b11ad55784b3478cbd1ef19](https://github.com/jorsamj/aixunlianpingtai/commit/da4de46736a782aa8b11ad55784b3478cbd1ef19)，VERSION42.24.388。准确22/22 Actions、59/59 Checks成功，失败0、取消0、跳过0。[最终前端工作流](https://github.com/jorsamj/aixunlianpingtai/actions/runs/40267329749) Node1342/1342、真实Chrome291/291成功；不是本地重复全仓执行。
- 改动安全/后端的5eea5b0d准确登录工作流已成功：[Linux文件安全与登录](https://github.com/jorsamj/aixunlianpingtai/actions/runs/40267037033)，受控文件安全50/50无跳过，登录Chrome2/2。其全体CI不能写成全绿：旧ZIP测试失败、后续推送导致部分原作业取消；后续da4de只修复测试等待且完整准确CI全绿。本地Windows软链接跳过的边界已由Linux实际执行覆盖。
- 本地核心Python六文件262通过/1 Windows链接skip；补审cleanup40通过/1同类skip；P001相关52通过/2同类skip；项目隔离7、发布保护7、转换身份20通过。CI修正相关29+24+13+1分组通过，重叠不相加。Node最后受影响两文件43通过，原ZIP8通过；本地Chrome按前文定向场景分批通过，最终仓库Chrome291通过。首轮失败、RED及修复过程全部保留，未删除测试/降低安全断言。
- 主要代码：app.py；platform_core/business_files.py、changlian_login_auth.py；external_algorithm_platform.py、external_algorithm_cleanup.py、external_algorithm_auto_sync.py、external_algorithm_publish.py；algorithm_sql_store.py、model_artifacts.py、storage/rescan_tasks.py、task_runtime/models.py；原static/modules/external-algorithm-platform.js、algorithm-list-runtime.js及main/styles/index缓存。受影响单测/API/Chrome与原两份工作流同步，完整文件差异以基线60dd80d8至上述提交为准。
- 不强制迁移历史图片/GT，不重建Task/Storage/Material Owner；原数据库按既有schema初始化新增持久清理元数据。正式部署需先一致备份数据库及outbox，不执行生产迁移。未登记历史模型不会开放任意目录下载，需恢复可信来源；登记的图片/模型/导出及Paddle配置层级已验证。
- 代码不轮换签名密钥、旧登录会话不因本次代码更新自动失效；潜在泄露后须运维另行授权轮换并通知重新登录。生产反向代理不可另行直出/data。备份、日志核验、手动轮换、验证与回滚限制见本文件操作章节。
- “清理已完成”保留recovery_retained及恢复副本，不能宣称磁盘空间全部释放；未知引用、活动消费者、symlink/junction保守停止。真实产品删除事件签名/语义、生产NAS/OSS、活动Worker退出、访问日志和旧密钥泄露范围不在隔离测试可证明范围。
- 原标注工作树HEAD8ba6ce1a的4本地提交/WIP、5944e1a558a34f7be008b644a5a3b07b4ed132cd及两份未跟踪训练模板测试已再次核对，全部保留。没有生产部署、删除、扫描、迁移、收费模型调用或真实训练。

接续：先由部署人员按操作章节核验代理、完整备份和密钥处置；真实产品删除契约取得前保持自动确认关闭，不把版本remove/404/空列表改成产品删除证据。需要启用真实自动确认时，仅在原VerifiedDeletionContract适配点验证服务商证据，不新增强删HTTP入口。文档收尾提交不再修改业务代码/VERSION；其自身准确SHA CI由最终交付核对GitHub Checks并归档，不形成自引用SHA或借旧绿。
