> 2026-10-22接续：场景评估/素材及标注UI的唯一专项进度为[本轮治理](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)，P0/P1代码及隔离CI已验收，生产未验证；新HEAD验收以唯一专项末节为准；本文原验收合同继续保留。

# VNext 模型质量工作台：设计、合同与验收

基线：`30f83c48bab39b9b8aca07f95b8481a3fbb672ec`；长期分支 `feature/external-algorithm-publishing`；正式 VERSION 保持 `42.24.355`。本轮仅本地开发、测试、提交。

## 实际 UI 调研

- [FiftyOne App](https://docs.voxel51.com/user_guide/app.html) 与 [Evaluation](https://docs.voxel51.com/user_guide/evaluation/index.html)：官方文档可访问；借鉴指标→类别→错误图片、GT/Prediction 图层。浏览器桥接访问超时，未宣称看过其产品实机截图。
- [Roboflow Evaluate](https://roboflow.com/blog/evaluate-roboflow-models)：实际 Chrome 打开官方文章，并查看文章中的混淆矩阵/图片网格截图。截图保存在本机 visualizations 的 `roboflow-reference.png`、`roboflow-error-workbench.png`。借鉴矩阵单元格与图像联动、错误图片优先；不复制商标、图片或源码到产品。
- [W&B Run Comparer](https://docs.wandb.ai/models/app/features/panels/run-comparer) 与 [Models](https://docs.wandb.ai/models/)：本轮网页抓取返回 Internal Error，访问未验证；不将印象当成实际调研证据。
- [LandingLens Models](https://support.landing.ai/docs/models-page)：页面仅返回重定向占位，产品截图未验证。
- [Ultralytics Val](https://docs.ultralytics.com/modes/val) 与 [Validate and Diagnose](https://academy.ultralytics.com/courses/train-your-first-yolo/validate-and-diagnose)：官方指标文档可访问；区分固定阈值 Precision/Recall 与跨阈值 AP，强调查看真实 FP/FN。
- [Grafana Dashboard Design](https://grafana.com/blog/getting-started-with-grafana-best-practices-to-design-your-first-dashboard/)：官方页面可访问；借鉴指标层级、留白、色彩节制、运行资源与业务指标分组。

不照搬营销站单列 Hero、不使用大屏拼图、不引入各产品的 SDK/评测引擎。UI skill 推荐只作为参考：保留原 Web 技术栈与系统字体，不因其 React Native 模板更换架构。

## 已有能力—问题—复用与修改

| 已有唯一能力 | 发现的问题 | 本轮复用方案 |
|---|---|---|
| training_evaluation 独立盲测 | portable 文件名与当前 stored_name 不一致；只有笼统409 | 继续冻结 Test 白名单；Image ID/SHA/bundle manifest 定位，响应字节再校验 |
| Snapshot / MaterialRepository / StorageManager | 历史命名或迁移导致失联 | 同ID或内容索引安全找回；不以同名替代，不修改历史 Snapshot |
| TrainingRecoveryRuntime | 详情信息混杂、空参数多 | 同一 Owner 四Tab；既有 metrics SQLite 提供有界历史 |
| reports / v44 report | 趋势简陋；mAP高就给部署建议 | 同一报告入口；曲线、证据诊断、四类验收事实分开 |
| TP/FP/FN 与问题图Top200 | 没有真实跨类别混淆和阈值曲线 | 在原 scorer 采集空间匹配和21个置信度采样；旧报告缺数提示 |
| hard_sample_mining / CandidateStore | 测试集与困难样本易混淆 | 保留现有未标注候选→AI_ANNOTATION→人工复核；冻结Test不回流 |
| 版本与评测身份 | 不同基准可能被直接比较 | 严格校验 scope、GT、标签、实际输入和协议；不满足则不返回差值 |
| quality 数据质量 | 要求各类别补齐相同数量缺乏依据 | 保留分布事实；建议结合错误证据检查覆盖，不要求相等 |

## 最终页面结构

- 训练详情：固定任务摘要；训练曲线 / 训练资源 / 数据与配置 / 日志与诊断；沿用现有实时事件与回退轮询。
- 训练报告：成果指标、验收边界、九组真实曲线、收敛与泛化趋势、冻结数据与实际配置、模型成果、独立评测/场景实测入口。
- 独立评测：质量总览 / 类别与混淆 / 错误样本 / Confidence分析 / 版本对比；完整内容工作区，单一模态壳复用，不另建页面状态系统。
- 图片核验：图片与SVG同宽高比，解码和尺寸核验后显示图层；加载失败不展示检测框；上一张/下一张、缩放适配、全屏、可重试故障。

## 关键真实性协议

- 预测阶段不读取隐藏GT，评分阶段才读取。
- 逐类TP/FP/FN：置信度降序、同类、一对一、IoU≥0.5；mAP仍按原跨置信度AP计算。
- 混淆矩阵：独立注明跨类别空间匹配协议，不用单类计数拼接矩阵；全量计数，单元格图像名单最多200，浏览器只能打开已保留Top200问题证据。
- Confidence曲线：来自实际预测，IoU=0.5、Confidence每0.05采样，共21点；PR为这些真实阈值的采样图，不冒充AP积分曲线。
- 泛化诊断：至少10个Train/Val配对Epoch；前后各四分之一（至少3）均值，Train下降>15%且Val上升>15%才报告趋势信号。可能原因不作为根因。
- 终态资源：仅使用任务开始/完成区间内已保留采样均值；保留720条采样的窗口限制必须说明，不把结束后0%当训练期事实。
- 页面仅请求当前任务/所选版本；矩阵和曲线有界，历史不足不回算虚构数据。

## 验收状态

### 已完成

- P0：冻结 Test 成员、稳定 Image ID、原始/归一化字节 SHA256、Bundle manifest 和 Storage Source 逐层校验；细分缺 Snapshot、身份歧义、哈希漂移、对象缺失、临时存储、权限与解码错误。加载或尺寸失败时不显示任何框。
- 训练详情：同一 TrainingRecoveryRuntime 的训练曲线 / 训练资源 / 数据与配置 / 日志与诊断四 Tab；Epoch 最多1000、资源采样最多720。终态均值仅取 started_at 至 finished_at，缺结束时间时不伪造均值；新采样含 CPU、系统内存、I/O、GPU/显存。
- 训练报告：真实记录曲线、最佳已记录 Epoch、泛化差距/平台期/波动/末段改善的确定性趋势规则；执行成功、停止条件、独立评测、业务验收分别陈述。历史报告没有完整任务事实时明确降级。
- 独立评测：5 Tab 工作区；可分页类别表；置信度优先的一对一 TP/FP/FN；跨类别空间匹配混淆矩阵；21 个实际 Confidence 阈值采样；Top200 高风险图片；严格同 Benchmark/GT/Schema/Input/Protocol 的版本差值。同图并排另要求相同 Image ID 与实际字节 SHA。
- 质量闭环：关键类别 TP=0 诊断保持“可能原因”；困难样本仍只进入既有 AI_ANNOTATION / CandidateStore / 人工复核，冻结 Test 禁止直接回流。

### 本地验收证据

- 实现提交：`9408d569`（评测证据、质量计算、训练报告与后端测试）、`04bbe8f4`（评测/训练工作台 UI 与浏览器/前端测试）；文档单独提交，便于审阅。
- Python：208 passed，1 个 Linux `/proc` FD 计数用例在 Windows skipped。
- Node.js 24.19：frontend 947/947 passed。
- Real Chrome：51/51 passed，覆盖评测、训练报告/详情、导航稳定性、训练任务性能和 ZIP 刷新恢复。
- 实际截图目录：`C:/Users/jorsam/.codex/visualizations/2026/10/13/01a1331b-b427-7bf1-9454-b0d48376c22c`。包含 1920×1080、1440×900、1366×768、375×812 下的 evaluation/image/detail/report，以及 Roboflow 调研证据。
- 一次并行运行中 pytest 收集与 Playwright 同时操作 `test-results` 触发 Windows samefile 竞态；串行、短 basetemp 原命令最终 208/208 业务用例通过。另一个输入完整性链的长默认 temp 路径触发 WinError 206，短 basetemp 下原测试 2/2 通过，未修改测试强度。

### 明确未完成 / 待现场

- 未访问生产数据库、生产历史素材或真实 OSS，因此只能证明隔离环境复现和代码合同，不能宣称已有生产历史图片全部可恢复。
- 未执行真实 GPU 训练；PT/ONNX/RKNN 的现场效果继续沿用现有场景算法实测，未新增转换引擎。
- 全量（超 Top200）错误索引、完整目标尺寸分布、真实场景切片和 PDF 导出需要新增可靠持久化证据或迁移，留作 P2；旧数据不推算。
- 独立审查任务尝试两次均因指定模型容量不足未启动；最终结论不写成已获独立审查通过。

本轮只做本地提交；正式 VERSION 保持 `42.24.355`，不 push、不合并 main、不部署。

## 独立审查问题修复（2026-10-13）

八项审查发现已在既有 owner 内修复：历史图片身份改为显式 Image ID / 唯一冻结 stored_name；场景实测统一进入质量中心 detect；训练历史按需一次加载、轮询仅取 summary；比较按 class_id；Snapshot 元数据有界缓存；训练 Tab 完整 ARIA 键盘模式；A/B 同倍率缩放与同步定位、单侧全屏；缺失差值与真实零严格区分。

1000 Epoch + 720 采样的合成基准为 296,333 B 全量、428 B 精简。统一按首分钟 40 次总请求计算：旧 `40×全量=11.3042 MiB`，新 `1×全量+39×精简=0.2985 MiB`，完整历史首次加载已计入，下降 97.36%；稳态 40 次 compact 为 0.0163 MiB。SQLite SELECT 从每轮 4 次降为 1 次。20k Snapshot 的 24 张页从 24 次解析降为 1 次，23 次缓存命中合计 5.23 ms；文件变化会重新解析。

本地证据：受影响 Python 60 passed / 1 skipped；Node 24.19 952/952；定向 Real Chrome 7/7，并输出 1920、1440、1366、375 截图且标注验收夹具。新鲜 Windows 全量 pytest 为 2325 passed / 12 skipped / 62 failed，独立 `30f83c48` 基线对照 62/62 同根因；旧 64 项报告没有可反查 JUnit。旧基线 Full Chrome 为 142/148、6 fail；最终 VNext Node 24 Full Chrome 为 143/149、6 fail，六项同名同断点。首轮多出的标签管理项已按真实缓存提交时点修复测试夹具，repeat 5/5、相关素材集合 22/22；服务节点旧基线启动竞态亦只修测试前置状态，repeat 3/3。真实生产历史图片、OSS、GPU、GitHub Ubuntu CI 仍未验证，详见 `VNEXT_FINAL_DIFFERENTIAL_AUDIT_2026_10_13.md`。
