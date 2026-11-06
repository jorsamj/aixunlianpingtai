# 素材库、图片详情与ZIP导入专项 42.24.552

日期：2026-11-06。真实基线42.24.548 / 4aa155ddc355b05d6f984e5f740c9540e4b81b2a；独立克隆长期分支。已读上轮审核专项全文和本轮Word全部7张插图，截图中的537不作为运行或部署证明。原WIP和另一工作树未改，生产未访问。

## 需求→现状→本轮修改→验收

|需求|真实原实现|本轮修改|验证|
|---|---|---|---|
|入库后直接标注|ZIP四动作已存在；素材卡片pending_decision只给清洗|默认全部素材，待标注直接人工/AI；质量维度独立投影|真实ZIP四动作和原素材浏览器回归|
|原图包正常完成|零框及未匹配标注通用橙色警告|依据scan_kind/result_kind分类，RAW无标注正常；真正异常仍提示|报告RED/GREEN、真实STORED/DEFLATE/YOLO/损坏/方法9|
|素材库工作台|48条服务端分页已完成，旧卡片标签/按钮密集|原app.js Owner简洁卡片、一主操作+更多、框默认隐藏、网格/列表、固定批量栏|三视口截图、局部DOM身份与Network证据|
|筛选与范围|来源/名称/标签及旧状态已有|原MaterialFilters/SQL增加批次、日期、待审核事实、质量投影；同谓词分页/计数/ID/冻结|API及原筛选删除回归；历史无元数据批次见限制|
|详情|原通用modal，重复关闭、无图像交互|原preview函数直接委托展示模块；Panzoom同层变换，正式GT按需读；唯一关闭、键盘跨页|660×440/1280×960/长窄图/EXIF JPEG/失败重试|
|批量操作|原MaterialBatch、AI创建、人工队列和NegativePool已有|显式勾选可跨页；AI/人工/质量/原冻结删除；最多200张暂存池；选择清单JSON|原链路与项目/筛选围栏回归；不声称选择清单是数据集导出|
|AI审核/草稿/恢复/转移撤销|548已完成|仅复用入口并回归，不重建|上轮真实API草稿/转池/撤销及工作台回归|

## 数据不变量、兼容与部署

- 素材仓储、AnnotationRepository、CandidateStore、NegativePool、TaskRuntime、分页/请求中心均保持原Owner。新增展示模块只处理图像、菜单、图标，不写GT或新增缓存/任务引擎。
- `processing_status=pending_decision`、`annotation_state=unannotated`仍是真实原图状态。打开AI/人工/稍后不调用mark-ready，不伪造clean_skipped；0框不能自动confirmed_empty。正式训练准入SQL、算法作用域、历史/Test隔离未放宽。
- ZIP worker在原image batch提交前附加可信import_batch_id/source_task_id来源元数据，复用原buffer提交与回滚；正式框、素材ID、物理文件不变。旧素材不批量回填。
- 素材库待审核筛选使用已持久annotation_needs_review/external_annotation_needs_review/needs_review事实，不全量扫描各候选库；已知AI任务仍用原任务入口。
- 质量“未检查/已处理/有问题”是已有状态和显式quality_status投影；已处理不宣称质量通过。有问题不凭空推导。
- 唯一SQLite增量为素材批次表达式索引 `ix_materials_import_batch`。保持schema6，旧schema5只读支持不变；原初始化锁内建立索引，测试模拟旧6升级不改素材修订/GT。无列迁移、无历史重写。回退旧代码可忽略索引，保留审计，不需要删除任何数据。
- 部署负责人依原流程备份业务目录/SQLite/ArtifactStore后升级；本轮仅仓库代码和隔离测试，未部署。

## API与原调用链接入

原GET `/api/v61/projects/{project_id}/materials` 及其 `/ids` 新增 `source_batch_id`、`annotation_state=needs_review`、`quality_status=pending_decision|processed|issue`、`created_from/to=YYYY-MM-DD`；日期闭区间以次日上界处理，非法/颠倒日期明确400。仍是48条默认服务端分页，单请求不回传全库ID或GT。

新批次使用JSON来源索引；历史批次没有素材级元数据时仅兼容读取原可信导入报告成员，浏览器仍只收到当前页。历史报告不会变成第二份素材真值，也不回填生产。此类历史批次FILTERED批量估算/创建明确409 `LEGACY_BATCH_SCOPE_REQUIRES_SELECTION`，要求跨页明确勾选；避免页面有图片而冻结0张。新批次和其他过滤继续原estimate→revision→freeze→task事务及删除引用保护。

单张/批量暂存负样本池进入原NegativePoolRuntime和成员API，用户指定算法与确认范围，正式正框预检阻断；只建立管理关联，不授予训练资格或覆盖GT。AI候选放弃/转移/撤销仍进入548候选审核事务链，不能用素材库关联冒充候选转移回执。

