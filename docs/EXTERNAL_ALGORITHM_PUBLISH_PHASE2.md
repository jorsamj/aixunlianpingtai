# 外部算法平台 Phase 2：训练成果发布 / 回退 / 对账 / GC 当前合同

本文记录新畅联训练成果发布链的**长期技术合同**。会话级 SHA、VERSION 和 CI 状态以 `docs/codex-handoff.md` 最新章节和实时 GitHub 为准，不在本文写死历史版本。

## 1. Canonical owner 与总链路

发布链继续复用现有 owner，不建立第二套模型产物或发布生命周期：

`training version`
→ verified `ModelArtifact`
→ immutable object storage
→ external Algorithm Version
→ original Weight
→ conversion artifact
→ conversion Weight
→ RKNN board validation / metadata promotion
→ drift reconciliation / rollback / exact-ref GC。

唯一 owner 约束：

- `AnnotationRepository`：Annotation Ground Truth；
- `ModelArtifactRepository / ModelArtifactService`：canonical 模型产物；
- `ExternalPublicationRepository + existing auto-publish worker`：external publication / reconciliation；
- `RemoteExecutionStagingLifecycle`：task-owned remote staging GC；
- `version_operations`：version rollback/delete 后 cleanup retry journal；
- `model_delivery_version_fence`：version retirement 与新引用创建并发 fence。

禁止新增第二 ModelArtifact、第二 publication worker、第二 conversion artifact identity 或第二 staging GC owner。

## 2. 原始模型发布合同

训练成功且模型产物完整性验证通过后：

1. 发现/注册 canonical ModelArtifact；
2. 上传到配置的算法与转换结果存储；
3. 使用 immutable object key；
4. 校验 `size_bytes + SHA256`；
5. 生成稳定 `public_url`，不能使用临时 signed URL 作为外部长期地址；
6. 对可访问 URL 执行必要的 HTTP Range GET probe；
7. original 上传成功后才允许创建/恢复 external Version；
8. Version + original Weight 都成功后才进入正式 PUBLISHED / SYNCED 语义。

发布失败不能反向污染本地训练成功 truth。

通用 original Weight 可空 `chipCode`；有明确厂商/芯片的转换 Weight 必须使用真实映射。

## 3. Conversion / RKNN 合同

ONNX / RKNN 等转换产物只能作为已有 algorithm version 的追加 Weight，不能重复创建 Version。

当前产品 Rockchip canonical 转换目标：

- `RK3568`
- `RK3576`

当前产品合同明确不开放：

- `RK3578`
- `RK3588`

RKNN 转换完成但尚未实板验证时保持 `converted_unverified`。板端验证成功后只提升**同一 canonical ModelArtifact** 的 validation metadata：

`converted_unverified → hardware_verified`

不得复制出 verified 第二 artifact identity；原 `artifact_id / object_key / sha256` 保持同一身份。

## 4. External Version / Weight 幂等与 reconciliation

网络超时、返回丢失或进程重启时，禁止盲目重复 POST。

现有 publication owner必须优先：

- 按 canonical Version identity 反查/恢复 Version；
- 按 canonical Weight identity 反查 Weight；
- 找到唯一 Weight 后，继续通过既有 edit owner 对齐 `computePlatformId / chipCode / fileName / filePath`；
- 远端缺失 Weight 时只恢复缺失 Weight，不重复创建 Version；
- 整个远端 Version 缺失时先清 stale provider IDs，再由原 publish owner 恢复 Version + Weight。

低频 drift reconciliation 继续由**同一个 auto-publish worker**执行，不新增第二监控器：

- 正常检查窗口保持 bounded；
- 失败采用退避；
- 单轮数量有上限；
- 同 product 的 Version list 要复用；
- Weight list 按 Version 读取，禁止逐 Weight N+1。

若同一 canonical Weight identity 在远端出现多个候选：

- publication / mapping 进入 `UNKNOWN`；
- auto-publish blocked；
- 不允许任意 edit；
- 不允许再 create 第三个 Weight；
- 必须先人工消歧。

## 5. External delete / local rollback 合同

本地 version rollback/delete 不能因为删除了 publication row 就假定远端 Version 已删除。

正式顺序继续 fail-closed：

