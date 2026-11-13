# P0｜冻结训练素材引用跨角色污染：单点修复与验收边界

- 日期：2026-11-13
- 只读审计基线：`b1ac71b1df9eea2cf230bcba3371279e7fc8258b`，`VERSION.txt=42.24.592`，准确 GitHub Actions 23/23 success
- 本轮只改训练选材前端角色边界、Node 回归及指定静态缓存键，无后端/训练 Worker/数据库/GT 变更

## 已证实的缺陷

`static/modules/training-material-picker-runtime.js` 中 `open(role)` 原用 `selectedRole !== 'test'` 恢复 `trainSelectionRef`，因此 `robustness` 增强原图范围也继承训练冻结清单。接着 `loadPage()` 对存在引用的 picker 发送 `/training-materials/selection-membership`，body 中 `role=robustness`。原后端 `platform_core/training_selection_reference.py:selection_context` 严格接受 train/test，直接以 422 拒绝该调用，导致增强选材当前页加载失败。此为确定性代码路径问题，并非 20k 性能猜测。

## 最小修复

1. 冻结引用只对 `selectedRole === 'train'` 恢复，保证普通 train 原样、独立 Test 和增强选择不误用训练引用。
2. 新增 Node 回归执行真实 `open(role)` 源码分支，固定冻结数量 22,015；代码前复现 train/ref=true、test/ref=false、robustness/ref=true（错误），修复后期望 true/false/false。
3. 精准更新 `static/main.mjs` 的训练选择器导入缓存参数和 `static/index.html` 的 main.mjs 入口缓存参数；`VERSION.txt` 不变，避免误声称已部署。

## 影响和限制

- 不改 `selection-reference`、`selection-summary`、草稿 `train_selection_ref`、创建任务 POST、TRAINING_PREPARE 的任一数据合同；不混用独立 Test 和训练样本。
- 当前 `static/main.mjs` 在正常配置下向提交模块传入 `admissionMode=background`，仍由原 Worker 最终执行素材/正式 GT 准入。
- **本修复不代表冻结 20k/30k 训练素材的增强手动子集选择已经支持。** 冻结引用只有 train Owner，增强原图手动范围需要在现有增强策略合同下另行审计，不能把空的显式训练 ID 当作已选大范围。
- 仍需正式 GT 20k/30k 的浏览器/网络/服务端/Worker 同一请求链只读取证；不要把隔离模拟当作生产验收。
- GitHub 新提交的准确 SHA/CI **待核验**；未部署、未重启、未修改 A800/4070、未清理或改写生产数据，不合并 main、不 force push、不建 Release。

## 首次提交 CI 与补修记录

- 首次业务提交 `34b75a1227061f6fd20636ecec7e009d17a1880e` 的准确 Frontend Runtime Stabilization/frontend Job：1663 个 Node 单测，1652 pass、11 fail；新增引用边界和未知总数跨页全选回归均通过。
- 11 项失败原因：app.js、main.mjs、styles.css 必须共享纯数字点分缓存版本；前次仅将 main 更新为带后缀版本，精确源码守卫仍是旧值。
- 补修统一入口和训练选择器导入版本为 `42.25.604`，固定版本断言同步，**没有删除或放宽任何测试**；原训练素材业务修复不变。
- 补修准确 SHA/CI 待核。未部署、未改生产 GT/任务或 Worker。
