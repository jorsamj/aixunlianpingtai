# P2C 数据 Owner 与 PostgreSQL 迁移准备

本文件仅描述源码合同与未来切换门槛；未添加 PostgreSQL 驱动、连接、DDL、Schema Migration 或双写。依据起点 5e9ae265 及本轮仅 Router 提取；没有读取生产库。本轮不能据此宣称 PostgreSQL 已支持。

## 正式域边界

| 数据域 / 唯一写 Owner / 当前存储 | 读取入口与业务身份 | revision / 幂等 / 事务与索引 | 文件引用与兼容门槛 |
|---|---|---|---|
| TaskRepository，task_runtime/repository.py；tasks.sqlite3 | v62、原 Worker；task_id、project_id、kind | claim/heartbeat/完成的 lease_token、attempt、到期条件；BEGIN IMMEDIATE；idx_task_claim/resource/project_list；任务重试不是重新创建身份 | payload/result_ref 指向 ArtifactStore；Worker instance/资源预约/lease/fencing 必须作为同一切换单元，不改状态机 |
| MaterialRepository，material_repository.py；项目 materials.sqlite3 | v61/StorageManager；image_id + project，source_id/object_key 为物理引用，SHA 不是图片身份 | material_meta revision、批处理原回执；按来源、状态、时间/id、SHA、标签索引；同库原子批写 | 保留 JSON 历史导入、共享对象、EXIF/原图 SHA 与坐标；迁移不扫描下载所有对象，不把存在路径当作字节可用 |
| AnnotationRepository，annotation_repository.py；annotations.sqlite3 | 原 GT API/Picker；project+image_id | expected_version CAS，冲突 AnnotationConflictError；annotation_meta/标签引用/删除备份；原事务更新标注与索引 | 正式 GT 与候选分离；保留像素 XYXY/源 SHA/删除备份和历史版本；不得由新库重解释坐标 |
| AlgorithmSqlStore，algorithm_sql_store.py；algorithms.sqlite3 | algorithms.py、v12/summary_only；algorithm_id、version_id，LOCAL/EXTERNAL | algorithm_revision、原导入锁与 SQL 事务，project/版本关联索引；未见全域统一 operation_id，不能声称所有编辑均幂等 | algorithms.json 是既有兼容导入/镜像合同；保留 lineage、训练 job、当前版本；转换权重仍追加原版本 |
| CandidateStore，annotation_candidates.py；每任务 candidates/items.sqlite3 | v60/原审核 Owner；task_id+image_id，box id | review_revision、draft_revision、源 SHA、GT expected_version、提交/转池回执；BEGIN IMMEDIATE；review/state/receipt 索引 | manifest.json/候选来源与编辑草稿；跨 GT 提交日志是恢复协议，不可当作跨库天然 ACID；未知结果查询原回执，不重复确认 |
| ModelArtifactRepository，model_artifacts.py；model_artifacts/artifacts.sqlite3 + config.json | v64/原模型交付及 v39 catalog；artifact_id 与正式 version/SHA/conversion_job 身份 | ux_model_artifacts_identity、version/storage_status/conversion_job 索引；catalog revision 和 conversion_catalog_operations 的 operation_id+request_digest，回执与变更同库事务；文件锁保护配置及交付 fence | 模型文件、OSS object_key、校验与上传状态分离；迁移不得重传或将历史转换产物建为训练版本 |
| ExternalPublicationRepository，external_algorithm_publish.py；external_algorithm_publish/publications.sqlite3 + config.json | 原 ExternalAlgorithmPublishService/回执 GET；publication_key、artifact_id、provider+artifact 的 mapping_id | 原 BEGIN IMMEDIATE、版本/产物映射唯一身份与 project/version 索引；保留请求指纹、UNKNOWN 和已有发布回执；不能用新自增 ID 替换外部身份 | SecretStore 不进业务复制；原自动回传开关/Owner 保持，失败留原任务和版本，未知外部结果禁止重复创建版本/上传 |
| NegativePool，negative_pool.py；复用 MaterialRepository 同库 | v61 negative-pool、原 Picker；material_id、algorithm_id/material_id | negative_pool_meta revision；negative_pool_operations.operation_id/请求 identity/回执同库原子；成员、分类链接及算法归属 FK/联合 PK | 不是第二套 GT/素材；迁移必须与素材 FK 和普通成员 CAS 一起切换，保留历史全局成员和算法范围差异 |
| StorageSourceRepository，storage/source_repository.py；由原 factory 提供 SQLite path | 原 storage factory/manager、配置 API；storage_source.id | runtime_revision 仅用于运行时配置失效，不是全业务统一 CAS；原 source 写锁、reference_counter 和迁移版本；不可虚构全域操作回执 | credentials_ref 仍交 SecretStore；不复制明文密钥；保留 local/OSS/S3/HTTP 类型、连接设置及引用删除保护 |
| BatchSelection + training_selection_reference.py；ArtifactStore/trainselection_*/selection.sqlite3 | 原 Picker/TrainingPrepare，reference+项目/算法/版本/role/请求作用域 | 原冻结 revision/摘要、一次提交标记与 .freeze.lock；BatchSelection 事务、成员唯一身份；manifest 是任务意图，不是 GT 真相 | 引用/内容 SHA/Train-Val-Test 隔离及活动任务保护必须保留；已冻结历史继续按原格式读取，不能重算后覆盖 |

