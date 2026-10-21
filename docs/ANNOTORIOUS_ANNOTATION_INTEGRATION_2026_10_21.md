# Annotorious v3 人工标注工作台正式集成（2026-10-21）

本文件是本专项唯一需求、设计、进度、问题、验收与接续依据，不与页面启动综合治理或GT素材生命周期专项混写。用户明确要求先完成综合治理补充验收，再单独实施本专项；前者最终 `4fcbcfc804748d37a07eaeb8b8ed960539d10b91` / VERSION `42.24.371` 已独立21/21 Actions、55/55 Checks、Chrome140/140通过。

## 1. 需求基线、授权与当前起点

仓库 `jorsamj/aixunlianpingtai`，唯一长期分支 `feature/external-algorithm-publishing`。开始已通过GitHub只读API重新读取远端：与本地4fcbcfc8一致，工作树干净；已阅读AGENTS、CURRENT_STATE、旧标注/清洗交接及现行工作台/保存/Repository。其他原D盘WIP、工作树和会话不覆盖。旧2026-09-25文档冻结VERSION42.24.0/近全屏等是历史时点规则，不能覆盖本次用户允许版本更新及现有Modal合同。

允许必要前后端、依赖/本地静态资源、隔离测试、文档和正常提交/推送。禁止生产部署、生产GT/数据库/素材修改、迁移执行和真实训练；不访问生产，不增加物理图片副本。前轮HTTPS Git短时中断后通过GitHub连接器以expected旧SHA、force=false快进发布相同文档树；本地未发布80615656保留于codex/governance-supplement-doc-local-80615656。后续仍优先普通Git、重新核对实际远端，禁止重写共享历史。

| 编号 | 正式需求 | 验收重点 | 状态 |
|---|---|---|---|
| ANN-01 | 官方Annotorious v3替换自研矩形画框内核；先隔离PoC再正式入口 | 非Demo交付，不叠加双层，不依赖私有API | 进行中 |
| ANN-02 | 矩形新建、多框选择/移动/缩放/改类/删除/取消 | 原图像素，临时框与正式编辑框区分 | 已完成待验收 |
| ANN-03 | 选择/编辑、画框、平移、显示/隐藏及分类过滤 | 隐藏不改GT且不可误编辑 | 已完成待验收 |
| ANN-04 | Del/Backspace、Esc、Cmd/CtrlS/Z/ShiftZ、H、1–9、左右键 | 仅激活工作台、非输入；Esc先取消画框/选择，销毁释放监听 | 已完成待验收 |
| ANN-05 | Fit、100%、按钮/滚轮缩放及平移 | 变换后绘制/移动/缩放无坐标偏移 | 已完成待验收 |
| ANN-06 | 单一GT↔ImageAnnotation/RectangleGeometry转换层 | 稳定Box ID、class/code/来源审核元数据、版本/SHA，不漂移，不造历史证据 | 已完成待验收 |
| ANN-07 | 沿用正式GT API及AnnotationRepository | expected_version/source_content_sha256/reviewed_label_codes、409不自动覆盖、权限/身份保持 | 已完成待验收 |
| ANN-08 | 删除全部框可存待标注；明确无目标确认才是负样本 | 空GT与confirmed_empty分离，真实审核范围；材料投影/训练准入/审计一致 | 已完成待验收 |
| ANN-09 | 简体中文UI、中文名+英文Label Code、原队列/画布/工具/类别对象布局 | 原Modal/Tooltip复用、合理边界和滚动、不新增管理器 | 已完成待验收 |
| ANN-10 | 连续标注、预加载、保存继续及Dirty/自动保存唯一Owner | 保存成功后切图，失败/冲突不丢修改，保存中关闭/迟到/切项目安全 | 已完成待验收 |
| ANN-11 | AI候选经人工确认编辑后写GT；保留来源/审核范围 | 未确认预测不是正式GT，不建第二候选/审核/标签/素材体系 | 已完成待验收 |
| ANN-12 | 精确锁依赖、许可证、本地离线资源、回归/截图/最终SHA CI | 无CDN/React整体改造/第二打包体系，保留版权 | 进行中 |

## 2. 接手代码、根因与复用边界（审计已完成）

