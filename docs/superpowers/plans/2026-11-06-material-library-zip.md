# 素材库、图片详情和ZIP导入实施计划

基线：42.24.548 / 4aa155ddc355b05d6f984e5f740c9540e4b81b2a，远端API已核对。用户要求按任务书直接开发；已读全部7张插图和上轮专项。只在独立克隆长期分支执行，不动其他WIP或生产。

**Goal:** 原图成功入库即可浏览并自主选择AI、人工、质量检查或稍后处理。
**Architecture:** 原素材仓储/AnnotationRepository/训练准入/候选审核/负池Owner不变。质量清洗与标注入口解耦，状态仅兼容投影，不批量改processed或clean_skipped。Panzoom/Floating UI/Lucide仅负责展示交互，原编辑器保留。
**Tech Stack:** FastAPI/Python、原生JS模块、现有48条服务端分页、原Uppy/Annotorious。

- [x] 状态和ZIP：先加RAW正常报告及GT不变量失败测试，再修app.py报告；验证现有STORED/DEFLATE/Deflate64/加密/CRC/数量安全合同，必要时补缺口。zip-import-runtime四动作独立，不追加强制整理；无schema变更。
- [x] 统一素材库：修改app.js唯一渲染Owner和material-pagination-runtime，默认全部，状态/来源/批次/日期/标签筛选在服务端；卡片一主操作和更多、框显隐、普通勾选与原批量接口，项目/筛选变化围栏；不全载20万ID/GT。
- [x] 组件最小PoC后整合：固定npm版本与lockfile，本地vendor manifest/NOTICE/hash/bytes；一个原图同层框Panzoom、一菜单Floating UI、一Lucide图标，验证清理与坐标；预览module仅是app.js现有详情的呈现，不新建业务Owner。
- [x] 图片详情：app.js旧preview函数直接delegate新呈现module；原图contain、同世界坐标变换、缩放/复位/100%、框标签开关、当前筛选页内和跨页导航；唯一关闭/键盘/触摸/模态释放，正式编辑仍openAnnotation。
- [x] 验收：先留原版真实Chrome截图；后留1920/1366/768页面/详情/ZIP截图；660x440/1280x960及窄长/EXIF坐标、失败图、旧请求、跨页范围、20万元数据48条Network/Performance证据。复跑上轮审核关键流，不重做其机制。
- [x] 交付：更新需求/设计/进度/AGENTS及四交接文件、版本与缓存。Python/API、Node全量、Chrome、依赖检查；推前核远端快进、安全commit/push，独立查准确SHA CI。4070与生产性能NOT VERIFIED。

组件选择：Panzoom预览，Floating UI菜单，Lucide按需SVG；现有Annotorious/Uppy复用；TanStack Virtual/Tabulator无实测必要暂不引入，PhotoSwipe与Panzoom重复不引入。竞品采用统一数据管理/导入与标注解耦，不照搬框架、自动负样本或商业实现。

本地验收完成，准确提交/CI终态按本轮最终交付记录独立核验；生产和4070均未操作。历史ZIP报告型批次FILTERED操作采取明确409并要求显式选择，避免扩大或空冻结，见专项限制。
