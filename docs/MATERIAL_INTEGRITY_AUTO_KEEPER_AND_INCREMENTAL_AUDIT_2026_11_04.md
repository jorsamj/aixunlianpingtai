# 素材完整性审计｜重复 GT 默认保留一份与审计复用专项（2026-11-04）

## 2026-11-04 第二批｜42.24.516 · DELETE_INDEX 后可信快速复核（隔离验证）

### 本批解决的真实堵点

- 在**现有** `AUDIT_MATERIAL_INTEGRITY` Worker 内优先寻找同项目最近的成功审计，识别两种无需逐图重新解码的路径：Material/GT/标签没有任何修订（`VERIFIED_UNCHANGED`）；或唯一的修订来自已结束、正式冻结并确认成功的 `DELETE_INDEX` 逻辑退休（`VERIFIED_RETIREMENT_DELTA`）。没有新审计 Owner、第二套缓存或同步扫描前端请求。
- 退休证据必须同时满足：原审计不可变 SQLite/元数据完整、素材 revision 增量与 `material_retirements` 逐张回执数量一致、GT revision 增量与正式持久 GT 删除数量一致、删除 Task 的项目/类型/计划/原审计身份/冻结成功条目一致、退休前 SHA 对应旧问题项、当前索引确实不存在、标签 Schema 摘要不变。任一不成立走原 Full Audit；不以旧快照冒充当前数据。
- 使用 SQLite backup 从原审计生成**新任务持有的审计副本**，旧快照不改写。仅剔除已退休 Image ID，更新关联问题组的规模、同 SHA 正式 GT 类型与诊断，单成员不再冒充重复组。计数和分页继续读取新的正式审计 SQLite。新结果暴露 `scan_mode/reused_images/verified_retirement_count/revalidated_groups/reused_audit_task_id` 供前端明确解释，不伪造实际解码次数。
- 原审计仍会显示 stale，不能继续生成删除计划；用户点击「继续治理 · 复核变更」后，后台新审计任务自动判断能否秒级复用，成功后继续在同一治理工作台批量/分页处理，删除前仍必须冻结预览+二次确认。
- `COCO`/`VOC` 导入补齐同源回归：带已确认映射的结构化清单，明确列出但无框的图片为该映射范围的 `confirmed_empty`，正式 GT 仅一次写入；无可靠映射的原图仍为 `unannotated`，不得擅自判负样本。

### 已核隔离结果与上线界限

- `test_conflicting_gt_auto_keeper_is_stable_and_keeps_one_formal_gt`：纠正对 `AnnotationRepository.get()` 虚拟未标注回退的错误断言，并直接验证 SQLite GT 行真正移除。
- 2531 历史引用的回归：按照新需求自动保留 1 个索引、计划退休 2530 个（原字节和旧 Snapshot 不变），不再期待人工决定。
- 新增“有正式删除回执时绝不重复 materialize、仍保留未处理冲突组、无变化可复用、无关 GT 修改强制回到完整核验”隔离 API 测试；另补“冻结成功回执被破坏强制全扫”和“异常 GT 身份删掉后冲突组正确转为同标注组”回归。
- 当前代码版本 `42.24.516`、前端缓存键 `42.25.513`。本机精确测试和 GitHub 新 SHA 的 Actions 结果应在提交后单独登记；**尚未进行真实 20 万张/OSS/A800/生产浏览器的计时，未部署，不修改正式数据**。
- 本地实际验证：Node 完整前端回归 **1514/1514**；专项目标 API/ZIP/历史回归 **72/72**；新增四个复核场景 **4/4**；Material Annotation Atomicity 首组测试 **200/202**，仅剩两个 `psutil.Process(os.getpid())` 在本工作容器抛 `NoSuchProcess`（运行环境 `/proc` 进程可见性，非产品断言，需以 GitHub Ubuntu 跑测为准）；版本身份、JS/Python 语法和 `git diff --check` 均通过。新 SHA 的 Actions 尚待核验，不把本地结果等同生产验收。
- 这一批专门解决连续安全删除的重复全量解码；**外部上传、直接修改 GT、存储对象变更与标签调整仍回退 Full Audit**。更一般的逐项增量变化日志与来源远程有效性核验、20 万真实 P95、跨 Worker 崩溃恢复属于下一阶段，不能冒称已全面增量化。

### 可验收的操作顺序

1. 初次执行一次 Full Audit，审核冲突组并创建冻结删除计划，手动确认。
2. `DELETE_INDEX` 完成后点击「继续治理 · 复核变更」，新的 Durable Audit 应报告 `VERIFIED_RETIREMENT_DELTA`，只刷新受影响哈希组，所有未变化图片不得重新解码。真实耗时以大数据验收为准。
3. 如有未提交/失败的删除、无关上传或正式 GT 变化，应以现存 revision 和回执为准，不能悄悄认定已经清理；有不可解释变化的任务执行完整审计。
4. 复核新审计的当前计数、分页组明细和新一轮冻结计划，确认旧审计原始字节和历史任务不被改动。

## 用户确认的业务规则