图片详情正式标注通过原 `/api/projects/{project_id}/annotations/{image_id}` 按需读取；失败显示重试，不把失败覆盖成0框。图像与框共用原始像素世界坐标及同一transform，EXIF以浏览器解码后实际几何验证；不迁移旧GT。

## 开源组件与产品取舍

|组件|固定版本/协议|用途及结论|
|---|---|---|
|@panzoom/panzoom|4.6.2 / MIT|仅详情缩放、拖动、触控；不替代正式编辑器|
|@floating-ui/dom|1.8.0 / MIT|原素材卡片更多菜单定位；边界、Escape、焦点及销毁统一|
|lucide|1.70.0 / ISC|只vendor七个需要的SVG节点，不在线加载整包|
|Annotorious/Uppy|原3.9.5 / BSD-3-Clause、原Core/Dashboard MIT|直接复用，不替换标注或上传系统|
|TanStack Virtual、Tabulator|本轮未引入|48条分页实测无大DOM瓶颈，避免平行列表状态|
|PhotoSwipe、Vue/React|本轮未引入|预览与Panzoom重叠；整站框架迁移不属于任务|

`tools/vendor_material_presentation.mjs --check`验证本地manifest/NOTICE/所有依赖许可证与integrity、SHA256、字节数；18项受验本地资源合计112407字节（另含manifest）（包含NOTICE/许可证，非gzip大小），无运行时CDN。生产依赖官方npm audit为0漏洞（当次检查），默认镜像audit端点不支持，已使用官方registry单独检查。

