# 2026-10-05 畅联云算法训练平台续接指令

继续处理 GitHub 仓库：

`jorsamj/aixunlianpingtai`

长期开发分支：

`feature/external-algorithm-publishing`

项目：

**畅联云算法训练平台**

这是 Annotation Ground Truth、Training Picker、Dataset Revision v2、训练资源真相，以及发布 / 回退 / GC / 新畅联 reconciliation 完成主要收口后的续接。

不要重新设计架构，不要重复已经 CLOSED 的工作，也不要根据本文件里的 SHA 直接假定当前状态。

## 一、第一步必须重新读取 GitHub 当前真实状态

开始任何开发前必须确认：

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD；
2. `VERSION.txt`；
3. 最近至少 20 个 commits；
4. 当前 HEAD 全部 GitHub Actions / check-runs；
5. 所有 completed failure 的真实 job log；
6. 与当前任务相关的生产代码、测试、workflow；
7. 最终实际生效 runtime / canonical owner。

本文件写入前的参考 cutoff 是：

- HEAD：`18eeb5a59d7319841d5f0a992abf1b7eccd75f0a`
- VERSION：`42.24.108`
- Actions：21 / 21 completed success
- failure / queued / in_progress：0 / 0 / 0

随后本次文档整理会把 VERSION 最小 patch +1 到 `42.24.109`，因此新会话绝不能直接把上面的 cutoff 当成当前 HEAD，必须重新读取远端。

## 二、优先阅读文档

按顺序：

1. `docs/codex-handoff.md` 最顶部 2026-10-05 最新章节；
2. `docs/PROJECT_HANDOFF_CURRENT.md` 顶部 2026-10-05 最新覆盖；
3. 涉及发布 / 回退 / GC / external reconciliation 时读 `docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md`。

旧章节只作历史证据。任何仍写 `VERSION=42.24.0`、把 RK3578 当当前产品正向能力、或把 external reconciliation / staging GC 当未完成工作的旧说明，都已被最新章节 supersede。

## 三、已经 CLOSED，不要重做

### Annotation / Dataset / Training

- AnnotationRepository 唯一 Ground Truth owner；
- AI Candidate → 用户审核 → Commit；
- structured ZIP / YOLO / COCO / VOC annotation_scope 合同；
- label_governance_fence；
- Training Material Picker 读取 AnnotationRepository GT；
- Source GT / Training Projection 分离；
- Dataset Revision v2 绑定 source_annotation_hash；
- split 防 leakage + new-label positive train reservation；
- Trainer 不重新决定 Batch / Workers / Cache / Precision；
- 不恢复 runtime OOM auto-batch、第二 planner、第二 reservation owner。

### ModelArtifact / Publish / Conversion

- ModelArtifact 是唯一 canonical 模型产物 owner；
- original model immutable upload + size/SHA256 + stable public_url；
- external Version / original Weight / conversion Weight 幂等发布；
- RKNN board validation 只提升同一 artifact metadata；
- 当前产品 Rockchip 只支持 RK3568 / RK3576；
- RK3578 必须负向 fail-closed，RK3588 当前也不开放；
- external Weight recover/edit/drift reconciliation；
- remote Version / Weight 删除漂移恢复；
- ambiguous Weight → UNKNOWN + blocked；
- version rollback/delete delivery purge；
- cleanup_failed 复用 version_operations 幂等续清理；
- version retirement 与新引用创建双向 model_delivery_version_fence。

### GC / orphan

- RemoteExecutionStagingLifecycle 是唯一 remote staging GC owner；
- storage Worker heartbeat 是运行 owner；
- exact task-owned object refs + size/SHA256；
- 禁止 list/prefix delete；
- conversion local orphan 已纳入；
- remote training generation orphan 已纳入；
- RKNN board staging / durable evidence retirement 已纳入；
- canonical ModelArtifact、shared training bundle、formal material、external publication mapping 不属于普通 staging GC。

不要新增第二 ModelArtifact、publication、conversion artifact identity、staging GC、Annotation GT、TrainingTaskRuntime、Scheduler、resource planner、GPU reservation、CandidateStore 或 ZIP owner。

## 四、当前真正需要做什么

不要继续把 external Weight reconciliation / artifact GC 当开放式重构项目。

正确顺序：

1. 先处理最新 HEAD 的真实 completed CI failures；无失败则不要凭空修。
2. 根据用户新的产品需求，定位最终 runtime / canonical owner 后做最小改动。
3. 若进入生产验收，优先补真实环境证据：
   - Linux / NVIDIA 真实训练与推理；
   - 正式 OSS PUT / STAT / Range GET / DELETE；
   - 新畅联生产 Version / Weight create / recover / edit / delete / drift reconciliation；
   - RK3568 / RK3576 实板 RKNNLite。
4. 若现场出现 orphan / rollback / publication drift：
   - 先取得 project/algorithm/version/task/artifact/provider exact identity；
   - 查现有 owner 和 durable journal；
   - 证明 reference truth；
   - 再扩展既有 owner；
   - 禁止新建第二套 janitor / reconciliation worker。
5. 继续关注 1k / 10k / 20k 性能：禁止 N+1 OSS/head、无界 remote list、全量 JSON hydration、O(N²)。

## 五、版本与 Git 规则

- 每个正式提交从远端真实 VERSION 最小 patch +1；
- 不 merge main；
- 不 tag；
- 不 release；
- 不 force push；
- 不删除测试；
- 不放宽测试；
- queued / in_progress 不等于 success；
- 一个 workflow success 不等于全绿；
- 不写死 Windows 路径；
- 远端若被其他会话推进，先审新增 commits，再继续，绝不能覆盖别人完成的工作。

## 六、开始时的判断原则

如果最新远端比本文 reference cutoff 更新：

- 先读新增 commits；
- 先读最新 handoff；
- 先看最新 HEAD Actions；
- 已被后续提交 CLOSED 的工作不重复做。

如果最新 HEAD 全绿且没有新的用户需求或真实现场证据，不要为了“继续开发”而人为制造新的重构任务。

