# P1O–P1R AI标注与审核产品化

基线6e3c61a8b83e745e5e826ace1da107e7c9bbb299，唯一分支feature/external-algorithm-publishing；实时fetch、干净工作区及GitHub22/22 success已核实。前序实际素材/Picker/回执/离线代码与验收资料已读取。VERSION42.24.592保持。用户明确连续授权A–F，不再逐阶段等待确认。

## 原Owner及最薄方案

| 领域 | 原权威 | 本轮改动 |
|---|---|---|
| AI任务 | v60 AnnotationTaskService / 原TaskRepository | 原GET的reader_view安全DTO，Vue游标列表/详情/失败分页；创建、差量retry与导出回原详情Owner，不自动推理 |
| 候选审核 | app.js最终reviewAiLabel427 / CandidateStore | 原state.ai60Review持有筛选、选择、冻结、修订和提交状态，Vue仅订阅有界snapshot并委托公开动作；原ai-review-route不变 |
| 人工候选编辑 | createAnnotoriousEditor / annotation-geometry-adapter / 原ai60Edit | 薄AnnotationEditor只DOM和生命周期，原factory与回调共享，原boxes/history/dirty/save不复制 |
| 正式GT/消歧/转池 | 原decisions(commit_selected)/AnnotationRepository/原歧义预检/NegativePool | 复用原分批/回执/锁/源SHA/CAS；只修本轮发现的未知结果持久化与身份缺口，不新建写服务 |

Vue Router仍内存模式；原登录/API/PageRequestScope/NavigationStability/PollRegistry/审核hash路由唯一。旧页默认保留、opt-in激活。没有新任务调度、推理、候选库、GT库或审核队列。不存在安全表达的操作交原Owner，不能绕过。

## A–F实施清单

- [x] A：实时HEAD/前序CI及任务、候选、几何、正式提交、转池、retry实际合同核查。
- [x] B：v60安全任务读投影及Vue任务中心；未知统计/索引准备/失败分页与原入口。
- [x] C：原审核presentation adapter、Vue沉浸式工作台、Annotorious薄组件、候选草稿与刷新恢复。
- [x] D：原冻结/跨页排除/消歧/GT分批回执/已入库禁选/转池恢复；发现缺陷先RED再最小修原Owner。
- [x] E：真实离线Annotorious Chrome编辑、1920/1366/768截图、生命周期/有界性能、离线构建及规范交接。
- [ ] F：分阶段正常提交推送、准确SHA自动CI及制品实物包含/字节/CRC核验。

## 强制第三方复用规范

成熟组件优先复用，Annotorious固定3.9.5，从static/vendor共享加载一次。Vue不引入第二份npm运行时，不新增SVG/Canvas/Pointer编辑、坐标换算、撤销/草稿库。已有adapter的缩放/平移及XYXY/EXIF合同保持。隐藏框用原适配按ID合并回完整框，保存前原flush；autoSave仅客户端事件，草稿PUT和正式GT提交分离。Uppy/分块上传、已有图表和复杂控件同理；许可证/NOTICE/source map/校验不删除，不使用CDN，不升级latest。

## 必要验证及安全边界

仅本轮API、类型/构建、少量Node和真实Chrome。真实官方插件draw/move/resize/reclass/delete/zoom、保存草稿重读、隐藏框保全、切图/卸载无残留与旧页编辑；审核冻结/排除/已入库禁选/明确确认/未知回执。所有写测试为临时库/合成任务，不运行真实模型、训练、转换/生产SDK。原真实retry只交旧入口；隔离差量合同不等于现场推理验收。禁止生产A800/4070部署、重启、GT/模型/素材/密钥变更、调度lease变更、main合并、force或Release。

## 已发现需处理的原合同缺口

原public任务/候选包含非白名单诊断且统计回退0，故仅v60任务读视图补安全nullable DTO；原默认保持。原已选直接入库每批request_id未持久保存，网络未知后刷新可能失去恢复身份；激活Vue写入前必须复用现有ai-review-operation键修复，不能换新请求重提。原歧义预检已有客户端有界算法，没有独立服务端预检，不在Vue复制。

