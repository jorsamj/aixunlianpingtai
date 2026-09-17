# 畅联云算法训练平台 — 当前接手总览

> **新 AI / 新开发人员先读本文件。**  
> 目标：10 分钟内知道“当前在哪个分支、什么已经做完、什么绝对不能重做、下一步该做什么”。

更新时间：2026-09-17  
仓库：`jorsamj/aixunlianpingtai`  
正式版本：`VERSION.txt = 42.24.0`  
当前持续开发分支：`feature/external-algorithm-publishing`  
本轮产品实现基线：`9873610ae75804348da73b6afd8212abecf4be95`  

> 本文提交本身可能继续推进分支 HEAD，所以 **不要把上面的实现 SHA 当成 checkout 目标**。接手时必须先读取远端最新 HEAD，从远端真实最新状态继续。

---

# 0. 接手第一分钟必须执行

不要先改代码。先确认真实状态：

```bash
git fetch origin
git switch feature/external-algorithm-publishing
git pull --ff-only
git status
git rev-parse HEAD
git rev-parse origin/feature/external-algorithm-publishing
cat VERSION.txt
```

然后再看：

```text
docs/PROJECT_HANDOFF_CURRENT.md
docs/BUG_AUDIT_2026-09-17.md
docs/CODEX_CURRENT_STATE.md
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

### 绝对约束

1. **不 merge `main`**，除非用户明确授权。
2. **不修改正式 `VERSION.txt`**，当前必须保持 `42.24.0`。
3. 不 tag。
4. 不 release。
5. 不为了测试通过删除测试、降低阈值、放宽断言、恢复 legacy owner。
6. Windows 开发 + NVIDIA Linux 生产必须同时兼容。
7. 任何“完成”必须有真实代码 + focused test + permanent guard；关键前端运行链路尽量有 Real Chrome。
8. A800 RC / genuine 10k ZIP 性能验收不要擅自恢复，除非用户重新要求。

当前 `main` 最近一次已验证仍为：

```text
2fe9394ccb10068d81cc2113879ac801c4831017
revert: keep external algorithm integration off main
```

如果接手时 `main` 不再是这个 SHA，先查是谁、为什么改，不要自动把 feature 内容合进去。

---

# 1. 产品定位

产品：**畅联云算法训练平台**。

当前优先目标不是做一个好看的 Demo，而是形成真实可用链路：

```text
素材导入
→ 数据清洗 / 标注
→ 训练配置
→ durable training task
→ 模型版本
→ 模型转换
→ 部署/发布
→ 线上算法回流
→ 评测
→ 低准确率算法再次迭代
```

当前主要算法框架：

```text
Ultralytics / YOLO
Paddle（兼容扩展）
OpenCV 等辅助能力
```

长期生产架构目标：

```text
Web / API
Scheduler
Training Worker
AI Label Worker
Video Worker
Model Conversion Worker
Deployment Test Worker
Publish Worker
```

Windows 负责开发、页面、普通 CPU 测试、素材/标注、视频切帧、小规模训练、ONNX 等；正式 GPU 训练/转换统一考虑 NVIDIA Linux。

---

# 2. 当前数据 owner / truth

这是最容易被新接手者弄乱的部分。

## 2.1 算法资产

**当前 authoritative store：SQL。**

主文件：

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
```

项目级存储目前为：

```text
algorithms.sqlite3
```

旧：

```text
algorithms.json
```

仅作为历史迁移源；首次迁移会保留：

```text
algorithms.json.pre-sql-migration-backup
```

### 重要：普通 CRUD 已经是 row-level SQL

不要再做一次“把 create/update/delete/version attach 从全量 replace 改为 SQL CRUD”的重复工作。

当前普通 owner 已经调用：

```text
AlgorithmSqlStore.create_algorithm
AlgorithmSqlStore.patch_algorithm
AlgorithmSqlStore.delete_algorithm
AlgorithmSqlStore.attach_version
AlgorithmSqlStore.patch_version
AlgorithmSqlStore.rollback_version
AlgorithmSqlStore.delete_version_with_operation
```

外部平台镜像也调用：

```text
AlgorithmSqlStore.sync_external_algorithms
```

