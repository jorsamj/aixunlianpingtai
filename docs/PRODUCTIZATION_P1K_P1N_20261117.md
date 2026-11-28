# P1K–P1N 素材业务产品化

基线107d4eb470f4b3b77ef9cc0be1dd54a0a8e1417f，唯一分支feature/external-algorithm-publishing。实时fetch一致、工作区干净，VERSION42.24.592。已直接查询GitHub该SHA38/38成功、核对前批真实入口与制品回执及代码，不仅依据文字答复。用户连续授权A–F，按已确认范围直接实施。

## Owner与最小设计

| 范围 | 原Owner/API | 方案 |
|---|---|---|
| 素材浏览 | MaterialRepository / v61 materials分页及原缩略图content | 原过滤/分页不重建；显式reader_view响应白名单，单图annotation按需读取，真实像素SVG，不把32框preview当完整GT |
| 负样本池 | NegativePool / 原negative-pool Router | 普通算法成员不改GT。原members缺CAS/回执，先在同一Owner复用已有negative_pool_operations账本补原子opt-in，再开放Vue加入/移出；审核仍回原Owner |
| 选择器 | TrainingMaterialPickerRuntime / 原v62 page/role/reference/membership/summary | 原Picker继续持有选择状态，Vue为展示adapter；原Draft唯一，冻结复用服务器manifest/request_id。不能安全表示的引用/逐张并集明确拒绝，不生成第二manifest |
| 创建与Worker | TrainingDraftRuntime / TrainingSubmitRuntime / 原TRAINING_PREPARE | 确认交回原Draft，原提交/引用展开/身份/GT修订准入不改；隔离验证请求体与Worker入口，不执行GPU训练 |

选择复用Owner与有界适配，而不是复制素材仓储、GT审核、选择manifest和训练草稿。原素材库、旧选择器默认保留。所有原图按需、缩略图懒读；无生产修改/部署、驱动SDK/调度/lease改动。

## 连续实施清单

- [x] A：实时HEAD/工作区/前轮代码与准确SHA CI验收核对。
- [x] B：原v61/annotation安全投影、Vue素材网格/列表/筛选/分页/详情/预览/当前页选择；必要API和Chrome定向合同。
- [x] C：原负样本成员事务/CAS/回执、Vue算法级成员浏览与加入/移出；网络未知复用原packet查回执，不篡改GT或其他算法。
- [x] D：原Picker展示适配、Vue完整选材、冻结数量/summary、原Draft交接；逐张/跨页/大引用→原提交请求→原Worker校验隔离证据。
- [x] E：桌面/平板真实截图、布局/请求生命周期/有界性能核验、离线构建/制品包含与交接。
- [ ] F：合理分阶段普通提交推送，准确SHA自动CI和实际artifact下载比对，最终列明未验现场与停止边界。

## 尚未改变的边界

无新物理删除、上传/清洗/标注/GT审核/正式训练创建Owner。普通成员关联不代表训练资格，零框不等于可训练；来源SHA、正式GT/revision、历史Train/Test隔离由原服务端继续负责。amd64/arm64、CUDA/Ascend未来扩展保留，不新增硬件适配。不重复全仓审计/训练测试/200k全量压测。

## 实际业务交付与入口

默认仍为原正式页面。`?vue_material_library=1&vue_negative_pool=1&vue_training_picker=1`：原算法页的“Vue 素材库”进入素材浏览，素材库进入算法负样本池；原训练创建的素材选择公开入口打开Vue展示。原NavigationStability/PageRequestScope/API会话、内存Router继续唯一；没有新增业务导航或登录。关闭开关即可回原页面；选择器有“使用原选择器”，同一Picker实例/选择/筛选直接切换呈现，不向Draft偷写未确认选择。robustness选择器仍原实现。

P1K：原服务端分页48张、名称/标签/标注及正式零框/质量/来源/批次/日期过滤，网格/列表、跨页普通选择≤200及摘要、懒缩略图、手动失败重试、按需完整标注详情（超过1000框明确截断）、原像素SVG和缩放、存储/来源可用性、单张按需历史分页。原接口没有池成员过滤，本轮通过算法负样本池入口查看该维度，不把零框当池成员或可训练。上传/标注/清洗/删除仍原Owner。

P1L：原v12算法摘要分页选算法、原v61算法池分页/名称/类别/标注标签/时间/审核/完整目标标签范围过滤；分类只读，资格/历史由服务端给出。只允许当前算法、明确≤200素材成员加入/移出，确认后原事务回执真实数量并权威GET。CAS409显示明确拒绝，可刷新后显式放弃；网络/5xx/无回执仍保留原packet，以相同operation_id查回执或显式重放。全局session槽跨项目仍阻断新意图，持久化不可用则阻止发送。审核/零框/GT范围/SHA/annotation revision继续原公开审核入口，本轮不复制。

P1M：原TrainingMaterialPickerRuntime持有唯一Set/筛选/页缓存/reference，Vue snapshot最多120行、100条已选预览，无大ID副本。原逐张/本页/跨页/当前筛选/全部可用；Train大范围原selection-reference/request_id/TTL/配额/同身份manifest；当前页membership。冻结后不能混合逐张或静默替代已有显式选择，无法表达的并集拒绝并保留。summary按需展示标签/GT计数，确认前全部显式≤2000项按原历史/GT谓词核验，五种revision前后栅栏，再交原Draft。Train/Test不混合；Vue Test仅支持逐张/本页有界选择（不支持全范围操作或大引用），已有Train引用时明确阻断Test选择，提示先Test再Train或回原流程。原Test确认不再清空已有Train引用。历史策略变更前先核验完整任务身份。

