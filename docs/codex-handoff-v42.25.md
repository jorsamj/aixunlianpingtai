# v42.25 Codex / 人工接管说明

> 本文件是 `docs/codex-handoff.md` 的增量交接说明，不替代旧历史记录。
> 后续 Codex、人工开发者或其他 Agent 接管 `refactor/v42.25-runtime` 时，必须先阅读旧 handoff，再阅读本文件。

## 1. 当前工作状态

- 稳定主分支：`main`
- 当前开发分支：`refactor/v42.25-runtime`
- v42.25 开发基线：`main@01636b61780361dde91c12ac2732f46d2289b6be`
- 基线版本：`42.24.0`
- 当前阶段：**v42.25 第一批“训练数据正确性与训练快照合同”已实施，尚未合并 main**
- README / VERSION 暂不提升版本，正式发布前仍保持 `42.24.0`
- 不允许把本分支描述成已经发布或已经生产验收通过

### 验证状态

本批代码已经做核心逻辑 sanity check，但当前没有完整执行全仓 pytest / Playwright / A800 真机训练回归，也没有 GitHub Actions CI 结果。

因此必须使用以下措辞：

- `IMPLEMENTED`：代码已写入分支
- `UNIT TESTS ADDED`：已增加对应单元测试代码
- `FULL REGRESSION NOT VERIFIED`：整仓回归尚未完成
- `A800 REAL TRAINING NOT VERIFIED`：真实 A800 训练尚未用本分支重新验证

不要把“测试代码存在”误报成“测试已经全部运行通过”。

---

## 2. 本批为什么修改

v42.24.0 的训练切分存在一个真实生产问题：

1. 先按 group / video / source group 等字段划分 Train / Validation / Test；
2. 划分完成后才检查 `content_sha256`；
3. 同一物理图片如果存在多条素材记录，就可能被切到不同角色；
4. 最终在训练正式启动前或打包阶段报 `content hash leakage`。

真实历史任务曾因为同 SHA 重复素材且标注不同而失败。人工删除重复素材只能清理当时数据，不能修复代码根因。

此外，v42.24.0 把 `boxes=[]` 直接视为“没有有效标注”，导致已经人工/导入确认过的 `confirmed_empty` 负样本无法进入训练；Annotation Ground Truth 也没有记录“这张图确认过哪些类别”的 `annotation_scope`。

v42.25 第一批的目标是建立稳定训练数据合同：

```text
Material Identity
    ↓
Annotation Ground Truth + Annotation Scope
    ↓
Duplicate / Conflict Preflight
    ↓
Inseparable Component
    ↓
Train / Validation / Test Split
    ↓
Immutable Training Snapshot v3
```

---

## 3. 本批实际修改的文件

### 核心代码

#### `platform_core/training_splits.py`

主要变化：

- 增加切分前 duplicate preflight；
- 相同 `content_sha256` + 相同规范化标注意义：只保留 canonical material，重复项本次训练排除；
- 相同 `content_sha256` + 不同规范化标注意义：抛出 `duplicate_annotation_conflict`，不得自动选一条；
- 增加 Union/Component 思路，在切分前构建不可拆分组件；
- Component 关系目前包括：
  - `content_sha256`
  - file identity
  - `group_id`
  - `video_task_id`
  - `source_group_id`
  - `near_duplicate_group_id`
  - `sequence_group_id`
  - `camera_session_id` / `capture_session_id`
  - 或 `camera_id + session_id` 组合
- **禁止仅按 `camera_id` 建组件**，否则会把同摄像头长期历史数据全部绑定；
- 组件关系支持传递合并，例如 A 与 B 同 group，B 与 C 同 video，则 A/B/C 同一个 Component；
- 最终仍保留 leakage guard，作为第二道防线；
- `confirmed_empty` 变成合法负样本；
- `unannotated` 仍禁止训练；
- 旧 `confirmed_empty` 无 scope 时兼容为全局 scope `['*']`；
- 重复标注比较优先使用稳定 label/code，不依赖历史 `class_id`；
- 重复框比较同时覆盖 `x1/y1/x2/y2` 与 `cx/cy/w/h`。

#### `platform_core/annotation_repository.py`

主要变化：

