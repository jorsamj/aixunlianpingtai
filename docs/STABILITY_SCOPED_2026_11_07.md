# 全站稳定性专项，2026-11-07

基线为 `feature/external-algorithm-publishing` 的 `fc38666004168104c1d9ed1356d690fb46218561`，正式版本 42.24.561。本地、远端一致。基线 SHA 的 48 项 Actions 均成功。GitHub 对 main 的比较为 ahead 335、behind 5，本轮从指定长期分支继续。开发使用独立检出，历史未跟踪的测试产物留在本机，另两个开发工作区的 WIP 保留原状。

本轮需求是减少已复现的取消提示和业务页面重复文案。用户补充要求优先保护训练、素材上传、AI 标注和正式数据，采用定向回归。正式 VERSION.txt 沿用 42.24.561，前端资源缓存键使用 42.25.562 区分。

## 实际修复与边界

| 问题 | 复现、根因和影响 | 最小设计与结果 |
| --- | --- | --- |
| 快速离页弹出内部取消标记 | Chrome 保持真实资源 GET 和 classic GET 在途，执行页面往返。两条调用均正确返回 null，但 Toast 写入两次 `__PAGE_NAVIGATION_CANCELLED__`。classic 的 `safe` 和资源通知闭包直接用了词法 Toast，绕过主入口既有过滤。 | `static/app.js` 的两处反馈适配器接入 `window.toast`，模块尚未装好或命中 DOM 同名属性时使用既有 classic Toast。GET 生命周期、资源缓存、弹窗租约、轮询和 POST 语义保持原合同。Chrome 核对往返后两条旧读取均收口，每条只有一次调用，真实 503 及启动回退仍显示。 |
| 负样本卡资格重复 | 使用隔离后端经正式 API 建立项目、算法和 201 张图片。展开卡片时，徽标“待确认”和内层“资格：待确认”同时可见，两处来自同一字段。 | `static/modules/negative-pool-runtime.js` 删除展开区重复一行。常显徽标、审核和训练使用提示保留。原批量移出、失败项选择、迟到上传保护照常验证。 |
| 静态缓存 | JS 入口或模块改动后，旧缓存键可能继续提供旧渲染。 | `static/index.html` 保持入口共用缓存键合同，`static/main.mjs` 更新负样本池模块导入键。 |

前端生产改动仅上述四文件。原 PageRequestScope 和主 Toast 为反馈权威，资源发现继续使用原 request、cache、poll owner。负样本池修改点是原渲染模板，前后端数据与 API 均沿用原实现。兼容风险在旧页面混用缓存版本及模块加载前通知，分别用缓存键和启动回退覆盖。

## 审计结果与处置

- 已证实并修复的缺陷为正常导航取消显示错误提示。体验问题为负样本卡重复资格。
- 负样本池 200 张分批、跨页筛选、幂等计数、未知回执、正式 GT 保护和训练选材仍由原入口验证。本轮无新的数据合同修复。
- ZIP 约 12 MiB 的 COCO、VOC 合成 sidecar 分别观察到约 +199、+212 MiB 峰值工作集，取消存在阶段等待。保留原解析以免改变合法输入及标签行为。[实测与取消边界](STABILITY_ZIP_RISK_2026_11_07.md)
- Windows 相同本地发布用例在目标路径 273 字符时失败，223 字符时通过。属于可复现的测试环境触发与条件性业务风险，生产根目录、策略与现场恢复待验。[路径复核](STABILITY_WINDOWS_PATH_RISK_2026_11_07.md)
- 旧 8020 鉴权风险沿用上轮证据。部署和调用事实仍未知，现场清单附后续只读核验。文件体积、历史兼容与调用层级仅是维护成本，原有 Repository、Worker、Provider、CandidateStore、缓存和必要 Observer 继续承担各自职责。
- 页面审计覆盖源码入口和可用的业务态证据。审计未找到充分依据时保留当前文案。[逐页记录](STABILITY_UI_COPY_AUDIT_2026_11_07.md)
- 1366 宽度的同流程对照截图使用独立运行的合成素材。 [修改前](evidence/stability-2026-11-07/negative-pool-before-1366.png) [修改后](evidence/stability-2026-11-07/negative-pool-after-1366.png)

## 定向验证

| 范围 | 本轮证据 |
| --- | --- |
| Python、API、Worker | 74 项通过。现有负池、AI 审核回执/转池/撤销、人工负样本审核、训练准备→执行→归档、ZIP 安全。隔离 SQLite、测试 Worker 和模型替身。 |
| Node | 请求生命周期、资源通知/缓存、负池、过期动作栅栏，39 项通过。入口缓存键的既有版本所有权合同另通过 11 项。 |
| Chrome | 15 项选择性回归中 14 通过，1 条既有 AI 夹具红项。负样本 4 项全过，覆盖 1920/1366/768、键盘、触屏、reduced-motion、分批/重试/迟到响应。新增导航用例由两个取消 Toast 复现红项，修复后通过，最终复验包含启动回退。 |
| ZIP 复核 | 风险测量同时复用了 34 项安全/取消/恢复基线用例。与上述 Python 集合重叠，不相加。 |
| 训练保护 | 以基线差异核对 Python、训练/上传/AI 业务 JS 入口。已有集成用例覆盖准备、快照、资源配置、执行回执和归档。训练参数、正式 GT、切分和执行逻辑沿用原代码，真实 GPU 见待验清单。 |
| 历史 AI Chrome 夹具 | `navigation-action-fencing-r2.spec.mjs` 的 v60 stale-completion 用例在当前与基线均失败。基线 app.js 通过 Chrome 路由按 Git blob 提供，同样停在“数据集”。现行提交临界区明确拒绝离开直到回执，旧测试仍预期提交期间离页，且模拟成功体缺现行 task 字段。保留原用例和业务锁。原 Navigation Action Fencing 工作流 push 触发配置仅列历史分支。 |
| Windows | 同一现有发布用例对照 2 次长路径失败、1 次短路径通过。未放宽断言，详情见独立风险记录。 |

Git 交付以最终推送 SHA 的现有 Actions 运行结果为准。基线绿灯只用于基线核对。

## 现场待验

三份文档所有现场项为 **NOT VERIFIED（待现场验收）**。本地模拟和浏览器记录为独立证据。生产服务器、正式素材、模型、预设账户和其他工作区 WIP 均保持原状。

- [A800](A800_FIELD_ACCEPTANCE.md)
- [4070 AI 推理与双卡](4070_AI_INFERENCE_FIELD_ACCEPTANCE.md)
- [20 万素材](MATERIAL_200K_PERFORMANCE_FIELD_ACCEPTANCE.md)