产品取舍参考官方资料：采用[Label Studio集中数据管理](https://labelstud.io/guide/manage_data)的统一浏览/筛选；[CVAT导入](https://docs.cvat.ai/docs/dataset_management/import-datasets/)的图片与标注区分；[Roboflow](https://docs.roboflow.com/)只参考上传后进入标注的流程，不移植其实现；[PAI多模态管理](https://help.aliyun.com/zh/pai/multimodal-data-management-and-usage)仅参考独立状态/管理维度；[ModelArts标注管理](https://support.huaweicloud.com/intl/zh-cn/usermanual-standard-modelarts/modelarts_23_0347.html)参考全部/已标注/未标注视图；[EasyDL未标注导入](https://aca.bce.baidu.com/doc/EASYDL/s/Wk38n312s)参考原图直接标注。商业实现、性能和许可不推断为本系统能力。

组件文档：[Panzoom](https://github.com/timmywil/panzoom)、[Floating UI](https://floating-ui.com/docs/getting-started)、[Lucide](https://lucide.dev/guide/lucide)。

## 验证与限制

所有截图位于images/material-library-zip-20261106；before来自独立548只读基线的真实Chrome，after来自实现页面，均为隔离夹具而非设计线框或生产数据。ZIP真实API浏览器使用临时Uvicorn/真实SQLite/实际压缩文件；模型未调用。

隔离20万真实SQLite元数据基准：每页48，21次采样，首页P95 6.996ms，深页33.524ms，来源+标签8.371ms，名称8.378ms。Network/DOM夹具模拟20万总数，只渲染48张，勾选至下一帧P50 16.6ms/P95 17.1ms，DOM身份保持。后者不是20万真实图片网络或整机性能，具体采样文件同目录。

明确NOT VERIFIED：生产20万真实图片/远端存储/P95、4070真实视觉模型、A800训练、长期多人并发及真实触控硬件。浏览器触控模拟和真实Chrome不等于生产实机。

兼容边界：旧直传POST `/import/jobs` 的前置扫描失败仍返回400且不创建任务；正式Uppy及原上传回退均复用`/import/uploads`持久链，本轮已验证损坏及方法9失败任务可重新打开。未为不用的旧入口新建恢复引擎。历史批次FILTERED范围保护及“导出选择清单”的边界如上。

本地完整数值、准确提交及GitHub CI状态以最终交付记录为准，未运行的验证不称通过。


### 最终本地验证记录

- 后端聚焦273/273：原审核/任务/负池/WeVisOne/难样本及新素材筛选、旧schema5/6、原选择原子性、ZIP报告。
- ZIP安全/格式/分类聚焦137 passed、1 skipped（原显式跳过条件保留）；集合与273有重叠，不合计为独立总数。
- Node24全量1555/1555；Python编译、JS语法及diff检查；新vendor18项、原Annotorious16项、Uppy87项校验。
- Chrome新素材/PoC/旧审核闭环11/11，原素材22/22，ZIP40/40。后两组更新授权UI对应选择器，保留GT、重复提交、生命周期、缓存和恢复断言。
- 实际回归修复：新原图缺批次元数据、复选框焦点拦截左右导航、图片onload覆盖GT读取失败、长列表底栏不可见、标签搜索宿主缺失、单图负池菜单失效、旧批次冻结为空风险。
- 原WIP和其他工作树未覆盖；独立548基线克隆仅用于before截图。没有生产写入、训练、转换、部署、main合并、tag/release或force push。
- 准确549 SHA/远端HEAD与CI终态在推送后独立核验，不能借用548绿灯。

最终展示真值补测：素材列表摘要未标注而正式GET已标注时，详情状态和编辑按钮立即采用正式接口状态；RED复现后Chrome PoC2/2及Node几何1/1复验，未改GT。后端独立只读审查未发现阻断问题。


### 2026-11-07 / 42.24.550 准确CI入口回归修正

549提交c9dd99cc674abbfc3e38f86cc662917955b73943首次CI出现Material Upload Chunking失败。准确job127992759040日志：五文件真实Uppy用例仍以旧精确名称“上传”查找素材库按钮，60秒超时；本轮产品已明确改名“上传素材”。仅更新对应选择器，保留真实五文件单POST、失败项隔离、任务回执和不创建GT的原断言。不修改上传实现、超时门槛或业务安全校验。

同时在原Frontend Runtime Stabilization工作流增加新vendor字节/NOTICE/manifest校验，避免只在本地校验。550产品实现与549一致；准确550 SHA CI必须重新核验，不能以549已成功的其他检查替代。生产未动。

同一旧选择器也使549的ZIP Import Durable Runtime真实浏览器41/43（另两项相同上传入口）失败；其Ubuntu/Windows合同与后端持久化均成功。已核对准确日志，未把该错误称为既有问题。550本地Material Upload Chunking原命令3/3，版本/展示Owner12/12；ZIP原完整CI命令本地复验43/43通过。


### 2026-11-07 / 42.24.551 原素材工具入口回归

549前端工作流最终cancelled不是可忽略噪声：两个Chrome分片因重复等待缺失按钮达到20分钟上限。真实根因是新素材页头遗漏原 `.data426-head .row` 宿主，原decorateDatasetControls414无法装载既有“重复与异常素材”和“智能质量分析”。已恢复原宿主，仍由原decorator/审计Owner提供入口，不添加第二套审计。

另外，旧Annotorious连续标注测试仍先点击已退役的批量模式按钮，现改为常驻复选框+固定人工标注栏；ZIP导航用例仍等待已按任务移除的整理按钮/自动整理，改走原四动作的明确人工/质量入口。GT、100/300框、20图连续修改、响应不确定、防重复POST和精确范围/导航清理的原断言均保留。新版入口丢失是本次引入的问题，未称为旧问题或单纯CI抖动。

550本地提交78974f6910ae2f305fa7e4914035b053daa92508因GitHubHTTPS连接失败尚未单独推送，551修复验收后将正常快进推送整个提交链。原CI运行终态46success/2failure/1cancelled，不能称549全绿；最终新SHA CI重新核验。

551本地新增复验：原素材完整性/智能审计15/15，完整Annotorious23/23，完整导航28/28，新素材布局与组件6/6；后者与先前11有重叠，不累加冒称独立用例。所有原GT、框数、堆采样、连续20图、事务范围和生命周期断言保留。

发布传输预案：GitHub HTTPS smart-HTTP多次连接失败时，使用现有Git认证在内存中调用GitHub官方Git Data API上传同一Git对象；逐个校验blob/tree/commit SHA与本地完全一致，先核对远端HEAD，最后force=false快进。若任何SHA或远端基线不一致立即停止，不重建/改写本地历史，不使用第三方代理、不关闭TLS、不输出或落盘凭据。最终实际是否成功以交付报告为准。


### 2026-11-07 / 42.24.552 全局项目维护入口收口

551准确CI终态40success/1failure，Frontend前端合同与分片1/3成功，分片2为115/116；唯一剩余用例等待旧“批量操作”再找项目清空入口。新版确实遗漏了该既有入口。现全局“更多操作”使用原Floating UI菜单，清空动作直接委托原clearProjectMaterials61→runMaterialBatch62(DELETE_INDEX,scope=PROJECT)。普通用户可进入原影响预览、项目名确认与冻结任务流程；无第二套删除Owner，无实际生产数据操作。

对应浏览器测试改走新菜单，并额外验证原Owner的操作与PROJECT范围参数；同文件真实38图准入、正式GT、失败/部分删除和精确项目名安全断言不变。移动抽屉回归改用更多操作并验证Escape焦点回收，不恢复退役批量模式。

552本地复验：完整训练准入/删除治理8/8、全量前端1556/1556；移动核心入口及三视口素材库组合6/6。移动核心入口旧算法按钮选择器同时兼容既有“新建本地算法”名称，未修改算法业务；新菜单Escape恢复焦点纳入原前端CI。