`save_algorithms()` 仍保留用于兼容路径/测试，不代表主业务仍把 JSON 当数据库。

## 2.2 Durable Task

任务真实状态以后端 TaskRepository / durable task runtime 为准。

前端不能自己“猜”任务已经结束、排队第几名或剩余百分比。

当前已关闭的核心任务 truth 包括：

```text
Training
AI annotation
material batch
storage scan/import
server ZIP import
resource discovery
video processing
deployment tests
```

公共 task projection 的 authoritative 字段优先级参见 `docs/CODEX_CURRENT_STATE.md`。

## 2.3 上传任务用户可见 owner

现在统一是：

```text
static/modules/upload-task-center.js
```

右下角显示：

```text
普通图片上传
ZIP 分片上传
ZIP 合并/校验
后台导入
标签映射
标注写入
素材索引
```

旧单任务 `zipImportDurableDock` 只保留兼容/详情 owner；当统一 Task Center 存在时应保持隐藏，不能再恢复第二套可见浮窗。

---

# 3. ZIP 上传 / 标签导入当前实现

这是 2026-09-17 最新重点批次。

## 3.1 ZIP 网络上传

主文件：

```text
static/modules/zip-import-runtime.js
platform_core/zip_multipart.py
app.py
```

当前：

```text
part size:        8 MiB
max concurrency:  4
part retries:      2
```

服务器每个 part 独立持久化，最终 assemble：

```text
确认所有 part 完整
→ 合并
→ 精确检查 assembled bytes
→ 计算完整 ZIP SHA256
→ 标记 multipart completed
→ 清理 parts 目录
```

浏览器续传 fingerprint 已不再只用 filename/size/mtime，而加入文件头/中/尾采样内容摘要，降低误复用另一个 ZIP 分片的风险。

### 刷新时

如果刷新发生在 browser File 还在上传的阶段：

```text
任务状态显示：上传已暂停，等待继续
```

用户重新选择同一个 ZIP 后，浏览器重新计算 fingerprint，服务器返回已完成 parts，仅继续缺失部分。

不能在刷新后继续显示“正在传输字节”，因为浏览器已经没有原 File stream。

## 3.2 ZIP 整体进度

必须区分：

- 网络上传百分比；
- 整个 ZIP 导入任务百分比。

当前整体进度：

```text
网络上传：       0 → 35
服务器合并：     36
ZIP 校验：       37
等待后台导入：   38
后台任务：       38 → 99
全部完成：       100
```

实际网络上传百分比继续显示在文本详情。

禁止恢复“上传 100%，然后后台又退回 8%”的旧表现。

## 3.3 YOLO 标签映射 / 索引

主文件：

```text
platform_core/storage/import_tasks.py
```

标签确认后 durable 阶段包含：

```text
mapping_labels
writing_annotations
indexing
```

当前索引事务批次：

```text
INDEX_BATCH_SIZE = 50
```

不要再改回 500 张一个大批次。用户之前 500 张转换时长时间无反馈，核心原因之一就是一个超大的落库批次。

---

# 4. 训练任务当前实现

## 4.1 创建训练

训练弹窗必须直接带：

```text
算法名称
本次训练任务 ID
```

任务 ID 格式：

```text
train_<16~32 hex>
```

前端唯一网络 owner：

```text
TrainingSubmitRuntime
static/modules/training-submit.js
```

后端：

```text
/api/v12/projects/{project_id}/train/start
```

同一个 planned task ID 如果因为响应丢失被再次 POST：

- 同项目；
- 已存在 task kind = TRAINING；

则返回已有 task，不能创建第二个训练任务。

## 4.2 迭代训练

已有算法继续训练时，必须基于该算法**当前/最新成功、产物完整性已验证、框架匹配**的模型版本。

禁止因为上一轮失败就悄悄回到母算法重新训练。

相关：

```text
platform_core/algorithms.py
choose_algorithm_iteration_base()
resolve_current_version_id()
```

## 4.3 用户对训练弹窗的明确偏好

不要重新加回：

```text
预计时长
训练完成后通知
大量提示性废话
标签缩略图
标签右侧 xx 张
```

需要：

```text
算法名称默认带入
任务 ID
数据质量按钮
本次训练标签选择
训练摘要：轮次 / imgsz / batch / 阶段检查 / 转换等
```

