## 2026-10-24｜ZIP自动标签确认与重复窗口治理（已完成待验收）

本节为本轮唯一需求/进度/接续记录。基线9acc75f799aac4144a9ce0d52c10c5efd6e24a4b / VERSION42.24.383，fetch0/0。代码递增VERSION42.24.384，入口缓存42.25.432，ZIP bootstrap4226368/runtime4226367、view4226366。保护5944祖先、两份未跟踪训练模板测试及其他工作树；未部署/生产扫描/迁移/删除/GT写入。

### 需求、根因与实现

用户合同：服务端selecting+label_confirmation_required+external_classes才显示；同项目同job待确认周期自动一次，用户关闭不重复，确认成功所属窗口关闭，旧状态不重开/重复start；多ZIP文件名/顺序明确，其他上传继续，刷新从原任务中心手动恢复；业务弹窗不被覆盖，不新增poll/第二流程。

真实根因：①uploadBatch/render依赖旧zip411节点，新Uppy没有；②confirmLabels成功后reconcile再open，可恢复旧进度窗口或切下一任务，缺少展示归属；③完成回调原有280ms自动打开“本次导入素材”；④共享上传层交接后若仍登记为上传窗口，首个确认关闭会误抑制其余ZIP；⑤原Modal底层节点会复用，仅节点相同不能证明还是原确认窗口。

最小实现：原ZipImportRuntime持有项目/job/窗口及内容身份、已展示/主动关闭/提交记录；sessionStorage仅保存本标签页UI显示记忆，原localStorage start intent保留服务端已受理凭据（含终态，forget原接口清理）。无第二任务库或轮询。Uppy只注册原上传层，扫描真实就绪后销毁视图并通过原Modal Stack交接；不取消原传输。上传层交接注销、同批其他候选仍保留。存在其他业务窗口则原poll后续再展示；手动任务中心打开先核验原detail API。成功start回执立即关闭本job原内容仍存在的所属层，随后reconcile；新业务窗口复用节点也不会被误关。已受理detail优先于迟到selecting列表，不重新POST。下一个待确认job按原创建顺序显示文件名/任务ID/队列位置，不将其说成同任务重复。旧入口、fallback和Uppy共用此Owner。

完成回调调用autoOpen:false，保留原手动“整理本次导入素材”入口，不自动跳到另一ZIP相关窗口。原后端v19状态机、标签映射/正式标签创建、GT入库、8MB分片/2ZIP槽位/4分片并发和任务中心不改。确认失败保留映射及可重试按钮，不能伪称成功；上传100%尚扫描不提前显示。

修改：static/modules/zip-import-runtime.js、uppy-zip-view.js；static/app.js仅原Modal关闭通知/指定层关闭及完成回调选项；原bootstrap/index缓存、VERSION、必要静态Owner守卫、原两个CI工作流加入新浏览器用例。无后端业务变更。

### RED→GREEN及最小回归

- 最初真实Chrome两个RED：Uppy扫描完成无自动确认；start成功后ZIP窗口仍存在。进一步RED验证多ZIP共享层误关闭、Modal底层复用误关新窗口，均已修复。测试三ZIP曾只等待请求发出即检查下一窗口，正确改为等待当前job确认窗口实际关闭；保留一次start/三素材及job隔离全部断言，不删安全检查。
- 新tests/browser/zip-label-presentation.spec.mjs共9场景：自动展示；确认关闭+连续旧列表+重复调用只1次start+真实done/1素材且不弹后续窗口；100%扫描与其他业务窗口延期；主动关闭/多poll/刷新/手动恢复；三ZIP分别确认/准确文件名和job/各1次start/真实3素材；迟到start不关新窗口；Uppy原fallback；经典importFile入口；409拒绝保留/安全重试。
- 真实Chrome：原Uppy15例+新9例首次23通过1失败（上述测试等待边界），该单例修正后1/1通过；同轮新7项曾整体7/7通过。无生产服务或素材，真实隔离HTTP/分片/后台导入/JPEG/GT；scanning/旧列表/409/迟到start通过路由仅注入所测竞态，不伪造导入成功证据。CI执行完整新增9及既有用例。
- Node：11个相关文件101/101通过；最后两处入口/顶部业务窗口保护修改后仅重跑受影响5文件51/51通过；0失败/跳过。同步守卫只调整真实缓存/函数签名及autoOpen:false，不降低Owner断言。
- Python：复用tests/api/test_v19_label_mapping.py，9通过、0失败/跳过（9.01s，5条既有弃用warning），覆盖明确确认/冻结映射/禁止隐式创建/正式GT回滚；没有全仓测试或GPU。
- node --check app/runtime、git diff --check通过。当前阶段A审计及RED/B修复/C本地回归已完成，D提交及准确SHA远端CI进行中；本地通过不能代替CI，提交SHA与最终回执待下一节补充。

### 首轮CI发现与修正（待准确修正SHA复验）

代码88ad694f85c72f402abdf55ba0f3e84fc2de12bc已正常推送；首轮CI ZIP Import Durable Runtime的Chrome失败：旧UP-08假设上传完成后仍能操作旧上传层，Linux自动交接更快使该等待超时。新增9场景在该工作流均通过，不能将总体失败说成通过。

复核正式入口进一步补出真实RED：关闭确认后，原“上传数据”选择窗口仍在下层。现原zip-import-bootstrap在组件导入成功、原项目/chooser仍有效且确为顶层时，通过原closeModalLayer424交接选择层，再打开Uppy；其他业务窗口不被关闭。没有改上传或后端。UP-08改为等真实确认、关闭后断言无残留，再从正式按钮重新打开并验证原fallback/两条不同ZIP持久任务，保留真实上传数量及状态断言。该例先RED后GREEN 1/1（9.5s），相关Node3文件44/44通过。bootstrap缓存4226368，新增用例也补入原ZIP工作流paths，避免未来单改此用例不触发相关CI。该修正需新SHA验收，原失败回执保留。

### 边界与接续

自动候选仅当前页面上传产生；刷新/主动关闭后须任务中心手动恢复，避免历史任务抢占用户。视图销毁不影响原控制器；原服务器仍对正式导入幂等负责，本轮未更改网络结果不确定的后端合同。UI显示记忆不是服务端任务状态，正常关闭不取消ZIP。未验证生产网络/浏览器多标签同时确认，生产未部署。后续只从本节及原Owner继续，勿重建ZIP轮询/Modal/任务表或自动跳过人工映射。

## 2026-10-24｜普通图片上传同一需求复核（复用既有实现，无业务代码变更）

用户再次提交55dcc111附件，内容与本文件2026-10-23普通图片专项相同。重新fetch后本地/远端一致：b1b32a445da3a669c1a6c056ebda8502abc890ea，VERSION42.24.382（上传功能在381交付，382为后续跨标签专项）。确认既有Uppy图片view、唯一MaterialUploadRuntime、UploadBatchStore、upload-confirmation、TaskCenter、清洗与Annotation入口仍在；没有重新建设组件/状态机/数据库，没有修改上传/GT/清洗业务代码，文档复核不递增VERSION。

