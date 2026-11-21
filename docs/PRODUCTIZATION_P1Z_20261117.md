# P1Z 统一工作台收尾与 CI 优先执行

基线9778f671375983ff362d4964681df0f5c17105f7；唯一feature/external-algorithm-publishing，开始前fetch确认远端/本地一致，未覆盖其他工作。VERSION42.24.592保持，入口三缓存统一42.25.622。

## 实际完成

- ?vue_workbench=1聚合已交付Vue opt-in，默认旧入口不变。唯一原renderNav/NavigationStability接收纯菜单元数据，主入口工作台、算法与模型、素材、AI、训练、资源、配置；原高级入口与原页面保留。没有第二导航/登录/业务Router/调度器。
- ProductWorkbench复用原trainingReaderApi和aiTasksApi，各服务端limit=5、reader_view=true；按实际状态显示近期记录，不伪造总数/ETA/成功指标，无新轮询。原client默认20保持，只增加1..20有界参数；工作台GET权限仅本项目两集合且limit5，禁止详情/素材/全算法读取。
- Vue runtime JS共享一次导入；memory router/Pinia仍每个短生命周期展示挂载，离开原app.unmount/history.destroy，保留唯一原业务Owner。没有证据证明强行合并全局SPA会改善当前问题，故不重构。局部真实观察：十次切页一个活动Vue app、同次页面仅一次Vue JS资源读取；不声称全站性能或堆内存压测已完成。
- 报告job/algorithm/version和returnPage=workbench保持；原ui-state只追加白名单项目+选择/报告身份，不保存token、密钥、模型对象、素材清单或指标，刷新按同项目恢复。退出取消本页HTTP，迟到响应不覆盖新页面；不会取消后台任务。明确退出统一开关可返回原总览/默认导航。

## 已确认的失败及修复

脚本实际为frontend/tests/real-product-workbench.acceptance.mjs。此前node tests/real-product-workbench.acceptance.mjs的working-directory是frontend，因此路径一致，根目录没有另一份同名脚本。现CI统一在仓库根执行node frontend/tests/real-product-workbench.acceptance.mjs，输出目录由import.meta.url解析，避免依赖cwd。

P1Z本地早期入口用例先误把恢复合法旧算法页后的首次入口当默认dashboard，后用错报告/模型资产aria名称；按原真实导航和组件实际名称修正，没有据此改业务。最终已有通过回执：原真实登录、两条5行GET、报告刷新返回、十次切页、退出取消、原入口回退、六宽1920/1600/1440/1366/1024/768。桌面/平板截图已查看，保存仓库外delivery-evidence/20261117/P1Z-real-entry，隔离预存合成记录不等于生产执行。

准确基线9778f67 CI实际37/38成功，唯一Frontend browser-navigation1中旧ai-create-experience用例在503后期待相同ID第二POST（Expected2/Received1）。本轮改为更严格原request_id GET-only，仍保留配置失败重试、输入/标签、二次确认和重复提交门禁断言；明确要求POST1、唯一ID及匹配GET、UNKNOWN保持。检查该用例还发现POST进行中重复调用会提前查询一次回执，原submitOwner补submitting/summaryLoading前置门禁。该单条原Chrome用例已通过；未放宽安全断言，未删除测试。

## 最新测试执行约束（用户2026-11-17补充，长期优先）

以后优先GitHub Actions。不要本地反复跑全量/浏览器/截图/起停多服务；不重复代码未变且已通过的测试。只在确认真实失败后必要本地快速构建；其余由准确SHA现有CI承担。失败只读对应失败Job日志并定向修复，不手动重跑全部工作流。本次补充指令后不再本地运行浏览器/全量Node/Python。

沿用Frontend Runtime Stabilization既有Node合同、Vue TS/Vite、Vue交互及导航/状态恢复CI，不建第二套workflow。只追加一个needs:frontend定向Job“P1Z isolated real-entry acceptance”：下载同SHA既有Vue资产、不重复构建；唯一临时DATA_DIR、lifespan off、SDK禁止，执行准确脚本一次，6视口文档及view横向溢出、GET5、身份/刷新/返回/取消、单Vue挂载、原导航回退，上传p1z-workbench-${github.sha}收据/截图/失败日志。Node/构建继续原Job，原浏览器其他工作流由仓库自然触发，不手动扩大。

补充前已完成必要定向Node92通过、原reader新增limit合同3通过、上述隔离真实入口通过；这些是历史本地证据，不替代本批准确SHA CI。提交前按用户要求仅一次快速TS/Vite构建，之后推送并检查该SHA结果，当前记录不预先宣称CI绿色。

## 离线与验收边界

static/vue-catalog被gitignore，单纯git archive不含构建资源。正式离线方式：获取准确SHA vue-catalog-preview CI artifact并确认workflow_run.head_sha，CRC/SHA校验；git archive相同SHA，再把该CI artifact的JS/CSS加入static/vue-catalog，保留全部vendor/LICENSE/NOTICE/map并核对包含性。仓库外交付回执及源码包含ZIP记录准确SHA/hash；不拿开发机产物冒充CI或现场安装。既有SFC eol=lf规则已恢复遵守，P1Y准确CI与最终本地LF两资源rawSHA均已MATCH。本批新SHA仍须实际核验。

P1S–P1Y不重新开发/审计。本批未调用生产/真实训练/推理/转换/GT/畅联云发布/OSS/SDK/节点生命周期，无schema/数据库迁移。原复杂配置、治理与高风险写动作继续原Owner，不宣称已将每张旧表单全部Vue化。实机异构硬件、真实外部交付和现场离线安装未验证；不切换默认正式入口。后续建议先按准确CI与用户验收补已确认缺口，再单独授权真实环境/默认入口对等验收；不自动启动P2或其他新专项。

## 本批实际文件

- .github/workflows/frontend-runtime-stabilization.yml
- AGENTS.md
- docs/CODEX_CURRENT_STATE.md
- docs/CODEX_READ_FIRST.md
- docs/FRONTEND_OWNER_MAP_V42_25.md
- docs/FRONTEND_THIRD_PARTY_REUSE_POLICY.md
- docs/PRODUCTIZATION_P1Z_20261117.md
- frontend/src/api/ai-tasks.ts
- frontend/src/api/training-reader.ts
- frontend/src/main.ts
- frontend/src/types/model-browse.ts
- frontend/src/types/product-workbench.ts
- frontend/src/views/ProductWorkbench.vue
- frontend/src/views/TrainingReport.vue
- frontend/tests/real-product-workbench.acceptance.mjs
- static/app.js
- static/index.html
- static/main.mjs
- static/modules/catalog-preview-runtime.js
- static/modules/navigation-presentation.js
- static/modules/product-workbench-runtime.js
- static/modules/ui-state.js
- tests/browser/ai-create-experience.spec.mjs
- tests/frontend/ai-task-reader-contract.test.mjs
- tests/frontend/catalog-preview-runtime.test.mjs
- tests/frontend/lazy-advanced-evaluation-owner.test.mjs
- tests/frontend/lazy-changlian-data-browser-owner.test.mjs
- tests/frontend/lazy-legacy-material-owner.test.mjs
- tests/frontend/lazy-quality-detection-workbench-owner.test.mjs
- tests/frontend/modal-style-scope-13b.test.mjs
- tests/frontend/navigation-presentation-owner.test.mjs
- tests/frontend/product-workbench-runtime.test.mjs
- tests/frontend/training-resource-cards-extraction.test.mjs
- tests/frontend/ui-state.test.mjs
- tests/frontend/upload-task-center.test.mjs