完成本轮后停止，不全面替换正式GT编辑器、不迁移数据库、不做硬件适配和全仓重构。现场模型质量、4070/A800及生产离线部署单独标记未验证。

P1O定向API/DTO4、Node2、Chrome1通过；原任务列表202索引态、未知统计、失败12张按需、403/切项目迟到及旧管理不发POST已验证。Annotorious离线16件资源与许可证校验通过，几何/原Owner/路由/新presenter定向Node39通过。真实插件初验暴露同identity快照触发新array watcher循环，按多source watch修复，继续真实交互验收。只读原图放大复用原MaterialPresentation/Panzoom，不另写缩放内核。

## 本地真实业务闭环

原入口脚本`frontend/tests/real-ai-review.acceptance.mjs`配合独立`tools/test_vue_ai_review_server.py`（loopback8030、原auth、强制新tempDATA_DIR、lifespanoff、SDK禁止）已通过：官方离线插件真实创建/移动/resize/改类/删除/撤销/zoom/pan；候选PUT后HTTP核对坐标，正式GT仍空；切图销毁、hash刷新恢复、原旧工作台再次编辑保存revision2，只有明确approve后隔离GT出现3框。每文档官方script仅一份，JS/CSS200、pageerror=[]。六张1920x1080/1366x768/768x1024审核/编辑截图位于test-results/p1or-real-entry/，均已实际查看。

`frontend/tests/real-ai-workflow.acceptance.mjs`配合独立workflow server（loopback8031）已通过：24+7跨页，冻结31排除1，明确确认后30张GT、未选中1保持；刷新和committed历史均禁选，全筛选余1。让真实POST已完成再丢弃响应，刷新读取原packet、GET-only查回执恢复，总POST仍1。另任务有框/zero转池预检/确认/回执/undo保持原图及GT；原auto/manual消歧预检各可处理1/保守跳过1，仅二次确认后入库。九张三视口截图与receipt.json位于test-results/p1or-workflow/，已查看。全部是隔离合成候选/本地图，不是生产模型推理。

失败差量retry没有在浏览器主动启动；定向原API验证同task只补failed/未处理、成功与草稿保护。Vue通过原详情供人工进入retry/完整导出，不新增取消/重试/模型执行接口。定向Python12/12包含新reader4、草稿CAS、冻结过期、所选提交、持久已入库防冻结、转池回执/undo/故障恢复、原retry与自动草稿不可冒充人工确认。

## 实际修复和回退

原已选与歧义入库每批同原ai-review-operation键持久完整body、kind、project/task、expected_count；无法存储即不POST。成功必须committed_selected/applied_images精确对应。未知/202/409保留原packet，lookup只GET且不误用整批结束；不换新request_id自动重发。原转池也增加写后回读核验，不能吞存储异常继续POST。旧任务、GT锁、CandidateStore、review-selection、sourceSHA/CAS和正式journal不改。

编辑器context稳定，late handle仅释放旧实例；factory失败无有效handle不显示ready。未决定accepted保留null，不压为false伪拒绝。原read/write动作绑定project，原request page epoch追加项目栅栏。原编辑渲染仅接受显式DOM refs，保存/undo/hiddenboxes仍原Owner与原geometry adapter，没有第二套坐标或撤销栈。

第三方复用长期规则见FRONTEND_THIRD_PARTY_REUSE_POLICY.md，并已写入AGENTS与OwnerMap。真实交互复用Annotorious3.9.5；原图只读放大复用MaterialPresentation/Panzoom；浮层/图标沿原FloatingUI/Lucide。没有复制npm运行时/升级/删除license、NOTICE、map；`verify:annotorious`16件校验通过。SFC源码通过.gitattributes固定LF，使Vue生产scope哈希在Windows和LinuxCI有一致输入，不改变vendor字节。

仍须准确SHA CI、最后构建/ZIP与制品实物比对；现场WeVisOne、生产GT/素材、A800/4070及目标机断网安装未验证。

## 最终定向核验及复现