本轮新执行的必要证据：
- Python：`python -m pytest tests/api/test_upload_clean_flow.py tests/api/test_upload_request_recovery.py -q`，31通过、0失败、0跳过（27.18秒），保留5条既有依赖弃用warning。覆盖混合决策/幂等/回滚/项目范围/正式GT保护及不确定上传回执恢复。
- Node：`node --test tests/frontend/material-upload-runtime.test.mjs tests/frontend/uppy-image-view.test.mjs tests/frontend/upload-confirmation.test.mjs`，25通过、0失败、0跳过；包括64张/128MB有界顺序批次、缺文件回执拒绝、真实成功ID/退役过滤、重复点击/项目切换、刷新/稍后处理、逐文件等待真实回执及本地资源回退。
- 真实Chrome：`npx playwright test tests/browser/material-upload-chunking.spec.mjs --grep 'Uppy five' --reporter=line`，2/2通过（10.5秒），隔离项目/真实后端。五张全成功：一个HTTP请求含五个multipart文件、五条服务端成功ID、确认页五图、正确大图、ready进入原标注但GT仍unannotated；四成功一损坏：确认页仅四张成功图，失败原因独立显示，刷新同批恢复，选一图产生原清洗任务、其余三图pending，稍后处理后刷新不再自动展开。
- 本轮没有重跑全仓；65图分两批/ZIP本地Uppy的既有证据保留于下方原验收，不将历史用例计入本轮2例。当前代码SHA已核验21/21 Actions、55/55 Checks成功：[准确Checks](https://github.com/jorsamj/aixunlianpingtai/commit/b1b32a445da3a669c1a6c056ebda8502abc890ea/checks)。本次仅文档补提产生的新HEAD仍须独立核验后交付，不能借该旧SHA代替。

根因与结论：五图通常是一批multipart、一个任务，不能将任务数当图片数；本轮实测五File→五请求项→五成功回执，未复现漏传，不能据此断言生产所有网络/文件均无漏传。当前任务中心及确认页已区分图片数/批次数/真实字节/成功/失败/待核验，不伪造逐图百分比。成功身份只取服务端本项目批次，失败和退役图不进入成功网格；不复制原图。clean/ready/pending走原v55决策，ready不写GT，稍后不启动清洗或训练。

已知限制继续有效：原后端每批只有一个clean_task_id，确认页禁止同批第二组追加清洗；首次选择不同图片分别clean/ready/pending正常。不能把该限制写成已解决，也不为重复需求擅自重建多任务关联。后续若明确需要同批多轮追加清洗，应先审原清洗任务身份、并发和恢复合同，再最小扩展原Owner。网络结果未知时只查询原requestId，不盲目重传；同名成功/失败无法可靠区分时禁用快捷重试。生产吞吐/NAS/OSS和真实网络仍NOT VERIFIED。

保留5944祖先、两份未跟踪模板测试和其他会话成果；未部署、未操作生产素材/GT/历史副本/模型/迁移，不扩大训练模板或跨标签专项。接续继续使用本文件原普通图片章节，不创建重复需求文档。

## 2026-10-23｜普通图片上传统一与本次上传处理（代码及隔离CI已验收）

本节为本轮唯一需求、进度及接续；原ZIP/任务中心验收记录保留。基线5cb25c3ce06e2a4c174814a7c6eb4775bcdeae41，VERSION42.24.380，fetch0/0；5944及两份未跟踪训练模板测试保留，不部署生产或修改历史素材/GT/模型。

确认需求：普通图片复用本地Uppy Core/Dashboard/简体中文，保留现有64张/128MB顺序multipart、requestId恢复、UploadBatchStore和唯一任务中心；批次字节进度不能伪装逐图百分比。上传成功后素材页内显示“本次上传图片”，身份来自实际服务端批次，不用临时recent数组；25/48条分页缩略图、选择、失败原因。按各真实batch提交clean/ready/pending，清洗接原任务，ready接原人工标注且不改变GT，later保持pending。刷新恢复指针，已决策不重复弹出；无新增永久记录表/原图副本。

代码初审：最终网络Owner在material-upload-runtime.js，五张通常组成一个HTTP批次；其accounted必须等于chunk.length，否则抛合同错误。目前只能确认分批与展示语义，真实五张漏传与否待实际API/Chrome证据。现有后续按钮依赖recentUploadedMaterials61，且没有本次批次专属持久页面，是已确认缺口；legacy app.js中多处旧上传实现不是正式修改目标。

最小设计/计划：
- A：定向验证五File、multipart五项、服务端成功/失败/真实GT。复用原测试，不全仓审计。
- B：原传输Owner暴露视图事件/外部view选项，新聚焦Uppy图片view只负责文件选择；原taskcenter显示图片数、批次、真实字节及服务器确认数。禁止第二传输器/队列。
- C：聚焦upload-confirmation模块读取原v55回执，以真实batchId+imageId关联分页；本地只保存会话指针，原UploadBatchStore唯一truth。与原素材Owner接线，迟到请求/项目/Modal隔离。
- D：原decisions API和Cleaning/Annotation重用，逐批显式提交/防重/重试，GT状态不因ready变化。必要后端合同缺口最小修复。
- E：必要Python/Node、真实五图/部分失败/65图顺序分批/刷新/GT/ZIP冒烟；阶段提交，最终准确SHA CI及文档更新。生产真实吞吐未验证，不以隔离数代替。

状态：A–E已验收（隔离代码/CI范围），生产仍未验证。具体证据与发现的问题见下节。

### 普通图片本轮实现与限定验收（2026-10-23）

A–D代码已完成并通过修正提交的隔离CI验收。原传输Owner增加外部view事件及会话指针；新uppy-image-view仅接官方addUploader，复用ZIP的本地官方加载器，没有新增上传协议、数据库、队列或依赖。upload-confirmation读取原v55批次/决策，48条分页、原缩略图/大图、跨批选择及失败明细，既有素材Owner提供入口/恢复。原图、GT、标签、清洗Worker及正式标注Owner不变；app.js仅允许原预览接收离页图片并隐藏其旧决策按钮，避免绕过批次合同。

RED→GREEN：真实Chrome先发现完成Uppy及底层旧上传选择Modal遮挡确认页，改为通过原Modal生命周期仅关闭所属窗口；checkbox的通用data-action被全局ActionRegistry拦截，改为本模块专属data-upload-action；进入页面触发restore抢占open的generation、遗留loading，新增Node复现失败后为正在读取的Owner加恢复防重，7/7通过。没有降低点击、GT或请求数断言。

实际限定证据：Python原上传清洗/请求恢复两文件31通过0失败0跳过；Node原上传/新view/确认页/分页/版本/整体进度首次49通过，后增加处理中回执与导航重入测试，最终定向合并51/51通过0失败0跳过；真实Chrome原65图=两个顺序请求（并发1）、任务中心65成功通过；五图全部有效=一请求五multipart项、五张入库并进入原标注、仍unannotated通过；四有效一损坏=4成功1失败、刷新恢复、选1清洗/3pending、稍后处理不自动弹出通过；原ZIP中文本地懒加载/真实导入冒烟1通过。浏览器均隔离项目/真实后端，不是生产数据。

本地可复现命令（均只针对受影响模块）：

```text
python -m pytest tests/api/test_upload_clean_flow.py tests/api/test_upload_request_recovery.py -q
node --test tests/frontend/material-upload-runtime.test.mjs tests/frontend/uppy-image-view.test.mjs tests/frontend/upload-confirmation.test.mjs tests/frontend/material-pagination-runtime.test.mjs tests/frontend/version-marker-owner.test.mjs tests/frontend/image-upload-overall-progress.test.mjs
npx playwright test tests/browser/material-upload-chunking.spec.mjs --grep 'Uppy five' --reporter=line
npx playwright test tests/browser/uppy-zip-poc.spec.mjs --grep 'Chinese local lazy Dashboard' --reporter=line
```

原65图场景在同一material-upload-chunking文件中已先行通过；导航修复只重跑失败的两个Uppy场景。最后传输准入锁移到分批验证之后，防止无效选择提前抛错遗留锁，原上传14项针对性复核通过。未机械重复全仓。

恢复边界：浏览器只存project/request/batch指针及计数；回执是唯一成功ID和decision来源。未取得回执显示“待核验入库”，30秒截止可重新查询，不能盲目重新上传；重选仅允许明确失败文件名，同名成功/失败无法可靠区分时禁用快捷重试。稍后处理仅延后入口、不改变pending。ready仅进入原标注队列，不自动产生框、confirmed_empty或正式GT。已有后端每批只允许一个清洗任务，本轮遵守该合同：已创建清洗任务的同批剩余图片只能直接标注或稍后处理，不重复创建/修改原任务；未来追加清洗需另审合同。生产吞吐/NAS/OSS/现场大数据未验证。

提交：审计和后端合同证据bede07ff69340199d3bbe881725719b2de6a2909；前端实现422f56a0790b0f2449ddbfb65aa50874fbab5f34、VERSION42.24.381已正常推送长期分支。该提交CI实际42/43 Actions、117/118 Checks通过，前端Chrome249通过1失败：旧material-workflows用例仍查找已按需求取消的上传完成弹窗。已将同一用例更新为本批页面、真实v55 clean/ready请求、原标注和unannotated合同断言，本地单例1/1通过，未删除用例或减少业务检查；其修正提交最终CI另核，不以旧提交绿色冒充本轮。接续仅处理本轮失败检查，禁止重建上传、清洗或GT Owner。5944祖先和两份未跟踪模板测试保留，未生产操作。

### 普通图片最终代码验收与接续回执

- 审计/后端合同：bede07ff69340199d3bbe881725719b2de6a2909；功能代码：422f56a0790b0f2449ddbfb65aa50874fbab5f34；旧用例适配修正：**646aeb0a1c005f38532f96a5fea1eaf95ead576a**，VERSION **42.24.381**，均已正常推送唯一长期分支。
- 最终代码修正SHA实际 **22/22 Actions、58/58 Checks成功，0失败/取消/跳过/运行中**。精确SHA证据：[Commit Checks](https://github.com/jorsamj/aixunlianpingtai/commit/646aeb0a1c005f38532f96a5fea1eaf95ead576a/checks)、[真实Chrome250/250](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39969940372)。首代码CI的上传等42个已通过工作流记录保留；不把首失败写成全绿。
- 本地必要验证：Python31/31、Node51/51，普通图片四个独立Chrome场景（65图、5成功、4成功1失败、原单/多上传流程）和ZIP冒烟1个通过；远端原前端Node1322/1322、修正SHA Chrome250/250通过。最后测试修改只有旧页面期望改成新页面/正式批次合同，产品代码未变化。
- 5944祖先和两份未跟踪训练模板测试保留；推送前远端0/0，无覆盖、强推、生产部署/扫描/素材或GT修改/GPU操作。
- 本次回执补提仅更新文档；其自身HEAD的CI必须独立查看该提交Checks并在最终交付核验，不能用上述代码SHA代替。无需因文档补提重复本地代码测试。文档自引用不写尚不存在的SHA，最终实际HEAD以GitHub分支及交付报告为准。
- 下一会话从本节、material-upload-runtime、uppy-image-view、upload-confirmation及既有v55 UploadBatchStore开始。不要再重建上传/清洗/GT体系，不扩大训练模板。生产现场吞吐/外部存储仍NOT VERIFIED；同批追加第二清洗任务的既有限制若需改变，应先审原后端任务身份合同。本轮已完成范围之外不自动迁移或回收数据。

> 最新接续：6A原UploadTaskCenter稳定性补充。旧Uppy验收仍有效；本轮准确SHA验收独立记录在6A.3。

# Uppy ZIP上传隔离适配PoC与兼容性报告

> 唯一专项需求、设计、进度与验收依据；日期2026-10-22；仓库jorsamj/aixunlianpingtai，唯一分支feature/external-algorithm-publishing。

## 1. 授权与基线

用户确认先建立隔离PoC，全部场景通过后才切换正式ZIP界面并保留原界面回退，允许成功后正常提交推送和最终SHA CI。禁止生产部署、生产服务/素材测试、正式GT/索引/历史修改。不使用Tus、Companion或第二上传控制器/任务库；8MB分片、每ZIP原并发4、全局2槽及恢复/幂等保持。Uppy上传完成仅指传输阶段，后台导入不能被误报完成。

实际fetch后本地/远端HEAD均c1af26ea8bb980916fc4a90abeeb5dcd1e69e5b0，VERSION42.24.373，目标工作树干净；原D盘WIP及其他工作树不动，未见同仓库其他活动会话。已读AGENTS、CODEX_CURRENT_STATE及既有ZIP持久性/多文件队列设计。

## 2. 已确认需求与验收矩阵

| ID | 场景 | 状态 | 证据 |
|---|---|---|---|
| UP-01 | 固定Core/Dashboard/简体中文版本、实际许可证及离线可复现资源 | 已验收 | 固定三依赖+官方发行；87项离线制品/声明，Node3项通过，许可限制见5.1 |
| UP-02 | 单ZIP、多ZIP及两个全局槽、每ZIP原分片并发 | 已验收 | Chrome真实3×33MiB，2个ZIP×4分片；第三个在原槽位释放后启动 |
| UP-03 | 实际传输进度，暂停/继续不重传确认分片 | 已验收 | Chrome中间真实字节+暂停确认分片不重传；官方Core真实回滚与恢复Node |
| UP-04 | 断网、刷新后同ZIP续传，失败不重复任务 | 已验收 | Chrome断网重试/刷新同mtime续传/complete响应丢失和未知查询，任务不重复 |
| UP-05 | 上传后ZIP校验/标签映射/Worker入库；传输完成与导入完成分开 | 已验收 | 真实JPEG+YOLO，原v19→映射→daemon Worker done→Material及正式GT |
| UP-06 | 关窗后台继续；销毁清理监听/实例；原界面回退 | 已验收 | 关窗原传输继续；迟到mount不复活；资源失败自动/手动回退 |
| UP-07 | 中文、隔离PoC、实际Python/Node/Chrome及准确SHA CI报告 | 已验收 | 本地Python82/Node1237/Chrome29+15；2ae6bdf7实际23/23 Actions、62/62 Checks通过，文档HEAD单独核Checks |
| UP-08 | PoC全通过后正式入口切换及可回退 | 已验收 | 隔离14项全通过后接正式按钮；真实菜单进入Uppy及原回退上传通过 |

## 3. 架构审计与设计取舍

- 唯一传输Owner为static/modules/zip-import-runtime.js。uploadBatch同步登记任务并使用createZipTransferLimiter(2)跨批FIFO；uploadZipMultipartJob复用会话、8MB、最多4个分片XHR及重试。暂停/取消/续传由同一Owner处理。UploadTaskCenterRuntime是正式状态展示Owner，原PollRegistry及v19持久任务继续工作。
- v19 Upload ID与正式Import Job ID可能不同；原任务中心rekey及标签/Worker链不能丢失。Uppy完成事件仅对应原控制器已确认分片合并交付，不将整个导入标成功。
- 新增适配层只绑定Uppy文件ID与原控制器返回身份、转发官方进度事件和操作意图；不创建传输XHR/会话/第二队列/轮询/持久任务状态。控制器暴露最小观察回调，批量结果需逐文件反馈，不能从最终一个任务猜其他文件成功。
- Uppy实例随原Modal内容生命周期创建/销毁；销毁只清Uppy事件及投影，不取消控制器任务；原任务中心继续读取原Owner快照，新界面重选恢复按原文件指纹/Upload ID核验。项目与Modal归属防迟到。
- 方案A（采用候选）：官方预编译uppy发行制品本地复制，动态加载官方aggregate+zh_CN，仅实例化Core/Dashboard，不启动其他插件。优势无需新增打包工具且可精确校验；风险包含未用插件代码，须记录实际字节、嵌入许可和懒加载证据。方案B：引入新bundler定制tree-shake，体积更小但与不增加第二套打包体系约束冲突，不采用。方案C：裸ESM/import map，传递依赖含非原生ESM，需自造转换器，不采用。
- 初选官方稳定Core6.3.0、Dashboard6.0.2、locales5.3.1，与官方uppy6.0.5预编译发行对应；以registry.npmjs.org和实际包manifest/source map核验后固定，禁止宽松版本。官方文档：https://uppy.io/docs/uppy/ 、https://uppy.io/docs/guides/building-plugins/ 、https://uppy.io/docs/dashboard/ 、https://uppy.io/docs/locales/ 。许可证以实际安装/嵌入依赖文本为准，不只看顶层MIT。

## 4. 实施计划与职责

> 按writing-plans及subagent-driven-development执行；每步RED→最小实现→GREEN→规范/质量复核。主agent统一提交，子任务不提交/推送，不并改共享文件。

- [x] A0：核验远端、并行工作区、既有Owner及用户约束，建立唯一文档。
- [ ] A1：固定依赖，tools/vendor_uppy.mjs复现官方资源/许可证清单及哈希；先写离线/版本/许可失败检查。负责文件package.json/package-lock.json、tools/vendor_uppy.mjs、static/vendor/uppy、对应Node制品测试。
- [ ] B1：原ZipImportRuntime新增最小传输观察入口；先动态测试逐文件身份/排队/进度/暂停/失败/交付及清理，不增加控制器或轮询。主agent负责原模块及其Node测试。
- [ ] B2：static/modules/uppy-zip-adapter.js通过addUploader及官方事件委托原Owner；测试不发旁路XHR、关闭不取消、旧响应不能覆盖新界面、暂停/恢复/取消只有单Owner。主agent负责。
- [ ] C1：独立PoC入口及真实浏览器，临时本地后端、真实ZIP/分片/校验/标签Worker，故障注入只隔离网络；覆盖UP-01–07全部场景，保留RED/失败原因。
- [ ] D1：仅C1全部通过后，原ZIP入口接Dashboard，显式原界面回退及资源失败自动回退；继续复用原Modal/UploadTaskCenter。必要静态缓存与VERSION按最终改动一次递增。
- [x] E1：相关Python、Node、Chrome和既有回归/许可离线验证；独立只读审查；更新AGENTS/CURRENT_STATE及既有ZIP入口；正常提交推送，准确代码SHA和最终文档HEAD均核验所有实际Actions/Checks。

## 5. 实际测试、问题与进度

### 5.1 A1离线制品与许可（代码CI已通过）

精确固定@uppy/core6.3.0、@uppy/dashboard6.0.2、@uppy/locales5.3.1；官方预编译uppy6.0.5作为dev依赖只供制品复制。Core/Dashboard嵌入manifest精确版本已由官方source map核验。uppy.min.mjs610629字节、CSS92037、独立zh_CN8261，运行时合计710927字节，按需加载；含source map的全部制品3009329字节，完整含notice目录3178573字节。不新增bundler或CDN，未启用Tus/Companion/远端来源插件。

tools/vendor_uppy.mjs离线复制与check均通过；87项制品/声明、76个实际安装依赖（71 MIT/4 ISC/1 BSD-3-Clause）审计。另补Airbnb Polyglot实际BSD-2-Clause插值授权及生成regenerator运行时代码MIT归属。官方MIT许可允许使用/修改/再分发/销售，保留版权及许可文本；[官方许可](https://github.com/transloadit/uppy/blob/main/LICENSE)。实际npm6.0.5文本版权2018，与官网main当前2019有差别，以固定包原文为准，未改写。

版本证据限制明确区分：安装依赖版本不等于预编译嵌入版本；compressorjs/cropperjs横幅证明嵌入1.3.0/1.6.2，另保留相应历史包许可。Preact等其余嵌入依赖精确构建版本未独立证明，source map包身份与相应宽松许可已核验。combine-errors/custom-error-instance仅属于未嵌入的安装依赖，分别有MIT README/ISC manifest声明但上游未提供完整单独license文本；保留实际发布声明、作者及来源，不伪造copyright或称已获得缺失文本。许可证清单与来源/完整性限制全部在static/vendor/uppy/manifest.json及licenses内。尚无已证实闭源商用许可冲突，不把上述证据限制隐去。

npm ci官方registry通过（88 installed、audit0漏洞），vendor Node3/3通过，原Annotorious16项制品核验保持。制品测试实际拒绝损坏资源、缺notice、宽松pin及未知license。原全前端第一次1225通过1失败：same-origin扫描器命中官方aggregate未启用远端插件的静态URL。仅对精确官方SHA256 4f77fed780378c09bb9c1cb818b9cadd21ab0f644070de1731e46013c352c37c允许已审查第三方源码例外，没有排除整个vendor目录；原平台代码仍全扫描，并在真实Chrome要求外部请求尝试为0。相关26项Node已通过，最终全量仍待重验。

### 5.2 原Owner与适配合同的RED→GREEN

- 原runtime新增只读subscribeTransfers、原File→localID→UploadID→JobID事件及getProjectId，不新增任务状态或轮询。逐文件session/实际字节/processing/success/error/paused/cancelled同步Uppy；uploadBatch原最后一个结果不再被当成整批结果。
- 原续传upload绕过全局两槽已确认；新动态2例先RED（观察/续传入口缺失），原Owner最小观察后GREEN。legacy单续传也进入原withBatchSlot；适配resumeTransfer复用uploadBatch和原expectedUploadId，多个续传同一FIFO，不受legacy单uploadControl误挡。项目切换排队不启动到新项目。
- 原completedParts取dispatch cursor，实际首PUT确认时误报3；动态RED后改为acknowledgedParts，13通过1失败→14/14。与原durable runtime及观察测试合并48/48通过。
- Uppy官方addUploader、upload-start/progress/success及upload-pause/pause-all/resume-all已接原Owner，取消仍从原任务中心（不启用Uppy并行取消器）。传输complete只记录服务端交付响应，后台selecting/running不变done。销毁先解除原订阅/Uppy事件/Uploader，再destroy（官方destroy会触发cancel-all），关窗不取消任务。
- 动态适配测试含实际安装官方Core共11/11；随后发现本地资源永远Pending会无限Loading，新增RED后复用原withRequestDeadline30秒回退，适配+view共13/13。旧mount迟到覆盖新view句柄有动态RED，改为await前登记handle、旧关闭后只销毁自身，1/1通过。

### 5.3 初期真实测试

Python一次12份ZIP/multipart/背景合并/持久化/规模/映射/回滚/正式标注导入文件合并 **48通过0失败0跳过，92.28秒**（C:/tmp/uppy-python-poc.xml），warning5条为现有依赖弃用。命令文件清单为test_v19_multipart_controls、test_v19_multipart_background_finalize、test_v19_job_atomic_persistence、test_v19_import_scalability、test_v19_import_report_externalization、test_v19_import_bounded_admission、test_zip_class_samples_v19、test_v19_import_failure_rollback、test_zip_processing_p1/p2a_annotation_connections/p2b_single_final_annotation/p2c_structured_single_final_annotation，均在tests/api，运行python -m pytest -q对应文件与隔离短basetemp。

首个真实Chrome通过：官方DOM选择ZIP、中文按钮、真实v19分片/合并→原标签确认→原daemon Worker done→Material imported_yolo+正式GT；不是只模拟zip容器或用假图片。首屏Uppy请求0、打开后本地懒加载，全部非本地请求尝试0。首轮夹具误读window.state（实际state为lexical）导致失败，仅修正确权威就绪读取后通过。当时其他场景尚未完成；最终完整矩阵见5.4。

下列记录补充后续实际验证，不以早期单例代替完整验收。

### 5.4 完整浏览器兼容性矩阵及正式入口

先在独立项目/临时存储中直接动态导入`/static/modules/uppy-zip-view.js`、调用`openUppyZipView({poc:true})`验证，不触碰正式入口。完整14项Chrome全部通过后才把原`chooseUploadZip426`接到bootstrap的`openUppyZipUpload`，仅用户点击时加载view及官方本地资源。正式菜单“数据集→上传→上传 ZIP”已真实点击验证；保留原原生文件选择/程序调用合同，以及Dashboard内“使用原上传界面”。旧v19导入兼容调用仍委托原runtime，不建立第二执行路径。

| 实际Chrome场景 | 验证证据/结果 |
|---|---|
| 单ZIP中文界面/离线懒加载/Worker/GT | 原DOM文件选择、上传、任务中心确认；真实JPEG+YOLO入库及正式box；首屏Uppy资源0、非本地请求尝试0 |
| 多ZIP和全局并发 | 3×33MiB真实磁盘ZIP；最多8个同时PUT，精确2个Upload ID各4分片；进度包含0–100之间真实字节 |
| 暂停继续 | 原pause API、同Upload ID继续；已确认part序号不重传 |
| 断网恢复 | 分片网络中断后原重试/官方retry，始终同一持久任务 |
| 刷新恢复 | 保留原文件名/大小/mtime/内容，重新选择后同Upload ID且跳过确认分片 |
| 完成回执丢失 | complete POST已执行但断响应，查询原持久任务恢复，不额外POST/重复任务 |
| 完成及查询均不确定 | 查询也断网时显示错误，不盲目重发complete |
| 关窗后台继续 | 官方实例destroy一次，原分片继续，原任务中心映射仍可打开 |
| 模块迟到 | 关闭后本地模块才返回，不重建Dashboard/污染新窗 |
| 原队列取消 | 原TaskCenter取消等待ZIP，不影响其余传输 |
| 回退 | 本地资源加载失败自动原UI、手动原UI，仍原runtime |
| 手动标签映射 | helmet→object经原映射/Worker写入真实GT，不另造标注格式 |
| 四视口 | 1920×1080、1440×900、1366×768、375×812，回退/关闭可见可用，加载占位结束后移除 |
| 正式按钮 | 数据集真实上传按钮打开Uppy、实际上传后手动回退另一ZIP，两个任务真实selecting |

`tests/browser/uppy-zip-poc.spec.mjs`最终15项；辅助ZIP/故障注入在`tests/browser/helpers/uppy-zip.mjs`。所有服务为playwright.config.mjs/test_server.py隔离本地8011、每次新建临时项目，未访问生产；4张截图在本地C:/tmp/uppy-chrome-{分辨率}.png。C:/tmp/uppy-chrome-matrix5.log最早完整14/14（58.5秒），spinner回归后C:/tmp/uppy-chrome-spinner-final.log再次14/14；正式新增第15项也通过。最终联合15新+14原恢复 **29通过0失败0跳过（1.7分钟）**，C:/tmp/uppy-chrome-final29.log；原末例屏障额外重复5/5。收尾入口迟到保护后，实际正式按钮回退场景再验1/1（C:/tmp/uppy-chrome-entry-final.log）。

浏览器失败留痕：first夹具误读window.state；matrix1为Playwright组合FilePayload超过50MiB，改真实磁盘输入并保留文件直到afterEach；matrix2因过早删除Chrome输入文件被中止，未形成最终计数；matrix3为同步断言selecting而服务端仍validating，改等待真实状态；matrix4为刷新未等原uiReady/项目就绪，被正确生命周期fence销毁，修夹具等待；正式联合首轮28通过1失败，原narrow取消场景request-count审计发生启动busy竞态：最后一段检查/调用分跨Playwright进程任务，启动poll可占busy导致审计调用早退0GET；改为同一browser task等待原启动promise+有界idle、由原PollRegistry清timer后立即reconcile，精确1GET及全部窄屏/取消断言保留。单例原样复跑1绿、同步屏障后5/5及最终29全部绿。没有降低动态业务断言或跳过关键场景。

### 5.5 复审修复、最终本地验证及限制

独立复审实际复现后逐项修复：

1. session回调立即暂停时，原local TaskCenter行未rekey：先正式rekey/upsert，再通知观察者；动态3例2绿1红→3绿。
2. XHR重试退避仍在退出时立即resume被原活动身份挡住：原control增加stopped Promise，原finally清map/释放槽后确认暂停；不另造控制器或队列。
3. pause HTTP失败仅通知却未给Uppy恢复事件：等待本地停止后发真实error；官方Core+真实原runtime验证失败→retry原ID→唯一Job ID，不能无限暂停。
4. legacy恢复暂停留下已停止uploadControl，Uppy重选误判重复：仅未停止的原owner阻止重复，保留File恢复信息；动态5绿1红→6绿。
5. 官方Core在100%后忽略字节回滚：按原XHR/确认字节重设投影后emit实际progress，不伪造99%或补值；merge已开始则提示后台处理，不能再pause；成功后迟到pause失败不覆盖成功。
6. 模块/样式永久Pending：复用现有withRequestDeadline，30秒明确回退。迟到view不覆盖新handle，关闭销毁清理事件/订阅/observer/uploader；不取消后台。
7. Dashboard挂载后原Loading残留：挂载前清占位，真实四视口断言已加入。
8. 正式入口view模块迟到仍可能重开已关闭chooser/跨项目：新增动态RED（1≠0），复用原input.isConnected及project身份校验后GREEN；不建立新Modal管理器。

前端全量最后 **1237通过0失败0跳过，17.75秒**（C:/tmp/uppy-node-final-green2.log）。此前一次1234中1232绿2红均为实际缓存版本变更后的旧精准守卫，已同步app421/ZIP4226365而未放宽断言；官方Core原Owner集成首跑仅夹具错误期待Upload ID而非真实Job ID，修为`job-core-pause.zip`，保留唯一行和原ID恢复断言。相关Node含7项原控制器观察/跨入口恢复、15项适配、2项view、3项制品，既有完整前端同跑。

Python API48项无后端代码变更后继续有效。原ZIP仓库/标注/审计/secret单元4份补验首轮33绿1红：测试夹具SQLite with只提交事务未close导致Windows无法unlink；仅夹具用contextlib.closing明确关闭并保留事务，原断言不变，34/34通过（2.57秒，C:/tmp/uppy-python-units-green.xml）。本轮合计不同Python测试82通过0失败0跳过。`python -m platform_core.build_identity --check-version-file VERSION.txt`确认42.24.374；正式VERSION本轮只递增一次。仅app缓存421、ZIP bootstrap/runtime/view4226365必要刷新，main/styles420未改。离线verify87项与Annotorious16项制品再次通过；.gitattributes对Uppy供应制品设置-text，避免Windows checkout改写官方字节/许可哈希。原ZIP完整Permanent guards实际bash执行退出0，语法/build identity/diff检查通过。

技术取舍/剩余限制：官方aggregate含未启用插件导致约711KB加载，不因预编译源码出现远端URL就启动相关插件，真实浏览器外部请求尝试为0；若以后要减体积，应经批准统一现有构建策略，不能另造bundler。取消继续使用原TaskCenter，Uppy不出现并行取消器。浏览器刷新后必须重选同文件，File句柄不跨刷新持久化；大于测试约33MiB、生产代理/超大文件、生产任务数量和真实断网环境仍需另行生产只读/发布后验收。本轮未部署、无生产素材/正式GT/索引/历史数据修改，测试写入仅临时隔离数据。

现有`.github/workflows/zip-import-durable-runtime.yml`增加锁定npm安装/离线check及上述定向Node/Chrome、原后台合并API，不新建第二CI或删除旧断言。最终提交/精确SHA Actions与Checks见5.6。

### 5.6 Git提交与准确SHA CI

首代码提交[a6bcd6362c0c78ba5e061d081a460cf7f00a8bed](https://github.com/jorsamj/aixunlianpingtai/commit/a6bcd6362c0c78ba5e061d081a460cf7f00a8bed)已普通推送。准确该SHA最终40条Actions：39成功、1失败；112 Checks：111成功、1失败，不能称首提交全绿。

- ZIP专项run[39725719831](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39725719831)：Linux/Windows合同、离线制品、后端均成功；后端单元34/API28及真实Chrome29通过。
- Frontend run[39725719673](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39725719673)：Node1237及Chrome184（8.5分钟）全部成功。
- 失败run[39725719739](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39725719739)、job119649022314：training-quality-reports旧夹具6失败、其余9通过，六处底层训练配置点击被正式准入诊断遮挡。

确定根因：此前GOV提交14419353正式增加空草稿“至少2张有效训练素材”的自动诊断；first-open等已接既有returnToTrainingConfiguration helper，quality-reports漏接。本轮Uppy没有改训练准入逻辑；基线c1af26ea同样存在该旧夹具缺口，原Frontend184集合不包括此quality文件，不能拿184绿色证明它通过。独立复审与本地原例实际RED一致（C:/tmp/uppy-ci-training-red.log）。仅在7处新建表单可见后复用原helper，点击真实“返回训练配置”且断言原草稿未变，不用force、移除诊断或修改成功标准。修复后原失败首例1/1、精确CI两文件training-create-first-open+training-quality-reports共15/15通过（40.2秒，C:/tmp/uppy-ci-training-full.log）。

收尾同时将截图输出改为跨平台os.tmpdir()/path.join（四视口+正式入口2/2再次通过，C:/tmp/uppy-chrome-portable-final.log），去除自有helper空白EOF；官方供应文件原生空白不改，以.gitattributes -whitespace仅保留第三方原字节，平台代码仍执行正常whitespace检查。VERSION保持374，不二次递增。当时尚未作最终绿色结论；修正提交实际结果见下一段，最终文档SHA仍独立核验。

修正提交[2ae6bdf71c24096e4ab75db5696c4609e6832678](https://github.com/jorsamj/aixunlianpingtai/commit/2ae6bdf71c24096e4ab75db5696c4609e6832678)已普通推送；准确该SHA **23/23条Actions全部completed/success、62/62项Checks全部completed/success**，代码与隔离测试已验收。训练回归run[39727149526](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39727149526)已成功；ZIP run[39727149529](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39727149529)全部成功；Frontend run[39727149494](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39727149494)Node1237及全量Chrome184（7.4分钟）实际通过；训练Chrome15（39.5秒）、ZIP Chrome29（1.3分钟）均通过，非借用首SHA。

本次最终文档补提仅更新本专项、AGENTS、CODEX_CURRENT_STATE及PROJECT_HANDOFF_CURRENT索引，不改业务或VERSION。交付前必须对**本文件所在最终HEAD**再次读取全部Actions及分页Checks，确认无queued/in_progress/failure/cancelled；不能沿用2ae6bdf7绿色。GitHub本提交关联Checks为最终文档SHA的持久验收证据（打开仓库分支Latest commit→Checks），交付报告提供最终准确SHA。独立完整回执另存本机visualizations附件目录`uppy-zip-ci-final-20261022.json`，包括首失败、修正及最终文档三组SHA/Actions/Checks；未来会话优先按本文件链接和GitHub准确SHA核验，不依赖聊天或本机临时日志。

### 5.7 兼容性结论

Uppy能够通过官方自定义Uploader接入原ZIP v19协议，无须Tus/Companion/新后端。直接复用原会话/8MB分片/4并发、全局2槽FIFO、指纹恢复/幂等、后台合并/校验、标签映射、原Worker和TaskCenter。必要的小幅修改为原Owner只读观察、续传共用原槽位、暂停停止屏障/错误反馈及前端投影/懒加载入口，没有新增上传控制器、持久任务库或轮询。

已测试范围未发现无法解决的协议冲突，中文界面及原任务状态一致；真正生产网络/超大ZIP仍未验证，不能外推性能或发布合格。受约束采用本地官方预编译制品，体积与未独立确定的嵌入依赖版本限制见5.1；实际已核许可证为宽松商业可用，保留版权/许可声明。不把711KB体积说成定制最小包，也不把后台selecting说成导入完成。


## 6A. 原 UploadTaskCenter 稳定性交互补充（2026-10-22，代码及隔离CI已验收）

基线83790b4c457a642af244ad2d7166301527603363 / VERSION42.24.374，工作树干净。用户要求先修原唯一任务中心，不以Uppy替代。仅隔离数据，不部署、不操作生产。

| 编号 | 需求及涉及模块 | 状态 | 已完成/剩余及风险 |
|---|---|---|---|
| UTC-01 P0 | 稳定按钮DOM、合帧渲染及节流持久化；upload-task-center.js | 已验收 | 已RED→GREEN，600更新0元素移除，关键状态即时保存；修正SHA22/22 Actions、59/59 Checks通过 |
| UTC-02 P0 | ZIP进度来源/阶段一致、顺序/rekey稳定；zip-import-runtime.js | 已验收 | 来源72.7→0已复现/修复，rekey及阶段分离动态通过；修正SHA CI通过 |
| UTC-03 P1 | 防重复操作、Loading、普通图片详情、Modal命中 | 已验收 | 原Modal/TaskCenter/Loading复用、真实图片详情、遮罩及超时已测；修正SHA CI通过 |
| UTC-04 P1 | 九类真实Chrome回归、Node/Python、最终SHA CI | 已验收 | Chrome38/Node1239/Python49通过，日志/矩阵见下；准确SHA22/59通过 |

执行顺序：审计与RED → 原任务中心补丁 → ZIP/图片投影修复 → 定向GREEN与原恢复回归 → 版本/文档/普通提交及准确SHA CI。当前已取得下述隔离测试证据，提交/最终SHA CI及生产性能不可提前宣称通过；旧5.6仅代表此前Uppy代码。

### 6A.1 根因、最小方案与取舍

1. 原patch每次replaceWith整组actions：真实Chrome按下暂停→150次进度→rekey→抬起，原按钮身份断言RED(false≠true)。改为按data-utc-action保留实际按钮，只在动作集合真实变化时增删；委托事件仍在原body，原生按钮键盘click不重复处理keydown。rekey先迁移原行dataset，保留按钮/焦点/创建时间及orderKey，不因临时ID改变位置；移除行hover位移，仅改变背景。
2. 原upsert每次persist+render并重置poll计时：现在内存立即更新，进度按rAF合帧、500ms尾部保存；状态/阶段/暂停/成功/失败/新身份立即保存；pagehide、隐藏、切项目、destroy刷盘并清定时器。无字段变化的进度不重排整个列表；持久存储仍为原localStorage键及原恢复合同，非第二数据库。TaskCenter状态轮询继续由原PollRegistry负责，进度更新不反复延期轮询。
3. 原upsert先用空previous补默认字段，再合并原行，部分更新误将kind/title重置为upload/上传任务：改用原行与原始增量直接merge，修复普通图片任务类型丢失；新增“查看详情”，复用原Modal Stack，显示真实任务ID/阶段/消息并随原行更新，失败仍可查看。标题“图片任务详情”避免被旧通用“上传”标题装饰器误识别成可穿透的上传窗口，真实Chrome确认遮罩命中。
4. 原legacy上传的轮询只读后端progress，未取当前uploading：动态Node RED精确72.7→0。统一原publishTaskCenterJob投影：活动浏览器阶段使用对应原transfer或legacy uploading的真实字节；post-upload且服务器暂仍uploading时显示合并校验，不退回上传。MERGING progress:null显示“等待服务器进度”、隐藏旧阶段条，不冒充上传100%为处理100%。真实分片失败按实际字节回算时显示“分片传输中断，按实际字节重算”；不以Math.max掩盖真实重试。后台校验/标签/入库仍用服务端真实阶段及进度。
5. 操作统一在原任务中心做每任务单次在途保护，相关操作按钮禁用，aria-busy复用全平台已有Spinner/reduced-motion样式，无新Loading系统。30秒超时停止Spinner并显示结果待确认；原控制器请求未结束时保留防重复锁、可打开任务核验，原请求结束后解锁。不能把未知提交伪装失败并重复发请求。详情/操作依旧调用原ZipImportRuntime，关闭窗口不取消后台。
6. TaskCenter状态读取按项目与原行引用核验，迟到结果不覆盖后来进度/新项目。审查补修destroy后clearCompleted迟到finally可能重建root：所有入口/渲染/arm增加destroyed保护；原实例移除root/事件，不能清掉新实例轮询。额外Node RED指出progressKnown:false持久化后被默认值改为true，已保留显式未知标记并用JSON往返断言GREEN。

替代方案：不整行重建/重挂监听、不为Uppy新建任务中心、不对全部进度取历史最大、不让每次XHR同步刷盘；这些方案分别丢点击/形成多Owner/伪造重试事实/阻塞主线程。现有业务ID、8MB分片、并发/暂停/恢复/幂等、v19/Worker/GT合同不改。material-upload-runtime.js只读审计后继续复用原批次/合帧，问题在TaskCenter增量合并；其正式65图两批Chrome已追加详情验收。

### 6A.2 真实Chrome九项覆盖矩阵及测试记录

| 用户场景 | 实际证据/断言 | 覆盖文件 |
|---|---|---|
| 1 高频更新期间展开/收起 | 30帧×20=600更新与6次点击并行，最终展开状态正确 | upload-task-center-performance |
| 2 pointerdown/up间刷新只执行一次 | 150更新+rekey，按钮/焦点对象相同，实际mouse抬起仅1次pause(formal ID) | 同上 |
| 3 两ZIP及多排队不跳 | 相同createdAt的4行顺序不变；原真实3/5/10ZIP与两槽FIFO继续回归 | 同上 + zip-import-refresh-recovery + uppy-zip-poc |
| 4 临时→正式ID | 原行dataset原位迁移，按钮仍有效，两个ID无重复行 | 同上 |
| 5 暂停/继续/取消/详情 | 原委托事件与在途锁、HTTP失败后可恢复，实际Uppy暂停续传跳过已确认分片；30秒未知操作不重发 | 同上 + uppy-zip-poc |
| 6 阶段切换 | MERGING→VALIDATING→MAPPING_LABELS→RUNNING→DONE原行不变，未知进度不伪造 | 同上 + Node unknown/ZIP source |
| 7 弹窗/最小化 | 原ZIP窗口及最小化dock可点击，业务二层Modal及标签确认独占点击，elementFromPoint真实命中 | 同上 + 原ZIP窄屏标签取消 |
| 8 图片与ZIP不串 | 混合行身份/操作严格隔离；真实65张图片两批入库后详情显示成功65失败0 | 同上 + material-upload-chunking |
| 9 >100更新稳定性 | 600次更新元素移除0、按钮对象保留；约498ms采样进度同步写存储0，后续暂停关键状态即时从localStorage读到PAUSED | 同上 |

新增TaskCenter共8项真实Chrome（含原1项），合并原Uppy15、ZIP恢复14、真实图片1共38项。首轮新增按下按钮断言真实RED；第二轮图片详情被标题误分为upload modal，命中RED后修标题；追加旧实例cleanup测试首跑37通过1失败仅夹具未让withRequestDeadline调度fetch就销毁，resolveDelete未赋值，补await Promise.resolve确保请求实际在途，原断言保持，单例GREEN。最终完整结果下文补记，不能用旧34通过代替当前38。

Node：upload-task-center新增未知阶段持久化RED(true≠false)后GREEN；zip-transfer-observer新增legacy来源RED(0≠72.7)后GREEN。两条旧源码守卫原意为无永久轮询/原ZIP Owner，现改精确断言可清理500ms单次持久化定时器、禁止setInterval及原owner.openTask；未删业务保护。全量Node1239通过0失败0跳过（C:/tmp/utc-node-final-green.log，22.64秒，后续最小CSS/保序优化及模块未就绪反馈已完成8项Chrome定向复测）。

Python定向：API test_v19_multipart_controls/multipart_background_finalize/job_atomic_persistence/import_failure_rollback共15通过；原仓库test_zip_multipart/annotations/audit_v19_partial_import/secrets共34通过；合计49不同测试，0失败0跳过，JUnit C:/tmp/utc-python-api.xml及utc-python-units.xml。无后端生产代码修改，未扩跑无关全仓Python。现有Frontend CI已覆盖TaskCenter Chrome；原ZIP工作流仅补真实图片1项，不新建CI或扩大无关测试。

实际修改：原upload-task-center.js、zip-import-runtime.js、必要main/index/zip-bootstrap缓存与VERSION；对应Node/Chrome测试、原ZIP workflow、本文及四个简短handoff/AGENTS入口。VERSION42.24.375一次递增，TaskCenter66013/main421/ZIP bootstrap与runtime4226366，原Uppy view4226365、app421/styles420不动。旧Uppy/vendor资源未改。

### 6A.3 最终验收与接续

最终本地完整Chrome **38/38通过0失败0跳过（1.9分钟）**，C:/tmp/utc-chrome-final-green.log；600更新487ms、同步进度存储0、元素移除0。最后最小CSS/保序优化复测8/8（13.5秒），增加模块未就绪明确反馈后8/8（12.4秒，C:/tmp/utc-chrome-delivery.log），无扩大或删除断言；Node1239/1239（21.27秒，C:/tmp/utc-node-delivery.log）与Python49通过，原Permanent ZIP guards实际bash退出0，build identity=42.24.375。代码审查两项具体问题已修正并加测试；审查子代理后续因模型容量中止，未宣称取得完整无问题报告，最终差异由主会话逐项核验。

代码首提交[4580756d92f373ccb40301ceeabf23aca045ea06](https://github.com/jorsamj/aixunlianpingtai/commit/4580756d92f373ccb40301ceeabf23aca045ea06)已普通推送。Frontend run[39736091868](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39736091868)的job[119681988102](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39736091868/job/119681988102)在旧“任何setTimeout均禁止”源码守卫失败，未进入Node步骤；不能称首提交全绿。根因是Node测试已适配可清理存储debounce，但工作流重复守卫漏同步。本轮用户明确要求避免每次XHR同步保存，故仅把同一守卫收紧为“恰好一处persistTimer = window.setTimeout(() => persist(), 500)、必须clearTimeout、禁止setInterval”，原PollRegistry调用断言和其他模块禁原生轮询规则全部保留，额外原生timer会失败。修正后的完整Polling guards原步骤已本地实际bash退出0，不删除/跳过测试，不新增轮询或CI范围。VERSION保持375；后续修正SHA的实际CI独立核验。

首代码SHA最终36条Actions：34成功、1失败（上述Frontend）、1取消（Remote Material Import在后续运行替代时取消），如实保留，不计为绿色。修正提交[18dae908ee841e9b874d27a38a0a8a0f946f2c00](https://github.com/jorsamj/aixunlianpingtai/commit/18dae908ee841e9b874d27a38a0a8a0f946f2c00)只改重复CI守卫及本文，不改业务/VERSION。新守卫隔离四变体实际执行：正式debounce允许；额外poll timeout、无clear、额外interval分别拒绝，保护未放宽为任意原生timer。

当前修正SHA额外触发ZIP专项以绑定同一SHA，run[39737134359](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39737134359)：四个job均success，Linux/Windows合同、后端和真实Chrome30（1.4分钟）通过，非沿用4580756d。Frontend run[39736492535](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39736492535)已success：Node1239与真实Chrome191（8.0分钟）通过，job119683289738中600次进度更新685ms仅存储1次、元素移除0。

修正SHA **18dae908ee841e9b874d27a38a0a8a0f946f2c00：22/22 Actions、59/59 Checks全部completed/success**，UTC-01–04代码与隔离CI均已验收；未借用首失败SHA。本轮可交付：稳定按钮/焦点、合帧与节流、即时关键保存、进度来源/未知阶段、稳定排序/rekey、防重复/超时可恢复、图片详情及Modal命中；Uppy仍只使用该唯一中心。

本次最后仅补记本文与AGENTS/四个handoff简短入口，不改业务/VERSION。文档最终HEAD必须再独立读取GitHub全部Actions/Checks，全部success后才交付；最终准确SHA以本文件所在Git提交及该提交Checks绑定，不能继承18dae908结果。独立回执另存当前会话visualizations附件目录`upload-task-center-ci-final-20261022.json`，含首失败、修正及最终文档三组SHA/运行ID与结果。未来接续从6A、upload-task-center.js、zip-import-runtime.js及performance浏览器测试开始，勿新建上传/Modal/Loading/任务Owner，不重复实施已验收功能。

生产网络/任务规模/真实素材仍NOT VERIFIED；约0.5–0.7秒600更新为隔离浏览器采样，不宣称生产延迟/吞吐或生产问题已发布。所有本轮写入在隔离测试目录。本轮不部署，不删除生产素材，不改变正式GT、历史任务及数据库。

## 6. Uppy阶段接续（历史；最新补充以6A为准）

本轮代码、隔离PoC、正式入口/回退、兼容性报告和修正SHA CI已完成；无需重复开发Uppy或上述恢复功能。最终文档HEAD自身的全部检查仍按5.6交付门槛核验，以GitHub绑定该SHA的实际结果为准。VERSION42.24.374，只在唯一长期分支提交推送，未部署生产。

后续会话从本文件、static/modules/uppy-zip-adapter.js、uppy-zip-view.js、zip-import-runtime.js及zip-import-bootstrap.mjs开始。官方制品更新必须同时更新精确pins、原始哈希、许可证/manifest与离线check；不可手工改minified文件。运行`npm ci`、`npm run verify:uppy`、`node --test tests/frontend/*.test.mjs`；本地临时后端通过`npx playwright test tests/browser/uppy-zip-poc.spec.mjs tests/browser/zip-import-refresh-recovery.spec.mjs`复现完整29项，训练兼容回归用两份training-create-first-open/training-quality-reports。Python文件/数量见5.3/5.5，原CI逐项覆盖见5.6链接。

禁止重复建设上传/任务/Modal/轮询；不得把Uppy交付成功写成Worker入库成功。正式入口可用“使用原上传界面”立即回退，供应静态资源失败也回退；无需改生产配置或数据。禁止未经授权的部署、生产服务测试、真实素材删除或GT/历史变更。仅生产代理/超大ZIP/实际网络和发布后现场仍待独立授权验收，不能把隔离测试外推为已生产发布。
