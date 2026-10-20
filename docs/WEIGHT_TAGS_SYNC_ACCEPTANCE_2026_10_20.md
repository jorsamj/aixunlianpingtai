# 训练与转换 Weight tags 专项验收｜2026-10-20

## 2026-10-20｜训练与转换 Weight tags 专项（阶段D测试通过 / 阶段E待推送CI / 生产未验证）

- 需求：核验冻结训练类别经原始PT/ONNX/RKNN到新畅联add/edit实际HTTP JSON；tags原生字符串数组、class_id顺序、未知省略且不阻断。上传人/身份/OSS对象标签不在范围。
- 已完整fetch/pull；分支feature/external-algorithm-publishing，起始HEAD 2cb3ba1617551f59abdc9c66115a0cde29d463f5，远端一致、工作树原始干净，VERSION42.24.358。
- 已有：冻结类别/Snapshot提取、可选扩展字段、旧ID edit、synced_payload_json与UNKNOWN恢复、转换完成唤醒。待核验：真实训练冻结格式、完整HTTP JSON、ONNX/多类/多版本与历史补齐链路；已核验没有新增业务缺口，仅补HTTP链路覆盖。
- 预计范围：既有发布/平台/转换通知测试与必要的最小修复、现有handoff；不新建Owner，不部署、不调用真实新畅联写接口、不操作生产OSS或历史数据、不运行真实训练/转换。禁止测试发散。
- 当前状态与下一步统一见 docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md；阶段变化持续持久化，最终CI须对应最终SHA。

## 阶段 A：现状核验（核验完成）

起始2cb3ba16为上一轮最终提交。上一轮最终证据归档：Actions22/22、Checks57/57成功；这是历史基线，不代表本轮CI。上一轮正确实现全部保留。已追踪training_tasks完成写入frozen_label_schema/frozen_label_codes、remote_training_tasks/remote_execution_transport同一冻结格式，以及conversion_tasks._finalize_conversion_job原通知Owner。发布层_frozen_weight_labels→discover_artifacts→ModelArtifact→_weight_metadata_payload→PublishingChangLianClient→ChangLianClient._request(json=body)链路已有且正确。上一轮DTO端测试已有原生数组证据，但未把冻结/转换通知/发布Owner贯穿到真实PreparedRequest.body。真实缺口是该层验收覆盖，不是业务功能缺失。

## 阶段 B：RED 检查（完成；未复现业务RED）

增加6项tags_wire测试，requests.Session及其JSON编码器为真实实现，仅HTTP adapter接入现有FakePublishingClient隔离后端；所有scheme装配adapter、断言changlian.example、trust_env=False，不访问网络。起点采用真实build_snapshot冻结排序与训练同用的attach_version_if_current；不声称执行了真实GPU训练。转换使用真实_finalize_conversion_job写job/通知、真实run_auto_publish_once同步。

首轮5 failed/1 passed：4项测试漏传now，另1项adapter复用Fake列表未按algoVersionId过滤，均为夹具错误，不是业务RED；修正后6 passed/109 deselected/0 failed/0 skipped。不得把该失败当业务修复证据，不为制造RED改业务。初次日志tags-wire-first-1020.log，修正tags-wire-second-1020.log。

## 阶段 C：实现（测试补全已实现待完整验收）

没有修改生产业务代码。保留上一轮字段提取、synced_payload_json、UNKNOWN恢复、原ID edit、文件SHA与芯片安全条件。仅tests/unit/test_external_algorithm_publish.py新增隔离链路验收；静态复核发现转换函数导入task_runtime需要psutil，仅在原SQL精简Job补该依赖，避免本地依赖掩盖CI遗漏；原有Fake后端复用而非伪造生产结果。无新Owner/队列/数据库/轮询/UI或身份变更。旧Weight测试额外清空旧确认回执，并在首次上传后禁止再次ensure_uploaded，确保补标签复用文件。

AGENTS.md追加永久进度规则；本专项为唯一验收文件，CODEX_CURRENT_STATE顶部为唯一接续入口。

## 阶段 D：GREEN 测试（测试通过）

- Python：`python -m pytest -q tests/unit/test_external_algorithm_publish.py tests/unit/test_external_algorithm_platform.py tests/unit/test_conversion_tasks.py --basetemp=C:/Users/jorsam/.codex/tmp/tags-final-1020`：200 passed / 0 failed / 0 skipped，69.78s，5项已有FastAPI/Starlette弃用警告。
- Node：`node --test tests/frontend/external-algorithm-publish.test.mjs`：16 passed / 0 failed / 0 skipped。
- Chrome：`npx playwright test tests/browser/external-algorithm-publish.spec.mjs`：3 passed / 0 failed / 0 skipped，11.0s。
- 复核增强转换Event.set断言后，仅重跑受影响6项：6 passed / 0 failed / 0 skipped（109 deselected），日志tags-review-1020.log。
- 新增wire回归6项均包含在上述200项内，不重复计数。既有UNKNOWN/文件身份/存储与芯片异常测试不删除、不降断言，真实转换成功/硬件待验证边界不变。
- 原始日志：C:/Users/jorsam/.codex/tmp/tags-python-final-1020.log、tags-node-final-1020.log、tags-chrome-final-1020.log，前两轮夹具调查日志同目录tags-wire-first/second-1020.log。
- 未运行无关本地全仓库测试、真实训练/转换或生产接口。