- `annotations.sqlite3` 新增 `scope_json`；
- 对已有数据库使用原地 `ALTER TABLE`，不得重建或清空历史标注；
- Annotation Ground Truth 现在包含：
  - `annotation_state`
  - `annotation_scope`
  - `boxes`
  - `content_digest`
  - `version`
- digest 由 `state + scope + boxes` 共同计算；
- `annotated` 且没有显式 scope 时，从 box label/code 推导；
- `confirmed_empty` 且没有显式 scope 时使用 `['*']` 兼容历史“已确认空样本”；
- `unannotated` 强制 scope 为空；
- Annotation Repository 仍是 Ground Truth authority；
- 保存正式标注后，把以下派生字段同步投影到 MaterialRepository，方便搜索/筛选/训练选择：
  - `annotation_state`
  - `annotation_scope`
  - `annotation_hash`
  - `annotated`
  - `box_count`
  - `labels`
- MaterialRepository 只是 searchable projection，不得演变成第二套标注真源。

#### `platform_core/snapshots.py`

主要变化：

- 新版训练 Snapshot schema 提升为 `schema_version = 3`；
- 每张入选素材锁定：
  - role
  - content SHA256
  - Component ID
  - annotation state
  - annotation scope
  - annotation hash
  - box count
  - labels
- Snapshot 记录 duplicate preflight 审计信息：
  - `excluded_duplicate_ids`
  - `duplicate_groups`
- 记录 `negative_scope_counts`，便于后续报告解释负样本覆盖；
- Snapshot ID 对新合同内容计算，后续修改标注或 scope 不应改写历史训练含义。

### 新增 / 修改测试

- `tests/unit/test_training_components.py`
- `tests/unit/test_annotation_repository_scope.py`
- `tests/unit/test_training_splits.py`
- `tests/unit/test_snapshots.py`

覆盖意图包括：

- 同 SHA + 同标注自动 canonicalize；
- 同 SHA + 不同标注在训练前报 `duplicate_annotation_conflict`；
- 稳定 label code 相同但历史 class_id 不同，不误报冲突；
- normalized `cx/cy/w/h` 坐标差异可检测；
- Component 关系可跨 group/video 传递；
- camera 仅在同 capture session 内绑定；
- file identity 不允许跨 split；
- 同 SHA 被显式分别选入 Train/Test 时拒绝；
- `confirmed_empty` 可作为合法负样本；
- `unannotated` 仍拒绝；
- 旧 confirmed_empty 无 scope 兼容；
- 老 annotations DB 原地新增 `scope_json`；
- annotation scope/hash 投影 MaterialRepository；
- Snapshot v3 锁定 annotation contract；
- Snapshot 记录 duplicate exclusions。

---

## 4. 重要语义：后续不得回退

### 4.1 重复素材不是简单删除

禁止重新实现成：

```text
发现相同 SHA
→ 随便保留第一条
→ 其他记录删除
```

正确语义：

```text
same SHA + same normalized GT
→ 本次训练 canonicalize / exclude duplicate
→ 不删除素材库记录

same SHA + different normalized GT
→ duplicate_annotation_conflict
→ 训练前阻断
→ 后续进入专门的冲突处理/Preflight UI
```

### 4.2 `confirmed_empty` 不是“未标注”

必须区分：

```text
unannotated
→ 没有人/系统确认 Ground Truth
→ 不允许进入训练

annotated
→ 有正式框
→ 合法

confirmed_empty
→ 已明确检查但没有目标
→ 合法负样本
```

`confirmed_empty` 的 YOLO 输出应自然表现为空 `.txt`，不要为了“看起来有标注”伪造框。

### 4.3 Annotation Scope 必须保留

后续不能只保存 boxes。

例如：

```json
{
  "annotation_state": "confirmed_empty",
  "annotation_scope": ["cigarette"],
  "boxes": []
}
```

代表“已确认这张图没有 cigarette”，不是“这张图对所有未来类别永远是负样本”。

历史无 scope 的 `confirmed_empty` 使用 `['*']` 只是兼容策略；新流程应尽可能写入明确 label code scope。

### 4.4 Stable label semantics 优先

重复标注比较不能绑定到可变的 class array index。

有稳定 `label/code` 时，以稳定 code 为主；只有缺少 code 时才回退 class_id。

---

## 5. 当前还没有完成的部分