- `static/app.js`存在多代renderAnnotator/drawBoxes/bindAnnotationEvents定义；实际末端工作台由稳定shell与`createAnnotationWorkbench`管理加载队列，pointer版编辑覆盖早期mousedown版。先按最终赋值和调用链确认Owner，不能只改最早同名函数。
- `static/modules/annotation-workbench.js`负责请求token/cache、dirty切图保存；`annotation.js`负责素材预览投影。`saveAnnotationCore420`和末端`saveAnn`为正式保存链，上一专项已补单flight、30秒、项目/图片/ann/SHA归属和未知结果GET核验；本轮必须继承，不能回退。
- 接手基线`app.py.AnnotationSave/save_annotation`只允许annotated/confirmed_empty；删除最后框被强制确认无目标，这与ANN-08的新要求冲突。`platform_core/annotation_repository.py`的STATES/现有SQLite约束和_content_payload**已经支持unannotated且清scope**，初审不需要新表或生产迁移；仍须逐链验证材料投影/训练准入/审计。
- 原Snapshot/Test冻结证据、AnnotationRepository、标签、AI候选审核、Modal Stack、Tooltip、Loading、API Client和队列继续使用。只退役旧编辑内核专属画框DOM/命中/拖拽/键盘，不删卡片或只读图片预览的业务overlay。

## 3. 依赖及技术方案（已选框架内的实现选择）

