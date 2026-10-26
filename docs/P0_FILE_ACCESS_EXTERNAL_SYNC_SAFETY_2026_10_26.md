# 业务文件访问与外部同步删除安全专项（2026-10-26）

本文件为本轮唯一需求、设计、进度、故障及验收依据。用户附件80541c09已授权实际开发、隔离测试、普通提交推送长期分支，不部署、不轮换生产密钥、不执行生产删除/扫描/迁移。开始HEAD60dd80d8c6f18a3f93550e2c6028c59ffa07bc9a，VERSION42.24.387；fetch远端0/0，当前隔离工作树干净。原标注4本地提交/WIP、5944与两份模板测试保留，其他工作树不改。

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
| A | 限定调用链、接口文档、业务记录、现有测试审计；不读生产目录 | 已完成待验收 |
| B | P0-01受控文件/原业务兼容、安全RED→GREEN、真实Chrome与独立安全复核；Linux链接和准确SHA CI待验 | 已完成待验收 |
| C | 原同步Owner严格产品合同与疑似状态，异常不进入purger；本地故障注入进行中 | 进行中 |
| D | 原TaskRepository/Worker清理/outbox/恢复、版本锁/归属/备份与故障注入 | 进行中 |
| E | 原Runtime真实状态/分页/同ID重试/有界Loading，Node38、Chrome4通过，追加作用域验收中 | 进行中 |
| F | 最小受影响Python/Node/Chrome、VERSION一次递增、逐阶段普通提交、push前fetch、准确最终SHA CI、部署与轮换手册 | 未开始 |

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