第一批只解决训练数据正确性，不代表 v42.25 全部完成。

### P0 / 第二批：Task Runtime fencing

接下来优先处理：

1. Worker lease 丢失时，当前 handler / 子进程必须立即感知；
2. 增加 `lease_lost` / cancellation token；
3. 增加 execution generation / fencing token；
4. heartbeat 因 lease owner/generation 不匹配失败时，禁止继续写 task result / artifact；
5. Training / Conversion 等子进程必须安全终止整个 process tree；
6. `release_expired()` 不得在旧进程仍可能存活时无条件允许第二个 Worker 重复执行；
7. recovery 前必须验证 PID + create_time + command hash；
8. 统一 ProcessController 语义，Conversion 不应继续保留较弱的单进程 terminate/kill 逻辑。

目标：彻底消除“Worker A 丢 lease 但仍运行，Worker B 又重新 claim 同任务”的重复副作用窗口。

### 后续批次（尚未实施）

- 旧 `app.py` daemon thread / legacy execution path 退役；
- ZIP / YOLO Import fast inventory + once-only SHA + batch insert 性能重构；
- `/data` 静态根目录暴露移除；
- CORS、SSRF、训练服务器 secret 生产安全收口；
- algorithms.json → SQLite Algorithm Asset / Version；
- `current_version_id`；
- 稳定 Label Identity；
- Train/Validation 与 sealed Test 分离；
- Final Evaluation Worker；
- 转换成功与硬件验证状态拆分；
- 畅联云 `IdentityProvider / TenantContext / AlgorithmCatalogProvider` 预留；
- GitHub Actions CI。

不要因为本文件列出这些事项就宣称已经完成。

---

## 6. 接手后建议执行顺序

### 第一步：不要直接合并 main

在独立工作树或测试机验证：

```bash
cd /data/platform/aixunlianpingtai
git fetch origin

git worktree add \
  /data/platform/aixunlianpingtai-v4225 \
  origin/refactor/v42.25-runtime

cd /data/platform/aixunlianpingtai-v4225
conda activate mc-platform
```

### 第二步：先跑本批定向测试

```bash
python -m pytest \
  tests/unit/test_training_splits.py \
  tests/unit/test_training_components.py \
  tests/unit/test_annotation_repository_scope.py \
  tests/unit/test_snapshots.py \
  -q
```

### 第三步：再跑与训练数据合同相关的既有测试

至少检查：

- training bundle
- durable training
- material repository
- YOLO import
- annotation persistence
- snapshot persistence

若新测试通过但旧测试失败，应先判断旧测试是否锁定了 v42.24 的错误语义，不能为了让旧测试变绿而把 `confirmed_empty` 或 Component split 回退掉。

### 第四步：做真实数据 Preflight

用曾经出现重复 SHA 的真实项目验证：

```text
same SHA + same GT
→ 自动 exclude duplicate，并在 Snapshot 留审计记录

same SHA + different GT
→ 在 YOLO 进程启动前明确返回 duplicate_annotation_conflict
```

### 第五步：再做小规模真实 A800 训练

确认：

- bundle 正常生成；
- confirmed_empty 对应空 YOLO label 文件；
- Train / Validation / Test 无 SHA / group / session leakage；
- best model 与报告生成逻辑没有被 Snapshot v3 破坏。

通过以上验证后，才讨论合并 `main` 或提升正式版本号。

---

## 7. 本批禁止顺手修改的区域

为降低风险，本批故意没有修改：

- `app.py` 主体；
- GPU Resource Manager；
- A800 调度策略；
- 训练 epochs / batch / imgsz / optimizer 等参数；
- 前端页面结构；
- 现有正式 API 版本号；
- README 正式版本号；
- 历史失败训练任务；
- 已有素材 ID / 标签 ID / 算法版本 ID。

如果后续改这些内容，需要单独说明原因并建立对应测试，不要把它们混在“训练数据正确性修复”里。

---

## 8. 相关设计文档

本批详细数据合同见：

- `docs/superpowers/specs/2026-09-11-v42.25-training-data-contract-design.md`

历史总体交接仍见：

- `docs/codex-handoff.md`

如果本文件与旧 handoff 对 v42.25 分支状态描述冲突，以本文件的 v42.25 增量状态为准；旧 handoff 的历史产品约束仍然有效。
