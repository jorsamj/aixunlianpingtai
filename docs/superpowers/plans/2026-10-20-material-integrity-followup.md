# 素材治理接续修复计划

**Goal:** 关闭当前代码可复现的标签映射漂移、提交响应归属和重试计数缺陷。

**Architecture:** 保留 MaterialBatch / DELETE_INDEX / AnnotationRepository、原冻结计划及 PollRegistry。已有审计 label_schema_digest 向下贯穿计划与执行清单；不增加状态 Owner。

**Tech Stack:** Python/FastAPI/SQLite，classic JavaScript，pytest/Node/Playwright。

- [x] 完整 fetch/pull 长期分支，核对六个提交、源码与现有回归。
- [x] 在 tests/api/test_material_integrity.py 加入三个阶段的标签映射漂移测试，以及真实部分成功任务重试测试；旧代码四项失败。
- [x] 在 tests/frontend/material-integrity.test.mjs 加入迟到成功/失败响应的执行测试；旧代码两项失败。
- [x] 在 platform_core/material_batches.py 冻结并复验已有标签摘要；Worker 仅复验未成功项，保持成功计数。
- [x] 在 static/app.js 的原 execute owner 核验项目、审计、计划、可见弹窗和原内容归属；当前页面内显示错误，后台受理身份保留。
- [x] 执行聚焦 RED→GREEN、全量 Node、API/Worker 安全回归和真实 Chrome；保留原始日志。
- [x] 更新验收与现有 handoff；保持正式 VERSION，递增入口静态缓存标识。
- [ ] fetch 核对远端后普通推送；按最终 SHA 查询全部 Actions 和分页 Checks，记录生产未验证边界。

执行命令：`node --test tests/frontend/material-integrity.test.mjs`；`python -m pytest -q tests/api/test_material_integrity.py`；`npm test`；`npx playwright test tests/browser/material-integrity-governance.spec.mjs tests/browser/material-workflows.spec.mjs`。
