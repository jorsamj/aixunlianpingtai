# 2026-11-11｜42.24.587 训练素材未知总数大批量全选 P0

## 现场现象与代码证据

- 用户在训练创建选择素材时批选约 20,000–30,000 张失败。Chrome Network 中 `bulk-selection` 红色失败，Timing 的 Initial connection 约 30.02 秒；截图并未提供 HTTP 状态/Headers/服务端日志，因此**不能把连接建立耗时直接认定为 SQLite 执行耗时**。
- `static/modules/training-material-picker-runtime.js` 加载首屏时传 `count_mode=deferred`，页面的 `picker.total` 常为 `null`；原 `resolveBulkSelection` 只在“已知 total>2000”时绕过 `/bulk-selection`。这导致明显跨页但总数未知的训练“全选当前筛选/全选全部可用”仍先调用至多 2001 张的同步探测；超过阈值后再调用既有 `/selection-reference`，多做一次可能昂贵的查询/连接。
- 原后端 `training_material_picker_api.py` 的 `/bulk-selection` 本身按 GT 与训练历史规则进行有界扫描；`/selection-reference` 已是正式服务器冻结 Owner，返回引用和数量，`/selection-summary` 及 TRAINING_PREPARE 做正式核验。此处无需新增 API、缓存或第二套选择状态。

## 本批最小修复

1. 对 `train` 且没有既有手工选择、动作是“全选当前筛选/全选全部可用”的请求，若已知总数超过 2000，或总数未知但已显示跨页（`hasNext=true` 或 `page>1`），直接使用原 `/selection-reference` 创建冻结引用，跳过 `/bulk-selection` 探测。
2. 已知不超过 2000、小到单页且总数未知的选择、已有手工选择项、逐页逐张操作、反选和独立 Test 保持旧显式 ID 路径。因总数延迟统计，未知总数但超过一页的少量筛选也可能安全采用冻结引用；用户仍能看到冻结数量，改变选择会解除冻结。
3. 沿用同一 `request_id` 的服务端幂等冻结、引用上下文、正式 GT/历史/负样本修订、训练标签和 Worker 准入检查。**不把冻结当作训练资格已通过**；不发送 2–3 万个 ID 给浏览器。
4. 同步正式版本 `42.24.587`、入口缓存 `42.25.593`、选择器模块缓存 `42.25.587` 与浏览器构建标识 `422616`；同步相关源码守卫和定向回归。

## 验证与限制

- 本轮隔离运行了选择器决策的 5 个实际调用分支：未知总数跨页/已知超过 2000 仅发 `selection-reference`；已知小范围/未知单页/已有手工选择仍发 `bulk-selection`，均通过；模块与新增测试脚本通过语法解析。
- 以上为隔离契约验证，**真实 4070/A800 连接建立时间、20k/30k 冻结耗时、服务端响应及训练提交尚未验证**；准确新 SHA GitHub Actions 需提交后再查。
- 用户截图中的 30 秒 `Initial connection` 可能包含网络、反向代理、浏览器连接或 Web 进程接受连接的问题。若新版本仍失败，需要同一次请求的 Headers/错误码、`/api/health` 同时段响应、Web/代理日志及服务端阶段计时才能判定瓶颈；不能据此直接扩改 SQLite 或增加超时时间。
- 本批只涉及原选择器 UI 调用与测试、缓存、文档；不更改 GT、MaterialRepository、Worker、数据库模式或生产数据，不部署 4070/A800，不 merge main/tag/release/force push。
