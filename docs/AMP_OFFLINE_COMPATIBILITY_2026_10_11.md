# 畅联云算法训练平台｜FP16 / AMP Worker 离线兼容性与 iframe 交互修复

日期：2026-10-11。目标分支：`feature/external-algorithm-publishing`；VERSION.txt：`42.24.350`，保持不变。

## 一、真实根因与调用链

`platform_core/training_tasks.py`（控制端）/ `platform_core/node_agent_training_runtime.py`（Agent）分别将已有冻结的 `resolved_precision` 交给同一 `train_worker.py`；后者将 fp16 映射 `amp=True` 并调用 `YOLO(actual_model).train(**train_args)`，训练器 `ultralytics.engine.trainer.check_amp` 默认执行 `ultralytics.utils.checks.check_amp`，原生实现硬编码加载 `YOLO("yolo26n.pt")`。在 8.4.127 中，某些 ConnectionError / AttributeError / ModuleNotFoundError 会记录“AMP checks skipped”后返回 True，因此 `trainer.amp=True` 不等于检查资源确实存在且完整通过。

正式母模型（如 yolo11n.pt）与 AMP 检查参考模型（yolo26n.pt）身份独立。当前 `requirements.txt` 固定 Ultralytics 8.4.127；原有 loader 工作流意外使用 8.4.143，本次已对齐。

## 二、唯一 Worker 决议

- 已有调度器继续冻结 batch / workers / cache / resolved_precision，不让控制端判断 GPU AMP；Worker 在 CUDA_VISIBLE_DEVICES 绑定和装载 PyTorch/YOLO 后、首次 model.train 前执行 `preflight_worker_amp`。
- 参考模型搜索范围仅限操作员设置的 `MC_AMP_CHECK_MODEL`（文件或目录），当前项目 models 目录、平台数据根 models 目录、Worker 当前目录、Ultralytics 已有 weights_dir。只接受实际存在的 `yolo26n.pt`；不自动下载、不创建假文件、不替换正式母模型。有效文件以真实 YOLO loader 验证，再在所在目录运行 8.4.127 原始 check_amp；只有捕获真实的“checks passed”输出且返回 True，才记通过。
- 缺少参考模型：不调用原始检查模型加载，直接执行当前 Worker GPU 的 CUDA autocast FP16 卷积前向输出、FP32 数值对照、梯度有限性和 GradScaler 更新。此方式只证明本机轻量数值检查通过，不冒充 YOLO26n 原始完整检查；不通过或异常一律 FP32。
- 参考模型损坏 / 不可读 / 原生检查失败：不重试网络，直接 FP32；不将 skip 当成功。运行 Ultralytics 非锁定版本则保守回退 FP32，需审计后才能扩大兼容范围。
- 控制端无 GPU / 分布式 Worker 有 GPU：只以 Worker 的 torch.cuda 与实际已绑定 GPU 为准，CPU 绝不宣称 FP16 可用。
- 参考模型检查只在短作用域内对第三方 asset downloader 做本地文件守卫，结束后恢复；已通过数值/参考模型预检的布尔结果只在该任务 `model.train()` 的作用域内被训练器的 check_amp 调用读取，退出后恢复原始函数。没有做全局永久 monkeypatch，也没有修改 site-packages。
- 若模型扩展续训，再次进入相同的限域 Trainer 防下载钩子；不改变母模型、正式结果和模型产物归档。

## 三、真实精度合同

`requested_resources.precision` 和 `requested_precision` 是用户偏好；`resolved_precision` 与 `resolved_resources.resolved_precision` 是调度冻结结论；`runtime_precision` 是 Worker 预检后选择；`runtime_resources.actual_precision` 在 on_train_start 由实际 Trainer.amp 核定，`actual_train_params.precision` 记录实际训练参数。回退写入 `amp_preflight`、`amp_check_method`、`amp_check_result`、`precision_fallback_reason`，随现有 Agent result archive / completion 转运，避免新增第二套 Owner。若训练器违背预检后的实际精度，继续 fail closed。

**注意：**预检结果不是已执行 Batch 的证据。真实训练精度以 Trainer on_train_start 回报 `runtime_resources.actual_precision` 为最终可信值，任务尚未到 on_train_start 时不应称“实际训练已开始”。

## 四、iframe 点击丢失

Chrome 历史诊断中失败时 iframe 不重载、事件完全未进入子页面，成功时同一菜单能收到 pointerdown 和 click；父页面 `.main` 在侧边栏收放中有 0.22s margin-left transition，可能导致 iframe 正在横向移动期间事件落点丢失。将布局过渡关闭范围限定于 `body:has(#nightInspectionIsolated) .main`，避免在 AI 底座内部点击时整体 iframe 继续移动。不更改 iframe sandbox 权限、不引入跨窗口通信、第二套导航 Owner 或定时器。仍须多轮真实 Chrome 与生产浏览器验证；此前偶发通过不等于确定根因已彻底消失。

## 五、测试与未完成验收

- `tests/unit/test_training_precision_contract.py`：无模型 CUDA 正/负决议、异常回退、参考模型存在与损坏、CPU、非锁定 Ultralytics、FP32、训练器钩子作用域恢复。
- `tests/integration/test_ultralytics_loader_resource_contract.py`：安装真实 Ultralytics 8.4.127，核对实际 `trainer.check_amp` API、依赖的 YOLO26n 路径及无文件时不进入下载；验证限定作用域 downloader 拦截并恢复。
- `tests/unit/test_remote_training_results.py`：模拟从 Agent FP16 冻结精度回退到 FP32 后的结果打包和字段保留；历史其他边界断言继续运行。
- `tests/browser/prison-night-isolation.spec.mjs` 与 `tests/frontend/prison-night-inspection-isolation.test.mjs`：验证无 iframe 移动过渡、实际点击子页、sandbox 隔离和回到主平台。
- 真实 NVIDIA A800 UAT：在完全断开外网的 Ubuntu Worker 上分别测试提供/不提供有效参考模型、损坏模型和无写权限 cwd；确认日志不存在任何 yolo26n.pt 下载、母模型仍 yolo11n.pt、真实首个 Batch 和 best.pt/last.pt 可用；核对任务详情/API 的 requested、resolved、runtime、AMP check 和回退字段。必须核查 Worker 上实际 `ultralytics.__version__ == "8.4.127"`。
- 当前未直接接触 A800，**真实 GPU 验收未完成**。不得以 CI CPU/模拟测试代替真机结论；最新 HEAD 的 CI 必须全部 completed/success 才能声明验收通过。

## 六、变更范围与发布限制

变更主要在 `platform_core/training_precision.py`、`train_worker.py`、Agent 结果/归档透传、既有 CI 版本、定向测试和 iframe CSS/浏览器测试。正式母模型管理、SHA256 校验、资源冻结、annotation ground truth、dataset snapshot 与成品模型归档未设计第二套逻辑。仅在长期分支提交。不合并 main，不 tag，不 release，不部署生产。
