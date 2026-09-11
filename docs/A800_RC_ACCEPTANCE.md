# v42.25 A800 RC 验收手册

> 目标：在现有 A800 正式部署形态上完成一次真实、可追溯的 RC 验收。
>
> 本手册不要求合并 `main`。使用 `refactor/frontend-runtime-stabilization` 分支直接部署并验收。
>
> 验收工具 `a800_rc_acceptance.py` 默认只读：不会创建训练任务、不会停止/重启 Worker、不会修改项目素材。

## 1. 验收目标

本轮必须拿到以下真实证据：

```text
GPU: NVIDIA A800-SXM4-40GB
training device: 0
batch: 16
workers: 4
cache: False
epochs: 3-5
training labels: fire + smoke
expected nc: 2
```

同时验证：

1. Web 与 Worker 使用同一个 `/data/platform-data`；
2. Worker execution fencing 已启用；
3. YOLO Python 可以看到 CUDA 与 A800；
4. 请求资源、资源决议和 Ultralytics 实际参数一致；
5. Snapshot v3 只锁定本次任务的 `fire/smoke`；
6. portable `data.yaml` 只有两个类别，等价于 `nc=2`；
7. `confirmed_empty` 负样本生成零字节 YOLO `.txt`；
8. verified model artifact 文件存在，size 与 SHA256 和 `result.json` 一致；
9. 迭代训练严格从最新成功、artifact-verified、trainable 的版本继续，而不是母模型或更早版本；
10. 后续单独执行 Worker 生命周期/重启 fencing 验收。

## 2. 部署前提

服务器当前预期：

```text
repo: /data/platform/aixunlianpingtai
data: /data/platform-data
web port: 8010
app env: mc-platform
YOLO python: /home/vipuser/miniconda3/envs/yolo/bin/python
```

环境变量必须保持：

```bash
export MC_TRAIN_DATA_DIR=/data/platform-data
export MC_DATA_DIR=/data/platform-data
```

不要把生产数据目录改回仓库内 `data/`。

## 3. 第一步：只读 Preflight

在仓库目录执行：

```bash
cd /data/platform/aixunlianpingtai

python a800_rc_acceptance.py preflight \
  --base-url http://127.0.0.1:8010 \
  --data-dir /data/platform-data \
  --expected-device 0 \
  --output /data/platform-data/rc/v42.25-preflight.json
```

建议在 `mc-platform` 环境执行；如果当前未激活：

```bash
/home/vipuser/miniconda3/envs/mc-platform/bin/python a800_rc_acceptance.py preflight \
  --base-url http://127.0.0.1:8010 \
  --data-dir /data/platform-data \
  --expected-device 0 \
  --output /data/platform-data/rc/v42.25-preflight.json
```

Preflight 必须至少通过：

```text
API uses expected persistent data dir          PASS
training device 0 is available                 PASS
GPU resource endpoint reachable                PASS
task worker check succeeds                     PASS
execution fencing enabled                      PASS
training.ultralytics capability registered     PASS
configured training Python starts              PASS
Torch CUDA is available                        PASS
GPU 0 is A800                                  PASS
```

任何一项 FAIL 都先停止 RC，不要继续创建训练任务。

## 4. 第二步：准备首轮真实短训练

在页面创建一条受控训练任务。

### 4.1 素材要求

本次只选明确用于 `fire/smoke` 的素材。

要求：

- 至少有足够训练图片，使最终 train split 不少于 4 张；
- 同时包含 `fire` 和 `smoke` 标注；
- 至少选入 1 张 `confirmed_empty` 负样本；
- 该负样本必须确认覆盖本次锁定结构 `fire + smoke`；
- 不要混入 `person`、helmet 等其他任务标签；
- 不要使用 unannotated 零框图片冒充负样本。

如果本次没有任何 `confirmed_empty`，训练本身可以成功，但 RC 工具会故意把“负样本实机证据”判为 FAIL。

### 4.2 标签

训练窗口中本次任务标签只选择：

```text
fire
smoke
```

预期：

```text
Snapshot label_schema = [fire, smoke]
data.yaml names       = [fire, smoke]
nc                    = 2
```

首次训练不能继承母模型类别。

### 4.3 资源参数

建议本次 RC 使用：

```text
训练设备：0
GPU 策略：exclusive
训练资源策略：manual / 手动
Epochs：3（最多 5）
imgsz：640
batch：16
workers：4
cache：False
```

RC 使用手动策略的目的，是要求参数“不兼容就明确失败”，而不是允许系统静默放大或改写资源。

## 5. 第三步：等待任务完成

在训练任务页面确认任务进入终态，并记下 `job_id`。

不要只依据页面显示判断 RC 成功。页面完成后必须执行下一步 artifact 验证。

## 6. 第四步：验证首轮任务

假设：

```text
project_id=f1fb1e6fa373
job_id=<实际任务ID>
```

执行：

