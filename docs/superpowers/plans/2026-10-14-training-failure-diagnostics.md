# 训练失败智能诊断实施计划

1. **锁定基线**
   - 确认 `4d2e5713`、`VERSION.txt=42.24.356`、工作区干净。
   - 运行 recovery Python/Node 现有测试并记录 Windows 已知信号差异。

2. **先写后端失败合同（RED）**
   - 在 `tests/unit/test_training_recovery_api.py` 增加结构化诊断、证据等级、误判防护、Checkpoint 和脱敏用例。
   - 在 `tests/unit/test_training_final_validation_oom_hardening.py` 增加 Linux Kernel OOM 采集的 PID/时间窗边界用例。
   - 运行新增用例，确认因合同尚未实现而失败。

3. **实现后端最小闭环（GREEN）**
   - 在现有 hardened Worker 失败路径单次采集可获得的任务关联 Kernel OOM 摘要。
   - 在 `training_recovery_api.py` 生成诊断类别、等级、依据、可能原因、建议并脱敏。
   - 不改变任务状态、恢复判定和训练资源行为。

4. **先写前端失败合同（RED）**
   - 扩展 `training-recovery-runtime.test.mjs`，要求只消费后端 `diagnosis`，按原因→依据→建议→技术详情展示。
   - 扩展既有 Playwright recovery 场景，要求无 Checkpoint 时显示固定边界且没有恢复按钮。

5. **实现 UI 与缓存合同（GREEN）**
   - 在现有详情组件和样式中增加紧凑诊断块，保持现有视觉体系和响应式布局。
   - 更新 training recovery runtime 的唯一缓存标识及对应 CI 守卫，不修改正式版本号。

6. **回归与真实浏览器**
   - 跑聚焦 Python、Node 24、Playwright Chrome；核验 Network 没有新增接口/轮询。
   - 保存训练失败详情截图；再跑相关工作流本地合同和必要扩大回归。

7. **交接、提交与推送门禁**
   - 更新 `AGENTS.md` 与四份 handoff 文档，明确未验证边界。
   - 使用 verification-before-completion 检查 diff、VERSION、测试与工作区，创建独立本地提交。
   - `git fetch` 后仅在远端仍为 `b520cc03`、本地严格领先两个预期提交且无分叉时普通 Fast-forward Push。
   - 等待新 HEAD 实际触发的 Actions；若需代码修复，只本地提交并停止继续推送。
