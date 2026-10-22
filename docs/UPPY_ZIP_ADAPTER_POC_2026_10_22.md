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


## 6. 接续

本轮代码、隔离PoC、正式入口/回退、兼容性报告和修正SHA CI已完成；无需重复开发Uppy或上述恢复功能。最终文档HEAD自身的全部检查仍按5.6交付门槛核验，以GitHub绑定该SHA的实际结果为准。VERSION42.24.374，只在唯一长期分支提交推送，未部署生产。

后续会话从本文件、static/modules/uppy-zip-adapter.js、uppy-zip-view.js、zip-import-runtime.js及zip-import-bootstrap.mjs开始。官方制品更新必须同时更新精确pins、原始哈希、许可证/manifest与离线check；不可手工改minified文件。运行`npm ci`、`npm run verify:uppy`、`node --test tests/frontend/*.test.mjs`；本地临时后端通过`npx playwright test tests/browser/uppy-zip-poc.spec.mjs tests/browser/zip-import-refresh-recovery.spec.mjs`复现完整29项，训练兼容回归用两份training-create-first-open/training-quality-reports。Python文件/数量见5.3/5.5，原CI逐项覆盖见5.6链接。

禁止重复建设上传/任务/Modal/轮询；不得把Uppy交付成功写成Worker入库成功。正式入口可用“使用原上传界面”立即回退，供应静态资源失败也回退；无需改生产配置或数据。禁止未经授权的部署、生产服务测试、真实素材删除或GT/历史变更。仅生产代理/超大ZIP/实际网络和发布后现场仍待独立授权验收，不能把隔离测试外推为已生产发布。