## API增量、写入与敏感边界

未新增Repository或独立Router。原v61 materials和原annotation GET增加`reader_view=true`安全白名单投影；原池列表同样投影，读视图≤120。仅单图按需GT，preview32/12框不冒充完整GT。媒体地址只接受同项目同素材的原v61content/thumbnail及v62training-thumbnail；没有自动全图降级或新下载接口。

原NegativePool.members新增paired `expected_revision`/`operation_id` opt-in（旧默认保持）；原生命周期fence+同库BEGIN IMMEDIATE+现有negative_pool_operations账本原子落成员/准确回执，重放不二次增长revision；新GET operations/{id}?algorithm_id仅回当前项目算法成员回执，跨范围404。无新增持久表结构或migration。普通成员写不触碰GT/文件/其他算法/分类。原selection-summary增加`validate_selection:true`有界只读投影，默认响应不变；复用原usage/GT Owner，没有新准入状态机。

## 验证证据

定向Python：素材reader/原负池37项，原selection-summary14项；另3项原冻结引用/HTTP/Prepare Worker合同（含20,000张参数用例与真实GT冻结阶段），均通过。20k只验证控制平面冻结/身份/Worker guard，无训练器启动。Node24直接相关14文件124项通过，涵盖缓存、桥接、旧Picker/负样本审核/资格、presenter和新API合同；新缺陷先RED后GREEN。新增3条Vue Chrome用例：素材跨页及40框坐标、未知成员写回执恢复/算法移出、原Draft两页选材/合成20k引用/旧呈现回退。合成20k UI回包只验显示，真实20k服务端/Worker由上述隔离Python证明，不能混称硬件验收。

TypeScript/Vite通过，最终构建尺寸和SHA制品回执另存`test-results/p1kn-real-entry/`。入口styles/app/main同缓存613，改变的算法列表与Picker自身标识613；未变模块不更新，VERSION42.24.592保持。Vue桥接资源标识p1kn1。没有新增轮询/任务领取/取消机制，退出只abort页面读取；modal原lease和任务执行不变。

真实入口复现：根目录`python tools/test_vue_productization_server.py`，frontend目录`node tests/real-material-productization.acceptance.mjs`。强制全新临时DATA_DIR、原真实登录/SQL/AnnotationRepository/125张本地图片、SDK禁止、lifespan/executor off。界面训练资源为明确模拟的HTTP回包，不代表现场资源；原Submit最终HTTP在浏览器截获不创建执行任务，验证algorithm/ref与空train_image_ids一致。原后端HTTP→durable parent→Prepare引用/GT冻结由定向Python独立验证，无GPU。

已从真实入口查看1600/768截图：素材网格、详情、负池、跨页选择和冻结选择。发现并修复v62缩略图被错误拒绝、候选选择清理后计数缓存、平板默认筛选过长；底部确认可见、无水平溢出。截图与receipt.json在`test-results/p1kn-real-entry/`，由脚本可重现。旧完整素材页返回可访问，pageerror=[]，Vue JS/CSS200。

## 离线与交付限制

沿用既有Frontend Runtime CI构建及upload-artifact，artifact `vue-catalog-preview-<准确SHA>`包含static/vue-catalog两文件与定向Chrome截图；没有新工作流或手动GPU/压测。原Algorithm SQL Store工作流补同一reader API测试，不引入第二CI体系。

正式源码包不能只git archive：必须追加该SHA构建的static/vue-catalog/catalog-preview.js和.css，或将同SHA CI制品还原到该目录。交付时验证ZIP CRC、两个成员及本地/CI字节一致；实际回执另存避免自引用SHA。只证明前端资源完整包含，不等于整套Python wheels/驱动/SDK离线安装验收。

生产A800/4070、真实硬件/SDK/训练/转换、20万真实素材性能、目标机断网安装均未验证。125张真实本地图片是隔离合成数据，不是生产素材；CI全绿不是生产验收。

## 后续边界建议（未实施）

素材HTTP读投影可沿原MaterialRepository/AnnotationRepository注入拆小Router；负池成员回执服务可留原同库事务单独封装，审核与资格继续独立Owner；Picker只读投影与manifest/训练准入分别标明依赖后再评估Router抽取。不拆新Repository，不机械拆app.py，不改Worker/lease/GT/frozen snapshot。linux/amd64、linux/arm64、CUDA/Ascend及其他硬件维持服务端能力事实约束，本轮没有硬件适配。

完成P1K–P1N后停止。素材上传/删除、AI审核、训练执行/新调度、全面后端重构和数据库迁移不自动接续。

## 精确SHA CI收尾修正

ecf93ddb8f96c04f0d9e263f5381137d6d087ebd的Frontend Runtime单元1706项中1703通过、3失败，均为lazy-advanced-evaluation/modal-style-scope/navigation-presentation的正则版本期望仍612，实际三入口统一613。同步这三个旧测试为613，保留完整scope/Owner/同版本断言；本地先RED后11/11 GREEN，无业务或缓存再变动。修正SHA另核CI及制品，不引用ecf失败结果为验收成功。

本地源码+Vue ZIP包含校验已通过：JS883902字节、CSS122311字节，ZIP CRC及两个成员字节一致；最终准确SHA离线包和CI artifact实物比对回执位于test-results/p1kn-real-entry。生产/现场离线状态仍未验证。