最后类型检查/Vite构建通过：1701模块，JS933.62kB（gzip247.46），CSS133.37kB（gzip20.01）。新任务/真实编辑器两个Chrome用例2/2，相关Node43/43，隔离Python12/12（8项既有FastAPI弃用告警）。本地入口三资源统一42.25.614；未变化的算法/Picker模块仍613，VERSION.txt不改。新Chrome真实官方插件用例保证同identity新快照不会重挂载、切图/卸载销毁和无HTTP写入。

复现先在隔离终端运行 `python tools/test_vue_ai_review_server.py`，另一个终端进入frontend执行 `node tests/real-ai-review.acceptance.mjs`；workflow同理使用 `tools/test_vue_ai_review_workflow_server.py` 和 `frontend/tests/real-ai-workflow.acceptance.mjs`。服务仅loopback、tempDATA_DIR，脚本内隔离账号与合成候选，不可连接生产。真实入口使用原登录会话及 `?vue_ai_tasks=1&vue_ai_review=1`，原AI标注页点击Vue任务中心，任务详情进入审核；旧审核按钮随时回原Owner。关闭插件只释放该页HTTP/事件/实例，不取消后台任务。

UI为可收起检查区、稳定网格key、底部固定操作及中性灰层次；1920/1366/768均核对截图和溢出。列表游标、12条失败分页、24张候选、100条有界snapshot及原冻结ID保持；无新增poll、全任务下载或全部GT扫描。没有执行数万张生产规模压测，隔离数据不代表现场吞吐。

正式离线包必须包含原Git源码及 `static/vue-catalog/` 两个构建文件，同时保留Git内 `static/vendor/annotorious/` 16件资源/清单/许可证。既有Frontend Runtime CI使用准确SHA命名的vue-catalog-preview制品上传JS/CSS和Chrome证据；交付再下载校验ZIP CRC与本地构建字节。构建成功与ZIP包含证明不等于目标机断网安装完成。

## 后续边界建议（本轮不实施）

后续可先将已白名单的annotation reader投影从app.py小范围Router抽出，注入原AnnotationTaskService/CandidateStore，不另建Repository；审核展示适配继续独立于原写Owner，只有有等价合同验证时再逐段抽取。正式GT/转池提交日志、任务执行/lease、WeVisOne协议和数据库保持原权威。保留linux/amd64、linux/arm64及CUDA/Ascend等真实异构能力的服务端证据展示，本轮无硬件适配。下一阶段优先安排获授权的现场只读与断网安装验收，不自动进入其他迁移。

## 具体HTTP合同与写入变化

- GET `/api/v60/projects/{p}/annotation-tasks?reader_view=true&limit=20&cursor=...&status=...&q=...`：原游标列表；GET同路径`/{task}?reader_view=true`任务详情；GET `/{task}/candidates?reader_view=true&filter=failed&limit=12&cursor=...`失败页。新增可选只读DTO，不新增HTTP路由/Repository，原get_project和task归属校验保持。GET沿原Owner可能启动搜索/统计回填，不宣称原系统完全无持久副作用。
- 原审核GET `/{task}/candidates`、`/candidates/{image}`及`/diagnostics`；PUT `/candidates/{image}/draft`仍只写CandidateStore，原revision/request_id/SHA校验不变。
- 原POST `/review-selection`冻结范围；POST `/decisions`（commit_selected=true）正式GT，GET `/decisions/by-request/{request_id}`回执；原POST `/negative-transfer-preview`、`/negative-transfer`，GET转池request回执和POST `/negative-transfer/{request_id}/undo`均继续由旧业务Owner执行。
- 原 `/retry`、任务创建、完整诊断导出继续交旧任务详情Owner，Vue不新增执行接口。原图仍走v61授权content/thumbnail与原MaterialPresentation。

没有新增服务端写路由或数据源。原浏览器ai-review-operation记录增加kind/project/task/expected_count和写后回读；原ai-review-transfer记录同样失败即阻断POST。它们是原未知操作恢复键的强化，不是第二个草稿库。Vue新增Owner限于组件展示与DOM实例资源；选择、草稿、撤销、正式入库和任务执行的业务Owner均未转移。