```bash
python a800_rc_acceptance.py verify-job \
  --base-url http://127.0.0.1:8010 \
  --data-dir /data/platform-data \
  --project-id f1fb1e6fa373 \
  --job-id <实际任务ID> \
  --expected-labels fire,smoke \
  --expected-batch 16 \
  --expected-workers 4 \
  --expected-device 0 \
  --output /data/platform-data/rc/<实际任务ID>-first.json
```

`--expected-cache` 默认就是 `False`，无需额外填写。

### 6.1 资源三层必须一致

RC 工具会核验：

```text
requested_batch   = 16
resolved_batch    = 16
actual batch      = 16

requested_workers = 4
resolved_workers  = 4
actual workers    = 4

requested_cache   = false
resolved_cache    = false
actual cache      = false
```

以及：

```text
requested_device = 0 / cuda:0
assigned_device  = 0 / cuda:0
actual_device    = 0 / cuda:0
```

其中 `0` 与 `cuda:0` 在验收工具中视为同一 GPU 索引。

### 6.2 Snapshot / data.yaml

工具会直接读取：

```text
/data/platform-data/task_runtime/artifacts/<task_id>/snapshot.json
/data/platform-data/task_runtime/artifacts/<task_id>/work/bundle/manifest.json
/data/platform-data/task_runtime/artifacts/<task_id>/work/bundle/dataset/data.yaml
/data/platform-data/task_runtime/artifacts/<task_id>/resolved-resources.json
/data/platform-data/task_runtime/artifacts/<task_id>/result.json
```

并核验 Snapshot ID、类别顺序、class_id 连续性以及 portable manifest 身份一致性。

### 6.3 confirmed_empty

工具按 Snapshot 的 `image_id` 精确找到 manifest 中对应的 `label_ref`，然后要求：

```text
annotation_state = confirmed_empty
对应 YOLO label .txt size = 0 bytes
```

不是通过文件名猜测，也不是只看前端状态。

### 6.4 verified model

工具会逐个读取：

```text
result.json -> verified_models[].ref
```

并验证对应 artifact：

```text
文件真实存在
size > 0
size_bytes 一致
SHA256 一致
```

## 7. 第五步：做一次迭代训练

首轮成功并生成正式版本后，再用同一个算法创建第二次短训练。

参数仍可保持：

```text
device=0
batch=16
workers=4
cache=False
epochs=3
labels=fire+smoke
```

平台应该自动从“最新成功、artifact_verified=true、trainable!=false”的版本继续训练。

完成后执行：

```bash
python a800_rc_acceptance.py verify-job \
  --base-url http://127.0.0.1:8010 \
  --data-dir /data/platform-data \
  --project-id f1fb1e6fa373 \
  --job-id <第二次任务ID> \
  --expected-labels fire,smoke \
  --expected-batch 16 \
  --expected-workers 4 \
  --expected-device 0 \
  --require-iteration \
  --output /data/platform-data/rc/<第二次任务ID>-iteration.json
```

`--require-iteration` 会额外读取：

```text
/data/platform-data/projects/f1fb1e6fa373/algorithms.json
```

重新按版本状态计算“最新成功可训练版本”，然后要求：

```text
base_selection_reason = latest_verified_version
本任务 base_version_id = 最新成功可训练版本 id
```

如果你还想把预期版本锁死，可再加：

```bash
--expected-base-version <version_id或version_name>
```

即使算法历史中存在一个时间更晚但 FAILED 的记录，也不能把它当作迭代起点。

## 8. Worker 生命周期验收

本脚本故意不自动 kill/restart 正式 Worker。

原因：进程生命周期操作会影响真实后台任务，必须由人工明确控制。

完成首轮和迭代训练后，再单独进行：

1. 确认当前没有不可中断的正式训练；
2. 记录 Worker PID / worker_id；
3. 创建一条受控排队任务；
4. 停止当前 Worker；
5. 按正式命令重新启动 Worker；
6. 检查原任务是否被正确恢复/接管，而不是产生双执行；
7. 检查 stale worker 不能继续 publish artifact；
8. 检查 GPU reservation 没有被旧 lease 继续占用；
9. 再执行一次 `task_worker.py --check`。

正式 Worker 命令：

```bash
nohup python task_worker.py \
  --data-dir /data/platform-data \
  --roles all \
  --worker-id "$(hostname)-prod-all-default" \
  > /data/platform-data/logs/worker.log 2>&1 &
```

Worker 生命周期验收不要与其他正式训练同时进行。

## 9. 判定规则

### 可以进入下一阶段

必须同时满足：

```text
preflight                 PASS
first short training      PASS
verify-job first          PASS
iteration short training  PASS
verify-job --require-iteration PASS
worker lifecycle/fencing  PASS
```

### 不能因为以下情况直接发布

```text
前端 Chrome CI 全绿
GitHub unit tests 全绿
CPU smoke training 成功
页面显示“训练完成”
best.pt 文件单独存在
```

这些都是必要证据的一部分，但不能替代真实 A800/CUDA RC。

## 10. 输出文件

建议统一保存：

```text
/data/platform-data/rc/
  v42.25-preflight.json
  <first-job-id>-first.json
  <iteration-job-id>-iteration.json
```

这些 JSON 可直接作为 v42.25 上线前验收记录。