官方源实际核验：`npm view @annotorious/annotorious version license dependencies --registry=https://registry.npmjs.org` 返回 **3.9.5 / BSD-3-Clause**，不是附件旧核验3.9.4。固定实际兼容验证通过的精确版本，不使用latest运行依赖。官方[API](https://annotorious.dev/api-reference/image-annotator/)、[事件](https://annotorious.dev/api-reference/events/)、[数据模型](https://annotorious.dev/api-reference/image-annotation/)与[原生JS集成](https://annotorious.dev/guides/annotating-images/)为公开合同来源。

方案：现有原生ES Modules与稳定workbench中增加一个画框kernel适配模块、一个纯GT转换层；采用官方发布的本地JS/CSS制品，可复现复制/校验，按需加载，不新增全站打包系统。替代方案是新建bundler整合或React重写，成本/Owner扩散大且用户未要求；CDN不满足离线要求，均不选。需实查发布包是否自包含、运行依赖与内嵌代码版权，不能仅凭根包BSD推断所有依赖许可。

GT仍由原state/保存API/Repository权威维护，第三方只编辑客户端矩形。既有ID和全部需要的metadata通过转换层保留，新框才分配新ID；验证坐标有限、边界、正面积，未知类别明确保留/纠正，不能静默改成第一类。原图像素与Viewport变换分离；PoC必须实测变换后坐标及move/resize。公开setAnnotations/setSelected/drawing方法及事件用于同步，不用私有store。实际3.9.5的setFilter仍是警告占位，改用原GT的可见子集投影；隐藏框不进入组件编辑集合，单框事件合并回完整GT，不能用可见集合覆盖原GT。

空框新合同：明确请求`annotation_state=unannotated`可删除错误GT并回到待标注，清空负样本审核scope；`confirmed_empty`仍必须显式操作且有真实审核类别。非空框仍annotated。保留版本/SHA/不可用素材/标签有效性及服务器来源恢复；旧调用缺明确空状态继续安全拒绝或维持既有兼容规则，不能悄悄变成负样本。实际方案以隔离API/Repo/准入测试确认，不把初审写成实现。

## 4. 分阶段计划与门禁

> 执行采用superpowers:subagent-driven-development；每项先RED、最小实现、定向GREEN、合同与质量审查。用户已确认组件与业务规则，无需重复设计审批。

| 阶段 | 工作与文件 | 优先级/状态 | 完成证据 | 剩余/风险/Commit |
|---|---|---|---|---|
| A | Owner/GT/依赖许可证审计；本文件、package.json/lock、本地资源 | P0 已验收 | 最终Owner审计、官方3.9.5发布资源与16项版权/离线校验 | Commit待本阶段整体提交；生产不访问 |
| B | 纯转换层+本地官方组件隔离PoC；Node与真实Chrome | P0 已验收 | Node24转换/资源9/9；真实Chrome PoC2/2通过（8.6秒） | 正式集成回归继续；尚无本专项提交 |
| C | 原GT保存空待标注合同、材料/准入/审计回归 | P0 已完成待验收 | 后端定向100通过（8文件，0失败0跳过） | 前端三态payload/当前负样本审核范围/dirty保留已接线，最终回归进行中；无生产迁移 |
| D | 原工作台及AI候选新kernel、模式/键盘/过滤/视口/队列/Dirty；退役旧监听 | P1 已完成待验收 | 新接线2项RED→GREEN；公开API/候选草稿/取消19项定向通过 | 不叠加双内核；继承保存deadline/未知恢复 |
| E | 编辑/数据/生命周期、四尺寸/逐张20图/100/300框/内存截图 | P1 已完成待验收 | 本地53个独立Chrome场景通过；真实截图与采样已归档 | 生产现场未验证；最终SHA CI待核验 |
| F | 定向Python、完整Node、真实Chrome、许可证/离线复现、VERSION/正常推送/最终SHA CI | P0 进行中 | Python175、Node1192、Chrome53独立场景及16项资源核验通过 | 提交/正常推送与准确SHA CI；生产仍禁止 |

## 5. 问题、测试、生产条件与接续

新问题发现即记录根因/影响/修复/实际RED→GREEN，不把尚未验证写已修复。旧空保存规则与ANN-08冲突已完成前后端最小实现；后端100项、保存/审核/装饰52项定向通过。官方RectangleEditor事件中bounds可能滞后一帧，转换层验证bounds有限但以x/y/w/h计算真实端点，新增RED→GREEN。PoC先后因资源尚未生成、选择editable参数、触摸分支手柄类名以及SVG零宽line的可见性判定失败；修正夹具选择公开API及真实可见按钮，保留全部真实pointer移动/缩放/变换后端点断言，最终2/2通过。

实际阶段证据：后端100通过、Node24转换及离线资源9通过、真实Chrome隔离PoC2通过。正式工作台20个功能场景通过（1.2分钟），含20张连续、100/300框、原图640/800/1920/3840、未知标签、负样本分离、409/422及未知保存GET。之后强化布局和取消初始化保护，尚需最终源统一回归；不能沿用中间绿色宣称最终验收。前轮140/1142/55是继承基线，不是本专项验证。计划复用material-workflows、annotation-workbench、annotations/provenance/negative/scope/repository/prepare等现有测试，必要新增真实官方kernel PoC与集成场景，保留安全断言。

下一步：实查官方3.9.5发布资源与许可证 → 单一adapter RED→GREEN → 隔离PoC真实draw/select/move/resize/坐标往返/cleanup → 才正式接入；后端空待标注契约可独立审计/TDD，激活前同验。禁止新GT库、标签库、任务/审核/Modal/Tooltip/Loading/自动保存Owner；禁止生产、真实训练、CDN依赖及改写共享历史。全部阶段和最终SHA/CI须持续写入本文件，后续会话从本文件、现有代码和Git History继续。

### 5.1 实际本地资源和授权链

固定官方3.9.5及Lockfile，官方发布UMD/CSS/source map纳入static/vendor/annotorious；tools/vendor_annotorious.mjs离线复制并逐字节核验、SHA256清单及许可证。根包BSD-3-Clause、依赖BSD-2-Clause/MIT/ISC，source map确认内嵌Svelte4.2.20，原版版权文件与NOTICE保留。构建首次因ISC未在允许集合中失败，实读quickselect许可证后补入合法清单；不忽略未知许可证。16项资源/声明可离线重建，.gitattributes限定这些制品与声明不做换行转换。Node24.19.0完成资源/转换测试；初装使用旧Node20产生engine警告，后续Lockfile及正式测试使用Node24，package engines明确受支持22/24/26+，CI原有24复用。

## 6. 正式接线、退役及审查记录（最终验收进行中）

- 新`annotation-geometry-adapter.js`为唯一纯转换层；`annotorious-editor.js`只管官方图层/事件/视口，业务GT/history/dirty/save仍归原Owner。官方3.9.5 `autoSave`仅指客户端生命周期事件，平台正式持久化仍走原30秒单flight、未知结果GET、CAS/SHA链。
- `main.mjs`公开一个factory；`app.js`稳定shell异步初始化、项目/图片/URL/generation/AbortSignal归属、立即Loading及资源失败重试，关闭或身份改变销毁，旧请求不得复活。旧mousedown、全局mousemove/up、pointer自研框、专属全局快捷键、`.box424/.handle424`及候选`.ai66-edit-box/.ai66-edit-draw`已退役，相关CSS清除；素材卡片/报告只读overlay保留。
- 官方更新可能延迟1000ms，`flush()`在pointerup及保存前读取公开getAnnotations同步真实几何，避免立即保存提交旧坐标；相同几何不重复历史/Dirty。原平台撤销栈唯一，修正旧redo通过pushHistory误清redo栈的问题。
- 隐藏和分类只投影可见子集，单框编辑合并回完整GT；隐藏不可编辑/删/坐标旁路，恢复不改GT。UI提供全部隐藏/恢复、指定类别及逐类别显示开关。所有缩放仅natural pixels world变换，禁止旋转，隐藏官方rotation group并由adapter拒绝rot非零。
- AI候选窗口复用同一factory，原`ai60Edit`仅候选草稿与一个草稿历史；稳定已有ID，缺ID只初次建草稿分配。保存候选仅写原review.edits/decisions，最终仍由原completeAiReview60→durable commit，取消不写正式GT。
- 独立read-only合同/质量审查发现P2：官方selectionChanged延迟，刚点选立即Esc读取旧cached ID可误关窗。实际Node复现`officialSelected=[a],cached=null,escapeHandled=false`；改读公开getSelected，补立即Esc/Delete及迟到取消选择回归。未发现其他确认的CAS/SHA/元数据或权限回退；这不是生产验收。

### 6.1 实际失败及修复留痕

| 问题 | RED证据与根因 | 修复/关闭证据 |
|---|---|---|
| 空GT被强制当负样本 | 新API测试9项RED；旧负样本继承positive scope | 显式unannotated清scope，本次confirmed_empty只接受本次reviewed codes；后端100通过，前端定向52通过 |
| 官方bounds滞后 | 新adapter旧bounds+新geometry回归先RED | 以有限有效geometry端点为准，稳定未编辑端点精确保留；转换测试通过 |
| 变换后立即画框偏移约3.26px | Chrome fit/wheel/pan→立即draw目标100实际103.256 | 清除world旧`.ann-stage transition:transform .12s ease`；原精度断言通过，未放宽阈值 |
| 移动端横向裁切/对象卡过高 | 375截图复核推翻弱布局绿色；强化canvasLeft实际-166.75；后续draw在视口外 | 工具分组限宽、触屏紧凑换行、正确内容滚动和fit定位、对象行不拉伸；最终截图/强化断言仍统一复核 |
| Loading hidden仍可见 | 截图显示已成功组件仍有Loading与retry，旧作者display覆盖原生hidden | 只在编辑器反馈区显式`[hidden]{display:none!important}`，资源加载真实完成后隐藏；错误/超时可重试 |
| 旧源码守卫 | 首全Node1181：1177通过/4失败/0跳过 | 更新已退役DOM/双态空保存合同；保留identity/权限/单Owner；UMD单行误将fetch(w)跨4121字符匹配到后续http文档，新检测真实URL参数并加正反用例；定向22通过，待最终全量 |
| 首前端全Node命令 | Node24传tests/frontend目录报MODULE_NOT_FOUND | 展开*.test.mjs后执行；不记作产品失败或通过 |

### 6.2 中间实测与截图

`docs/evidence/annotorious-2026-10-21/`保存四分辨率真实Chrome截图及100/300框样本。原测100框Fit按钮墙钟89ms、406官方SVG节点、整页heap13,880,027B；300框162ms、1206节点、heap17,668,729B。均为隔离真实组件/真实任务库操作样本，不是生产首屏，不是独立编辑器内存，也不能证明无泄漏。布局和资源保护后还要最终重跑；历史采样JSON明确测量范围。

### 6.3 当前实际修改与剩余

后端：app.py AnnotationSave/save_annotation、API空状态测试；无需新数据库/迁移。前端：app/main/styles/index必要cache、annotation-workbench/negative-samples、两个新模块、现有Node/Chrome Owner定位迁移及新真实交互测试。依赖：package/lock、vendor脚本、16项本地制品/许可证和限定.gitattributes。CI只在既有frontend browser集合增加本专项两个spec，在既有annotation合同集合补空状态/准入/Snapshot，不新建并行体系或扩大无关GPU工作。

当前剩余：AI候选真实审核、保存中关闭/晚回新Modal、项目切换/快速重开、加载资源失败重试和更严格内存生命周期回归；最终四视口截图复核；最终Python/Node/Chrome统一验证与VERSION一次递增；提交/正常推送及准确SHA CI。本地限定验收及后续更新以6.6为准；不能借前轮4fcbcfc8绿色作为本轮结论。生产部署、正式GT/DB/素材变更仍禁止。

### 6.4 历史无ID兼容与最终回归进展

真实旧material-integrity回归先17/19通过，1例导入的Repository GT本来没有box.id，组件拒绝而旧索引DOM能显示；另1例选择到了已隐藏的rotation button。前者增加单一adapter内withLegacyBoxIdentities：仅缺ID的当前live GT按image_id+原序号生成确定性兼容ID，避开已有ID，已有ID（含数字0）与元数据不变，不更改服务器或冻结证据，不因打开触发自动保存；首次原CAS显式保存才持久化。新增Node确认确定性/碰撞/无突变/跨图隔离9/9通过；旧实际Chrome仍待复测。后者明确定位可见编辑手柄，保留真实move/resize尺寸断言。完整Node当前1192/1192、0失败0跳过；VERSION按基线一次递增42.24.372，最终缓存与CI待完整核验。

### 6.5 最终前补充验收与缺陷关闭

独立审查P2已补公开当前选择读取，真正canvas点击后立即Esc/Delete不用等待回调的Chrome通过。AI真实首drag另发现绘制模式仍留旧选框，官方只有无editor时才挂绘制工具；明确draw模式无selection/不接受命中编辑，select模式才EDIT，对象列表主动选择进入select，连续两框不再吞首drag。删除/改类、Backspace、撤销重做仍保留原GT/history/CAS。

新增资源生命周期Chrome10/10通过，JS/CSS各实际失败可重试、加载中关闭不复活、关闭保存200等待/422保留、迟到保存不关新Modal、项目身份变化fence、AI草稿不POST GT且经原decision payload（接收端为隔离夹具，无推理/生产写入）。20次开关在4/8/12/16/20次CDP GC后 documents=1/nodes=1157/listeners=110恒定；整页heap约3.92→4.37MB，属于此隔离场景未见DOM/监听增长，不声称绝对无泄漏。

统一52项Chrome首验51通过1失败，仅剩旧素材100×80/4倍缩放fixture的pointer目标：SVG stroke/交互buffer扩大可见bbox，按bbox右下偏移实际点到了背景，GT无变化；改定位真实可见官方右下circle中心，保留原屏幕宽高增长并新增GT宽高增长，真实Chrome重复3/3通过。与已通过51项为52个独立场景，不累计重复次数。新增连续20张逐张实际改类、原CAS保存并切图的强化用例，避免把仅建立20张fixture/显示队列当作完成20张编辑，待定向结果。

最终Node24/npm test1192/1192（0失败0跳过）；第一次cache递增后3项旧marker断言RED，精确同步419/negative545后通过；npm子进程PATH曾仍选系统Node20导致glob找不到，明确使用Node24 PATH后通过，CI原Node24复用。后端独立175项=空状态/GT/准入/Snapshot100 + 原AI候选/审核/任务/API75，全部通过，现有5个弃用警告各批保留，非失败。

## 6.6 代码提交前实际验收与接续（当前权威结论）

当前正式VERSION **42.24.372**，基线371一次递增；app/main/styles419，annotation-workbench595、negative-samples545及新官方模块必要cache已同步。代码、文档、测试与截图一同提交；当前状态为**已完成待验收（最终新SHA CI待核验）**，没有生产部署或生产数据变更。

| 验证集合 | 实际命令/范围 | 结果 |
|---|---|---|
| 后端GT/空状态/材料/准入/冻结 | pytest annotation_unannotated_contract / annotation_flow / concurrency / repository_scope / negative_sample_contract / training_annotation_admission / snapshots / material_annotation_lifecycle | 100通过、0失败、0跳过 |
| 原AI审核及持久任务 | pytest annotation_candidates / annotation_task_service / annotation_runtime / annotation_task_runtime / persistent_ai_annotation_e2e | 75通过、0失败、0跳过 |
| 全前端Node | Node24.19.0 PATH + npm test（显式frontend/*.test.mjs） | 1192通过、0失败、0跳过 |
| Chrome正式/隔离/旧回归 | annotorious-poc2 + workbench22 + lifecycle10 + material-workflows11 + material-integrity-governance8 | 53个独立场景全部通过；统一52首验51通过1旧bbox目标失败→该例真实句柄+GT尺寸增强3/3复验；随后3项强化（其中新增1）通过，不累计重复次数 |
| 离线发布资源 | Node24 tools/vendor_annotorious.mjs --check | 16项制品/声明逐字节通过 |
| 版本/基础检查 | build_identity --check-version-file VERSION.txt、JS syntax、git diff --check | VERSION372、全部通过 |

完整浏览器矩阵：实际draw一框/连续两框、select/edit/move/resize/reclass、Del及Backspace、撤销重做、Esc临时绘制与即时选择、H、1/2类别键和左右切图、隐藏全部/逐类/指定类别、input焦点保护；GT原ID/无ID兼容/元数据/未知标签、保存重开/1000次纯转换无漂移、640/800/1920/3840原图、小目标/贴边、清最后框待标注与明确负样本、409/422保留、未知提交GET先核验；CAS/SHA/失效标签/Train-Val-Test/YOLO/冻结Snapshot由真实隔离API/Repository测试补证。UI逐张20图实际改类后原CAS保存与键盘切图、快速/20次开关、保存中关闭成功/失败、新Modal晚回/项目身份fence、加载Pending关闭、JS/CSS失败重试均有独立场景。实际AI候选使用官方图层、原草稿及decisions接口合同通过；隔离接收端不替代后端75项真实任务/审核持久化测试，未调用真实模型推理。

四视口1920×1080、1440×900、1366×768、375×812的图片已实际view_image复核。最初弱overflow断言未检出移动端内部裁切，后加强canvas边界/宽度、工具在视口、canvas不被工具覆盖；修复移动换行/fit滚动后通过，未将初始错误截图当最终验收。当前截图见[evidence目录](evidence/annotorious-2026-10-21/)。原100/300框样本89/162ms为中间记录，最后统一复验JSON为76/177ms（Fit按钮墙钟，非生产/首屏；SVG节点406/1206），按JSON实际范围解读。CDP20次开关节点/监听数量恒定，只支持此隔离场景无明显DOM/监听增长的结论。

生产前条件：部署尚未授权；按现有流程备份、验证本地静态制品齐全/缓存失效、生产浏览器与真实图片/大量GT、真实AI候选审核/多用户CAS及权限，且不能修改冻结证据。无数据库迁移需求；历史缺ID只在当前live文档确定性补齐并在原版本校验保存时写入，现有ID不换，生产不批处理。不另建GT/标签/素材/审核/任务库或Modal/Tooltip/Loading/自动保存Owner，不恢复旧内核。

下一步只做普通提交/推送并查**本次实际SHA**的所有Actions/Checks；失败读准确job日志修复，绿色后写本文件最终CI节、更新入口，再核验文档补提新SHA。禁止重复建设或把综合治理/GT生命周期/chipCode取消需求混入本专项。

### 6.7 首提交CI与守卫同步

实际代码提交e65ab6cb4dae4c3f53d31a98716e762399ed5d28（本地未发布a96d0197同树81e1aef5，保存在codex/annotorious-local-a96d0197）。普通Git443连接持续失败，通过GitHub连接器逐个核对65个唯一blob/67文件及完整tree完全一致，expected旧4fcbcfc8、force=false快进；共享历史未改写，本地按相同tree同步远端原始commit对象。

首提交Label Normalization Contract在Python/Node合同通过后，Permanent source guards仍要求旧双态Literal而失败（run39611132659/job119259964409）；已只把该类型守卫同步为unannotated/annotated/confirmed_empty三态，原空确认错误/审核与其他所有限制保留。完整原Permanent source guards本地执行通过；不是删除测试或扩大负样本标准。VERSION372不再递增，最终修正SHA仍须全部CI，首提交不能当全绿。

### 6.8 第二轮 CI 的浏览器夹具修正

3b0a72e8ea2f8a1d7386dd90a4c1368aabc49e6a 的 Node 作业119262539934实际1192/1192通过；Chrome作业119262540552（run39611873766）实际174项169通过、5失败，不能以API缓存中的in_progress当作绿色。四项选择/删除失败来自零位移drag仍发送8次move：官方SVGAnnotationLayerPointerEvent的点击合同为pointerdown至pointerup少于250ms，繁忙CI可能超过；改为真实mouse.click，非零拖动仍保留8步及全部选择/Delete/input保护断言。另1项300框采样在GT状态到达但异步官方图层尚未挂载时开始；补等待官方组件和准确DOM框数，不降低300框断言或扩大超时。

仅修改浏览器测试夹具，未改产品内核。修正后本地完整annotorious-workbench.spec.mjs真实Chrome22/22通过、0失败、0跳过（约1.4分钟），包含实际拖动/缩放/删除/保存和100/300框。最终提交仍须重新完成其准确SHA的全部CI；此前失败保留追踪。