## 阶段 E：Git推送与CI（待提交推送 / CI未开始）

普通FF推送唯一长期分支；当前已具备提交内容，尚不能宣称CI通过。VERSION42.24.358、静态缓存不变。

最终提交后按实际完整SHA查询所有Actions和Checks（分页完整计数），关键Publish contract/Chrome及SQL合同须核对；未触发项明确标注。最终SHA、远端HEAD、全量运行/Checks清单及结论保存在独立验收附件 `C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-tags-ci-final-20261020.json`。按用户9.4例外，最终CI附件不产生新代码SHA；下次受验证的进度提交需先归档该结果至本专项，再继续。此待验收表述是提交前记录，最终结论必须读取附件和该SHA的GitHub Checks，不借用基线绿色。

## 阶段 F：本地验收（测试通过 / CI待验收 / 生产未验证）

本地验收成立：best.pt、ONNX、RKNN通过同一可信标签来源同步；add/edit实际HTTP JSON均为字符串数组且按class_id，未知省略正常成功；旧ID安全补齐、零重复交付。真实新畅联写入、生产旧Weight、生产OSS、GPU转换与硬件加载未授权未验证。源码交付完成尚待最终SHA CI；CI通过后仅可进入另行授权的部署验收，不自动部署。

新会话接续：先读CODEX_CURRENT_STATE顶部→本文件A至F→独立最终CI附件并核对远端SHA→在下一次受验证提交归档CI；不重复开发已存在标签机制。


## 验收追溯（隔离合同，不冒充生产结果）

| 用户验收项 | 直接证据 |
|---|---|
| 训练完成best.pt标签、JSON数组与class_id顺序 | tags_wire_training_and_completed_onnx_rknn：真实Snapshot排序/条件版本提交→训练发布通知→run_auto_publish_once→真实DTO/Session JSON encoder→PreparedRequest.body |
| 转换完成RKNN/ONNX继承、两芯片一致 | 同用例实际_finalize_conversion_job提交Job与通知原Owner；4个Weight只建立1个远端Version，全部tags同冻结版本；RK3568/RK3576分开验证 |
| 单/双/三以上模型、非字母顺序 | 参数smoke；smoke/fire；helmet/fire/smoke/vest，不截断且不按代码字母重排 |
| 历史不受当前项目影响、版本迭代 | 项目标签current-only与冻结类不同；tags_wire_model_iterations单独验证两个Version各自类序 |
| 未知标签正常同步、不清空 | None参数4个Weight均PUBLISHED且无tags；旧Weight后续真实edit尺寸时仍省略tags，保留模拟后端原标签 |
| 旧ID edit及幂等、文件不重复上传 | tags_wire_old_weight清空旧确认回执，恢复可靠标签→原ID原VersionID edit；上传后ensure_uploaded设为遇调用即失败；再次发布零add/edit；原artifact_id/uploaded_at不变 |
| 真实大小/SHA/尺寸与芯片安全 | 现有完整发布/平台/转换通知三文件回归；新wire用例继续核验训练800/转换640、真实文件事实存在，异常细节沿用原覆盖 |
| UNKNOWN/超时只读恢复 | 上轮既有sync_unknown与恢复测试继续执行；不为本轮复制第二套用例/Owner |
| UI非阻断状态 | 现有Node external-algorithm-publish及Chrome单规格；本轮不改UI |

新链路不执行训练进程、真实转换、GPU或公网业务调用；Snapshot输入为隔离合成类别、Job输出为临时文件，原Worker完成写入格式另由源码与既有测试核对。新增转换通知断言包装真实Event.set并保留原调用，明确每次转换恰好发出一个信号，避免依赖run_auto自动扫描来推断通知成功。HTTP adapter响应为明确Fake后端，不能据此声称真实新畅联业务已接收。


## 只读复核

独立复核未发现tags业务P0/P1；发现1项CI P1依赖遗漏（转换函数间接顶层import psutil，SQL精简Job未安装），已按建议仅补该项。确认网络隔离、真实序列化、原ID edit/禁重复上传断言合理；转换通知增加真实信号发出断言。复核未运行额外测试。
