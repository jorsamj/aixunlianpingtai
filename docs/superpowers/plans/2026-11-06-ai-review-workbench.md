# AI 标注审核工作台实施计划 2026-11-06

基线：9656ded4 / 42.24.543。用户已授权全部 Word 需求与六张原型，继续执行无需重复设计审批。

架构：CandidateStore 是候选及审核草稿唯一 Owner；NegativePool 是池成员 Owner；AnnotationRepository 是正式 GT Owner。沿用任务 FileLock、request_id、receipt 和既有请求中心。不操作生产数据。

- [ ] P0 存储：CandidateStore 增加不可变原始框证据、带 revision 的审核草稿、持久排除状态、筛选/统计。先写失败测试，再实现；旧候选兼容，正式 GT 不变。
- [ ] P0 流转：原 v60 API 接入草稿保存、冻结选择及有界负样本转移，复用 NegativePool；GT 冲突阻断、人工确认范围、可恢复回执及撤销；最终审核只提交剩余候选。覆盖并发、重复提交、部分失败。
- [ ] P0 诊断：失败/取消/无产物任务详情可读；按图错误、阶段、HTTP、建议、脱敏导出、原重试入口；WeVisOne 原生及网关路径合同和超时一致性。真实内网访问失败则如实记录而继续其他工作。
- [ ] UI：原 app.js Owner 改三栏工作台、筛选/当前图检查、跨页选择、稳定底栏、同层转移侧栏、草稿保存状态；原编辑器复用。局部 patch、请求过期防护、中文、键盘/reduced-motion/44px 触屏。
- [ ] 验证：原 Python/Node 定向与回归、真实 Chrome 1920/1366/768、20k 合成任务有界读取/交互性能；真实模型不得以 mock 冒充验收。
- [ ] 交付：版本/README/AGENTS 与四份交接文档更新，git diff 检查、远端 HEAD 快进核验后提交推送，查询精确 SHA CI。生产不变。

审计已确认：单图保存仅 JS Map；候选 GET 缺 result_ref 返回409；已有恢复/重试、SQLite游标分页及池 API，禁止重复实现。原工作区 WIP 保留，开发只在独立克隆。