---

# 5. 新畅联平台交互

## 5.1 Domain 关系

当前按：

```text
品目
→ 产品
→ 分析方式
→ 算法版本
→ 权重文件
→ 算力环境
```

外部算法主数据同步到本平台后：

```text
source_type = EXTERNAL
provider_type = CHANG_LIAN
master_data_readonly = true
```

本地已有算法不能因此消失。

外部产品从远端消失时：

```text
external_active = false
```

保留历史训练/版本，只阻止新训练。

多分析方式产品创建训练时必须明确绑定本次 `external_analysis_id`。

## 5.2 当前认证事实

现在不是最终 production canonical signing。

当前明确：

```text
/internal/auth/test-sign
→ /internal/auth/token
→ Bearer Token
```

UI/API 明确暴露：

```text
auth_mode = test_sign_bridge
```

后续不能把这个事实改写成“正式签名已经确认”。

## 5.3 发布

已经实现 Phase 2：

```text
训练版本/转换产物
→ artifact index / object storage
→ stable download gateway
→ 新畅联创建算法版本
→ 新畅联创建权重
→ 保存 remote IDs
```

核心原则：

- 发布失败不能破坏本地已验证模型；
- 有 idempotence / retry / UNKNOWN 处理；
- HTTP timeout 后不能盲目重复创建远端对象。

详细见：

```text
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

---

# 6. 2026-09-17 BUG 审计结论

完整记录：

```text
docs/BUG_AUDIT_2026-09-17.md
```

本轮已经修复并进入永久测试：

```text
FIX-01 Linux 无 Keyring backend 导致 config 500
FIX-02 ZIP 整体进度 100 → 0/8 倒退
FIX-03 multipart 上传途中刷新后假装仍在上传
FIX-04 multipart fingerprint 元数据碰撞风险
FIX-05 Real Chrome 仍验证退休的单任务 dock
```

永久 workflow 最新本轮验收：

```text
ZIP Import Durable Runtime
Run ID: 35213047885
```

该 run：

```text
Ubuntu contracts                 PASS
Windows contracts                PASS
backend persistence              PASS
SecretStore contracts            PASS
multipart contracts              PASS
bounded 10k hot-state            PASS
Real Chrome refresh recovery     PASS
```

---

# 7. 当前 OPEN 项目

这部分不能在汇报里包装成“已完成”。

## P1 — Headless Linux Secret 持久化

公开读取现在安全降级，不再 500；但真正保存新畅联 AccessKey/AccessSecret 仍需要一个明确、可运维、安全的 headless Linux Secret backend。

不能用 plaintext JSON 代替。

## P1 — Multipart session GC

未完成上传目前可长期留下：

```text
<project>/import_uploads/<upload_id>/parts
```

要做 TTL / expires_at / cleanup / freed bytes 记录。

## P1 — 真实 500 张 ZIP benchmark

代码结构已优化，但尚未用用户原先那个真实场景重新量化。

部署后必须拆阶段测：

```text
network
merge
validation
extract
format parse
annotation write
material index
total
```

## P1 — 新畅联 live contract 最终确认

仍需要真实环境确认：

```text
production canonical signature
filePath
chipCode
algoVersionId response
weight remote final state
remote commit recovery
```

## P2 — UploadTaskCenter 常驻 project switch interval

当前仍有：

```text
setInterval(switchProject, 1500)
```

后续应由 NavigationStability / project owner 主动通知，不应该长期轮询项目 ID。

## P2 — 外部平台 auto-sync 在 Web 进程 daemon thread

单进程能工作，FileLock 能避免同目录同时 sync；但多 API worker / 多机后应迁到现有 Scheduler/Worker。

不要因此新造第二套 scheduler。

## 架构演进 — PostgreSQL

当前 algorithm SQL 是 per-project SQLite。

它是当前单机/开发可用方案，不代表适合 NFS 多机器中央事务数据库。

未来保留 Repository abstraction，新增 PostgreSQL backend；不要把 SQLite over NFS 当最终答案。

---

# 8. 当前最重要代码索引

## 算法 / SQL

```text
platform_core/algorithm_sql_store.py
platform_core/algorithms.py
tests/unit/test_algorithm_sql_store.py
tests/unit/test_algorithms.py
.github/workflows/algorithm-sql-store.yml
```

## 上传 / 导入

```text
platform_core/zip_multipart.py
platform_core/storage/import_tasks.py
static/modules/zip-import-runtime.js
static/modules/upload-task-center.js
static/modules/storage-import-progress.js
static/zip-import-bootstrap.mjs
app.py
```

测试：

```text
tests/unit/test_zip_multipart.py
tests/unit/test_secrets.py
tests/frontend/zip-import-durable-runtime.test.mjs
tests/frontend/zip-multipart-upload.test.mjs
tests/frontend/upload-task-center.test.mjs
tests/frontend/storage-import-progress.test.mjs
tests/browser/zip-import-refresh-recovery.spec.mjs
tests/api/test_v19_job_atomic_persistence.py
tests/api/test_v19_import_scalability.py
```

永久 CI：

```text
.github/workflows/zip-import-durable-runtime.yml
```

## 训练

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-submit.js
static/modules/training-task-runtime.js
static/modules/training-task-visibility-runtime.js
platform_core/algorithms.py
app.py
```

