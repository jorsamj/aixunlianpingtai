# v42.25 训练任务标签合同

日期：2026-09-11  
状态：IMPLEMENTED ON `refactor/v42.25-runtime`; targeted Linux CI PASSED; A800 REAL TRAINING NOT VERIFIED; NOT MERGED

## 1. 问题

旧训练链把项目 `meta.json` 里的全部 active labels 直接传入 Training Snapshot / YOLO `data.yaml`：

```text
项目标签库全部 active labels
→ Snapshot label_schema
→ data.yaml names
→ Ultralytics nc
```

因此项目里只要存在 5 个标签，即使本次烟火算法只需要 `fire / smoke`，Ultralytics 仍可能收到 `nc=5`。

这违反产品语义。项目标签库只是可用业务标签目录，不等于某一个算法的类别合同。

---

## 2. 正确标签来源

本批把算法标签定义为训练任务级合同。

### 2.1 首次训练

只有：

```text
已选训练/试验/测试素材实际携带的标签
    ↓
用户在创建训练任务时明确勾选
    ↓
本次 label_schema
```

母算法 / 预训练模型自身类别一律不继承。

例如 `yolo11n.pt` 即使预训练自带 COCO 80 类，也不能把 80 类带入本算法。

项目里其他没有被本次用户选择的标签也不能进入算法。

### 2.2 版本迭代

迭代标签：

```text
上一成功、可训练算法版本的 label_schema
+
本次已选素材中，用户明确选择的新标签
=
新版本 label_schema
```

上一版本标签属于模型头的既有类别身份，必须继承且不能在普通迭代中随意删除或重排。

母算法仍不参与标签继承。

### 2.3 历史版本兼容

新版本会直接保存 `label_schema`。

历史版本如果还没有 `label_schema`：

```text
version.task_id / job_id
→ task_runtime/artifacts/<task_id>/snapshot.json
→ 恢复历史 label_schema
```

如果历史版本既没有自身 schema，也没有可恢复 Snapshot，则训练必须 fail closed，不允许从：

- 项目全部标签；
- 当前素材猜测；
- 母模型类别；

自动重建类别映射。

---

## 3. Class ID 规则

算法自己的 label schema 独立于项目全局 class_id。

首次训练按本次用户选择顺序生成连续：

```text
0 .. N-1
```

例如项目全局可能是：

```text
0 fire
1 smoke
2 person
3 helmet
4 cigarette
```

如果本次只选：

```text
helmet
cigarette
```

算法不能继续使用 `3 / 4`，而必须得到自己的：

```text
0 helmet
1 cigarette
```

迭代时上一版本已有 class_id 保持不变，新标签只能追加到末尾。

例如：

```text
旧版本:
0 fire
1 smoke

本次新增 cigarette

新版本:
0 fire
1 smoke
2 cigarette
```

禁止重排旧类别，否则模型检测头语义会错位。

---

## 4. 素材如何决定“可选标签”

标签可选项只从本次精确选择的素材读取，Ground Truth authority 仍是 `AnnotationRepository`。

正样本：读取 box `label/code`。

明确负样本：读取具体 `annotation_scope`。

历史 `annotation_scope=['*']` 不作为“用户可新增标签”的来源，因为 `*` 已经丢失当时具体类别集合，不能扩成当前项目所有标签。

---

## 5. 未选标签框与负样本

如果一张图片同时有：

```text
fire
person
```

而本次算法只选择 `fire`：

- `fire` 框进入训练；
- `person` 框从本算法训练投影中移除；
- `person` 不进入 `data.yaml names`。

但如果一张图片只有：

```text
person
```

而本次只训练：

```text
fire
```

平台不能把 `person` 框过滤掉后，把整张图片静默变成 `fire` 的负样本。

这种情况训练前直接拒绝，并要求：如果业务上确实要把这张图作为 fire 负样本，必须先通过正式标注流程明确“确认无目标”。

这保持了上一批 `confirmed_empty` 的 Ground Truth 合同。

---

## 6. 生产实现

### 后端

新增：

- `platform_core/training_label_tasks.py`

负责：

- 从精确选择素材解析可选 label codes；
- 读取 `TrainReq.train_labels`；
- 首次训练不继承母模型类别；
- 迭代继承上一成功可训练版本标签；
- 老版本从 Snapshot 恢复 schema；
- 生成连续 task-local class_id；
- 将素材标注投影到本次 schema；
- 写 `label-contract.json`；
- 新版本完成后持久化：
  - `label_schema`
  - `label_codes`
  - `label_contract`
- `result.json` / `job.json` 同步保存标签合同审计信息。

`platform_core/worker_registry.py` 的 training role 改为：

```text
platform_core.training_label_tasks
```

因此生产 task worker 会经过标签合同，而不是仅在页面层过滤。

### 前端

新增：

- `static/modules/training-labels.js`

在创建训练任务页面增加“本次训练标签”：

首次训练：
- 可选项仅来自已选素材；
- 可以勾选/取消；
- 不显示母模型类别为继承类别。

迭代：
- 上一成功可训练版本标签显示为“继承”，不可取消；
- 当前素材出现的新标签作为可选新增标签；
- 新标签不会因为素材中出现就自动加入迭代版本，用户需要明确选择。

提交 `/api/v12/.../train/start` 时，通过已有 `TrainReq.train_labels` 传递本次用户新增选择，不扩展 API schema。

---

## 7. Snapshot / data.yaml 最终合同

Training Snapshot 的 `label_schema` 必须等于本次有效算法 schema，而不是项目全标签。

Portable YOLO bundle：

```text
dataset/data.yaml names
```

严格来自 Snapshot `label_schema`。

例：项目有 5 标签，但本次有效标签只有：

```text
fire
smoke
```

最终必须是：

```yaml
names:
  0: fire
  1: smoke
```

Ultralytics 因而得到：

```text
nc=2
```

而不是 `nc=5`。

---

## 8. 验证结果

临时 GitHub Actions Linux Runner 验证完成后已删除 workflow 文件。

最终定向验证：

```text
frontend Node tests: 7 passed / 0 failed
Python targeted tests: 61 passed / 0 failed
```

覆盖：

- 只从已选素材提供标签；
- 首次训练不继承母模型类别；
- 项目 5 标签、本次选 2 标签时仅生成 2 类合同；
- 未出现在已选素材中的标签拒绝；
- 迭代继承旧 label schema；
- 新标签追加且 class_id 连续；
- 旧版本 Snapshot schema 恢复；
- newer failed version 不覆盖上一成功版本标签；
- 无成功可训练版本时不回退母算法；
- 防止过滤未选正类后制造假负样本；
- 负样本合同、Snapshot、split、portable dataset 回归；
- Worker registration / no-web execution path；
- 最终 `data.yaml names` 只包含有效标签。

这不是 A800 真机训练验收。A800 REAL TRAINING NOT VERIFIED。

---

## 9. A800 验收重点

真实训练时至少检查：

1. 创建任务页面只出现已选素材带来的可选标签；
2. 首次训练选择 `fire / smoke`；
3. 即使项目还有 `person / helmet / cigarette`，Snapshot 与 `data.yaml` 仍只有 2 类；
4. Ultralytics 日志应出现 `nc=2`；
5. 训练完成版本保存 `label_schema=[fire=0, smoke=1]`；
6. 下一次迭代自动继承 `fire / smoke`；
7. 若本次素材出现 `cigarette`，只有用户明确勾选后，新版本才变成 `fire/smoke/cigarette`；
8. 不能因为当前基础模型是 COCO 等母模型而出现额外类别。