上表只把源码已有机制写为现状：没有统一 CAS 或幂等机制的域必须在未来单域设计中确认，不能由迁移层假定已具备。具体 SQL 以对应模块 _SCHEMA/CREATE INDEX 和事务方法为准；附带源码清单便于逐域查证，不在本轮生成新 Repository 接口。

## 必须显式处理的跨库读取

- material_batches.py：batch_selection ATTACH，用于冻结批处理范围；与实际素材修改的事务/回执边界必须联合设计。
- material_repository.py：rescan manifest ATTACH，保留差异扫描身份和原提交边界。
- training_material_picker_api.py：usage_index ATTACH 为训练使用索引；annotation_gt ATTACH 为正式 GT，包含 SQL 过滤/连接。
- PostgreSQL 不能直接翻译本地 SQLite ATTACH：正式切换前将同事务必需表纳入同目标数据库/Schema，通过原 Repository 查询；不可把一个 JOIN 改成多次无一致性 HTTP/跨库读取。只读投影如允许独立必须写清 revision 高水位，未知状态继续 fail-closed。

## 其余持久化与非迁移数据

| 范围 | 原 Owner / 处理方式 |
|---|---|
| 服务节点、Worker instance、GPU 配置/预约、AI 推理限流/许可 | service_nodes.py、gpu_resources.py、task_runtime/worker_instances.py、inference_resources.py；与 TaskRepository 协调，不新建调度所有权；CUDA 下标不能变为通用 NPU 身份 |
| 任务日志/产物、训练 job.json、finalized 报告、转换 job.json/历史投影 | Task ArtifactStore、训练/转换及报告原 Owner；大日志/权重不进关系数据库，保留受控引用、不可变摘要与恢复记录；conversion_history 是投影，不升格为写真相 |
| 存储导入/治理 manifest、外部算法缓存、质量/资源发现缓存 | 原 storage/material_batches/external_algorithm_platform/resource_discovery Owner；区分冻结事实和可重建缓存，缓存不以迁移生成“正式记录” |
| 项目/标签/配置 JSON、登录会话、SecretStore、审计与历史兼容 JSON | 原 app 项目/标签函数、local_login_auth/changlian_login_auth、secrets.py 等；单域明确写锁/原子替换与读入口，账号/密钥独立授权迁移；本轮不复制其实际内容 |

P2_STORAGE_SOURCE_INVENTORY_20261117.json 收录 platform_core/app 中 Repository 类及 SQLite/JSON 文件字面量的文件和行号。它是静态源码索引，动态拼接路径和运行时数据范围仍须单域确认，不等同于生产库盘点或已批准全量迁移。未确认唯一 Owner/事务边界的项禁止切换。

## 单一写入迁移步骤与可验收门槛

1. **Owner 审计**：为单域补齐全部写入口/事务/FK/索引/异常/回执合同，列出 ATTACH、SecretStore、文件引用；未覆盖入口不得实施。
2. **一致性副本**：授权环境下冻结备份/高水位；跨库范围必须取得一致切面。复制正式业务主键、revision、回执和引用；大文件保留原存储。校验行数、身份集合、摘要、NULL/真实 0、时间和 JSON 类型，不调用执行器。
3. **只读影子对比**：原存储仍唯一写入；按 Owner 有界采样分页/筛选/异常与未知结果，标记同一快照或高水位，不能拿两个时间点数据误判。影子不发写请求、不触发外部发布。
4. **单一写入切换**：短维护窗口/明确写栅栏，停止该域写入与领取，最后增量对账后单次切换 Provider；禁止双写。Task 域必须另有排空/lease 交接设计，本轮未授权。
5. **结果对账**：验证操作幂等重放、CAS 冲突、分页索引、跨表关联、外部 UNKNOWN、冻结与真实 GT 引用；新写只能落一个权威库。
6. **回退窗口**：切换后若尚无目标库写入，可直接恢复旧 Provider；已有新写时先阻断写入、反向一致性导出并核对 revision/回执，再切回。不能直接启用过期 SQLite，否则会丢失新写和重复发布。
7. **旧存储退役**：经过授权观察窗和备份恢复验证后，把旧存储封为只读历史并最终退役；不存在长期双写。版本化兼容读取与对象引用保留到历史任务生命周期结束。

下一批应先选择无执行租约的单域做原 Repository 合同抽象；Task/正式 GT/冻结链路单独授权。没有日期承诺，没有生产迁移完成声明。
