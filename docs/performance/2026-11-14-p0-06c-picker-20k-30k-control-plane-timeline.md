# P0-06C｜训练素材 20,000 / 30,000 张冻结—汇总—创建—Prepare Worker 控制链路阶段计时（2026-11-14）

## 一、验收标识和范围

- 唯一开发分支：`feature/external-algorithm-publishing`
- 有效测试代码 SHA：`867bf156632bbd05f6ff46710ef77bd288f3b927`
- [Training Material Picker 完整工作流 #43552222962](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43552222962)：**success**，`contracts`、`real-chrome-picker` 均成功。
- 变更范围：`tests/api/test_training_request.py` 增加现有 20k / 30k 合同的阶段计时与正式 GT 汇总断言；`.github/workflows/training-material-picker.yml` 启用对应 `pytest -s` 日志保留。**没有修改业务逻辑、数据库结构或前端运行时**。
- 测试环境：GitHub Actions Ubuntu；真实 `MaterialRepository`、`AnnotationRepository`、任务持久化以及在进程内 HTTP 客户端。20k / 30k 素材均为**隔离生成元数据**，不是真实视频帧或生产 GT。未进行 GPU 训练、生产机部署或真实图像解码。

## 二、已覆盖的精确链路

1. 创建 20k / 30k 个已处理素材记录并初始化训练算法。
2. 调用正式 `POST /api/v62/projects/{project_id}/training-materials/selection-reference`，通过文件名筛选冻结真实素材 ID。响应只返回引用和数量，不把完整 ID 发送到浏览器。
3. 调用创建页实际使用的 `POST .../selection-summary`，以 `train_selection_ref` + `summary_only=true` 获取正式 GT 汇总；验证请求数量、素材匹配数量、可选数量和缺失素材。
4. 调用 `POST /api/v12/projects/{project_id}/train/start`；验证返回 202、训练父任务为 QUEUED、Prepare 子任务存在、父任务持久化的 `train_image_ids` 与请求冻结的 ID 全部一致。
5. 调用真实 `TrainingPrepareHandler.run()` 进入 Worker，**在完成冻结引用身份校验后主动中断**；比对收到的 20k / 30k ID。篡改掉一个冻结 ID 必须拒绝。

本链路包含真实 HTTP 路由/数据库/任务仓库/Worker 的**控制面**，但不包含 Prepare 的 GT 冻结计算、图像 I/O、GPU 实际训练及训练结束报告。

## 三、GitHub Actions 实测

从成功 CI `contracts` Job #132317030686 的标准输出读取。以下数值每种素材规模为**一次链路运行的阶段耗时**（ms），不是稳定 P50/P95，也没有真实网络延迟。

| 阶段 | 20,000 张 | 30,000 张 |
|---|---:|---:|
| HTTP 服务端筛选与冻结引用 | 316.575 | 369.156 |
| HTTP 按引用读取正式 GT 汇总 | 126.306 | 184.237 |
| HTTP 创建任务并持久化 | 414.364 | 483.835 |
| Prepare Worker 冻结引用校验 | 22.100 | 30.860 |
| **四阶段独立计时之和** | **879.345** | **1,068.078** |

这些阶段之间还包含测试断言、读取持久化产物及其他操作，所以“四段之和”**不是**严格的用户点击到页面返回的完整墙钟耗时；不应作为生产耗时承诺。

- 20k 与 30k 均：冻结引用 HTTP 响应 **133 B**；汇总响应 **416 B**，未返回成千上万个素材 ID。
- 20k：持久化 ID 数量 20,000，Worker 校验 ID 数量 20,000；30k 对应均为 30,000。
- 每个 ID 的值也逐个对照完整一致；篡改后的引用必须被 Worker 拒绝。
- `contracts` Job：基础后端合同 **176 passed / 2 skipped**，冻结到 Worker 合同 **3 passed**；其它性能测试子集通过。
- `real-chrome-picker` Job #132317030942：**success，20 passed**；60 张模拟卡、首次绘制 134.2ms；20 次温态 P50 93.4ms、P95 119.5ms、0 个温态 Long Task。该浏览器测试通过 Playwright 模拟后端大批量响应，并未同一次加载真实 30k SQLite 元数据。
- 相关代码提交：[加入阶段测量](https://github.com/jorsamj/aixunlianpingtai/commit/3db7138d986fc692c9616ec7b59642c5852a0839)、[保留 CI 日志](https://github.com/jorsamj/aixunlianpingtai/commit/867bf156632bbd05f6ff46710ef77bd288f3b927)。

## 四、解释与风险边界

- **已经证实：** 在隔离控制面条件下，20k / 30k 的筛选冻结、创建任务与 Prepare 引用校验不会丢失 ID；用户浏览器不需接收全部素材明细。
- **尚未证实：** 真实素材/真实 GT（含多标签、重复内容、异常标注）、多用户并发、生产磁盘与网络延迟、Prepare 的全量 GT/图像物化、实际训练执行及报告结果。
- 目前单次最耗时的被测控制面环节为创建任务（约 414–484ms）；但没有足够重复采样和真实环境证据证明其构成实际卡顿根因，**暂不实施盲目重构**。
- 原先用户反映的“批量确认后无法进入任务”在此隔离链路不可复现，但不能据此宣布全部真实场景已修复。
- P0-06C **生产端到端对账仍为 DEFERRED / NOT VERIFIED**；不能用此报告替代生产闭环。若要进一步调查，应先在获授权的**非生产**实例对真实 GT/图像样本进行只读分段跟踪，并把请求 ID、冻结引用、任务父子 ID、Worker 产物相互对齐。任何生产部署、重启服务或处理生产数据必须另行获得明确授权。

## 五、建议

此专项可认定为**控制链路隔离证据补齐、成功验收**，不需要额外的代码拆分、MySQL 迁移或 Vue 改造。后续优先关注 Prepare 全量 GT 和图像物化的真实瓶颈；在取得可复现的问题前不扩大开发范围。
