# 2026-09-11 Training Resource Contract Incident / Fix

状态：IMPLEMENTED + TARGETED LINUX CI PASSED on `refactor/v42.25-runtime`; A800 REAL TRAINING RERUN NOT YET VERIFIED.

## 1. 事故现象

真实训练任务日志显示用户/任务请求：

```text
batch=16
workers=4
cache=false
device=0
```

但 Ultralytics Trainer 实际启动参数变成：

```text
batch=64
workers=4
cache=disk
device=0
```

随后用户反馈训练出现 DataLoader / pin-memory 相关失败。

GPU、Torch、CUDA、AMP 和数据扫描本身已经进入正常流程，所以本次首先修复的是平台对训练资源参数的隐式覆盖。

## 2. 根因

根因不在 Ultralytics 参数解析，而在平台自身：

```text
Training payload
  ↓
_training_argv
  ↓
train_worker.py builds requested train_args
  ↓
train_worker.py prints those args as “实际训练参数”
  ↓
resolve_resources(... resource_strategy=auto)
  ↓
platform overwrites batch/workers/cache
  ↓
model.train(**train_args)
```

旧 `platform_core/training_metrics.py::resolve_resources()` 在 `auto` 模式下：

- 根据显存估算重新选择最高 batch，上限为 64；
- 即使用户明确 `cache=false`，只要本地 bundle 和磁盘条件允许，也可能自动改为 `cache=disk`；
- workers 也由平台按 CPU/存储 cap 自动决定。

因此 A800 环境中出现：

```text
requested batch=16 -> resolved batch=64
requested cache=false -> resolved cache=disk
```

这是平台合同错误，不是 Ultralytics 自动修改。

## 3. 修复后的资源合同

### 3.1 显式正整数 batch 是硬上限

用户：

```text
batch=16
```

含义：

```text
auto strategy 可以为了安全降低到 8/4/...
但绝不能提高到 32/64
```

即：

```text
resolved_batch <= requested_batch
```

### 3.2 `batch=-1` 保留显式自动语义

平台历史 API 已支持 `batch=-1`。

只有用户明确提交：

```text
batch=-1
resource_strategy=auto
```

才表示：

> 用户主动把 batch 大小委托给平台资源解析器。

此时平台可以根据 GPU 安全预算解析出正整数 batch（当前 conservative cap 仍为 64）。

`resource_strategy=manual + batch=-1` 非法。

### 3.3 `cache=false` 是权威关闭

用户：

```text
cache=false
```

则：

```text
resolved_cache=false
```

Auto 不得把它改成 RAM 或 Disk。

用户主动请求 RAM/Disk 时，Auto 可以出于安全原因降级：

```text
ram -> disk -> false
```

或：

```text
disk -> false
```

但不得反向升级。

### 3.4 workers 不得自动增加

用户：

```text
workers=4
```

Auto 可因 CPU/runtime 限制降低，但不得增加到 >4。

用户：

```text
workers=0
```

代表明确选择单进程 DataLoader，必须保持 0。

## 4. 修改位置

核心：

- `platform_core/training_metrics.py`

测试：

- `tests/unit/test_training_resource_contract.py`

临时 CI 验证：

- `.github/workflows/v42.25-runtime-validation.yml`

该 workflow 只是当前 v42.25 分支定向验证工具，正式收口后可删除或并入未来统一 CI。

## 5. 日志/审计

Resource resolution 现在输出明确的 requested/effective 对照：

```text
[资源决议] strategy=auto;
requested(batch=16, workers=4, cache=False);
effective(batch=16, workers=4, cache=False);
adjustments=['none']
```

`resolved-resources.json` 同时记录：

```text
requested_batch
requested_workers
requested_cache
resolved_batch
resolved_workers
resolved_cache
adjustments
reasons
```

注意：当前 `train_worker.py` 在 resource resolution 之前仍保留一个历史打印标题“实际训练参数”。它对应的是 `requested_train_params`，不是最终 effective params。新的 `[资源决议]` 行与 `actual_train_params / resolved-resources.json` 才是最终生效值。后续整理 train_worker 日志时应把旧标题改成“用户请求训练参数”，不要删除 requested/effective 双层审计。

## 6. 本次 CI

目标测试包含：

- existing Task Runtime fencing tests
- conversion process fencing
- `tests/unit/test_training_resource_contract.py`

最新定向 Linux GitHub Actions 已通过。

资源合同回归覆盖：

1. `batch=16/workers=4/cache=false` 在充足 A800-like 预算下仍为 `16/4/false`；
2. workers=0 不被平台自动增加；
3. explicit positive batch 可安全下调但不可上调；
4. batch=-1 明确委托自动 batch；
5. manual batch=-1 被拒绝；
6. cache=false 即使磁盘充足也不能变成 disk；
7. manual 模式保持 exact values。

## 7. `optimizer=auto` 不是本次同类 bug

日志还出现：

```text
optimizer=auto found, ignoring lr0=... and momentum=...
```

这是 Ultralytics 的 optimizer=auto 语义：优化器、初始学习率/动量由 Ultralytics 决定。

因此后续 UI/日志必须明确：

```text
optimizer=auto
=> lr0 / momentum 属于 runtime-managed / 不保证按用户值生效
```

不要把这个现象和平台偷偷覆盖 batch/cache 混为一谈。

## 8. `nc=5` 另一个已定位的设计问题

当前 TrainingHandler 构建 Snapshot 时调用项目级 `_label_schema(project)`，该函数读取 `meta.json` 中全部 active labels，然后 portable data.yaml 使用整个 Snapshot label schema 生成 `names`。

因此：

```text
Ultralytics: nc=5
```

说明平台给本次 runtime YAML 的 `names` 有 5 类；不是 Ultralytics 自己猜成 5 类。

但仅凭这份日志不能断定本次任务应该是 2 类，因为尚未证明该任务就是 D-Fire 两类算法。

正确后续设计不是“按当前图片里出现过的标签自动删类别”，而是：

```text
Algorithm / Training Task
    ↓
explicit stable label schema (label codes)
    ↓
Training Snapshot locks that schema
    ↓
validate every box/scope against schema
    ↓
runtime data.yaml names only from that schema
```

在算法级 label schema 尚未落库前，不要为了把 nc=5 强行改成 nc=2 而根据样本出现频次推断类别。

## 9. A800 下一次真实验证

部署本分支后，用原配置重新训练：

```text
batch=16
workers=4
cache=false
device=0
```

日志必须看到：

```text
[资源决议] ... requested(batch=16, workers=4, cache=False) ...
effective(batch=16, workers=4, cache=False)
```

Ultralytics `engine/trainer:` 必须对应：

```text
batch=16
workers=4
cache=False
```

如果此时仍出现 `Pin memory thread exited unexpectedly`，再单独排查：

- kernel OOM / cgroup OOM
- `/dev/shm`
- PyTorch DataLoader worker crash
- host RAM / pinned-memory pressure

不要在未验证修复后的 16/4/false 前直接把全平台 workers 强制改成 0。