1. 对 external Version/Weight 做 provider delete / reconciliation；
2. 删除结果不确定时反查；
3. 只有能确认远端状态后才允许继续本地 version retirement；
4. local version metadata retirement 后，精确清理该 `project_id + algorithm_id + version_id` 的 ModelArtifact / publication mapping / storage object / conversion delivery；
5. 任一清理步骤失败都记录到既有 `version_operations`；
6. 后续通过同一 cleanup journal 幂等续清理，不重建 version metadata，也不重复执行已确认的远端 Version 删除。

immutable storage object 删除失败时必须保留 canonical ModelArtifact row，禁止数据库先删、远端对象状态未知。

## 6. Reference fence / TOCTOU

version retirement 与以下新引用创建必须复用同一 `model_delivery_version_fence`：

- 迭代训练；
- conversion；
- 普通 deployment test；
- RKNN board validation；
- ModelArtifact upload/retry；
- external publish。

拿锁后必须重新读取 version truth：

- version 已退役 → fail-closed；
- 迭代训练 base/current version 已变化 → stale fail-closed。

因此形成双向保证：

- reference 先创建，retirement 能看到 active reference 并拒绝；
- retirement 先完成，后续 reference 创建会发现 version 已不存在并拒绝。

## 7. Remote staging / orphan GC 合同

唯一 owner：`RemoteExecutionStagingLifecycle`，运行在 storage Worker，复用现有 heartbeat；禁止新增独立 timer/thread/scheduler。

普通 task-owned staging 只允许 exact：

`remote-execution/{project_id}/{task_id}/...`

删除必须具备：

- `storage_source_id`
- exact `object_key`
- `size_bytes`
- `SHA256`

删除前必须重新 `stat` 校验。禁止：

- `list_objects` 推断 orphan；
- prefix delete；
- 只凭文件名/目录猜 identity；
- provider/identity 不确定时强删。

以下对象不属于普通 task staging GC：

- canonical ModelArtifact immutable object；
- `remote-training` shared dataset bundle；
- formal material object；
- external Weight / publication mapping；
- version 存活期间仍是 durable evidence 的 RKNN board output。

conversion 本地 orphan、remote training provisional delivery orphan、RKNN board task-owned staging 都继续扩展这一个 lifecycle / fence 体系，不另建 janitor。

## 8. RKNN board durable evidence

active RKNN board validation 会从 `source_conversion_job_id → source_trace` 回溯 version，QUEUED / RUNNING / CANCEL_REQUESTED 时 version retirement 必须拒绝。

成功板端验收后：

- hardware verification 写回 conversion manifest/job；
- board output 的 exact storage identity 作为 durable evidence；
- version 存活时不由普通 staging GC 删除；
- version retirement 时由既有 version cleanup owner精确删除；
- 删除前再次校验 size/SHA256；
- 删除后保留审计 metadata，并明确标记 evidence 已不可用/已删除。

## 9. 性能与失败语义

所有 reconciliation / GC 继续满足：

- bounded page / bounded batch；
- 不做 N+1 OSS HEAD；
- 不做无界 remote list；
- 不做全量 JSON hydration；
- 不引入 O(N²) Python 状态；
- provider/network 异常 fail-closed；
- queued / in_progress 绝不当 success；
- publication retry 不得改变 canonical artifact identity。

## 10. 验证边界

永久 CI 继续覆盖：

- upload / Version / Weight create；
- timeout recover / idempotent retry；
- Weight edit / drift reconciliation；
- ambiguous Weight UNKNOWN；
- rollback/delete cleanup retry；
- ModelArtifact identity 与 RKNN validation promotion；
- exact-ref staging / orphan GC；
- version retirement reference fence；
- frontend publication / conversion contracts。

CI 通过只代表仓库合同验证。生产验收仍应单独取得真实证据：

- 正式 OSS PUT / STAT / Range GET / DELETE；
- 新畅联生产 Version / Weight create / recover / edit / delete / drift；
- Linux / NVIDIA 真实训练与推理；
- RK3568 / RK3576 实板 RKNNLite。

出现真实生产证据与本文合同冲突时，先记录接口/对象/任务 exact evidence，再修改现有 owner；不要先扩架构。