永久 CI：

```text
.github/workflows/training-task-visibility.yml
```

## 新畅联

```text
platform_core/external_algorithm_platform.py
platform_core/external_algorithm_publish.py
static/modules/external-algorithm-platform.js
static/modules/external-algorithm-publish.js
docs/EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md
```

## Secret

```text
platform_core/secrets.py
tests/unit/test_secrets.py
```

---

# 9. 不要重复的 CLOSED 工作

除非你找到新的、可复现证据，否则不要重新开启：

```text
training mirror fields
/train/start single owner
/jobs duplicate race
training metrics SQLite FD leak
training / AutoLabel / video / source polling owner
setupPagePolling legacy timer cleanup
classic setPage owner cleanup
Task Runtime Truth
Worker Runtime Truth
Training Queue Readiness Truth
Training Bundle Snapshot Cache
algorithm JSON → SQL migration
algorithm row-level CRUD migration
external algorithm mirror preserving local algorithms
external inactive preservation
external multi-analysis training binding
external publish Phase 2 base implementation
ZIP durable runtime owner
ZIP resumable multipart base implementation
training planned task id identity
```

如果某个 CLOSED 项目现在失败：

1. 先给出复现；
2. 找 regression commit；
3. 修 regression；
4. 不要把旧架构整体重写一遍。

---

# 10. 推荐下一批实际工作

如果用户没有重新指定其他方向，建议按：

```text
1. Headless Linux SecretStore 正式方案
2. Multipart session TTL / GC
3. 真实 500 张 ZIP 分阶段 benchmark + 性能热点优化
4. 新畅联 live API 最终合同验证
5. UploadTaskCenter 去除 project-switch 常驻 interval
6. External auto-sync 迁入现有 durable scheduler/worker
7. 多机前再做 PostgreSQL Repository backend
```

其中第 3 项必须用真实 ZIP，不能根据单元测试估算“优化了多少倍”。

---

# 11. 每次交付最低检查

至少：

```bash
cat VERSION.txt
git status
git rev-parse HEAD
git diff --check
```

按涉及模块跑 focused tests。

上传链路至少确认：

```text
Ubuntu contract
Windows contract
backend persistence
Real Chrome refresh recovery
```

训练链路至少确认：

```text
TrainingSubmitRuntime 单 owner
planned task ID = backend durable task ID
刷新后任务可见
重复提交幂等
```

算法 SQL 至少确认：

```text
legacy JSON 迁移不丢 ID
本地算法不被 external sync 删除
row-level CRUD
version current pointer
rollback/delete transaction
```

最后再确认：

```text
main 未被误改
VERSION.txt 仍为 42.24.0
无临时 one-shot helper/workflow 残留
```

---

# 12. 给下一位 AI 的一句话

**不要从头重构。先读取远端真实 HEAD 和本文件，从当前已验证 owner / SQL / durable task / upload runtime 上继续，把 OPEN 项逐个关闭；任何“性能更快”必须用真实阶段数据证明，任何“可恢复”必须经过刷新/中断测试证明。**