- 同一内容哈希的图片出现不同正式 GT 时，批量去重默认由系统选择一份当前素材及其 GT 保留；用户不必逐组作人工选择。
- 用户仍可在预览前明确指定保留身份；显式人工决定的优先级高于默认规则。
- 自动选择仅是**确定性留存策略**，不是对哪份 GT 更正确的质量裁定；所有结果要让用户在冻结治理预览中看见并手动确认执行。
- 继续使用既有项目审计、冻结计划、后台 `DELETE_INDEX`、素材/GT 所有者和历史证据链。不删除不可变 Snapshot、原物理图片或训练历史；不绕过执行阶段身份、GT 摘要及标签 Schema 的验证。

## 本批实现

1. `platform_core/material_batches.py`：对于无其他异常的 `DUPLICATE_ANNOTATION_CONFLICT` 组，不再一律计入 `MANUAL_DECISION_REQUIRED`。沿用原 `_material_integrity_keeper` 的稳定优先级选取保留项（存在引用/来源/正式标注状态/处理状态/批次/素材 ID）；人工 `manual_decisions` 仍覆盖默认选择。计划中冻结保留项的素材哈希和正式 GT 摘要，并记录 `keeper_reason=AUTO_DETERMINISTIC_CONFLICT`、`auto_conflict_keeper_groups`。
2. `static/app.js`：预览页显式说明系统默认保留组数以及“自动选择不证明 GT 正确”，保留人工指定、整组明确放弃的原入口；修改原“必须人工保留”误导文字。
3. `static/app.js`：当已发布的删除任务最终失败或取消，且 `succeeded/logical_removed` 均为零时，不再只因任务终态就把旧审计 UI 标记过期；后续接口仍按真实素材/正式 GT/标签修订号独立判断过期。

## 质量及安全边界

- 不能假定同 SHA 多份正式 GT 中任意一份一定正确。若来源存在无效图片、内容哈希异常、未核验等其他问题，原 `ANOMALOUS_MATERIAL` 等跳过规则仍生效。
- 显式“整组放弃”是另一操作，不应被默认“保留一份”的策略取代；需要原有确认凭证。
- 计划执行前，GT、SHA、标签及身份变化继续 fail-closed；任务完成后保留素材及 GT 退休证据，用于追溯。
- 不自动开始训练，不修改正在训练的输入、已冻结 Test、历史 Snapshot，不进行生产数据写入。

## 验证矩阵

| 检查项 | 验证方式 | 当前结论 |
|---|---|---|
| 同图不同标注默认保留一份 | API 回归新增/修订；校验自动保留、手工覆盖、GT 及退休备份 | 已编码；需 CI Python 执行 |
| 两次预览保留项一致 | API 回归比较两次计划的 keeper | 已编码；需 CI Python 执行 |
| 失败且 0 删除不误标审计过期 | Node VM 真实函数隔离执行 | 通过 |
| 前端审计与确认文案 | Node `material-integrity.test.mjs` | 36/36 通过 |
| JS 与 Python 语法 | `node --check`、`py_compile` | 通过 |
| Python API/Worker 正式回归 | 需要 pytest、FastAPI、filelock 环境 | 本地未执行，CI 待查 |
| A800 实际 20 万级审计与删除 | 生产部署、耗时分段与操作回执 | 未部署，未验证 |

## 遗留 P0：审计只能治理一次且每次重扫 20 万张

**本批没有解决成功删除后旧 Full Audit 的全局过期问题。** 当前审计 Worker `MaterialBatchHandler._run_material_integrity_audit` 固定遍历整个项目的 `materials.list_page`，每张均 `StorageManager.materialize` 并调用图片分析子进程解码；审计快照绑定全项目 `material_revision`、`annotation_revision` 和标签摘要。只要一次成功逻辑删除使 Material/GT 全局 revision 改变，后续预览就拒绝旧快照。后端这一保护在没有可信差量证明之前不能直接移除。

建议下一批在**原有审计任务与存储所有者**上实现：

1. 以每张素材的可验证来源身份、哈希、GT 摘要和持久修订序列为依据，建立有界的增量审计证据；同一未变化源的图片解码结果可复用。首次完整扫描不丢失，未经验证或来源改变则重扫对应项。
2. 对本系统 `DELETE_INDEX` 的持久退休回执建立精确删除差量投影：仅移除实际成功退休的索引，重算受影响哈希组，并留存原审计不可变证据；未执行/失败项不被误认为已清理。
3. 只有能证明从基准 revision 到当前 revision 的**全部** Material/GT 变更均已纳入投影时才允许复用；未被证实的外部上传、人工改 GT、标签变更必须定向补审或全量回退，不能因为性能要求跳过严格校验。
4. “已处理、真正删除、预览跳过、执行失败、待复核、未核验”分开展示；每个跳过组可定位到原因和下次可执行操作，批量/分页查看跳过项，不能用一个笼统“跳过 N 组”代替解释。
5. 验收：20 万数据一次全量后，多次治理仅复核受影响组及变更素材；跨项目、版本漂移、并发标注、删除重试、任务取消以及 Worker 恢复均须有自动回归及真实计时。禁止用延长超时伪装性能完成。

## 交付状态

- 仅长期开发分支：`feature/external-algorithm-publishing`。
- 本轮范围是默认保留策略和 0 删除误过期修复；**增量审计仍未完成**，不可宣称已解决二十多万张重扫。
- 不执行生产部署、数据库迁移、删除生产素材、主分支合并、Tag、Release 或强制推送。
