> **2026-10-30 / 42.24.434 AI 自动标注真实单图试跑**：433 的代码提交 `80502b0d` 精确 22/22 GitHub Actions、真实 Chrome 307/307 已验。本批在原 v60 AI annotation API/Worker 适配器上增量增加单素材显式真实试跑，输出不会创建 Task/Candidate 或覆盖 GT；创建区同层选图、错误重试与结果变更失效。详细测试与遗留见 [唯一 AI 计划](superpowers/plans/2026-10-16-ai-annotation-cleaning-scope.md)；本批最终 SHA CI、真实远程模型和 OSS 性能未验，未部署。

> **2026-10-30 / 42.24.429**：428 基线 `b13d8705` 已核准确 38/38 GitHub Actions 全绿；413/415/416/425/427 的 P0 Owner 已存在。此次原 TrainingSubmit 迟到成功/核验结果不再提示到替换的训练弹窗，原持久任务/GT/幂等不动；生产 A800 磁盘、请求 P50/P95、角色精确冷索引、ZIP 恢复、多类别 Worker 与副本清理均未现场验证。见 [唯一 P0 进度](performance/2026-10-29-p0-followup.md)，429 自身 SHA CI 待推送核验，未部署。

> **2026-10-29 / 42.24.418 素材选择器 CI 合同测试纠正**：`a694ee4d`／417 在 Training Material Picker/contracts 再次因路由 introspection `StopIteration` 失败（81/82 后端通过，Chrome Job 通过），因此 417 不是通过版本。418 移除该失败用例对 `.routes` 内部结构的依赖，调用已有同路由公共 HTTP 合同并断言迭代空选材的真实统计、免角色扫描；本地 HTTP Portal 存在超时等待故未宣称该用例本地通过，准确新 SHA CI 待验，生产和运行时代码未动。详见 `performance/2026-10-29-p0-followup.md`。

> **2026-10-29 / 42.24.417 素材选择器 CI 单测纠正**：`52c3ecf7`／42.24.416 经 GitHub 完整只读检查为 **29/30 Actions 通过**；唯一红项 Training Material Picker/contracts 中 1/82 后端用例因 `TestClient.app.routes` 路由枚举 `StopIteration`，real Chrome 已通过。417 定向让测试从原始 FastAPI app `.routes` 找真实 endpoint，不变更运行时代码、GT/训练提交合同或数据库。新 SHA CI/生产待验，详见 `performance/2026-10-29-p0-followup.md`。

> **2026-10-29 / 42.24.416 迭代角色页 P0**：原 `/role-page` 在继承版本的只读角色合同内逐页完整 SHA256 `best.pt`；本批仅角色预览和选材意图显式省略哈希，最终提交/Worker 冻结照常真实 SHA256。原诊断增加角色/历史/页使用关系分段；12k/50k 候选与现场 22.87s 根因仍待实测。准确 CI/生产未验，未部署。详见 [唯一台账](performance/2026-10-29-p0-followup.md)。

> **2026-10-29 / 42.24.415 P0 合同纠正**：CI 证实 414 空摘要 `eligible_total=null` 违反既有真实全池总数合同，已回滚；只保留 413 前端零选材免请求、后端空态不进入训练提交角色校验。修正 `_IncludedRouter` 测试枚举。精确新 SHA CI 与 A800 仍待核，未部署。详见 [唯一台账](performance/2026-10-29-p0-followup.md)。

> **42.24.414 历史红项（415 已回滚）**：曾试图直接让 API 空摘要跳过整池统计并把总数置为 `null`；旧合同不允许，不能视为已交付优化。

> **最新 P0 接续（2026-10-29 / 42.24.413，本地已验证、CI/生产待验）**：`training_options` 已从旧服务器请求期串行健康检测、Paddle configs/weights rglob、项目训练历史 `job.json` 扫描转为有界快照/轻量索引；迭代 `selection-summary` 的 `image_ids=[]` 合法，前端零选材本地空态。旧服务器检测缺失/过期显示未知、需显式检测；旧 Paddle 配置需手动重新启用形成新快照。Python 137/137、Node 1404/1404，现场 26.5s 分段、`role-page`、P50/P95 尚未取证。详见 [P0 续批台账](performance/2026-10-29-p0-followup.md)；最终 SHA/CI 必须独立核验，未部署。

> **最新接续（2026-10-29 / 42.24.412）**：训练素材状态及新增标签正样本证据修复，业务/测试提交 `86c83c30fd2056f61dd58fb79772bc1f3cc86cbc` 已通过精确 SHA GitHub **21/21 套件、57/57 Job、浏览器导航 107/107**；纯文档补记提交自己的 CI 需再核，仍未部署生产。详情见本文末尾及 [训练工作台专项](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)。以下 42.24.411 小节是上一批历史。

## 2026-10-29｜性能诊断与万级素材/GT 隔离验收（42.24.411，代码 SHA CI 全绿）

唯一长期开发分支 `feature/external-algorithm-publishing`。起点远端 HEAD `9e6edbb38d1db54731c00e058e31f771c1f1c854`、VERSION `42.24.410`、干净工作区；精确基线 GitHub Actions **24/24**、Checks **65/65** 均成功。目标版本 `42.24.411`，最终提交及其 CI 必须在推送后另验；未部署生产。

代码提交 `5ddc516499b99c80b6fe980b64a6d84c860aa466` 已通过 GitHub 精确 SHA 检查套件 **25/25**、Job Checks **68/68**，Chrome/Windows 均 success；Blob 与完整 Tree 校验一致。此后更新进度文档的纯文档提交 SHA/CI 需单独确认，不借代码提交绿色；当前 HEAD 以 `git rev-parse HEAD` 为准。生产现场仍未验收。

- **P0-01 已开发待验证**：在原 opt-in `MC_PERFORMANCE_DIAGNOSTICS=1` 增补现有 Repository SQLite execute/fetch/transaction 计时、外部畅联鉴权等待与真实 HTTP、缓存 SHA 文件读取，以及 v63 安全路由类别。原 API body、Token singleflight、正式 GT/训练资格不变；SQL/项目/URL/凭证不记日志，未知锁等待仍为 `null`。本机首次新增诊断测试 RED（原模块无 `connect_sqlite`），GREEN 及 API 合同通过；浏览器/生产真实 P95 未验。
- **P0-02 已开发待验证**：隔离 12k Material+GT 全标签/角色/深页/统计次数与 EXPLAIN 新回归通过，50k 冷/热角色及 6k 两类 SQL 性能对照完成。对 `%LIKE%` 的延迟取页未见稳定提速，故不改 SQL、不加索引/FTS/迁移，不破坏原材料/GT/任务真值。
- **测试**：相关 Python **208/208**，原 FastAPI 性能 API **3/3**，完整 Node **1396/1396**；本机 Chromium 不可用，但代码 SHA 的真实 Chrome CI 已通过；文档补记提交须再验。`AGENTS.md` 长期规范没有变化，因此按文档管理规则不堆日志。
- **剩余 P0**：P0-03 浏览器代理/网络服务端同 ID 采样（待开发）、P0-04 旧训练跨 Worker 与归档现场验收（已开发待验证）、P0-05 算能等芯片真实 SDK 耗时与 UNKNOWN（已开发待验证）。P1：工作副本候选清理、普通历史 Train/Val/Test 原图溯源均待生产只读取证，禁止删除、重建或伪造。
- **下一轮**：先核准确新 HEAD 与 Actions/Checks；读取唯一主进度 `docs/performance/2026-10-29-p0-followup.md` 顶部；按 P0-03→04→05 继续，生产 HAR、SQLite 冷/热 P95、真实 SDK 均未验证，不能凭合成数据宣布可部署或根因确定。不合并 main/Tag/Release、不 force push、不自行部署。

## 2026-10-29｜P0 新畅联 API 鉴权网络往返消除（42.24.410 / LOCAL GREEN、CI 待核）

基线远端 `1d027803`／42.24.409；原 v63 路由持有一个 `ExternalAlgorithmPlatformService`，但每次业务请求仍创建一个全新 `ChangLianClient`，每个客户端在首个业务 GET 前独立签名并申请 Token。新增仅进程内/服务内、已保存凭证生效的单飞缓存，作用域为 URL、Key/Secret、两个鉴权端点的 SHA256；不共享 HTTP Session、不持久化 Token，不缓存草稿配置。配置变更、显式退出、HTTP 401 清缓存，不自动重试写请求。8 个同时 GET 原产生 8+8 次认证，当前仅 1+1，业务 GET 仍为 8；无生产耗时推断。受影响 Python 137/137、完整 Node 1396/1396 通过；发版、准确 SHA GitHub CI 和真实远端延迟仍须核验。真实 `%LIKE%` 查询 4 万行对照没有显著改善，保留原 SQL。A–F 详见 [P0 性能续批](performance/2026-10-29-p0-followup.md)。不部署生产、不改数据库、不合并 main、不强推。

## 2026-10-29｜P0 负样本池并发筛选修订保护（42.24.409，LOCAL GREEN / CI 待核）

接续 `3fdc5f33`／42.24.408，已独立核实 23/23 Actions、61/61 Checks 成功。原 GT 选择器和训练角色页在先计算负样本池成员、再读取正式素材页期间允许跨请求池修改，返回结果可能混用旧候选名单与新修订号。本批在原版本快照/现有 revision 读点增加精确比较，不一致明确拒绝并提示重试；没有新增数据表、任务、调度或外部操作，原池成员资格和正式 GT 判定不变。新增两个先失败后通过的并发保护测试；受影响 Python 35/35 与完整 Node 1396/1396 通过。准确新 SHA 的 CI 和真实生产性能仍须核验，未部署生产。专项详见 [P0 性能记录](performance/2026-10-29-p0-followup.md)。

## 2026-10-29｜P0 GT 翻页快照元信息收敛（42.24.408，LOCAL GREEN / CI 待核）

接续 `95e52d32`／42.24.407，修复正式 GT 翻页读取后跨新连接获取负样本确认数和池修订号的问题。现在从原 Material + `annotation_gt` 同一个 `BEGIN` 快照读取，避免额外打开两个 SQLite 连接，以及并发写入时将旧页与新修订号混合；兼容无可选历史表的旧项目。对原正负样本资格、筛选、标注、训练任务、数据库 schema 均无更改。原路径新增一条先失败后通过的保护性回归，受影响 Python 33/33、完整 Node 1396/1396 通过。远端最终 CI 仍待准确 SHA；真实生产 HAR/SQL/网络耗时未采样，不宣称全部 P0 现场验收完成，不部署生产。专项 A–F 见 [P0 性能记录](performance/2026-10-29-p0-followup.md)。

## 2026-10-29｜P0 正式 GT 计数与性能诊断完善（42.24.407，LOCAL GREEN / CI 待核）

`f45e8934`／`42.24.406` 已 25/25 GitHub Actions、65/65 Checks 全绿，未部署。接续 [专项 A–F](performance/2026-10-29-p0-followup.md)：GT 选择器的重复 `COUNT(*)` 以素材/正式标注两个独立 revision、两份 SQLite 文件身份和精准筛选哈希缓存，128 项有界；新增 RED→GREEN 覆盖跨页复用、GT 编辑和素材状态变更两次失效。保持原 AnnotationRepository 的真值、负样本、标签、排序和训练角色。默认关闭的性能诊断现在显示素材列表/计数与显式资源检测的独立耗时，不记录资源身份、SQL、API Key，也不主动触发 SDK/远端探测。本轮本地 Python 与 Node 结果、最终 SHA CI 以专项最新记录和实际核验为准；生产 HAR/远端耗时/真实规模仍须现场只读验收，禁止生产自动部署/数据修改。

## 2026-10-29｜P0 素材深分页与筛选计数（42.24.406，LOCAL GREEN / SHA CI 待核）

延续 [P0 任务记录](performance/2026-10-29-p0-followup.md)。本批只调整 `MaterialRepository` 和正式 GT 选择器的分页 SQL：在无 payload 过滤条件时先用窄索引翻页，再只对当前页补取 JSON；`LIKE '%...%'`、JSON 过滤仍保留原查询计划，所有排序、页码、cursor、total、角色及负样本业务语义不变。筛选总数按 SQLite DB 身份及 revision 做 128 项有界跨请求缓存；第二 Repository 模拟其他 Worker 提交后缓存失效。旧清洗确认测试新增针对原有效范围校验的 mock，生产的证据校验保持不变。6000 条合成样本的深页旧/新约 0.18/0.09–0.10 ms，仅用于证明路径效果，绝不代表生产数据。定向回归和最终 CI 以本轮实际命令/准确 SHA 为准；网络 Stalled、畅联云/芯片外部检测、正式 GT 大库及线上 P95 尚待只读取证；不部署、不触碰正式数据。

## 2026-10-29｜P0 训练只读热路径与素材用量索引（隔离测试通过／最终 SHA CI 待验）

基线 `e777983c845934af0a4e8694b3d3ba53c1b9a080`／VERSION `42.24.404`；本批版本 `42.24.405`。延续 [P0 性能专项](performance/2026-10-29-p0-followup.md) A–F 跟踪：GET `/jobs`、项目详情、训练报告和 v53 启动快照不再启动旧训练/写历史索引/触发版本归档；旧队列仍由独立启动维护线程按项目及跨进程文件锁继续恢复，旧版本归档仍保留原 CAS 并串行化。原有 Task/Durable Owner 和正式模型/素材数据不变。训练素材使用 token 通过原 SQLite 复合主键批量精确定位、先去重窄 ID 再读原记录，项目隔离与重复身份不变；无新表、无索引迁移。隔离 Python 189/189（后补保护 9/9）、完整 Node 1396/1396；高密度样本旧/新 30.33/0.42 ms 是本地中位数，非生产承诺。首次 `cd04e635` 的 Release Regression 发现旧报告测试夹具不接受新增只读参数（373 通过、7 失败），已保持生产合同，仅纠偏夹具并单文件 10/10 通过；修正后最终 SHA 的 CI 仍待核验。生产 HAR、旧队列真实现场未验；未部署、未碰生产数据、不宣称所有 P0 关闭。

## 2026-10-29｜训练回收与异常证据定向修复（LOCAL VERIFIED / CI及生产未验证）

[唯一审计报告](docs/TRAINING_WORKSPACE_EVIDENCE_AUDIT_2026_10_29.md)：远端40327743/VERSION399隔离基线；原Lifecycle补异常outcomes/框证据归档、显式ID与SHA保护、自动阻塞/归档失败回执。定向71通过/1系统symlink权限跳过，真实原API清理前后相同字节验证通过。用户已授权提交到开发分支；本次提交CI待核验，未部署；保留其他工作树WIP。Checkpoint恢复、未知历史所有权继续保护，远端最终回收/生产启动与接口性能NOT VERIFIED，不能称全量最终回收已验收。无前端/DB/版本更改。

## 2026-10-29｜全平台性能第一阶段审计与两链轻量修复（代码及隔离CI已验收）

[唯一专项](docs/PLATFORM_PERFORMANCE_AUDIT_2026_10_28.md)记录220历史/1000素材真实隔离计时。原/jobs仅all-Durable同请求复用、终态N+1消除，legacy后读/活动fresh get保留；素材usage重复revision连接移除，冷角色全局计算保留且不宣称整体提速。默认关闭纯ASGI标量诊断/Request ID；VERSION399，定向Python、Node22与Chrome1通过，未全仓/生产/GPU操作。其他登录/算法/素材/设备/转换/上传仅审计与排序，下一步须用户确认；5944/模板/其他工作树保留，代码4cd4e3e47c3a1e65910345bb3924b2ec2ad55985准确47/47 Actions、130/130 Checks成功；文档自身HEAD的CI独立核验。

## 2026-10-28｜模型版本转换模块优化（代码及隔离CI已验收）

[唯一专项](docs/MODEL_VERSION_CONVERSION_GOVERNANCE_2026_10_28.md)记录原Owner渐进加载/单资源300秒观察与检测、20条服务端历史分页与只更新活动任务、CSC四矩阵及外部参考ZIP。VERSION398；真实微型ONNX/参考CLI、远程合同与提交回滚、定向Node41及Chrome通过；受控旧1380ms/新36–79ms不代表生产。CSC未安装设备、applied=false/板端NOT VERIFIED；不部署/生产操作，5944/模板与其他工作树保留。代码f2af4af35e45b86920bbddcc63aa13df816d178b准确41/41 Actions、115/115 Checks成功；文档自身提交Checks独立核验，勿借旧绿。

## 2026-10-28｜目标负样本、池管理与真实YOLO导出（代码及隔离CI已验收）

[唯一专项](TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md)顶部记录目标/素材版本绑定确认、原GT不变、Prepare实际空标签及正样本门槛、池关联与独立管理分类、原Picker/三步提交及按需CSC预览。VERSION397；真实导出、必要Python/Node及Chrome相关场景分批通过；最终代码92203c8c准确21/21 Actions、57/57 Checks成功，旧失败及修正留痕。本次文档自身HEAD另核CI，不借旧绿。无生产/GPU操作；旧V1–V3、原Task/Draft/GT/Storage保留，5944及其他工作树/WIP不动。未验证NAS/OSS/真实模型效果，勿将池成员当所有算法的已确认负样本。

## 2026-10-28｜三步训练工作台、可信素材历史与四预设CSC（代码及隔离CI已验收）

[唯一专项](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)顶部记录正式表单先开/独立加载、稳定分页标签、原Picker筛选恢复、Task库可重建使用投影与祖先/同源隔离、train-only四CSC及原报告实际数量。VERSION396；业务e1ed27bf准确39/39 Actions、109/109 Checks成功，Node1386/1386、原Chrome303/303通过；截图/四金值/隔离性能及失败修正见专项。本次纯文档HEAD自身CI另核，不借旧绿。原Task/Draft/Submit/GT/Storage及fencing不重建；5944、a741075c WIP/模板及其他工作树保留。无生产操作/真实GPU；NAS/OSS/摄像头/模型效果NOT VERIFIED。接续先核对专项及准确HEAD，勿重复建设。

## 2026-10-28｜上传与场景进度UI/高级Tab定点修复（代码及隔离CI已验收）

[唯一专项](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)顶部记录隐藏输入重复美化、原队列预览/URL释放、scenario唯一批次进度及四组下划线Tab。VERSION395；定向Node120及Chrome7种场景通过，原业务Owner/路由/后台合同保留。代码ed19d9f1准确22/22 Actions、58/58 Checks，Node1381/Chrome302通过；本次纯文档HEAD自身CI另核，不借旧绿。生产推理/母模型大文件未验，不部署。原a741075c/退役WIP/5944与其他工作树全部保留。

## 2026-10-27｜场景检测创建恢复（代码及隔离CI已验收）

[唯一专项](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)顶部记录原Task异步准备/幂等身份/暂存原图恢复、lease与模型引用保护、真实阶段及稳定原图预览。VERSION393；代码28fbea92准确35/35 Actions、97/97 Checks成功，Node1377/1377、Chrome301/301；旧失败与修正留痕。文档提交自身HEAD另核CI，不借旧绿。生产OSS/GPU/性能NOT VERIFIED，不部署；5944/其他WIP保留。本机工具断连后仅文档经远端安全快进提交，接续先fetch保护本地状态，从专项与原Owner继续。

## 2026-10-27｜训练SQLite锁、Lease与跨恢复计时（代码及隔离验收完成）

[唯一专项](TRAINING_SQLITE_LEASE_TIMING_2026_10_27.md)记录有限忙重试/确认期限、原fencing/GPU保护、短事务及登记前启动校验；原job执行片段/三时间/UTC/最终Worker与列表详情同步。VERSION392，d37400c6准确47/47 Actions、128/128 Checks成功，Node1357/Chrome301通过；末次ETA未知保护及文档自身HEAD交付前另核，不借旧绿。实际生产锁持有者、原任务首末/累计/Worker及真实GPU未核准；不部署/改生产，原ZIP/WIP/5944/模板保留。接续仅按专项的定向只读证据计划，不重复建设Owner或回填推测时间。

## 2026-10-26｜ZIP任务记录安全P0（代码及隔离CI已验收）

[唯一专项](ZIP_IMPORT_RECORD_SAFETY_2026_10_26.md)记录根因、RED/GREEN与接续。原停止栅栏保护活动删除/提交/迟到写入，终态轻量证据归档与临时清理分离；原ZIP/任务中心UNKNOWN、退避及跨标签页恢复，持久写错/死前驱有诊断。VERSION391，必要Python44及窄修复2、Node101、Chrome5不同场景通过，独立审查问题已闭合；业务代码f181a9e0准确22/22 Actions、59/59 Checks成功，Node1355/1355、原Chrome298/298；本次纯文档及新增Chrome接线自身HEAD交付前另核，不借旧绿。生产两任务入库及事故原因未知；不生产操作、不重建Owner，原WIP/5944/两份模板测试保留。

## 2026-10-26｜FiftyOne可选智能分析（代码及隔离CI已验收）

[唯一专项](FIFTYONE_SMART_MATERIAL_AUDIT_2026_10_26.md)顶部为接续：VERSION390，代码fd850e62准确23/23 Actions、58/58 Checks成功；三个原区域/原Task与GT Owner/默认关闭、真实Brain、只读复核及原保存已接通。旧CI失败及修复留痕。超过2000张完整分析未实现；生产许可、Linux/NAS/OSS/真实模型与生产性能NOT VERIFIED，早期PoC删除被自动审批拒绝保留。原WIP/5944/两份模板测试保留，不生产操作。本次纯文档HEAD自身CI另核。

## 2026-10-26｜ZIP旧数据零损坏补验（隔离及专项CI已通过）

[唯一专项新增14条矩阵](ZIP_IMPORT_METADATA_PERFORMANCE_2026_10_26.md)。基线4ff26779/VERSION389；历史71f真实schema5 DDL及SQLite备份，全业务表/原图/GT/Snapshot/任务与模型引用、缺dataset default及旧claim、升级中断/恢复2场景通过；相关13/13，补验57052f30准确22/22 Actions、56/56 Checks成功。文档摘要换行说明修正自身HEAD另核。仅测试/夹具/CI/文档，无业务代码或版本变更；索引5→6必要性、首次锁风险与备份回退已明示，未生产部署/迁移。最终提交自身CI未通过不得建议上线，旧绿色不替代；原WIP/5944/模板保留。

## 2026-10-26｜ZIP导入素材索引性能（代码及隔离CI已验收）

唯一需求/设计/性能/失败及接续：[ZIP性能专项](ZIP_IMPORT_METADATA_PERFORMANCE_2026_10_26.md)。VERSION389，代码69451cbb准确48/48 Actions、129/129 Checks及Linux真实HTTP10k成功；本地A–D原逐图全量1001/10001→0，D1855.60→321.15秒，Windows完整HTTP10k445.52秒。schema6稀疏索引/原锁及恢复保留、只读兼容5/6；CRT EACCES读冲突有界恢复，无虚假0。文档自身最终HEAD另核CI；生产、大图及NAS/OSS/S3未验，不部署/改生产；原标注WIP/5944/模板测试保留。

## 2026-10-26｜文件访问与外部同步删除P0（代码及隔离CI已验收）

唯一需求/设计/进度/验收：[P0安全专项](P0_FILE_ACCESS_EXTERNAL_SYNC_SAFETY_2026_10_26.md)。基线60dd80d8/VERSION387，远端一致；先受控文件及旧地址兼容，再同步完整性/确认/原任务安全清理和UI。P001与P002已实现并经独立复核，VERSION388，代码da4de467准确22/22 Actions、59/59 Checks、Node1342/1342与Chrome291/291成功；Linux文件安全50/50无跳过，登录Chrome2/2。文档自身最终HEAD另核CI；产品删除权威契约未取得，自动确认默认关闭，版本remove不是产品删除证据；不部署、不轮换生产密钥/删生产数据，原标注WIP/5944/模板测试与其他工作树保留。

## 2026-10-25｜训练创建Loading与异常恢复（代码及隔离CI已验收）

唯一需求/根因/测试/接续：[训练创建专项](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)顶部。原submit全过程try/finally、独立最终DOM恢复、VERIFYING/稳定UNKNOWN及原ID查询、准备请求截止/旧项目和Modal隔离、后端业务码透传与锁竞争核验；VERSION387。原标注工作区4个未推提交与WIP、5944及两份模板测试全部保留，隔离修复不混入；本地Python11、最后受影响Node95、Chrome56不同场景通过；审查补齐409/5xx正文中断防重及外部核验超时重试，最终代码382c1b95准确26/26 Actions、68/68 Checks成功，409损坏JSON最小安全修正已验收；文档最终HEAD另核。不部署、不改生产数据或启动训练。

## 2026-10-24｜高级功能四入口整合（代码及隔离CI已验收）

唯一映射/设计/进度/截图：[前端治理记录顶部](frontend-legacy-audit.md)。实际7项收敛为算力与节点、模型转换环境、AI辅助配置、存储管理；迁移收纳存储Tab，对接与只读浏览保留独立。原state.page/业务Owner/API/轮询不变，无后端/数据库改动；导航取消reason沿原PageRequestScope隔离。VERSION386/cache434；f95e221f准确CI23/23 Actions、60/60 Checks成功，Node1331/1331、Chrome267/267通过，旧失败及关闭证据见记录。文档自身最终HEAD另核Checks。5944与两份模板测试保留；不部署、不改生产数据，真实GPU/NAS/OSS/对接生产环境NOT VERIFIED。

## 2026-10-24｜大模型Chat/Responses协议兼容（代码及隔离CI已验收）

唯一需求/设计/进度：[协议专项](LLM_API_PROTOCOL_COMPATIBILITY_2026_10_24.md)。原provider兼容Chat/Responses，准确端点识别、受控结构化降级、安全错误证据；原M4高级配置/Bootstrap投影同步，连接测试与正式v60同工厂及字段校验。VERSION385/cache433；最终代码982069c8准确CI47/47 Actions、128/128 Checks成功，协议44、API55（含配置11/正式E2E4）、Node1328、Chrome265通过。文档自身最终HEAD另核Checks。5944及两份模板测试保留；真实GLM/收费接口NOT VERIFIED，发布前须授权环境实测，不部署。

## 2026-10-24｜ZIP自动标签确认与重复窗口治理（代码及隔离CI已验收）

唯一记录：[Uppy专项顶部](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。原Runtime统一自动确认/主动关闭抑制/成功立即关所属内容，旧列表不倒退；Uppy/旧入口同Owner，原选择层交接及复用节点保护，多ZIP独立顺序，完成后整理窗口改手动。VERSION384；代码/测试610878cd准确CI23/23 Actions、60/60 Checks成功，Chrome264/264、Node1328/1328；ZIP相同业务代码52939779的独立Chrome41/41。历史失败和最小Python9/Node/Chrome证据见专项，文档自身最终HEAD交付前另核Checks。5944及两份模板测试保留，无后端/GT合同变更或生产操作。

## 2026-10-24｜创建训练弹窗滚动修复（代码及隔离CI已验收）

唯一记录：[训练创建专项顶部](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)。原CSS收敛高度/单一layout滚动、标签自然展开、footer真实占位；无JS或后端/参数/调度变更，important减少15。五视口真实wheel5/5、原标签提交Chrome1/1及Node27/27通过；VERSION383，CSS cache4226355，代码f5ba6192准确CI 36/36 Actions、99/99 Checks通过，文档最终HEAD自身另核Checks。5944及两份模板测试保留，未部署/未启动训练。

## 2026-10-24｜普通图片上传同一需求复核

[唯一专项](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)顶部已记录当前b1b32a44/VERSION382复核：既有本地Uppy/原multipart/本批确认/clean-ready-pending/标注与恢复直接复用，无业务代码变更。新Python31、Node25、真实Chrome五图/部分失败2项通过；原每批一次清洗限制保留，不冒充多轮追加已实现。代码SHA21/21 Actions、55/55 Checks通过；本次文档新HEAD另核CI。5944及两份未跟踪模板测试保留，无生产操作。

## 2026-10-24｜P1跨标签负样本与首次训练（代码及隔离CI已验收）

唯一需求/进度：[训练质量专项P1](TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md)。任务标签与原始标签分离，正/已确认负/待审核共享后端合同；人工有限批审保留原框、CAS/源SHA与事务审计；新V3纯负保留像素/空YOLO、混合与历史V2保护不变。VERSION382，必要Python/Node与Chrome四个独立场景通过；代码cd8cde89准确CI 23/23 Actions、60/60 Checks成功，最终文档HEAD自身另核Checks，详见专项回执；不自动确认/丢弃/训练，不生产操作。5944及两份未跟踪模板测试保留。

## 2026-10-23｜普通图片Uppy与本次上传处理（代码及隔离CI已验收）

唯一进度：[Uppy专项普通图片节](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。原multipart64张/128MB顺序Owner、UploadBatchStore及唯一任务中心复用；本地中文Uppy、48条本批确认页、真实失败/待核验、刷新恢复、原清洗/标注已接通，ready不写GT。Python31、必要Node及Chrome五图/部分失败/65分批/ZIP冒烟通过；VERSION381，修正646aeb0a实际22/22 Actions、58/58 Checks、Chrome250/250与Node1322/1322通过；本次文档自身HEAD另核Checks。每批仅一个原清洗任务限制保留；生产未验证/未部署/未写入，5944及两份模板测试保留。

## 2026-10-23｜旧素材全面检查体验修复

[唯一专项](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)顶部为接续依据。一次开始顺序50条、真实汇总及25条明细分页、暂停/刷新/失败恢复已实现；原迁移单独确认，检查不改正式数据。VERSION380，Python15/Chrome3/版本9通过，代码6f663e1c实际38/38 Actions、102/102 Checks通过；本次文档新HEAD另核。原图仅逐条检查时点，库外原位改写/无版本GT不冒充全库原子证明；5944及两份模板测试保留，未生产操作。

## 2026-10-23｜P2模型深度评测（代码及隔离CI已验收，生产未验证）

唯一需求/进度/限制：[场景评测专项P2](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)。A1只读冻结信任、A2正式匹配证据和有界框、B同基准逐图变化、C原反馈/已审核候选/训练草稿衔接已提交；VERSION42.24.379。原场景Chrome28、Node82及必要Python分批通过，未跑全仓；dHash/连续帧/审核版本缺历史证据保持未检查或未知，框证据上限200图/每层120。5944和两份未跟踪模板测试保留，不部署/不生产写入/不自动训练。代码9280实际21/21 Actions、55/55 Checks通过，Node1311/1311、Chrome248/248；本次文档自身SHA交付前另核CI，不借旧绿；不重建存储、GT、Task或Candidate Owner。

## 2026-10-23｜存储生命周期第二阶段：代码及隔离CI已验收

唯一进度：[生命周期专项](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)顶部S2矩阵/17项回答/最终回执。VERSION42.24.378，代码42339bd4da00d5f0ea082f2fd16791564bdb990a实际23/23 Actions、62/62 Checks、Node1305/1305及Chrome244/244通过。排队仅索引、lease后本地/远程物化、原Scheduler安全回收、失败详情/历史只读、临时元数据工具、缩略图及真实存储口径已验收；成功未知Checkpoint保留，只释放input。原图物理GC仅受控local离线，NAS/OSS/在线不开放，真实生产量/外部存储/GPU未验。5944及两份未提交模板测试保留，无生产操作。本次文档自身HEAD必须另查准确CI，不借旧绿。下一步按专项生产前只读计划和独立授权接续，勿重建Owner或扩大模板。

以下为历史其他专项入口，存储旧阶段结论以最新唯一专项为准。

## 2026-10-22｜训练模式、创建流程与评测可信度（审计进行中）

唯一综合进度：[训练模式专项](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)顶部2026-10-22节。基线3cc331f2/VERSION377已fetch且干净；先审计服务端预设/参数快照、阶段val与独立Test、按需准入，再P1创建及管理、CDE增量和P2。已发现旧尺寸优先及预设隐式阈值停止，尚未修复/新测试/CI；原场景/素材/标注Owner复用。禁止生产部署/数据/权重/GT写入/真实GPU，其他工作树保持。

## 2026-10-22｜场景评估、素材与标注UI（代码及隔离CI已验收）

唯一需求/进度/问题/截图：[本轮专项](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)。P0分别提交1f606d30/13c70368/b8d04f04；正式训练资格贯穿原Worker/Agent、双模式内联框证据、素材同Owner网格/列表、标注唯一审核/正式色/居中已实现。P1复用原ECharts与严格同基准比较；VERSION42.24.377，最终代码42bf33b2实际23/23 Actions、60/60 Checks、Chrome239/239；本地Node1297/Python213通过，广泛352曾339通过13失败后逐项fresh通过，未宣称重跑全绿。本次文档/旧fixture补提自身完整SHA须再核CI，最终回执与限制见唯一专项。未生产部署/数据/权重写入/GPU；从唯一专项接续，禁止重复建Owner，生产真实精度与许可仍需独立核验。

## 2026-10-22｜训练创建按需准入与Loading（代码及隔离CI已验收）

唯一专项：[生命周期治理第十一节](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)。打开/编辑保持安静，仅“开始训练”触发原完整准入与创建；有效阻塞才显示原因，草稿/项目/Modal过期及网络错误隔离。旧自动弹窗/自动正式复检触发被本轮用户要求覆盖，后端与删除GT合同保留。VERSION42.24.376，Node1239通过/Python126通过2环境skip，本地Chrome59独立场景分批通过；实现c0163347287beeca1e3e52fa0e42c71c423527bc实际41/41 Actions、114/114 Checks通过，CI Chrome207/207及first-open15/15；本次文档HEAD自身仍须独立CI。禁止改Uppy/UploadTaskCenter实现，未生产部署/写入/GPU。接续从原submit/summary及新增on-demand Chrome开始，完整RED/问题/限制见唯一专项。

## 2026-10-22｜原 UploadTaskCenter 稳定性修复（代码及隔离CI已验收）

唯一专项：[Uppy专项6A](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。按钮按action原位保留、进度合帧/500ms保存、关键状态即时保存、稳定rekey/order、原ZIP进度来源与图片详情均在原Owner修复。真实RED及追加审查问题已记录；VERSION42.24.375，Node1239/Python49/Chrome38及收尾定向8通过；18dae908ee841e9b874d27a38a0a8a0f946f2c00实际22/22 Actions、59/59 Checks通过，CI Chrome191/30；首守卫失败及修正已留痕，本次文档HEAD仍须独立核验。无新任务中心、上传控制器或数据库，未操作生产，其他工作区不动。接续先看6A，勿将旧Uppy验收冒充本轮。

## 2026-10-22｜Uppy ZIP适配（代码及隔离CI验收完成）

唯一需求/进度/接续：[Uppy专项](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。固定Core6.3.0/Dashboard6.0.2/locales5.3.1本地离线；原ZipImportRuntime/v19/TaskCenter/Worker单Owner，PoC14项通过后正式按钮接Uppy并保留原UI回退。VERSION42.24.374；本地Node1237/Python82/Chrome29+15通过，修正2ae6bdf71c24096e4ab75db5696c4609e6832678实际23/23 Actions、62/62 Checks通过（CI Chrome184/15/29）。首提交39/40及旧quality漏适配自动诊断的真实修复均留痕；本次仅补验收文档，其最终实际HEAD仍按专项5.6独立检查GitHub绑定结果。传输交付不等于入库；许可/711KB制品/生产未验证限制见专项。禁止生产部署或生产素材测试，勿重复建设上传控制器。

## 2026-10-22｜训练准入诊断与素材删除一体治理（代码及CI验收完成）

唯一专项：[生命周期治理](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)第十节，最新回执/交接10.13。GOV-01–11复用原Owner，自动多阻塞诊断、草稿全部问题排除、不可变预览/幂等Worker逻辑删除、GT整组/跨分页/项目清空、真实成功ID完整复检均完成。成功登录且可访问项目即同权，无admin/白名单/RBAC；清空仍须项目名与精确范围确认。旧隐式删除退役，活动/共享字节保留且释放0；排队10000→9500原范围重冻结。VERSION42.24.373，代码d207ba570a7209d2776b4b6b7240c511691b456a实际31/31 Actions、81/81 Checks、Chrome184/184及Node1209/1209通过；本地Python356+3 Windows symlink skip，Linux CI相应边界实际通过。首推失败及修正已留痕，本次文档/PoC时序增强补提自身SHA须再核CI，以最终GitHub绑定结果为准。禁止生产删除/迁移/部署/GPU；旧单份图片、物理GC和Bundle回收未实施，不重复建设已验收GOV。

## 2026-10-21｜Annotorious人工标注正式集成（代码及CI验收完成）

唯一专项：[Annotorious集成](ANNOTORIOUS_ANNOTATION_INTEGRATION_2026_10_21.md)，**6.10为当前接续**。官方3.9.5本地离线资源、单一GT转换、manual/AI候选同kernel，空GT待标注与显式负样本分离，旧画框DOM/pointer已退役。VERSION42.24.372；代码0e6cff67实际21/21 Actions、55/55 Checks、CI Chrome175/175及Node1192/1192通过。本地Python175、Chrome54独立场景和16项制品校验通过，失败/修正/四视口/100–300框/20次开关证据均归档。本次验收文档补提自身须按最终实际HEAD核验CI；生产未部署/写入/迁移/训练，真实现场条件见专项，禁止重复建设。

## 2026-10-21｜综合治理补充验收（代码及CI限定验收完成）

唯一接续依据：[综合专项](FRONTEND_STARTUP_REPORT_UX_GOVERNANCE_2026_10_21.md)第10节。基线36aff618/VERSION370，最小修复Loading防重/截止/未知结果查询与标注保存归属，报告明确成功数、全部任务与含失败耗时；PARTIAL_SUCCESS保持正式训练成果已提交但独立评测失败的既有口径，不扩大成功标准。Python55、Node1142、Chrome90独立场景分别通过；bbb4950d实际35/35 Actions、98/98 Checks及CI Chrome140/140通过，准确回执见专项10.6；本次仅文档补提，自身检查仍须核验。VERSION42.24.371。未知批量提交缺幂等请求ID，保守查询锁仍需人工核验；ZIP等未逐接口Pending及生产12.08秒实际链路未覆盖，完整矩阵/生产只读方案/测试失败留痕见专项。未生产部署/数据修改。综合补充验收最终4fcbcfc8自身21/21 Actions、55/55 Checks通过；Annotorious按用户确认顺序另行实施，独立状态见顶部入口。

## 2026-10-21｜页面启动、报告与训练任务交互综合治理（代码及CI验收完成）

唯一接续依据：[综合专项](FRONTEND_STARTUP_REPORT_UX_GOVERNANCE_2026_10_21.md)。八项代码需求已实现：Snapshot增量/概要与核心先返回、有界恢复；正常报告/评测弹窗、共享Loading/Tooltip及真实曲线无恢复控件；创建成功立即仅关原窗，完整成功训练次数和排序缓存一致。VERSION42.24.370；实现/修正f0f3010d实际21/21 Actions、55/55 Checks、Chrome128/128通过，本地Python104/Frontend Node1108通过。首提交两条旧夹具失败及修复已留痕。本次仅补记文档，自身新SHA须独立CI，见专项第9节与GitHub提交Checks。生产未部署，现场12.08秒仍需分解核验；取消临时需求已全部撤销，无发布字段改造混入。

## 2026-10-21｜GT素材与训练数据生命周期专项（A进行中，B–F未开始）

唯一需求/进度/问题/验收依据：[专项文档](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)。已建立用户新需求基线并部分审计原Material/GT/Prepare/Bundle链；旧合同基线41通过、1软链接能力跳过，不代表新需求验收。历史永久保护取消、排队删减重冻结、单份图片和工作Bundle回收尚未实现；下一步完成活动字节租约/消费者及迁移契约审计后按B→F推进。旧历史条目仅为当时策略，不能覆盖本专项新需求；VERSION42.24.369保持，生产清理/部署未执行，首提交CI失败及隔离测试同步修正已留痕，949961c3实际CI21/21 Actions、55/55 Checks及Chrome112/112通过；本次仅补记文档，自身新SHA仍须独立CI。详见专项，不把基线验收当B–F完成。

## 2026-10-21｜报告交互与确定性ChatGPT材料（本地限定验收完成 / 最终SHA CI待核验）

基线ba6e9c3497c04e69a2e80c3f7dbf07d52fb391c2/VERSION368已fetch/pull且提交前再次一致；其他会话/工作树不动。原v44报告/TaskRecord/Snapshot/ModelArtifact/预览及TrainingRecovery Owner复用：固定模板A-H+4可空现场描述、复制/预览/隐私过滤，无AI调用；本地ECharts交互/生命周期、冻结8–12错误引用及期望评测/图片SHA核验；实际Trainer Optimizer/LR记录、转换源精度约束、迭代实际尺寸/精度及模式保持。完整需求/根因/RED→GREEN/质量审查/测试命令及未验证见[训练质量追踪](TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md)顶部，完整生成文本见其示例链接。Python去重97通过/Windows已有Linux FD一例skip，Node118、Chrome16场景通过；未扩大到无关业务。VERSION一次递增369，app/main/styles416及必要模块缓存统一；最终实际SHA CI待普通推送，独立回执training-report-materials-ci-final-20261021.json。未生产部署/写入/重训转换；真实Person/Car质量、板端插件标签/性能及现场UI仍NOT VERIFIED，不把基础PASS当业务合格。

## 2026-10-21｜本地厂商/芯片稳定ID与新畅联一对一映射（本地验收完成 / 待最终SHA CI）

基线bb1fed555b60409109b9c62c875b30b72e6c31c5/VERSION367已fetch/pull干净且远端一致；其他会话/工作树未覆盖，上轮23/59 CI回执已核验。完整需求、根因、原target_mappings稳定ID扩展、双向唯一性、历史迁移/回退、危险改挂边界及测试证据见[发布专项](EXTERNAL_ALGORITHM_PUBLISH_PHASE2.md)。原Repo/API/Owner复用，动态本地字典投影，SDK与业务厂商分离；同SDK不同厂商交付/恢复隔离，未知远端分类保持保护；已有Weight分类变化不自动edit，原ID/回执保留。停用历史透传、revision及草稿/保存中返回/迟到保护已闭合。Python去重203、Node28、Chrome1通过，未全仓扩测，版本一次递增368，main/styles415、发布64014，app413不变。最终实际SHA CI待普通推送核验，独立回执stable-vendor-mapping-ci-final-20261021.json；生产字典/DB/OSS/Weight/训练转换/部署未操作，真实provider及历史迁移仍NOT VERIFIED。

首推6339c297实际CI中发布Python/Node/Chrome通过，Syntax and wiring guards检出旧源码契约未同步：退役编辑器丢失仍准确的SDK/字典提示、源码守卫依赖原字段空格及旧“映射变化自动edit”测试名。已恢复真实页面提示/原字段风格，仅将既有workflow一条grep改为本轮更强的“待审核且身份不变”实际测试名，未删除/跳过/削弱动态断言，也未扩展CI触发或测试集合。原完整Syntax and wiring guards本地实际执行退出0，build_identity确认42.24.368；VERSION本轮不二次递增。需以接续修正最终SHA核验全部CI，首推不能当全绿。

## 2026-10-21｜畅联云Weight完整详情与官方withTags分页查询（本地通过 / 最终SHA CI待核验）

基线22587dd7/VERSION366已fetch/pull干净且远端一致，其他工作区/会话未覆盖；上轮26/70最终绿色回执归档。原畅联云数据Runtime/Client/详情及分页API复用，24字段分组详情、Tags正式list withTags=true精确ID分页补查、int64浏览器安全投影、来源/空值/冲突/失败区分、按需缓存及迟到生命周期保护；无新增Owner/轮询/包装。完整需求/官方合同/RED→GREEN/字段/质量审查/限定测试见[接口与详情验收](CHANGLIAN_APIFOX_API_CATALOG.md)。Python去重127、Node32、Chrome3场景通过，VERSION一次递增367，main/styles414及浏览模块缓存63002，原app413保持。最终实际SHA CI待推送核验，回执weight-detail-ci-final-20261021.json；SSH只读拒绝，真实provider Tags/getInfo候选参数及生产历史仍NOT VERIFIED；未部署/写生产DB/OSS/Weight。

首推9d2cdd48的CI复现Client校验层次回归；已将严格ID校验移至原Provider路由并保留默认Client兼容性，新增RED及直接Client9/HTTP1/原失败wire26 GREEN，原发布安全测试未改。VERSION367不二次递增；后续最终SHA CI待核验，详见接口专项。

## 2026-10-21｜Tags / 转换参数 / AMP / SDK 一致性（本地通过 / 待最终SHA CI）

基线b74a3866/VERSION365、fetch/pull干净且远端一致，其他工作区不动；前轮48/131实际CI回执归档。原Owner最小修复空prepared标签、HTTP请求/回执/读回事实、preset精度、异步参数覆盖与页面归属、单资源检测、真实编译模式/ONNX导出与Agent传递/manifest事实。完整需求/根因/矩阵/质量审查/限定验收见[专项](CONVERSION_PARAMETER_CONSISTENCY_2026_10_21.md)。分批JUnit去重403例通过，Node相关文件分批通过，Chrome9种相关场景通过；修复中失败与复测如实记载。VERSION一次递增366，必要app/main/styles413、训练CSS4226354/submit422600、publish64013。无新Owner/包装/监听器/轮询，生产写入/部署禁止；只读SSH拒绝，17/7及真实SDK/GPU/网页未现场核验。最终实际SHA CI待安全推送，按tags-parameters-ci-final-20261021.json独立回执核对，不能提前标绿。

首推058b2ec1实际CI检出两处测试适配问题（轻量夹具误依赖onnx、旧源码守卫要求非冻结pid）；已原位修正，Python1/Node11定向通过，安全断言保留，无CI依赖/范围变更。VERSION366不二次递增；最终后续SHA核验中，详细日志结论见专项。

## 2026-10-21｜字典普通编辑与历史引用校验分离（限定验收完成 / 待最终SHA CI）

最新8d74588d95ffa3549f0769431d92072dfa1300cc/VERSION364已fetch/pull干净；无可见同仓库其他活动开发，其他工作树不动。前轮Weight22/57绿色回执已核验归档，不代表本轮。生产缺失job证据、完整需求、最小方案与定向TDD计划见docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md顶部。普通名称/启停不依赖历史扫描；详情返回真实诊断，不允许can_delete假成功；删除/改挂严格fail closed，只可信任务合同/同项目任务路径可恢复。限定本次Python/API/Node/Chrome，版本最终基线一次递增，生产数据/文件/OSS/Weight/重启/部署均禁止。原scanner/Repo/API/UI已最小修复；原严格删除/改挂保护保留，可信任务身份与matcher一致后才恢复，普通短表单可用/诊断折叠，toggle异步归属已修正。Python分批51及受后续改动影响37/4通过、Node9后短表单7、Chrome既有3+新场景1通过；完整RED/质量审查及夹具排序复测见专项。正式VERSION365一次递增，main412/字典模块2、8版本投影一致；最终实际SHA CI待推送核验。

## 2026-10-20｜Weight自动覆盖发布（A-D限定验收完成 / E待最终SHA CI）

最新b74834c4a8d87090aad64876df50bbf548f2bdac/VERSION363已fetch/pull干净；其他同项目会话未活动、原WIP不动。用户已正式取消常规人工审核：每版本/芯片一个Weight，可信任务完成时间确定最新有效成果，完整性与OSS成功后原ID edit/唯一首次add，全部写后查询确认；本地多SHA和历史审计保留。真实官方edit/detail/list OpenAPI已通过下载入口解析，包含filePath/computePlatformId/chipCode和可选元数据；生产写接口未调用。

完整需求、原始根因、架构/限定TDD计划、生产边界及证据见docs/CONVERSION_WEIGHT_PUBLISH_RECOVERY_2026_10_20.md顶部。只复用原Repo/版本fence/发布Owner/恢复/审计，旧审核UI已改自动交付；官方字段合同已核验，文件身份/跨Artifact未知请求/单Owner/同ID编辑/读回/迟到防回滚已实现并完成分批RED→GREEN，最终限定发布175+2复测、资产11、Node18+缓存1、Chrome4通过；最终历史投影及optional读回补断言定向复验记录见专项；本轮生产数据库/OSS/Weight写入/批量迁移/部署仍禁止。本轮VERSION一次递增364，main411/发布模块64012；上一轮31/83 CI已归档，不代表本轮。

- 首SHA26856b02 CI发现selection HTTP测试导入整个app引入精简环境无yaml；仅夹具改复用轻量error_body，无新增依赖/测试扩围，VERSION364不二次递增；最终后续SHA CI待核验。

- ac4229f3发布CI动态Python282/Node25通过，旧源码行守卫未随统一发现Owner迁移；仅更新既有3项守卫至真实ModelArtifact/芯片/接线，保留全部动态断言及测试范围。VERSION364不变，最终后续SHA CI核验中。

## 2026-10-20｜厂商与芯片完整CRUD（A-D限定验收通过 / CI待最终SHA）

最新ed946c9b43ba7c5e014c60076d5539b6cbdf20b8/VERSION362已fetch/pull干净，无其他同仓库活动会话；前轮40/112绿色按附件核验归档，不借用。本轮升级为部署资源内正式区域及真实单条CRUD/引用安全删除/幂等审计/搜索分页/每资源SDK自动决议；原Repo/字典表/检测/resolve/Worker复用，旧编辑实现退役不并存。完整需求、架构、限定RED→GREEN及质量审查清单见docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md顶部。仅实际受影响测试，通过未受新变更影响不重跑；不加大型CI或扩触发。本轮生产/外部写入/部署仍禁止。

- 本轮VERSION42.24.363一次递增，app411/main410/styles409；七正式入口一致。原Repo/API/detect/resolve唯一Owner，单条CRUD+同库原子审计/全引用安全删除/服务端分页/自动SDK约束，部署页嵌入管理区，旧编辑及CSS移除。无引用待适配SDK可编辑，历史身份受保护。
- RED→GREEN、Python分批限定结果、Node5+版本断言1、Chrome4流程及实际质量审查整改，详见专项顶部；不重复累计/不跑无关测试。现阶段提交前fetch远端未变，最终CI仍待实际SHA；生产未操作、现场未验证。

- CI接续：首提交2284615ac1d9ede7c4480967af0bfe78abc1afe3的frontend静态守卫要求原beforeInvokeNavigation侧栏hook完整保留。已将catalog.leave移入原performNavigation且先于state.page变更；不改/削弱守卫或工作流。新增定向Node1 RED→GREEN、原CI导航源守卫及Chrome CRUD刷新返回1通过。VERSION保持本轮363不二次递增；需核验后续修正实际SHA，首SHA不能作为最终绿色。

## 2026-10-20｜字典管理UI/UX简化（限定验收通过 / 最终SHA CI待提交 / 生产未部署）

- 基线6f34efd3ef09741147f90dadadb37591751c3c41/VERSION361已fetch/pull且工作树初始干净；无其他同仓库活动会话，原WIP/worktree不改。上轮21/55最终绿色回执已核验归档，不代表本轮。
- 原字典Owner改默认搜索列表+同modal短表单，自动稳定ID/可信5型号建议/高级折叠/完整revision PUT；原ID/SDK/code保留、厂商模板不可改挂，未知SDK可空但不准入。原resolve抽出共享SDK事实供列表与预检，配置/编译/板卡状态分离，不改外部映射/Weight/执行器。
- 真实RED与进度：Python4、Node3及HTTP/别名各1、基线Chrome1；修复刷新叠modal及待配置投影500。最终限定Python33、Node32、Chrome2通过（0失败0跳过），七版本入口362一致。完整需求/设计/实施/测试/未验证见docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md顶部。
- VERSION42.24.362（一次递增），app410/styles408/main409。最终SHA CI回执catalog-ui-simplification-ci-final-20261020.json另存既有visualizations附件目录，下一受验证提交归档。不部署/修改生产数据库、配置、OSS、新畅联或真实转换；现场仍NOT VERIFIED。

## 2026-10-20｜正式部署资源入口补修（限定验收通过 / 最终SHA CI待推送 / 生产未部署）

- 基线8366b4edf79e8a4231fe5033a8c86ec92858bd80，fetch/pull干净且提交前远端未变化；原转换Weight23/59绿色已归档，不作为本轮CI。其他会话与工作树未覆盖。
- 原renderDeployResources/字典弹窗/API已存在。最小修复正式高级菜单、canonical Owner、导航别名及启动恢复四处接线；模型配置保持独立，无新页面/Owner/包装。普通路径：展开高级功能→部署资源→厂商与芯片字典。
- RED：Node17通过2失败；恢复基线后Chrome在菜单缺失处失败。GREEN：Node29、Chrome3、字典/API定向Python8通过，0失败0跳过；真实隔离GET/PUT、新增RK3568、刷新、返回及BM1684/BM1684X/RK3568显示/转换选择通过，七版本入口一致。
- 首提交CI暴露两条旧退役导航期望，与本轮合同冲突；已改为独立正式Owner/菜单并定向2通过（39未选中），其余保护保留，最终SHA仍待CI。
- 正式版本42.24.360→42.24.361一次递增，app408/main409/nav422518；样式407与发布模块64011保持。详细需求/根因/测试与最终CI附件位置见docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md顶部。本轮未读取/修改生产字典、部署或调用真实外部写接口，现场页面仍待部署后验收。

## 2026-10-20｜转换Weight身份/交付选择与审核（本地限定验收通过 / CI待提交 / 生产未操作）

- 最新fetch基线a3a99ec1760366ddda5193ca60b200c3b719c2d5，VERSION42.24.359；上轮47/128全绿已核验附件，不借用为本轮。其他工作树/可见会话未覆盖，提交前再fetch。
- 用户最终业务：每版本/芯片一个当前Weight，本地多SHA历史全部保留；明确选择只是本地交付意向，接口合同/唯一身份/写入授权未确认前不替换、不退为多Weight。原Owner/Repo/上传/转换调度复用。
- 同名异SHA歧义与异名可能重复add、持续UNKNOWN重试、父子分类审核投影、稀疏metadata丢来源及异常阻断唤醒均已定向RED→GREEN；新旧ID/SHA生产证据、实现/测试/dry-run详见docs/CONVERSION_WEIGHT_PUBLISH_RECOVERY_2026_10_20.md。
- 本轮正式版本按最新基线一次递增42.24.360，main408/发布模块64011，app/styles407保持；限定Python122、API/审计3、Node27、Chrome4通过（重叠不累加），正式七入口一致/永久守卫通过；最终SHA CI待提交。真实源任务/远端Weight/接口替换能力NOT VERIFIED；只读SSH连接被拒绝，未读取生产或发送API/OSS请求，未部署或写入。

## 2026-10-20｜动态厂商字典与真实SDK目标（本地限定验收通过 / 最终SHA CI待推送 / 生产未部署）

- 完整fetch/pull基线7a2492b24de5d6259bf792ed074f1548e66d6eda，原39/109绿色归档不是本轮CI。复用初始干净长期分支工作树，其他工作树/会话未覆盖。
- 唯一专项docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md保存完整用户V2/第十八条、产品合同、架构、RED、已完成与剩余计划。原ModelArtifactRepository/compute_platform_catalog/Adapter/Worker/Durable MODEL_CONVERSION/发布Owner复用，无平行模型库/队列/调度/轮询。
- 动态本地厂商/芯片表初始为空，模板不等于业务记录；SDK/本地/外部ID分开。BM1684按1.30.2官方矩阵+实检开放F32、原X/88 F16保留；未知组合不乐观放行。后端统一resolve和POST，真实目标/参数/命名、结构/hash、资产快照可追溯，硬件验证独立。
- 正式VERSION本轮已一次42.24.358→42.24.359；必要app/main/styles缓存42.25.407、发布模块64010。正式显示继续读后端版本。最终Python262、Node70、Chrome8通过，另7项发布安全定向用例通过；版本七入口一致、语法/diff/原永久守卫通过。最终完整SHA CI待推送，记录于专项指定独立附件。
- 未部署/重启/安装SDK/改生产密钥或数据库/操作OSS/历史Weight；本机Windows未找到TPU-MLIR工具，真实BM1684编译、模型质量与板卡NOT VERIFIED。生产17项元数据/7Weight补齐仍未执行，须独立授权。

## 2026-10-20｜Weight tags及本地元数据（本地通过 / 最终SHA CI待提交 / 生产补齐未执行）

- 基线0cf65c48bf6c6d0ec0df852128c2faccf4072f8e已完整fetch/pull；历史48/131绿色归档，不代表本轮。VERSION42.24.358，app405/styles402保持，仅main406/发布模块64009必要更新。
- 原模型标签/JSON add-edit/UNKNOWN/差异检测已有。RED确认通用资产未持久化模型信息+upsert整体替换、PARTIAL幂等ensure重置重试时钟、edit多候选未消歧、无外部映射本地标签投影遗漏。共享原解析合同、原SQL/ModelArtifact/发布Owner增量修复，无平行队列/数据库/轮询。
- 版本冻结schema/codes或可信Snapshot为唯一来源；Artifact保存验证快照，未知不清空已知、冲突不覆盖。训练/转换先登记本地，与外部/上传配置独立；已有对象身份保持，不复传。原ID唯一edit，缺可选字段不阻断交付；回执和真实远端读回分开。
- 主Python335通过，版本兼容25、训练/转换传输18通过；Node26、Chrome3通过，0失败0跳过。7缺失实际ID+10隔离对照通过，7edit/10零edit，重复不新增。最后完整SHA仍须CI。
- 唯一专项docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md顶部含只读预检、显式本地修复及原Owner受控外部补齐步骤/7ID表；scripts/audit_weight_metadata.py默认只读，--apply-local也不上传或调用新畅联。
- 未连接生产执行补齐/部署/重启/改密钥/操作OSS/S3；生产17项尚未实际修复，远端tags持久化需另行授权读回验收。部署启用自动Owner可能恢复历史重试，也须先审核并批准补齐。

## 2026-10-20｜Sophon资源与页面一致性（本地通过 / 最终SHA CI待提交 / 生产未部署）

- 基线a36b9cdec1cd4aa07c9cde2d9c84bc98bb66b479已fetch/pull，历史22/22 Actions、59/59 Checks归档专项。现场两chip真实FP16编译/远程done与probe可用是用户提供证据，不等于板卡验证。
- 扫描/plugins复用原v39 detect Owner解析secret_ref、鉴权、持久化及公共投影；资源列表/转换弹窗读取同一事实。健康失败清空Sophon能力，恢复重新可用，不泄露密钥；无第二探测/调度/轮询。
- 本机工具明细仅展示本机；整体Sophon按有效资源汇总，区分本机未配置/本机失败/远程可用。版本修为完整v1.30.2-20260831，远程资源展示工具版本；独立Python保留原逻辑已有测试保护。
- RED后端8、Node1、Chrome1→限定Python136/136、Node20/20、Chrome10/10（0失败0跳过）；语法/diff/原永久守卫通过。VERSION42.24.358，app缓存405，main404/styles402不变。
- 唯一专项docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；最终CI附件见本轮E节。不修改生产服务/密钥/依赖，不部署，不调用真实新畅联写接口；部署后真实网页与板卡结果仍需现场复验。

## 2026-10-20｜Sophon model_tool CLI兼容（本地测试通过 / 最终SHA CI待提交 / 现场依赖未验证）

- 本轮基线c44752934524dcfc86f89d8cf24fc34f32cee011，完整fetch/pull远端一致。该历史SHA的48/48 Actions、131/131 Checks已归档Sophon专项；不当作本轮CI。
- 现场TPU-MLIR1.30.2的model_tool不支持--help，Usage后非零不能判工具损坏；仅修共享probe为官方--version+退出码/版本输出校验，保留编译后--info及其他严格合同。
- RED11 failed/6 passed→最终限定Python98 passed/0 failed/0 skipped（含--info错误芯片/失败保护）；py_compile及diff检查通过。只改共享probe与原Sophon回归测试，无前端变化，不扩跑本地Node/Chrome/硬件。
- 不安装依赖、不破坏训练环境、不部署、不调用真实新畅联接口。服务器实际缺失依赖与修复后现场health待明确Sophon SSH目标或pip check/traceback核验，NOT VERIFIED。最终CI附件见专项本轮E节。
- 唯一专项docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；VERSION42.24.358与前端缓存均不变。

## 2026-10-20｜Sophon BMODEL（A-D测试通过 / 最终SHA CI待提交 / 生产与硬件未验证）

- 起始62647aeea258a26ba423f0a9db23d8f6f8ba3b1a；上轮23/23 Actions、59/59 Checks已归档原tags专项，不代表本轮绿色。VERSION42.24.358不变。
- 首期BM1684X/BM1688、FP16、Batch1/static；修复显式芯片/矩形导出与ONNX shape、可运行工具探测及真实产物结构/hash合同。Sophon remote并入原ConversionHandler/MODEL_CONVERSION，原Key/Lease/取消/恢复与确定ID幂等；无第二执行器/数据库/轮询。
- 发布继续原ModelArtifact/Owner与Weight add/edit，同Version下PT和两chip BMODEL共存，tags冻结原生数组，未知可选信息不阻断；Sophon必要chip严格校验。UI增量字段与真实资源/任务/待硬件状态，app/main缓存404、styles402、发布模块64008。
- 本地Python313/313、Node40/40、Chrome10/10，0失败0跳过；最后BMODEL edit断言聚焦4通过。硬件2 SKIP/NOT VERIFIED，无真实TPU-MLIR编译或板卡加载证据；独立规格P1两项均补RED关闭。
- 唯一专项docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；提交后最终CI依该文档指定独立附件核对，不能提前宣称CI通过。禁止生产部署/API/OSS/GPU/生产转换；下一会话先读本节和专项后接续。

## 2026-10-20｜训练与转换 Weight tags 专项（A-D测试通过 / E待提交与最终CI / 生产未验证）

- 需求：核验冻结训练类别经原始PT/ONNX/RKNN到新畅联add/edit实际HTTP JSON；tags原生字符串数组、class_id顺序、未知省略且不阻断。上传人/身份/OSS对象标签不在范围。
- 已完整fetch/pull；分支feature/external-algorithm-publishing，起始HEAD 2cb3ba1617551f59abdc9c66115a0cde29d463f5，远端一致、工作树原始干净，VERSION42.24.358。
- 已有：冻结类别/Snapshot提取、可选扩展字段、旧ID edit、synced_payload_json与UNKNOWN恢复、转换完成唤醒。待核验：真实训练冻结格式、完整HTTP JSON、ONNX/多类/多版本与历史补齐链路；已确认链路原本实现；真实缺口为贯穿到PreparedRequest.body的验收覆盖。6项链路测试已通过，不制造业务RED，不改业务代码。
- 预计范围：既有发布/平台/转换通知测试与必要的最小修复、现有handoff；不新建Owner，不部署、不调用真实新畅联写接口、不操作生产OSS或历史数据、不运行真实训练/转换。禁止测试发散。
- 本地限定Python200/200、Node16/16、Chrome3/3，0失败0跳过；无业务修复、无真实业务RED，初次夹具失败如实记录。最终SHA CI尚未执行，不得提前称全绿。
- 只读复核关闭1项CI依赖遗漏：原SQL精简Job补psutil；转换链路强化真实Event.set发出断言。最终SHA需独立CI。
- 当前状态与下一步统一见 docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md；阶段变化持续持久化，最终CI须对应最终SHA。

## 2026-10-20｜权重补充元数据发布（最终合同：可选、非阻断）

- 首次SHA 6f83076f的CI发现精简Job缺TestClient依赖、浏览器文本守卫未适配参数化；仅补httpx2及更新守卫匹配，保留核心身份零POST断言与全部实际测试。后续1faa9693的后端200项与Chrome3项已通过，另将唤醒信号守卫同步到既有真实Event.set发出断言及消费后无重复断言；最终SHA重新验收。
- 基线93c56659，复用ExternalPublicationRepository / ModelArtifact / 原发布与转换通知Owner。六扩展字段可信则传、未知省略，tags未知不发[]；缺失不阻断交付、不改转换成功状态。
- 原ID edit补齐与确认payload回执、UNKNOWN写入只读恢复、矩形尺寸及冻结标签解析、原版本行内联事实/真实错误展示。无第二队列/数据库/轮询/弹窗Owner；不操作生产。
- 聚焦Python三文件194 passed、Node三文件41 passed、Chrome单规格3 passed，末次schema/存量19 passed。原始RED/失败及纠偏记录见 docs/WEIGHT_METADATA_ACCEPTANCE_2026_10_20.md。
- VERSION42.24.358不变；app/styles402不变，仅main403及两个模块缓存更新。最终SHA Actions/Checks需独立验收，附件：C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-metadata-acceptance-20261020.md。
## 2026-10-20｜素材完整性接续审查（本地验证，最终 SHA CI 待验收）

- 完整 fetch/pull 长期分支到 d623a2d6327143571898e778050e5d42cc5e4a4d，六个已知修复全部包含；原工作区保留，复用既有长期分支工作树。
- 仅修复三项真实复现：标签映射摘要未贯穿普通治理计划/Worker；execute 迟到成功/失败未完整校验弹窗归属；恢复复验把已成功删除项重新记作失败。沿用原计划/Task/DELETE_INDEX/AnnotationRepository/Modal/PollRegistry，无新 Owner。
- 审计已有 label_schema_digest 贯穿冻结计划、执行清单和逐项删除；标签锁先于 Material 生命周期锁。缺摘要旧计划 fail closed，需要重新审计/预检；已成功项保持历史计数，未完成项仍复验 keeper/GT/hash/Test/引用。
- 本地新回归 RED：Python 4 failed，Node 2 failed；最小修复及边界补充后聚焦 Python 6 passed，Node 全量 1021 passed。安全扩展最终 116 passed。真实 Chrome 两份规格 19 passed；最后补顶层弹窗按钮归属后聚焦 2 passed。独立复核未发现本次差异的 P0/P1；其 Python 首轮 5 setup error 为 C:/Temp 父目录不存在，换已有短目录后 6 passed，Node 35 passed。首轮新 Chrome 夹具误用 window.state 导致 2 failed，已改为仓库既有 lexical state 并保留所有业务断言。
- 正式 VERSION=42.24.358 不变；入口 app/main/styles 静态缓存 42.25.402。最终准确 SHA、全部 Actions/Checks、未触发与未验证边界记录在 C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/material-integrity-acceptance-20261020.md；不沿用基线 40/40 绿色。
- 未部署、不重启生产、不连接生产数据库、不执行真实素材删除，不自动发布模型。生产 OSS/S3、历史现场、GPU/A800、大库并发与查询 SLA 仍 NOT VERIFIED。
## 2026-10-19｜P0 批量 GT 冲突辅助治理

- 本轮唯一进度为 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部批量GT节；复用 TrainingCompatibility、原审计/MaterialBatch、ImportCandidateStore、正式 AnnotationRepository 和 DELETE_INDEX，两个入口共用 TrainingMaterialSummaryRuntime。来源证据不代表GT正确，必须人工审核；无第二套存储/队列/Owner/轮询。
- 正式VERSION42.24.356不变；不连接生产、不覆盖GT、不动历史/Test，不部署。最终SHA及实际Actions/Jobs/Chrome证据以追踪文档指向的独立最终验收附件为准，生产960组进一步根因数量未验证。

## 2026-10-19｜P0 远程清理同步锁误保护精准修复

- 现场只读证据由用户提供；精确豁免 `remote-material/staging-cleanup.json.lock`，不豁免真实台账或其他锁。实际清理调用的 RED→GREEN、API/Worker 和 CI 证据统一见 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部专项。
- 复用原历史引用、MaterialBatch/DELETE_INDEX Owner；Payload/关联任务/执行记录/冻结/Test/Snapshot/模型/未知依赖仍保护，不改任务历史，不操作生产，不改 VERSION=42.24.356。最终 SHA/Actions/Jobs 以独立最终 CI 验收附件为准，不沿用前一 SHA 绿色。

## 2026-10-19｜P0 素材治理与训练冲突删除闭环

- 当前专项唯一进度仍为 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部 P0 节；TQ-04 已完成批次不重做。既有素材治理验收文档追加本次证据，最终准确 SHA/Actions/Jobs 以其关联的 CI 附件为准，不继承旧绿色。
- 仅在可证明 FAILED 输入从未形成现存依赖时释放请求引用；Snapshot/Test/恢复/模型/未知依赖继续保护。同组保留全部保护身份和 keeper。两个入口共用原冻结计划、DELETE_INDEX、MaterialBatchRuntime62 与 PollRegistry；不删除共享源文件，不改历史记录，VERSION仍42.24.356，不部署。

## 2026-10-19｜TQ-04 类别指标真相接续

- 当前任务与实际测试/CI唯一进度入口：`docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md`。仅维护既有 evaluation/iteration decision/report Owner；禁止生产操作、历史数据重写和 VERSION 变更。最新修复的实际 SHA/CI 需按追踪文档关联的验收证据查询，不沿用旧 SHA 结果。

## 2026-10-18｜安全推送验收阶段（用户已授权 / CI 待最终 SHA 验收）

- 首轮 `edee5fb6fcd32812ee62b0197728dc7ab51d8b0f` CI 发现恢复/素材选择 Chrome build 断言与实际资源不一致，以及新接入 Hardening 守卫锁定退役的注册模块。最小修复只同步精确版本和真实 Production→CheckpointResume→Recovery 继承合同，并增强真实注册对象断言；恢复 Chrome 5/5、素材选择 Chrome 2/2、Node 982/982、两个原始 Bash 永久守卫通过。扩展 Windows 测试的 14 项长路径失败在短 basetemp 消失（19 passed/1 Linux-only skipped）；另 1 项 manual workers=8 与既有 Windows 上限4冲突，不改生产资源保护；相同未变源码的 Ubuntu 124项已实际通过。最终 SHA 仍需重新完整 CI。
- 用户已授权本轮普通 Fast-forward 推送及必要 CI 修复；禁止强推、main 合并、Release、生产服务/数据操作和正式 VERSION 修改。此前 LOCAL ONLY 记录是上一阶段，不再作为本阶段推送限制。
- 代码提交基线 `5d3ad65bf7ff287521481a2ac6bfbd1f7caed52e`，远端父提交 `5a28e4539b81c03b4eaa27fa4b6c718138542169`。范围审查确认只涉及图片标注、类别检查、素材治理和训练冲突闭环，复用原 Repository、TrainingCompatibility、Snapshot 与 Task Owner。
- 推送前独立复核补齐固定 Benchmark 与 duplicate_review 合同：API/Worker 只在真实 Benchmark 解析后正规化；保留原 revision，拒绝客户端 Test 角色及保留素材排除，不暴露私有 Test ID。9 个真实 API→Worker 场景通过，相关 Python 109 passed；Node 全量 981 passed。
- 发现 Release Regression 与 Training Final Validation Hardening 仅监听旧分支，已接入唯一长期分支，并补源码/测试触发路径及 Node 守卫；不删除测试或放宽断言。正式 VERSION=42.24.356，静态缓存规则不变。
- 远端验收必须按最终完整 SHA 查询全部 Actions/Jobs，旧 SHA 结果不可继承。最终 SHA、统计及生产只读核验边界将记录于 `C:/Users/jorsam/.codex/visualizations/2026/10/18/training-conflict-p0/CI_FINAL_HANDOFF.md`，该外部验收文件不产生未经 CI 的额外代码提交。
- 生产 2531 张现场、OSS/S3 历史对象、GPU/A800 和大库并发仍 NOT VERIFIED。历史 Snapshot/Test/模型证据保护保持，不自动解除 FAILED/no-freeze 保护，不删除共享原文件。详见本轮验收文档。

## 2026-10-18｜训练重复冲突与标注/治理闭环（LOCAL ONLY / CI NOT RUN）

- 当前隔离分支 `codex/training-failure-diagnostics`；本轮不得 push、部署、修改正式 VERSION 或操作生产素材。验收与现场边界见 `docs/TRAINING_CONFLICT_GOVERNANCE_ACCEPTANCE_2026_10_18.md`，不能沿用旧 SHA CI。
- 原始正式 GT 同 SHA 冲突在任务标签投影前检查；预检、准入、Worker 和冻结复验共用原 digest。显式排除仅改变新训练草稿且双 revision/原始角色必须验证；Train/Test 泄漏不可绕过。冻结前后复验、锁内发布，外部平台 HTTP 在标注锁外。
- 训练差异/失败诊断仍由 TrainingMaterialSummaryRuntime 管理，标注仍由原工作台/AnnotationRepository 保存；未检查类别默认折叠、单一绘制类别、四视口布局。零可删仍能看真实图与保护原因并人工核对 GT，不创建空删除任务；FAILED/no-freeze 不自动解除保护。
- 移除 MaterialBatch 路由内部重复训练恢复挂载，保留 app 配置完整的唯一 Owner。Snapshot/Test/模型/历史记录不改，共享源文件不删；任务轮询和 DELETE_INDEX 归属不变。
- VERSION=42.24.356；入口 app/main/styles 缓存=42.25.389。最终 Python 聚焦131、API/素材安全115、Node24完整980、真实Chrome24全部通过（无失败/跳过）；原始日志和截图见验收报告。素材选择沿用原Owner，解析全选期间禁止确认，迟到结果校验项目/选择器归属。GitHub/Linux、生产2531张案例、OSS/A800实机仍 NOT VERIFIED。

## 2026-10-17｜最新交接入口（代码已推送、生产待核验）

- **优先阅读**：[HANDOFF_2026_10_17_CURRENT.md](./HANDOFF_2026_10_17_CURRENT.md)。此文件总结当前项目、近期关键提交、代码 SHA CI、素材治理 P0、安全约束、生产两次 DELETE_INDEX 尚未核验的 Task/日志，以及下一会话第一步。
- 本轮代码基线 `7de5be0dbbe06953f6ecace2d92496569adcf4e4`、`VERSION.txt=42.24.356`。该代码 SHA 的 GitHub Actions 已独立查询 **24/24 completed/success**；另外 16 类工作流未触发（不计通过）。Codex 报告 **61/61 Jobs 成功**。新写入的交接文档提交**不是**该代码 SHA，不能自动继承它的 CI 结论。
- 新版**未部署生产**，真实 A800/OSS/S3、历史评测图片及现场第一次/第二次异常素材删除任务未验证；先只读收集 Task ID、状态、错误码、Worker、素材索引/正式标注与旧审计信息。严禁为验证而再次删除生产图片。
- 本批只更新交接 Markdown，不改程序、VERSION、main、部署、生产数据；后续推送/部署/删数据须依据用户当轮授权。

---

## 2026-10-17｜素材治理推送后的 Chrome 跨平台证据路径修复（FINAL SHA CI OPEN）

- 已授权提交9830f1de快进推送；该 SHA 实际44次Actions运行中43成功、1失败。唯一失败为 Frontend browser-navigation：Ubuntu缺USERPROFILE，两条新增治理用例在截图路径处中止（93 passed / 2 failed），并非可计为通过的环境跳过。
- 本地清除USERPROFILE稳定复现2 failed / 1 passed；现有三条治理Chrome统一使用Playwright testInfo.outputPath，证据按用例隔离，不依赖Windows或仓库内.codex目录。保留全部业务断言，无生产代码、静态缓存或VERSION变更。
- 修复后相同无USERPROFILE条件下相关Chrome21/21、Node24完整978/978通过；本轮另有Python41/41。9830的Ubuntu Release runtime-contracts实际456 passed，包含test_material_integrity.py；最终修复SHA须重新验收，不能借用旧SHA成功。
- VERSION42.24.356不变；不部署、不触碰生产素材/数据库。生产原两次删除Task及真实存储仍待只读现场核验。

## 2026-10-17｜重复与异常素材删除 P0（LOCAL VERIFIED / CI OPEN）

- 既有素材治理计划 Owner 增补 FILTERED / SELECTED_IMAGES / 异常组冻结；全筛选不下发全量 ID，重复 keeper、不同 GT 人工确认、Test/历史引用与扫描未核验保护不变。异常筛选不能绕过去重保护，DELETE_INDEX 不删除共享原始文件。
- 素材治理在同一个弹窗内完成全选、跨页选择、预检与确认，失败保留上下文；MaterialBatchRuntime62 / PollRegistry 仍是唯一任务状态与轮询 Owner。所有索引删除终态刷新分页并失效旧审计；旧分组不再冒充当前素材。图片尺寸/加载失败时藏框，真实宽高比与 Content API 保持一致。
- 独立代码复核的发布前失败重试、refresh 期间切换项目、Chrome Worker 跨用例领取三项 Important 已关闭并补回归。未发布 manifest 只有完整身份、归属和 pending 状态完全相同才复用；篡改 409。测试 Worker 唯一 capability 仅用于隔离目标临时 Task，生产调度未改变。
- VERSION42.24.356 不变；入口 app/main/styles 缓存42.25.388，MaterialBatch build/import422406。最终 Node24 978/978、Python41/41、真实 Chrome21/21；详细结果和现场边界以 docs/MATERIAL_INTEGRITY_P0_ACCEPTANCE_2026_10_17.md 为准。现场原两次 Task ID/日志尚未取得，不声称生产删除数量或根因已核验；未 push、部署或操作生产数据。

## 2026-10-16｜菜单推送后专项修复

最后视觉收口：<=760px状态Tab不缩窄/不逐字换行，只在原栏内滚动；styles42.25.387。正式VERSION与app/main不变，最终CI按最新SHA。

原3be88817远端40工作流/112Job全成功。后续最小修复：独占原子JSON staging与有界Windows替换重试、训练Grid窄屏只在表格内滚动。Node24 972/972、Python75/75、Chrome44/44；VERSION42.24.356，styles42.25.386。修复提交自己的远端CI尚需按最终SHA核验；不沿用原SHA结果。见 ROW_ACTION_MENU_ACCEPTANCE_2026_10_16.md。

## 2026-10-16｜行菜单与导航简化（LOCAL VERIFIED / REMOTE NOT RUN）

基线 85dfb0f5；算法/训练菜单共享唯一展示 Owner，保留全部原业务按钮/权限/确认。nav-project 与顶部重复徽标移除但项目事实保留。Node24 972/972、Chrome 44/44；VERSION 42.24.356、入口缓存 42.25.385。fetch 连接重置，远端新鲜状态未核验，不 push/部署。报告：ROW_ACTION_MENU_ACCEPTANCE_2026_10_16.md（含 Windows ZIP 写文件日志与窄屏训练布局边界）。

## 2026-10-12｜CI 止血阶段：精确 HEAD 复核与修复（完整验收未完成）

- 交接 HEAD `b7c59d9` 的 47 条 Actions：42 成功、5 失败。重复失败集中于评测页面 JS 异常、IoU 对抗样本、ZIP 上传额外 GET、旧诊断文案断言以及存储页 Worker 请求；原始日志已分别核查。
- 已直接提交到唯一长期分支的四批增量修复：`037e786a` 修复 `previewUrl=row` 错误及无歧义重叠 GT 测试；`12ff43bd` 上传弹窗算法版本选择改为显式聚焦才查询、标签编辑成功响应另核验正式标签；`bbebf341` Worker 获取失败时也适用短期缓存抑制重复 GET；`23fd6704` 问题图返回与排序不重复堆叠评测模态层、历史 lineage Chrome 断言对齐真实“先诊断，再考虑补样”的新语义。
- 模态层回归覆盖返回/排序后同名弹窗唯一性；绝不取消浏览器测试或将原多余请求列为白名单。最终分支 HEAD 的所有 Actions 必须 `completed/success`，不能凭旧 HEAD 测试或排队任务声称全绿。
- P1 审计中观察到现有 YOLO 推理仍将普通预测框全部写入 CandidateStore（虽附困难信号和优先级），困难性过滤、候选数量控制、模型标签顺序严格校验、Remote GPU 实际模型可达性和 1k/10k/20k 真正压测均尚未验收；必须在核心 CI 通过后继续，不能宣称困难样本功能已闭环。
- 严守原 Worker、CandidateStore、AnnotationRepository、Snapshot/Test 唯一事实源；`VERSION.txt=42.24.350` 不变。不合并 main、不建 tag/release、不部署生产。

## 2026-10-12｜P1 YOLO 困难样本挖掘第一批（未完成完整验收）

- 最新阶段沿用 `TaskKind.AI_ANNOTATION` + 原 Worker / CandidateStore / AnnotationRepository：只支持显式选已有素材、普通图片上传选择版本后自动排队两种入口；同一套审核 UI 新增困难信号筛选，没有第二套任务或标注 Owner。
- `platform_core/hard_sample_mining.py` 为无状态计算：全项目历史快照 Test ID 和 SHA 禁入；YOLO 推理仅输出低置信度/小目标/密集目标/无检测待核查，绝不把无 GT 直接断言为真实 FP/FN。已有训练 PT + 训练快照 label_schema + 内容哈希冻结，Worker 再次校验数据/模型/标签，需 `mining.ultralytics` 能力及真实 CUDA；远端无模型或无 GPU 不假成功。
- 后端统一创建入口：`POST /api/v64/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining`；普通图片上传可选 `mining_algorithm_id/mining_version_id`，上传与挖掘结果独立，挖掘失败不谎称已撤销上传；同批 upload receipt 重试幂等。
- 现有独立评测 UI 一键选择未标注素材前 100 张；上传 UI 一项可选版本；原人工审核卡片展示困难信号和未确认原因，仍需人工接受、修改或拒绝后才入正式 GT。
- 安全与缺口：冻结 Test 快照/内容防护在任务创建、Worker 启动、审核 commit 前三次执行；暂不提供 ZIP 导入自动触发、Remote Agent 权重分发、模型间增强/严格基准续训闭环；未完成真实 GPU、20k 压力或浏览器实机验收。这个批次不能宣称 P1 fully delivered / CI passed。
- `VERSION.txt=42.24.350` 不改，只长期分支；本轮不合并 main、tag、release 或部署生产。GitHub Actions `queued` 不等于 success，最终 HEAD 需重新核验。

## 2026-10-12｜P0 后续核验：阈值可见、真实缩略图、评分匹配一致性（CI 待跑）

- 最新分支已提交 P0 三类定向修复：置信度优先一对一 GT/预测匹配统一类别 TP/FP/FN 与逐图框证据；问题图片卡片改为真实冻结 Test 只读缩略图，不可读时不伪造图；原图失败时隐藏 GT/预测 SVG 防止脱离图片显示假证据。
- 版本独立评测总体指标直接显示 `protocol.operating_conf` 与 `protocol.matching_iou`，区分 mAP 与固定阈值 TP/FP/FN；历史无可确认协议 mode 时显示「未记录」，不得暗填 0.25/0.5。
- 增加真实重叠目标评分一致性单元测试、Chrome 缩略图及 409 失效保护、评测阈值和历史降级断言；static app/style cache key 更新。版本 42.24.350 不变。
- P0 判定仍 BLOCKED：对应精确 HEAD Actions 若 queued/in_progress/failed 不算成功；真实 3 组业务 Test 素材、真 GPU/Storage、1k/10k/20k 压力仍未完成现场验收。P1 不得在这个 P0 门槛通过前当作已实现；未合并 main/tag/release/生产部署。

## 2026-10-10｜P0 Chrome 导航 Owner 收敛（待精确 HEAD CI 验收）

- 核验长期分支基线 HEAD `13f27c7ff0ae2f2c7f75190b745bb0e4b028632f`、VERSION 42.24.350，现有 37 个 Actions 中仅 Frontend Runtime Stabilization 的 browser-navigation 失败（78/79 Chrome 测试通过）。
- 源 HTML 中 V4/V5/V6 等多版 showPage/onclick 覆写和多个文档捕获监听，最后执行的点击 guard 可能被更早的捕获监听截断。
- 在隔离 HTML 的 body 顶部注册导航捕获 Owner，调用现存 window.showPage 进行业务渲染，确定性更新活动 section 与 nav，阻断旧 onclick 重复切页，删除之前的超时 guard。只限 sandbox iframe，不触碰父平台 NavigationStability。
- Chrome 测试扩展设备接入、通道查看的真实点击与页面显隐，原事件/任务/工作流断言全部保留。
- ZIP 正式就绪 FIFO 与标签批量确认尚未改动。当前提交待精确 HEAD CI 核验。

## 2026-10-10｜旧 HTML 最终脚本导航回归与重复合法按钮

浏览器日志表明原 HTML 的多套导航绑定中，较早 guard 会被后置源脚本遮蔽；最终 guard 仅在 iframe HTML 的所有旧脚本之后安装，使用捕获阶段点击监听、navigation epoch 与两次有限校正，不对平台主窗口增设任何路由或任务 Owner。总览里同一算法同时出现在质量排行与正式资产清单是预期双入口；Chrome 验证任意一个真实算法按钮可见，不要求业务上合理重复的按钮 DOM 全局唯一。缓存键严格同步。精确 HEAD CI 待验，不触碰数据真相与算法调度。

## 2026-10-10｜真实算法清单补充与独立 Demo 导航修复

按新 HEAD 浏览器与单元日志核对：算法一张图只呈现有分数的排行导致无评测算法资产名称被隐藏，现单列算法资产清单（最多 30 项，待评测与已有评测分开标记），保留质量排名真实分数。独立 AI算法底座源 HTML 含多个版本导航 onclick 冲突，事件中心切页曾出现点击后隐藏状态；仅在 iframe 内增设无请求、无定时器、无跨父窗口引用的微任务导航纠正，其他平台 Owner 不触碰。前端缓存键严格同步，旧测试没有跳过。前一 commit CI 未全绿，最新 HEAD 需重新复核。

## 2026-10-10｜算法底座导航/算法一张图/算力三连击演示/真实 PT 与实测图片

在长期分支实现：进入「AI算法底座」时只折叠平台主菜单，独立提供展开/收起按钮；算法总览正式更名「算法一张图」，调整真实指标优先的视觉和信息架构，将无真实源的运行排行与单位分析收纳为可展开区域，保留既有生产 Dashboard Owner。算力一张图 2 秒内连续点击 3 次进入**仅前端演示数据模式**，有明确标识和退出按钮；模拟节点/GPU/监控指标只传给当前渲染函数，绝不改变缓存、API、Agent 或 Scheduler 准入状态。场景算法实测的服务端版本 PT 选项按当前项目正式算法版本以及存在、非空的 best_path/stored_path PT 证据返回，排除 last.pt；前端保留版本身份，不以文件名必须等于 best.pt 作为唯一约束。检测详情优先显示浏览器本次上传原图，在渲染结果图加载失败时按后端真实 bbox 坐标回退，不显示裂图；历史素材若不可访问则明确说明。质量中心子 Tab 文案改为「场景算法实测」。只修改已有单一 Owner 的必要路径，无新增平行调度或检测服务。版本从 42.24.349 增至 42.24.350，静态入口缓存键独立更新。随本次提交纳入原有前端/Chrome 回归测试，最终 CI 和真实 GPU/现场文件仍需精确 HEAD 验证；不部署生产。

## 2026-10-10｜独立演示菜单改名 AI算法底座 + iframe 内长菜单滚动修复

按用户要求仅将平台独立一级菜单和 NavigationStability Page Owner「监所夜间离床研判」统一更名为「AI算法底座」，同步 iframe 的页面可访问性标题；嵌入 HTML 内的监所夜间离床业务示例及数据不改为生产功能。该模块仍仅为独立前端演示，无真实设备接入、后端持久化、推理调度或告警服务。追查前一精确 HEAD `207165a0` 的 Chrome 红灯，唯一失败是独立 Demo 长侧边栏的工作流入口滚动后被父层 #view 拦截点击；仅在 sandbox HTML 内配置 .sidebar flex 与 .nav 独立滚动，保留真实浏览器点击验收，不 force click、不跳过用例。同步更新隔离测试和严格入口缓存断言；VERSION.txt 保持 `42.24.349`，不修改主算法、训练、导入、资源调度的 Owner。新 HEAD CI 须独立验收。

## 2026-10-10｜监所夜间离床研判独立演示菜单（不污染平台模块）

独立 HTML 副本经 Chromium sandbox 真实点击 13 个内页确认可切换；已修复原 Demo 内部 window.events 与 DOM ID 冲突、旧事件列表节点被后续 UI 替换时的空引用、未声明 renderTasksV4 的 ReferenceError。只对独立 HTML 进行了 14 处定点兼容保护，未接入业务服务；浏览器验收覆盖多内页并保留 pageerror 断言。

新增独立一级入口「监所夜间离床研判」，位于原左侧「展开/收起高级功能」菜单下方。用户提供的 4296 行 HTML Demo 完整保存为独立静态资源（主页大屏、事件中心、设备通道、视频任务、模型/算法、工作流、字典模板等），通过仅含 allow-scripts/allow-modals 的 sandbox iframe 呈现。禁止 allow-same-origin；Demo 的 4 处 localStorage 引用转换为 frame 内内存存储以适配受限 origin（跨页面刷新不承诺持久化），所有示例数据/服务状态均为 Demo，**不接通生产监控/告警/训练/调度/OSS**。既有 NavigationStability 注册一个独立 Page Owner，未复用训练/标注/Agent Owner、未增加后台接口/数据库表/轮询；样式仅作用于入口和本页面，退出后 iframe 自行销毁。加入 frontend 静态和 Playwright 隔离验收；最终精确 HEAD CI 尚需独立验证。平台 VERSION.txt 遵照现有冻结约束未改变。

## 2026-10-10｜场景算法实测检测框回退预览

精确 HEAD `032641d2` 的 34/34 Actions、95/95 Check Runs 已核验成功。进一步源码审查发现无 `result_image_url` 时旧结果组件只显示检测列表而不显示真实框。现优先保留服务端结果图；仅在原图 URL 可用而结果图缺失时，按已有推理 `x1/y1/x2/y2` 坐标绘制 SVG 预测框，图片加载失败明确提示、不伪造框、不触碰 Durable Task/模型身份/训练调度。Chrome 场景检测测试新增真实 BMP 与非空坐标断言，静态资源 `app.js`/`styles.css` 缓存键同步递增，`VERSION.txt` 不变。本提交产生的新 HEAD 必须重新验收自己的 CI；真实 GPU 推理与生产数据仍需现场验证。

## 2026-10-10｜训练任务弹窗自动化调度标识

为精确匹配 UI 文案需求，将徽标文字固定为“智能自动化调度”（包含“自动化调度”），保留原有 CSS 和调度器运行逻辑；将原前端训练弹窗正式测试升级为断言确实渲染此徽标。只改视觉文案不增加第二套资源调度。

## 2026-10-10｜训练继承版本浏览器用例状态一致性

在 `995a6f78761088e983fca55d7d4a117f9b28a574` 反馈的两个单测失败中，BaseModal 原拥有者仍只有一套，导入最小化只是 decorater；更新严格断言覆盖旧 BaseModal + 装饰器调用、最小化 CSS 状态清理。版本缓存检测改为与已更改的 ZIP 启动脚本 `4226353` 严格相等。训练版本化用例仍要求“继承当前有效模型版本”、锁定原有模型、80 Epoch 和独立切分，但测试原先仅 mock 算法 GET，Bootstrap 首屏仍无版本，现补齐同一正式成功版本的启动快照响应，防止两个事实源互相矛盾。未改变训练/标签/存储核心或 VERSION.txt。

## 2026-10-10｜UI 合同与精确码映射 Chrome 回归对齐
按 HEAD `cf4c85443798b71470eda9b5faf4c58d70fb0ba7` 的失败日志，仅更新与本轮明确要求冲突的旧浏览器断言：场景来源按钮改名、模型检测抽检动作名、隐藏 legacy patience 控件改为不存在断言、YOLO/COCO/VOC 外部英文标签与已有 canonical code 精确一致时自动预选且最终确认 payload 必须保持 classId→code。保留原先抽检持久化、映射最终 POST、数据模式及按钮功能断言；未删除测试。label-normalization 与 ZIP 工作流仍断言静态缓存键精确等于实际已加载版本，补 assert 现有 source-label 手动入口；不改变调度或标签 Owner。剩余训练继承身份错配另行审计。

## 2026-10-10｜ZIP 精确同码映射浏览器合同同步

原 `zip-import-refresh-recovery.spec.mjs` 两处旧断言要求同码存在时仍保持空映射，与用户要求“外部英文编码和平台英文相同直接导入”冲突。已更新为：首次读取匹配有效 canonical code 时显示“编码一致”、自动填入目标选择，不产生新的标签 POST；显式创建 source code 并刷新后应继续自动恢复同码映射。确认并启动 ZIP 的服务器 POST 与持久化身份断言仍保留，未跳过测试。

## 2026-10-10｜场景算法实测真实浏览器验收纳入主 CI

`tests/browser/quality-detection-workbench.spec.mjs` 之前存在但不在 `frontend-runtime-stabilization.yml` 显式 Chrome 运行清单内。现将该规格加入已有导航工作流，不新建 CI Owner，也未删除/跳过/放宽其他测试。验收包括场景算法实测、模型版本选择、检测批次详情及原始推理工作流；以精确 HEAD 的 Chrome result 为准。

## 2026-10-10｜控制端展示不依赖 Agent 注册列表

补强算力一张图：若 Service Node API 超时或失败，仍可以独立显示已有的控制端本机 CPU/内存/磁盘/GPU 快照。Agent 节点数量与在线 GPU 不得被误标为 0，明确显示未知；保留请求错误。无新 Agent、无额外轮询或调度逻辑。新增定向测试，更新静态缓存数字版本，VERSION.txt 未变。

## 2026-10-10｜算法总览重复质量请求回归修复

合并算法总览和原生产看板后，发现两个 Owner 同时 GET `/api/v42/.../quality-overview`，导致已有页面性能合同失败。Overview Tabs 现在优先复用原生产 DashboardExtras 按项目隔离的 `dashboard422ExtrasRefreshPromise` 与 `state.v42.quality`，对于该 Owner 读取失败不即时再打第二个 GET；在无原生产 Owner 的单元环境保留本身 GET，保持异步 A→B→A 项目隔离。严格 DOM 测试模拟器实现真实 insertAdjacentHTML 行为，并模拟原生产 owner 对 view 的覆盖；新增单 GET 复用契约。未新增轮询、未删除或放宽测试。

## 2026-10-10｜两张总览/场景检测/导入交互与本机统计补强

本次合并「算法生产总览」与「算法一张图」为算法总览，实测数据优先显示，后段保留业务运行指标空态；算力一张图新增复用 Node Agent 的本机控制端只读 CPU/内存/磁盘/GPU 采样，不将本机直接加入可调度 Agent；训练弹窗显示智能自动调度，不修改调度参数；场景算法实测以单模型为默认，额外可加对比模型，只允许预训练原始 YOLO 模型及正式算法版本 best.pt，沿用真实推理、批次和结果带框图；ZIP/存储导入使用英文 code 完全匹配既有标签，其余仍需手动创建/映射及确认，原图预览放右侧；上传/导入弹窗可最小化且保留原 DOM 上传任务。同步旧测试期望和入口缓存版本，无测试放宽，无 VERSION.txt 变更。最终 CI/真实浏览器状态必须精确 HEAD 核验后认定，不部署生产。

## 2026-10-10｜缓存版本与清洗回归断言对齐

精确 HEAD `fc40336` frontend 单测结果 908/909，唯一红灯为 `clean-task-view.test.mjs` 仍静态断言旧的 main.mjs 缓存标识 `42.25.349`；已仅将精确期望改为当前页面 `42.25.350`，保留原有完整严格断言和 app.js、cleaning.js 缓存防回退核验，不修改清洗业务实现，也不修改 VERSION.txt。

## 2026-10-10｜Chrome 用例接入既有 CI

检查 `frontend-runtime-stabilization.yml` 发现浏览器导航工作流显式枚举 spec 文件，新建 `tests/browser/overview-tabs.spec.mjs` 不会自动运行。现将总览真实 Chrome 用例加入该已有 `browser-navigation` 测试列表；保留原有所有测试，未跳过任何断言，也没有新建第二套 CI owner。是否通过须依据精确 HEAD 对应 job 的 completed/success。

## 2026-10-10｜总览三 Tab Chrome UI 回归用例

新增 `tests/browser/overview-tabs.spec.mjs`：真实 Chrome 路由合同样例检查原生产总览不回退、两张图 Tab 切换、质量指标与算法版本计数、GPU 采样缺预约时的未知态、离线节点风险/非实时资源隔离、中心边缘过滤、1366×768/1920×1080 Tab 可见、节点接口失败后不再展示旧资源。该用例必须由最终 HEAD 的真实 Chrome CI 成功后方可标记通过。

## 2026-10-10｜三 Tab 静态资源缓存版本合同

6bd7384 精确 HEAD 前端 CI 报 material-upload-runtime.test.mjs 断言主入口缓存标记必须为数值点分版本；改为既有规则的 `main.mjs?v=42.25.350`，同时将总览 CSS 与 Runtime 模块查询版本设为 `4226350`。这只是静态缓存键，不修改 VERSION.txt，也不放宽测试。其他已观察到的 training-create patience 控制断言与 GitHub 安装 oss2 依赖不完整问题需与总览修复区分，按最终精确 HEAD 单独审定。

## 2026-10-10｜三 Tab 验收 CI 修正

第一次精确 HEAD `50b7615` 的 frontend 测试 908/909 通过，唯一失败为早期 GPU 测试在缺少预约/调度政策字段时仍期待 candidate=1；已将该测试 fixture 显式提供 active_tasks/reserved_bytes/max_concurrent_per_gpu/memory_safety_bytes，使正向准入断言仍被覆盖，新缺数据 fail-closed 测试保持不变。更新 index 与 main.mjs 的局部静态资源缓存键，不修改 VERSION.txt。需要重新核实本次最终 HEAD 全部 CI。

## 2026-10-10｜三 Tab 首轮验收补强（保持版本 42.24.349）

在长期开发分支核实 a1bb67a970201297afe4c3ebc06f72bb40cad812：21/21 GitHub Actions 成功；未改 main、tag、release、生产部署。确认现有唯一 Overview Tabs Runtime、质量接口、服务节点 Agent、GPU runtime、存储源接口。针对 GPU runtime 仅提供采样、不包含 active_tasks/reserved_bytes/准入阈值这一真实合同，修复缺字段默认为 0 导致的虚假“候选空闲 GPU”：没有真实预约证据时显示 —，绝不把低利用率当成可调度。算法视图改为按当前项目请求 /api/v12/.../algorithms，不依赖可能跨项目滞留的全局缓存；异步请求增加 cache identity fence，阻断 A→B→A 老请求回填；失败清除旧响应并展示错误，返回结构无效不转成零。服务器列表保留在线/超时/禁用/未连接，并禁止离线节点旧采样冒充实时；可按中心/边缘筛选；算法版本数量与模型评测覆盖率分开统计，模型排行可打开已有算法详情；提高核心字号。阈值统计称“资源风险节点”，不冒充历史告警事件。

待接事实源：1）生产推理调用计数：须从业务推理网关/外部平台得到 algorithm_id、调用时间及去重计数；2）策略准确率：须业务判断结果与复核标签及分母；3）单位排行/运行状态：须单位 ID、部署实例、算法 ID 和运行态关联；4）OSS/S3 Bucket 真实容量：须 provider 可审计只读用量接口，暂无则显示未知；5）精确 GPU 调度候选：须现有 Scheduler/Reservation Owner 提供只读准入投影，当前 /api/v62/gpu-runtime 不含预约账本、不能推断。

已增回归：GPU 预约证据缺失、离线节点占用隔离、版本数、项目 A→B→A 迟到响应与失败清空旧算法。精确 HEAD CI 与真实浏览器结果须以后续实际执行为准；未执行/未完成不得标绿。

## 2026-10-10｜总览三 Tab CI 契约补强

恢复前端历史导航静态断言依赖的 `['总览', 'renderDashboardCanonical422']` 映射，保留新 `overviewTabsRuntime` 注册的最终唯一执行 owner（注册顺序由已存在的 NavigationStability Map 覆盖规则保证）；仅修改缓存版本相应的测试期望，不放宽测试。新增算法类型、精度与策略隔离、中心边缘显式位置、离线节点过滤、调度数据失联 fail-closed 的纯函数测试；修正 bytes KB/MB 单位及生产总览上无需交互的刷新按钮。针对 CI 已查实未触碰旧训练创建控制问题，维持其红灯以供后续修复。

## 2026-10-10｜总览三 Tab（42.24.349）

按用户要求，在既有「总览」页中增加「算法生产总览 / 算法一张图 / 算力一张图」三 Tab。复用原生产总览，不重造任务和指标 owner；通过现有 API GET /api/v12/.../algorithms（缓存态）、/api/v42/.../quality-overview、/api/v63/service-nodes、/api/v62/gpu-runtime、/api/v61/storage-sources 展示真实数据。独立视图模块 `static/modules/overview-tabs.js` 为现有总览页面唯一导航 owner，异步 60 秒 TTL、按 project 隔离、真实空态。算法类型和行业排名、模型评测质量；策略准确率、生产调用频率、单位运行状况缺少可信事实源时必须为缺数，不得用训练数冒充。算力展示在线 GPU、中心/边缘/未分类分布、GPU 显存与使用率、CPU/内存/磁盘节点占用、配置的存储源、阈值预警占比；云 Bucket 容量无真实采样时显示未接入。服务节点显式 placement 元数据用于中心/边缘分类，连接模式绝不可代替部署位置；旧数据迁移默认 unclassified。无第二套采集器、无假数据、不开额外后台轮询。仍需 CI 和浏览器验收，仅长期分支，不合并 main/tag/release/deploy。

## 2026-10-10｜企业 Logo 临时替换（42.24.348）

登录封面与系统左上角使用用户上传的贵州高速、贵州中南交通科技有限公司横向 Logo，取真实图像透明边界后的 825×96、64 色 PNG。单一静态资源由登录桌面、登录移动端及导航左上角复用；登录深色背景增加白色铭牌，收起侧边栏裁切仅显示彩色符号。更新 CSS 引用缓存版本；加 PNG 文件头/界面引用静态测试与浏览器加载断言。仍需 GitHub CI 验收，严格禁止 main 合并、Tag、Release、生产部署。

## 2026-10-10｜独立 RKNN venv 装配边界补充核验

RKNN 转换执行器的 Python 只安装 RKNN SDK，不应导入 platform_core/__init__.py 以致加载平台批量材料 Repository 或额外依赖。执行器仅用标准库与 ONNX 属性执行最后一道兼容性检查；平台内的节点/Worker 仍复用同一探测 owner。新增 Runner 独立运行边界静态回归。

## 2026-10-10｜RKNN 依赖故障最小回归补齐

新增 runner 缺失 onnx.mapping 在 load_onnx 之前中断断言，以及 Agent 实际子进程失败后读取 job.json 错误码、避免传播 traceback / 上传假产物的集成式单测。沿用既有 tests/unit 文件，无新 owner；仍需当前 HEAD GitHub Actions 验证。

## 2026-10-10｜RKNN-Toolkit2 2.3.2 与 ONNX 环境不兼容（42.24.347）

- 用户生产报错：`rknn.load_onnx` → `AttributeError: module 'onnx' has no attribute 'mapping'`，运行环境 `/opt/changlian-rknn-venv`。根因是 Toolkit2 2.3.2 使用旧 ONNX API，转换执行环境装入不兼容版本；不是模型训练问题。
- 修复：`platform_core/rknn_runtime.py` 对 RKNN Python 真实环境检查 ONNX 版本、`onnx.mapping`，不兼容 fail closed，不宣称 RKNN 转换 capability；传统 Worker 在源模型处理前阻断，错误码 `RKNN_ONNX_DEPENDENCY_INCOMPATIBLE`、可操作解决方案；runner 在 `load_onnx` 前二次检查；远端健康检查也用相同探测；Agent 发布清晰错误而不是整段 traceback。
- 回归：更新能力探测 unit mock，加缺失 mapping / probe 缺少真相 / worker 预检失败断言。只提交长期分支；未触及生产 Python 环境、版本发布、主分支及部署。实际 RKNN 2.3.2+onnx1.18.0 烧录/转换需现场验证，CI 需以精确 HEAD 为准。

## 2026-10-10｜四模式训练创建 CI 修复（42.24.345，待全量复验）

- 实际核对基线 `2e01bde1ee362060c23a82be1fad2c5e44341bf3` / `42.24.344` 的 6 个失败 Workflow、对应失败 Job 的原始日志；Remote Material Import 两次触发为同一缓存键测试根因。
- Training Create First Open：训练弹窗 Browser 测试使用已删除的全局高级展开按钮和旧弹窗标题；改为现有“创建训练任务”及数据划分原生 disclosure，训练素材/固定 Benchmark/标签规则仍继续检查。
- Frontend Runtime Stabilization：对应旧标题、旧高级配置与创建提交文案、TrainingDraft 写入顺序的断言漂移，已按可见真 UI 更新；导航与标签的真实操作仍须 Chrome 复验。
- Training Task Visibility / Algorithm SQL Store：同一 `four modes freeze only training semantics` 前端测试揭露生产链缺陷：`trainingDraftToRequest` 通过 `createTrainingDraft` 把历史 `gpuPolicy:auto` 覆盖掉 builder 的 `exclusive`；现在四模式规范化统一强制独占。保留中央 TaskScheduler、GPU Reservation 和 Worker 运行前真实资源决议。
- Remote Material Import 两次：原测试把 `app.js?v=42.25.333` 当成永远不变的字面缓存版本；现在验证版本不回退到旧修复点，同时入口缓存版本实际升级至 `42.25.345`。
- 自定义模式取消“兼容自动隔离”选项；普通模式不显示 Batch/Workers 专业设置；标签搜索、勾选、正式 GT、首次母模型、续训有效版本继承、60/20/20 比例以及单一 TrainingSubmit Owner 均保留。
- 本次只修改对应最小生产文件、前端测试、Browser 测试和现有文档，不另建 Owner、不删减安全测试；最新精确 HEAD 的全量 Linux/Windows/Chrome CI 仍待核验，真实 NVIDIA 同卡阻塞/双卡并发、OSS、Agent、10k/20k 素材 UAT 仍需现场执行。**不合并 main、tag、release、部署生产。**

## 2026-10-10｜训练创建弹窗四模式简化与标签保留（PENDING CI/UAT）

已在唯一训练草稿/提交 Owner 上接入快速、完整（默认）、复杂、自定义四模式，非自定义资源由目标 Worker 入场前决议，自定义为手动硬约束。创建页只保留算法身份、任务优先级、首次母模型选择、训练素材/划分、四模式、**末尾完整的 canonical 训练标签选择和搜索**；取消重复名称/ID/Batch 展示并提高字号。既有标签继承、显式新增、benchmark、精确素材和测试集隔离保持不变。设计及待验收清单：[TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)。静态 JS/V8 定向校验已完成；GitHub Actions 当前 HEAD 与真实 Chrome UAT 尚未完成。不得 merge main/tag/release/deploy。

## 2026-10-10｜训练默认性能/独占优化（代码已提交，验收待定）

正式首训默认 150 Epoch、继承有效上一版本默认 80 Epoch；Auto + Performance；单物理 GPU 独占；小训练集 Batch 限幅以保留每轮多次更新，canonical 资源解析器按 RAM/CPU 限制 Workers；早停显式可选、默认关闭。旧任务和显式参数不迁移、不改写。详见 [本轮专项修复记录](TRAINING_PERFORMANCE_EXCLUSIVE_2026_10_10.md)。**GitHub Actions 精确 HEAD / 真机 GPU UAT 尚未完成，严禁提前宣称全绿或生产完成。** 不合并 main / tag / release / 部署。

<!-- LIVE_UAT_2026_10_09_ISSUE_21 -->
> 2026-10-09 现场 UAT #21 正在验收：七项问题代码提交已存在，3042 张生产失败导入素材尚未实际审计/恢复。新补源文件 SHA256、GT 框数/投影/lineage 只读审计及对应 ZIP CI 测试；此前精确 HEAD 的 55 check-runs 全 queued，不能认定通过。唯一详细事实源见 `docs/UAT_2026_10_09_IMPORT_FIX_PROGRESS.md`、GitHub Issue #21。禁止部署、重导入、清理部分提交素材，Issue 不关闭。

<!-- LIVE_HANDOFF_2026_10_09_GATE_S15 -->
> 2026-10-09：42.24.334 精确 HEAD ee2b0e5 的 22/22 Actions 和 57/57 Checks 全部 success。T1 确认 AUDIT-167 INT8 version Snapshot drift、AUDIT-177 pending feedback label drift，42.24.335 做最小隔离/引用保护并新增回归；新 HEAD CI/UAT 尚未验证。详见 docs/codex-handoff.md 顶部 Gate S15。禁止据此部署生产。

<!-- CURRENT_STATE_ANNOTATION_CLEANING_2026_09_25 -->
> ## 2026-09-25 标注与数据清洗当前状态
>
> 最新详细交接已转到 docs/CODEX_HANDOFF_2026-09-25_ANNOTATION_CLEANING.md。文档写入前 cutoff c1e9dc2d...，VERSION.txt=42.24.0；34 workflows 中 31 success / 3 failure。标注/清洗关键 workflow 均 success；Label Normalization 两个红灯为 source guard exact literal，Training Task Visibility Real Chrome 需另行 focused reproduce。
>
> 标注 durable v60 / provenance / legacy v47 retirement / UI owner 已收口。新的产品优先级是复用现有 MATERIAL_BATCH/CLEAN + OpenCV/Pillow/hash runtime，区分已标注、未标注、已确认无目标，并把图片质量与标注质量分层；默认中央 Worker，远程 Agent 仅在 cleaning capability + portable storage preflight 通过时提供。
>
<!-- CURRENT_STATE_TRAINING_DETAIL_CI_FOLLOWUP_2026_09_24 -->
> ## 2026-09-24 训练详情收口后的 CI 红灯分类
>
> 训练详情代码基线 `8e50195f...` 出现两个 completed failure 后已读取真实日志：External Algorithm Platform Real Chrome 是测试仍引用退役 `[data-external-category-filter]`；ZIP Windows contract 是 guard 仍硬编码 `main.mjs?v=42.25.195`。前者的 Platform contract/wiring 已成功，后者 42 个 ZIP frontend tests 全成功，因此均分类为 **stale test/guard debt**，不是训练详情产品回归。
>
> 已以 `3262d5c100caa214517000e985b7b71437edf472` 迁移到当前 `AlgorithmListRuntime` 品目 owner，并把 ZIP 的无关 global cache exact-version guard 改为有效 cache-busted main 入口检查。没有恢复旧 DOM、旧页面 owner 或旧 cache key；`VERSION.txt=42.24.0`。该 HEAD 新 checks 当时仍 queued，不能宣称全绿。
>
<!-- CURRENT_STATE_TRAINING_DETAIL_LOG_2026_09_24 -->
> ## 2026-09-24 训练详情 / 日志 / 错误提示收口（最新覆盖）
>
> 文档写入前代码 HEAD：`8e50195f76d0aa58ccf6082bdbd7c93029b528b7`；`VERSION.txt = 42.24.0`。当时 88 个 checks queued、0 completed failure，queued 不能视为通过。
>
> **CLOSED：** 训练成功被旧 error/recovery 误显示为失败；训练详情/日志多 owner；详情 GET 回写 worker truth / 重建 index / 触发队列；错误证据过少；运行中详情不跟随 SSE；终态 SSE 后详情停在最后一帧之前；远程/本地日志只有单一来源；详情布局过于平铺。当前唯一 visual owner 为 `TrainingRecoveryRuntime`，列表 owner 为 `TrainingTaskRuntime`，实时事件 owner 为 `TrainingProgressStream`。
>
> **后端合同：** canonical durable `task_status` 优先；SUCCEEDED 清除历史 fatal error，PARTIAL_SUCCESS 转 warning；Worker 写入 `error/error_type/failure_stage`；详情 GET 返回 enriched in-memory truth + runtime metrics / resolved resources，但明确 `allow_version_archive=False`，不承担归档业务；日志 endpoint 合并 `train.log` 与 durable scheduler/worker log。
>
> **刷新合同：** 运行中详情由 SSE 即时 patch + PollRegistry 1.5s detail/log 对账；收到 terminal SSE 后强制再做一次 canonical detail + final log reconcile，随后停止刷新。浏览器 cache 已推进到 `training-recovery-runtime.js?v=422575`、`main.mjs?v=42.25.226`。
>
> **技术债约束：** 不得恢复旧 `openTrainDetail423` renderer、旧 train run center、第二日志弹窗、runtime 私有 CSS owner、裸 setTimeout/setInterval、详情 GET 的业务副作用。
>
> 详细交接与 commit/test 清单见 `docs/CODEX_HANDOFF_2026-09-24_TRAINING_DETAIL_LOGS.md`。
>
<!-- CURRENT_STATE_ANNOTATION_TTL_P0_2026_09_23 -->
> ## 2026-09-23 素材标注 P0 修复（最新覆盖）
>
> 修复前远端 HEAD：`0a8f5c5f1eb0f2153ec04792cead5fe674c04110`；新的 Linux 预部署代码候选：`f50b71da760d5c136010f4d6a4495837e64be795`（直接后继，`fix: share label schema cache ttl`）；`VERSION.txt = 42.24.0`。
>
> **真实生产回归（已 CLOSED）：** 用户从 `素材 → 打开标注` 收到 `打开标注失败：LABEL_SCHEMA_CACHE_TTL_MS is not defined`。唯一 TTL 常量原在 v42.14 标签管理 IIFE 私有作用域，后续独立 annotation workbench IIFE 的 `ensureWorkbench()` 跨 lexical scope 引用它。现已把唯一常量提升到两者共同的文件级 lexical scope；标签管理和标注工作台共享同一个 TTL owner，不新增副本、`window` 接口、fallback 或第二 owner。
>
> `static/app.js` 只移动常量定义；`static/index.html` 的 `app.js` cache key 推进为 `42.25.216`；focused 浏览器验证 `4 passed`，覆盖工作台 ready、标签选择与绘制/保存、cache-first → authoritative refresh、“确认无目标”、已有框恢复。两个相关 JS 文件 syntax check 通过。
>
> **当前 blocker 状态：** 没有其他已 isolated 确认且尚未修复的 production blocker。Linux 真实 GPU / 正式模型、Paddle 环境、真实 OSS / 新畅联、Agent/RKNN 实板、生产数据增量 migration 仍为预部署现场 OPEN；未跑 67 项 Frontend Runtime 或全仓库测试，不得宣称全绿或正式可上线。
>
<!-- CURRENT_STATE_LINUX_PREDEPLOY_AUDIT_2026_09_23 -->
> ## 2026-09-23 Linux 预部署前代码侧审计（最新覆盖）
>
> 审计基线 / 审计前远端 HEAD 为 `5345eba592b4bbf48dbe19fb66e4f7458d437eb7`，`VERSION.txt = 42.24.0`。本轮没有新增产品功能、schema 或第二 owner。
>
> **真实生产 blocker（已修）：** Web 的正式训练 API 支持 `ultralytics / paddle`，并按 framework 写 required capability；final Worker owner `platform_core/training_runtime_tasks.py::worker_registration` 却只注册 `training.ultralytics`，使 Paddle durable task 能创建但无法被本机 Worker claim。最小修复只在同一个 `ProductionTrainingHandler` capability set 增加 `training.paddle`。先验证新增断言在旧代码上按预期失败，再确认 focused registry check、Python 语法和 `task_worker --check --roles training` 通过；Worker 输出同时包含 `training.paddle`、`training.ultralytics`。
>
> **其余代码侧结论：** `app:app` 与独立 `task_worker.py` 可装载；Web/Worker 共享 `resolve_data_dir`、`task_runtime/tasks.sqlite3` 和 artifacts；全部正式 TaskKind 均有对应 handler/capability。SQLite 初始化/迁移为 additive、locked、transactional 或 fail-closed，未发现启动时清空/覆盖正式数据。`projects/<id>/deployment/jobs` 是 control-plane conversion root，`projects/<id>/deploy/jobs` 是 Agent durable commit root，ModelArtifact 有明确优先级和去重，不是双 owner。
>
> **静态启动证据：** app import 成功并装载 264 routes；HTML 11 个本地静态引用、JS/MJS 65 个相对 import 均存在；54 个 `app.js/main.mjs/modules` 文件语法通过。当前 cache key 为 `app.js?v=42.25.215`、`main.mjs?v=42.25.211`、`navigation-stability.js?v=422517`。
>
> **Actions 分类：** Remote Conversion / RKNN failure 依赖退役“部署转换”页面，ZIP failure 是旧 `main.mjs?v=42.25.195` guard，Label/Training Create 是旧 source-regex/cache/helper 合同，均属 stale/test debt；Frontend Runtime 中“测试发布”“工作台”是 stale IA，“上传/选择图片”是 locator ambiguity。其余 annotation/source revisit 红灯尚未 isolated 分类，不修改生产代码，不算本轮 Linux blocker。
>
> **部署前必须保证：** Web/Worker 使用同一真实 `MC_TRAIN_DATA_DIR`（或 `MC_DATA_DIR`）、两个 service 同时运行、Web 继续监听 `127.0.0.1:8010`。外部 OSS/新畅联/GPU/Agent 缺失时主平台仍应启动，相应能力 fail closed。
>
> **OPEN：** Linux 真实 GPU / 正式模型训练推理、Paddle 实际环境、真实 OSS 长期 URL、新畅联 Version/Weight、Agent/RKNN 实板、生产数据目录上的启动/增量 migration 观察，以及尚未逐条 isolated 的浏览器回归。除本轮已修 capability 断层外，当前没有确认且尚未修复的代码侧预部署 production blocker。
>
> 详细 A-J 证据见 `docs/CODEX_HANDOFF_2026-09-23.md` 顶部。未跑全仓库测试或 67 项 Frontend Runtime；不得宣称全绿、正式上线或生产验收完成。
>
<!-- CURRENT_STATE_FOCUSED_RUNTIME_FIX_2026_09_23 -->
> ## 2026-09-23 Focused Runtime 当前真实状态（最高优先级覆盖）
>
> 基线 HEAD：`6dc0d7d3856f2a8015b78188ba93f14a2242a85f`。本轮本地代码修复提交：`8a29809afb797eeef9bafc946d70797c41ef8830`（`fix: route late UI helpers through final owners`）。`VERSION.txt` 仍为 `42.24.0`。
>
> 真实生产回归 `cleanTaskView427 is not defined` 来自 `9839cb46`：清洗进度代码迁入后置 IIFE 后，仍跨词法作用域调用前一 IIFE 的私有 helper。final owner 是 `PlatformCore.cleaning.cleanTaskView`，来源 `static/modules/cleaning.js`，由 `static/main.mjs` 安装。修复只让后置 UI helper 直接调用该 owner；不暴露旧私有函数、不新增 fallback、不建立第二 owner。
>
> 同轮 AI Candidate Review 失败经 isolated reproduce 确认不是 edits 丢失，而是后置 IIFE 无法访问私有 `displayLabel412`，只显示 raw label code。AI v60 标签展示点已路由到现有 `PlatformCore.materials.labelDisplay`。`static/app.js` 合计仅 7 行替换。
>
> “工作台 / 总览”已 isolated reproduce 并分类为 **compatibility alias 未归一**，不是 stale test：`NavigationStability` 原先保留旧请求值，`main.mjs` 也把“工作台”注册成 canonical dashboard owner，`renderTopCanonical413` 因直接显示 `state.page` 而泄漏旧 IA。当前唯一链路为 `normalizeNavigationPage('工作台') -> 总览`，`main.mjs` 安装最终 `window.setPage` 并只注册 `总览 -> renderDashboardCanonical422`；标题 owner 继续由 `renderTopCanonical413` 显示 canonical `state.page`。启动持久化迁移、最终导航菜单和 dashboard extras 守卫均统一为“总览”，没有第二 owner。
> 现有浏览器 cache key 同步推进到 `app.js?v=42.25.215`、`main.mjs?v=42.25.211`、`navigation-stability.js?v=422517`；`VERSION.txt` 不变。
>
> **验证：** 前轮 JS 语法检查通过、focused Playwright `2 passed`（remote cleaning progress、AI Candidate Review accept-all）；本轮 `node --check` 对三个导航改动文件均通过，focused `dashboard revisit reuses focused source and quality extras` 为 `1 passed`，并确认旧 `setPage('工作台')` 后 `state.page === '总览'`。未跑 67 项 Frontend Runtime、全仓库测试、真实 GPU / OSS / ChangLian E2E，不得宣称全绿、正式可上线或生产验收完成。
>
> **CLOSED：** `cleanTaskView427` ReferenceError；AI Candidate Review accept-all focused case；“工作台”兼容 route 已归一到唯一 canonical “总览” owner。
>
> **STALE TEST / TEST DEBT：** 仍进入退役“测试发布”页面的算法版本发布浏览器测试；依赖退役“部署转换 / 部署中心”页面的 RKNN 旧 route 测试。测试应迁往受支持入口，底层版本发布与 RKNN 能力保留，不恢复旧产品 IA。
>
> **OPEN：** 其余 broad 浏览器失败尚未逐条 focused 分类；Linux 真实 GPU / 正式模型推理 E2E；真实 OSS / 新畅联生产 E2E；Rockchip 真实板卡验收。当前没有其他已经 focused 确认且尚未修复的生产 bug。
>
> **下一步：** 一次只复现一个失败；先判断 production bug、stale test、测试隔离或时序问题，再做最小修改。不得为了旧测试恢复“测试发布”“部署中心”或其他退役入口。
>
<!-- CURRENT_STATE_CONTINUATION_2026_09_23_CODEX_TAKEOVER -->
> ## 2026-09-23 Codex 接手当前状态
>
> 文档写入前最后确认 HEAD：`c9064dcde055daab926252bf67aea181af6aa0f5`；`VERSION.txt=42.24.0`；89 个 checks 全 queued、0 completed failure。
>
> 当前主线已经从“继续造功能”转到：**等待真实 CI completed 结果 + 只修真实失败 + 补真实 GPU / OSS / ChangLian 生产 E2E + 在 P0 真通过后继续全站 performance profile**。
>
> 不要重复：手动标注、ZIP 可恢复映射、质量中心检测、AI Review 多页/stale fencing、clean PollRegistry、训练提交 scoped refresh、训练任务 jobs-only、启动去二次 extras、训练设备缓存、标签 first-paint、页面 revisit cache、训练资源/模型 prompt background 局部 patch、退役部署 page owner 等 CLOSED 工作。
>
> 接手先读实时 GitHub，再读 `docs/CODEX_HANDOFF_2026-09-23.md` 最新顶部覆盖；Codex 可直接使用 `docs/CODEX_TAKEOVER_PROMPT_2026-09-23.md`。
>

<!-- CURRENT_STATE_CONTINUATION_2026_09_23_BATCH3 -->
> ## 2026-09-23 最新状态：缓存首屏与页面回访守护继续补齐
>
> 文档刷新前最后确认 HEAD：`0fd99a33bec1527c1d4d3d96a220ac43d3fd999b`；`VERSION.txt=42.24.0`；51 个 checks 全 queued、0 completed failure。
>
> 本轮新 CLOSED：训练设备 24h cache 跨 reload；标注标签缓存 first-paint + authoritative revalidation；标签管理 / 训练资源 / 组件检测回访缓存；模型提示词按需；平台对接 / 服务节点 / 存储 / 素材接入 / 视频切帧回访守护；AI Review 54 张三页的跨页 edits / stale request / closed-session fencing。
>
> 仍 OPEN：目标 HEAD completed Actions、真实 GPU 正式模型推理、真实 OSS / ChangLian Version/Weight 生产 E2E。接手先读实时 GitHub，再读 docs/CODEX_HANDOFF_2026-09-23.md 顶部最新覆盖。
>

<!-- CURRENT_STATE_CONTINUATION_2026_09_23_BATCH2 -->
> ## 2026-09-23 最新状态：AI 审核大批量与 stale lifecycle 收口
>
> 文档刷新前最后确认 HEAD：`76fbfdfd5aecce22c32de90f507a1703dbffc21b`；`VERSION.txt=42.24.0`；89 个 checks 全 queued、0 completed failure。
>
> 本轮新 CLOSED：质量中心真实文件夹 input Chrome；clean progress PollRegistry modal patch；AI Review 54 张/34 标签/3 页真实 Chrome；跨页 edits 保留；分页乱序 stale fencing；审核关闭/提交后的 late response lifecycle fencing。
>
> 仍 OPEN：目标 HEAD completed Actions、真实 GPU 推理、真实 OSS / ChangLian 生产 E2E。接手先重读实时 GitHub，再读 `docs/CODEX_HANDOFF_2026-09-23.md`。
>

<!-- CURRENT_STATE_CONTINUATION_2026_09_23 -->
> ## 2026-09-23 续接最新状态 — Real Chrome / 性能 owner 继续收口
>
> **最高优先级仍先读 `docs/CODEX_HANDOFF_2026-09-23.md` 顶部“本轮续接更新”。**
>
> 文档刷新前最后确认代码/测试 HEAD 为 `bb3803167e8cd7ac039cf9766b0b8cfc79c06f2f`，`VERSION.txt = 42.24.0`。该 HEAD 当时 **55 个 checks 全部 queued、0 completed failure**，所以不具备“全绿 / 部署候选”结论。
>
> 本轮已把 P0 浏览器守护进一步补到：手动标注画/拖/resize/删/撤销/缩放/显式空标注/前后切图 autosave/stale fencing；ZIP exact-code 复用、显式新增标签、关闭重开、refresh recovery；质量中心 builtin/算法版本 A/B、A-only/B-only、confidence、真实文件夹 input、durable history、人工核验、Online Feedback bridge。真实 GPU 模型推理 E2E 仍 OPEN。
>
> P1 已继续收口：启动后二次 extras 重绘、训练提交 broad reload、训练任务页多余 training_options/models、标签保存悬空 `refreshImages414`、重复 active nav、退役部署 page-extras owner、质量检测 extras freshness，以及自动清洗详情 raw timer；clean progress 现在由 PollRegistry page owner 原地 patch。page-loading performance spec 已进入正式 Real Chrome CI。
>
> 接手不要重复上述 CLOSED 工作；实时 Actions 一旦出现失败必须先读 job log。真实 OSS / ChangLian / GPU E2E 仍单独 OPEN。
>

<!-- CURRENT_STATE_2026_09_23 -->
> ## 2026-09-23 当前接手入口
>
> **最高优先级：`docs/CODEX_HANDOFF_2026-09-23.md`**
>
> 文档写入前代码/测试 HEAD：`203948a5ef7b68e4a23fc609a6c4233f09d48e95`；正式版本继续保持 `42.24.0`。
>
> 当前已经完成的关键产品变化：退役 standalone 测试发布/检测台和部署中心 owner；收起高级功能时只保留总览/算法生成/数据中心；模型检测迁入质量中心并支持 A/B 原始模型/算法版本、多图/文件夹、持久批次、人工核验和线上抽检证据桥；手动标注改为增量 box patch + 标签缓存重验 + 确认无目标 + 滚轮/适应窗口；ZIP 标签确认可自动复用/显式新增并可从任务中心恢复；AI 审核支持可搜索映射和批量统一标签；数据集卡片、平台对接页、质量中心、AI 素材、工作台启动继续做 stable shell / lazy hydration / focused refresh。
>
> 当前最新 HEAD Actions 在文档写入前尚未形成 completed 结论，不能宣称全绿。新接手者必须先重读实时 check-runs。
>
> 本节与 2026-09-23 handoff 优先于下面所有旧 CURRENT / NEXT。

<!-- LIVE_CURRENT_STATE_2026_09_22 -->
> ## 2026-09-22 LIVE CURRENT STATE — 先读 `docs/CODEX_HANDOFF_2026-09-22.md`
>
> 当前最高优先级交接已迁到 `docs/CODEX_HANDOFF_2026-09-22.md`。本文件后面的 2026-09-20 / 2026-09-21 priority、NEXT、旧部署候选只作为历史证据，不得覆盖实时 GitHub 与 9 月 22 日 handoff。
>
> 9 月 22 日主线：前端 public owner / wrapper 主体已基本收口，继续解决“页面每次点击加载中、切回页面重复等待、创建训练首开卡顿、标注弹窗重开慢”等用户可感知问题。优化原则固定为 cache-first、stale-while-revalidate、in-flight dedupe、scoped refresh、PollRegistry lifecycle、DOM in-place patch；禁止恢复 broad `loadAll()`、raw timers、第二套 truth。
>
> 文档更新前最后一个代码/测试基线：`22e52dc0e86c03ad1b30e5547072d2ec3b388487`，`VERSION.txt = 42.24.0`。接手必须重新读取远端真实 HEAD 和最新 Actions，不得假定该 SHA 仍是当前 HEAD。

# Codex Current State

<!-- PUBLICATION_DURABLE_OWNER_ENFORCEMENT_BATCH3_1_2026_09_21 -->
> ## CURRENT RESUME POINT — DURABLE OWNER ENFORCEMENT BATCH 3.1 COMPLETE LOCALLY
>
> `AlgorithmSqlStore` now enforces the legacy remote-field boundary itself: ordinary version attach rejects `external_algo_version_id/external_publish_status`, explicit patch attempts fail closed, full-graph runtime replacement preserves existing physical legacy values but cannot modify them or create new ones, and only the one-time legacy JSON migration path may populate those columns. This preservation is compatibility evidence, not restored ownership.
>
> Existing canonical ModelArtifact rows now merge only missing legacy storage truth. Matching values are idempotent; conflicting non-empty `storage_source_id/object_key/public_url` or definitive storage status keep canonical truth unchanged and set the provider mapping to `UNKNOWN` with `ARTIFACT_STORAGE_MIGRATION_CONFLICT`. `source_path` is not a remote storage identity. AlgorithmSqlStore legacy Version IDs are copied into `external_version_publications` lazily when publication service/status accesses that Version; `ExternalPublicationRepository.__init__` does not scan every AlgorithmSqlStore.
>
> Focused evidence: 21 AlgorithmSqlStore tests, 63 external-publish tests, and 3 directly affected ModelArtifact nodes passed. No full pytest/integration/browser/Actions run. VERSION remains 42.24.0; Batch 4 RK3568/RK3578 has not started.

<!-- PUBLICATION_DURABLE_TRUTH_BATCH3_2026_09_21 -->
> ## CURRENT RESUME POINT — PROVIDER PUBLICATION DURABLE TRUTH BATCH 3 COMPLETE LOCALLY
>
> `AlgorithmSqlStore` now owns only local algorithm/version business truth, `ModelArtifactRepository` owns file/OSS truth, and provider-aware `external_version_publications` plus `external_artifact_publications` own remote Version/Weight mappings and retry state. Runtime no longer writes `algorithm_versions.external_algo_version_id/external_publish_status` or `external_model_artifacts`; both remain frozen migration sources. Provider/version and provider/artifact uniqueness are enforced, legacy backfill is idempotent, and conflicting remote IDs become `UNKNOWN` and fail closed before remote mutation.
>
> Focused evidence: 60 external-publish unit tests and 5 directly related ModelArtifact tests passed. No full pytest/integration/browser/Actions run. Real OSS and ChangLian production E2E remain OPEN. VERSION remains 42.24.0.

<!-- OSS_CONNECTION_BINDING_BATCH2_2026_09_21 -->
> ## CURRENT RESUME POINT — OSS CONNECTION/BINDING BATCH 2 COMPLETE LOCALLY
>
> StorageSource is the durable owner of endpoint/bucket/public_base_url and secret reference; ModelArtifactConfig owns only storage_source_id/root_prefix. One canonical builder emits final Bucket-relative keys, and artifact uploads suppress the material Provider prefix so the root is never doubled. Connection testing performs PUT/STAT/READ/DELETE plus public Range GET when configured; remote publication probes the real artifact URL before any ChangLian Version/Weight mutation.
>
> Focused evidence: 20 Python tests, 9 frontend tests, and 1 storage-page Chrome smoke passed. Real OSS credentials/public delivery and real ChangLian production E2E remain OPEN. Before Batch 3 database changes, publish the field-owner/migration table and preserve migration→dual-read-if-needed→single-write; no DROP and no long-lived dual-write. VERSION remains 42.24.0.

<!-- CHANGLIAN_VERSION_WEIGHT_BATCH1_2026_09_21 -->
> ## CURRENT RESUME POINT — CHANGLIAN VERSION/WEIGHT BATCH 1 COMPLETE LOCALLY
>
> Current work is still `feature/external-algorithm-publishing`, based on safely synchronized remote `2ff431a7`. Batch 1 makes Version recovery a strict AND identity (`versionName + versionNo + bound analysisId`) across product/analysis query paths; ambiguous or incomplete candidates become UNKNOWN without a POST. Weight creation requires all five official fields; recovery requires exact file/platform/non-empty chip and matching returned `filePath` when present. Weight prerequisites are checked before remote Version creation.
>
> `code=0` remains primary while `code=200/SUCCESS` remains marked legacy compatibility / OPEN. Focused verification: 15 new-contract cases (including cross-list same-ID deduplication and retry after repairing FAILED prerequisites) + 9 directly affected regressions passed; no browser/full pytest/integration/Actions run. Batch 2 status is superseded by the latest section above. `VERSION.txt` remains `42.24.0`.

<!-- CACHE_FIRST_LOADING_2026_09_21 -->
> ## CURRENT RESUME POINT — CACHE-FIRST PAGE LOADING COMPLETE LOCALLY
>
> Latest product commits are `9fff42df` (v53 request-local counts/cache replacement + label summary SQL owner) and `2e3a726b` (single cached startup snapshot, no ordinary `refresh=true`, no extras jobs/model-config duplication, v61 current-page-first paint).
>
> Owner truth remains unchanged: AlgorithmListRuntime / TrainingTaskVisibilityRuntime / MaterialPaginationRuntime / ServiceNodeRuntime and PollRegistry perform page-specific authoritative refreshes. Explicit refresh still requests an authoritative snapshot. No second cache, polling owner, fake data, or long durable-task confirmation chain was introduced.
>
> Browser inventory improved from `10 requests / 2 snapshots / refresh=true / ~998ms` to fresh-cache `4 / 1 / false / ~542ms`, or stale-snapshot page-owner SWR `8 / 1 / false / ~353ms`; dataset visibility improved from `6 requests / ~145ms` to `4 / ~27–30ms`. Targeted verification passed: API 5, frontend 12, browser 4. Full pytest/integration and Actions are NOT VERIFIED. `VERSION.txt` remains `42.24.0`; no merge/tag/release/deploy.
>
> Read `docs/CODEX_HANDOFF_2026-09-21.md` section 0A before every older NEXT below.


<!-- P0_OWNER_CLOSURE_2026_09_21 -->
> ## CURRENT RESUME POINT — P0 OWNER CLOSURE COMPLETE LOCALLY
>
> Read `docs/CODEX_HANDOFF_2026-09-21.md` section 0 before every older NEXT below. Four P0 usability paths now reuse their real owners:
>
> - training creation: durable `TaskRepository` response → strict identity validation → `TrainingTaskRuntime` immediate merge;
> - navigation: `state.page` → `NavigationStability` registered owner → target shell; no title-observer routing;
> - training modal: immediate shell → parallel cached hydration guarded by the existing epoch/scope;
> - material boxes: current-page batch → `AnnotationRepository` → source-coordinate SVG, with three explicit annotation states.
>
> Local implementation commits include `249a8b89`, `e92d6c00`, `89c04070`, followed by the material-box/handoff commit. `VERSION.txt` remains `42.24.0`. No full suite, full integration, Actions wait, deployment, merge, tag, or release was performed in this P0 batch.


<!-- CURRENT_HANDOFF_2026_09_21 -->
> ## CURRENT RESUME POINT — 2026-09-21
>
> **Canonical current handoff: docs/CODEX_HANDOFF_2026-09-21.md**
>
> Read that document before using any older NEXT/current-priority text below. It records the current code/test baseline, SQLite lifecycle fixes, ResourceDiscovery spawn root cause, material/annotation batching contracts, Training V3 Dataset Revision truth, ChangLian integration rules, exact remaining integration validation, and deployment gate.
>
> Last code/test HEAD before the handoff-document commits: bc88fcdfd7a5097499a67596741b8f13018f7645.
> Handoff document commit: 8ab473efbca7cb2c95b032de0858bb7070d8b0af.
>
> Current immediate priority is **verification, not more production-code expansion**:
>
> 1. re-read live remote HEAD / VERSION / recent commits / Actions;
> 2. run the two focused integration tests fixed after the 0fc6acd candidate run;
> 3. run full tests/integration and require 0 failed;
> 4. only then run task_worker.py --check and deployment preflight.
>
> The 2026-09-20 LIVE CURRENT STATE below is retained as historical context and no longer overrides the 2026-09-21 handoff.


> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

<!-- CODEX_LIVE_HANDOFF_2026_09_20 -->
## LIVE CURRENT STATE — 2026-09-20

> **Codex resume point.** This section overrides older “NEXT”, “Current priority”, acceptance-HEAD and implementation-baseline text below when those historical notes conflict with current GitHub reality. Always re-read the remote branch first because this documentation commit will advance HEAD.

本次 Live Handoff 记录的代码 HEAD（文档提交前）：`9d4fdeb7c1417dec61a26b6a0f4603306580da90`

当前正式版本：`VERSION.txt = 42.24.0`

上述代码 HEAD 的 Actions 快照（2026-09-20 本轮重新核对）：
- total: 18
- queued: 18
- in_progress: 0
- completed success: 0
- completed non-success: 0
- **queued != passed；在当前 HEAD 的永久 workflow 实际完成前，不得写“全绿”，不得部署或切换 `/data/platform/current`。**

GPU 正式服务器当前仍运行上午部署：
- full SHA：`ea1b6f198f81556c05d963f4c3f70d2865f316ff`
- release：`/data/platform/releases/ea1b6f198f81`
- current symlink：`/data/platform/current`
- Web service：`changlian-web.service`
- Worker service：`changlian-worker.service`
- Web listen：`127.0.0.1:8010`
- Windows SSH tunnel：`http://127.0.0.1:18010`
- business DATA_DIR：`/data/platform-data`
- secret env：`/etc/changlian/secret.env`
- encrypted credential store：`/data/platform-data/secure/secrets.enc.json`

**重要：GPU 正式服务器尚未部署上述代码 HEAD；接手时仍必须先重读远端 HEAD，因为后续文档提交也会推进分支。**

### Algorithm list filter owner closure

本轮已完成算法列表筛选 owner 收口：

```text
AlgorithmListRuntime
  query
  selectedCategoryIds[]
  source
  status

ExternalAlgorithmPlatform
  category metadata
  external metadata
  training readiness
  decorator only
```

并已补齐搜索真实字段：算法名称、算法编码、Product ID / productCode、描述、行业、算法类型。永久测试和 `external-algorithm-platform.yml` guard 已增加；当前 Actions 仍 queued，不能部署。

### Exact analysis training gate

新畅联分析方式训练资格按官方字段精确判断：

```text
status = 1
AND
analysisType = 1
```

只有同时满足两项才允许 YOLO 训练。status=0、analysisType=2/3、字段缺失/空值、按名称猜“视觉”、以及仅有旧 `external_analysis_ids` 而无明细佐证，全部 fail closed。前端、后端、SQL store 和永久测试已统一到这一规则。

### Automatic model delivery and destructive rollback

Current product contract:

- Algorithm rollback means deleting the current version, then selecting the target historical version as current.
- ChangLian external-version rollback/direct delete calls the official version-remove API first. Local deletion is fail-closed if remote deletion fails or cannot be uniquely confirmed.
- If delete transport returns an unknown result, the platform immediately re-queries the product version list. Confirmed absence is treated as recovered success; an existing or ambiguous version blocks local deletion.
- Successful training creates the local algorithm version first. The trained model is then archived automatically to canonical model storage; after OSS verification, ChangLian version/weight records are synchronized with persisted `algoVersionId / weightId / filePath`.
- Original trained model delivery is mandatory. Later ONNX/RKNN conversion results are appended to the same external `algoVersionId` without re-creating the version or re-registering existing weights.
- Model Artifact storage is canonical. The UI page is **存储配置**, with **素材存储** and **算法与转换结果存储** sections. Model auto-upload cannot be disabled.
- Model Artifact DB persists stable `public_url`; storage testing validates both provider read/write and the actual long-term URL that ChangLian will receive. Private/unreachable URLs fail before external publication.
- External mode forces ChangLian master-data polling every 60 seconds. The daemon checks due every 5 seconds; provider requests remain 60-second rate limited.
- Remote conversion discovery must scan both `deployment/jobs` and `deploy/jobs`. Remote conversion commits persist `source_trace.algorithm_id/version_id`.
- Remote training objects already uploaded and verified in canonical model storage are reused by publication rather than duplicated.
- Business API authentication remains `Authorization: Bearer <accessToken>` per the current full OpenAPI compilation.

Latest code HEAD before this document update: `8b6f34122f608b74f469010e34480c4ee0265820`.
GitHub Actions snapshot: 18 workflows queued, 0 completed. **queued != passed; do not deploy or switch `/data/platform/current`.**

### Current ChangLian contract

新畅联当前 canonical Provider contract：
```text
POST /internal/auth/test-sign
POST /internal/auth/token
GET  /internal/base/category/tree
GET  /internal/base/compute-platform/listAll
GET  /internal/algorithm/product-ai/listAll
GET  /internal/algorithm/algorithm-analysis/listByProduct/{productId}
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

不得把接口改回旧裸路径：
```text
/compute-platform/listAll
/algorithm-product/listAll
/algorithm-version/add
/algorithm-weight/add
```

完整 31 项 OpenAPI 汇编已经确认：品目、产品、分析方式、算力环境、算法版本、算法权重等内部业务接口均声明 `Authorization: Bearer <accessToken>`。旧 `Access-Token` Header 实现不得恢复。

### Current execution priority

当前第一主线不是继续堆新功能，而是：
```text
重新读取远端 HEAD / VERSION / Actions
→ 为当前 HEAD 创建新的 /data/platform/releases/<sha-short>
→ 不覆盖 ea1b6f198f81 回滚版本
→ 原子切换 /data/platform/current
→ restart changlian-web.service + changlian-worker.service
→ GET http://127.0.0.1:8010/api/health
→ 真实畅联测试：
   test-sign
   → token
   → category
   → product
   → analysis
   → compute-platform
→ 查看真实交互日志和业务码
```

如果 canonical `/internal/base/*` / `/internal/algorithm/*` 已正确但仍出现 HTTP 200 / 业务码 401，下一步检查畅联云侧 AccessKey 应用权限、租户/组织权限、接口授权范围；**不要先把 endpoint 改回旧裸路径。**

真实畅联云生产/联调 E2E 在完成前继续保持 **OPEN / NOT CLOSED**。

### Codex do-not-repeat rules

- Do not redo label normalization / human confirmation / alias-memory / durable annotation commit; that flow already exists.
- Do not re-open CLOSED central scheduler / Agent lease / portable training / conversion work unless there is a reproducible regression.
- Do not invent a second frontend polling owner or a second task state machine.
- Do not treat an older successful workflow count as evidence for the newest HEAD.
- Do not change `VERSION.txt`, merge `main`, tag or release.




<!-- CODEX_CHANGLIAN_BUSINESS_CODE_AUTH_2026_09_20 -->
## Current fix — ChangLian code=0 / endpoint auth / full API catalog

2026-09-20 live integration corrected three contract defects:

- Numeric `code=0` must remain `"0"` and audit as SUCCESS; the old `body.get("code") or ""` path incorrectly converted 0 to empty string and marked successful token calls FAILED.
- The complete 31-endpoint OpenAPI compilation supersedes earlier partial assumptions. Internal business APIs use `Authorization: Bearer <accessToken>`; versions expose full edit/add/remove/list/by-product/by-analysis/listAll/detail and weights expose edit/add/remove/list/by-version/by-product/detail.
- HTTP 2xx with a non-success business code (for example `99999`) now raises at the HTTP-client boundary while preserving the remote business code and message.
- The 31 user-supplied official Apifox documents are registered in `docs/CHANGLIAN_APIFOX_API_CATALOG.md` and surfaced in the platform UI. Only verified Method/Path bindings are marked wired; remaining CRUD/page/detail documents must not be guessed.
- Connection tests remain non-destructive: auth + read-only master-data queries only.

Permanent guards: `tests/unit/test_changlian_audit_client.py`, `tests/frontend/external-algorithm-platform.test.mjs`, `tests/browser/external-algorithm-platform.spec.mjs`, `.github/workflows/external-algorithm-platform.yml`.

## Complete algorithm provider contract — 2026-09-20

The user supplied a consolidated OpenAPI file covering all 31 interfaces. Current code now treats it as the source of truth:

- `/internal/base/category/*` for algorithm categories.
- `/internal/algorithm/product-ai/*` for algorithm products.
- `/internal/algorithm/algorithm-analysis/*` for analysis modes.
- full algorithm-version and algorithm-weight CRUD/query contracts.
- read-only connection diagnostics cover versions and weights.
- destructive edit/remove calls are explicit provider management APIs only.
- publishing pins official paths and parses scalar `data` IDs returned by add-version/add-weight.

Do not reintroduce editable Provider paths in the publish UI.

## Current fix — ChangLian internal API namespace

On 2026-09-20 real integration exposed that the previously stored bare business
paths could reach the gateway but fail with HTTP 200 / business code 401. The
ChangLian Provider now uses canonical internal namespaces for master data and
publication/recovery calls:

- auth: `/internal/auth/*`
- base data: `/internal/base/*`
- algorithm management: `/internal/algorithm/*`

Known legacy bare paths are migrated only on exact match; unrelated custom paths
are preserved. The platform UI no longer exposes Provider endpoint editing.
Business calls use the complete official `Authorization: Bearer <accessToken>` contract. Formal `VERSION.txt` remains
`42.24.0`.

## Current closure — Reusable Fixed Benchmark Training v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The current algorithm version's `bundle_verified` Benchmark Scope can now be
reused by the next Durable TRAINING request without exposing the hidden test
cohort to browser state or creating another training/evaluation owner.

The browser receives only source-version/scope/snapshot/count/binding metadata.
Training submit carries `benchmark_source_version_id` and
`benchmark_scope_id`; the control plane revalidates current-version identity,
successful Evaluation, bundle-verified scope, Snapshot identity, test source
content SHA256, annotation hash/state, and label-schema truth before resolving
the exact test IDs server-side.

The resolved cohort becomes the independent test split. If user-selected
training candidates intersect that hidden cohort, the server now applies the
same component relation truth as the split leakage guard and reserves exact
test materials plus connected duplicate-content/file/group/video/session
samples before freezing the Durable TRAINING payload. The Dataset Revision and
Snapshot therefore describe the effective train/validation candidates and the
fixed test cohort, not the browser's pre-reservation selection.

Only selected/reserved/effective candidate counts are added to benchmark reuse
audit metadata. Hidden test identities remain server-side. A selection that is
entirely reserved fails closed with an actionable request for additional
training material.

Frontend Impact Review is complete. The stable training modal calls these
materials “训练候选素材”, explains that fixed evaluation material is
automatically reserved, keeps the test picker out of the fixed-benchmark mode,
and submits only benchmark identities. Real Chrome verifies the browser-blind
contract.

No Agent permission changed. Central Scheduler, assignment/execution leases,
generation fencing, portable object transport and server-confirm remain the
existing owners.

Implementation:
- `39f05792f5f6a25c74539d7c7dba1cfabff4e34d`
- `b22fcf66b8e598fa83cfa2fef47c2ce7c555318b`

Acceptance:
- `39f05792...`: 30 workflows / 30 success / 0 failure / 0 pending.
- `b22fcf66...`: 25 workflows / 25 success / 0 failure / 0 pending.
- Training Input Integrity push `35439895596`: Ubuntu + Windows success.
- Remote Training Runtime `35439898019`: API + Ubuntu + Windows success.
- Training Create First Open `35439895675`: Ubuntu + Windows contracts +
  Real Chrome success.
- `VERSION.txt = 42.24.0` unchanged.

**OPEN:** physical RK3568/RK3576 acceptance remains independent. This closure
does not introduce a standalone Benchmark Registry/proactive re-evaluation
scheduler, and it does not change the existing `automatic_execution=false`
iteration semantics. Controlled automation remains a separate future phase and
must reuse the current Durable TRAINING/Evaluation owners.

## Current closure — Evaluation Benchmark Scope v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Independent Evaluation now persists a benchmark identity that distinguishes
Snapshot test truth from the exact verified Test Bundle that was actually
evaluated.

No new TaskKind, scheduler owner, database owner, or automatic retraining path
was introduced. Snapshot v3 remains the source of test cohort and hidden
ground-truth identity. Benchmark Scope v1 freezes test image IDs, source
content SHA256, annotation hash/state, and label-schema identity.

A Snapshot-only benchmark is persisted as
`binding_level=snapshot_truth` and is descriptive only. Strict comparison
requires `binding_level=bundle_verified`, which additionally validates the
task-owned `work/bundle/manifest.json`: exact test cohort, Snapshot source
SHA256, materialized evaluation image SHA256, hidden label SHA256 and one
training-input policy. Those inputs produce a deterministic
`evaluation_input_digest`.

Evaluation protocol identity is versioned with
`evaluation_protocol_version=1`. Feedback-adoption before/after results are
strict only when both evaluations succeeded, both benchmark scopes are
bundle-verified and equal, and both evaluation protocol IDs are equal.
Historical or incomplete evidence receives
`benchmark_input_binding_missing` and remains descriptive.

Local and Remote Agent training use the same truth. The local compatibility
job overlay whitelists only `dataset_manifest_ref` from the Durable TRAINING
result so version archival can read the task-owned manifest without copying
the whole result into legacy job JSON. Remote server-confirm reads the target
TRAINING task's `snapshot.json` and `work/bundle/manifest.json` directly
before persisting the remote Algorithm Version evaluation. Agent permissions
did not change; the Agent still cannot access central SQLite/NFS.

Frontend Impact Review is complete. The existing independent Evaluation modal
renders persisted benchmark identity and binding level, showing “已校验 Test
Bundle” for bundle-verified evidence and “仅 Snapshot truth” otherwise. The
browser does not calculate strictness.

- Acceptance code HEAD：`ac8ac782632c3d63cb7ed6a8c807a826451abb5e`。
- Current-head shared regression：23 workflows / 23 success / 0 failure / 0 pending。
- Remote Training Runtime push `35436884535`：API + Ubuntu + Windows success。
- Remote Training Runtime PR `35436887856`：API + Ubuntu + Windows success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Algorithm SQL Store `35436643513`：contracts + Real Chrome lineage success。
- Parent `6c2c7c92d733176a24438c22cea570bc4786b5a8` 的 Training Task Visibility `35436643535`：Unified training job overlay truth + Real Chrome success。
- `VERSION.txt = 42.24.0` unchanged。

**OPEN:** real RK3568/RK3576 physical-board acceptance remains independent.
Benchmark v1 does not introduce a standalone Benchmark Registry or automatic
cross-snapshot re-evaluation owner; such a future phase must reuse the existing
Evaluation/Durable Task architecture.

## Current closure — Feedback Adoption -> Iteration Outcome / Effectiveness v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

A feedback-backed training adoption now produces persisted, version-owned
effectiveness truth without introducing a new task or database owner.

The new Algorithm Version field is `feedback_adoption_outcome`. It is derived
only from the source version's persisted independent Evaluation, the new
version's persisted Evaluation, and the new version's
`training_lineage.supplement_provenance`. It does not reread transient UI
drafts, rescan feedback rows, or rebuild a Candidate Set.

Source identity is fail-closed: the source version comes from the real training
lineage base version and must match the supplement provenance source version.
The deterministic outcome records source/new version identity,
candidate_set_id, adoption_id, action_id, source/new evaluation IDs, adopted
feedback identity, overall Precision/Recall/mAP50/mAP50-95 before/after deltas,
and per-source-weak-label metric / FP / FN effects.

If the required persisted evaluations are missing or unsuccessful, the outcome
is `not_comparable` with reason codes rather than an invented improvement.
Every outcome is `descriptive_only=true` and
`automatic_execution=false`; it never creates another training task.

Frontend Impact Review is complete. The existing Algorithm Version independent
Evaluation modal reads the persisted outcome directly and shows “补数据效果”,
adopted feedback count, overall metric deltas, source weak-label changes and
Outcome/Candidate Set/Adoption provenance. The browser does not calculate the
effect itself and explicitly says that the report will not automatically start
another training iteration.

Acceptance code/test HEAD:
`c26b7449b06697fcac52979e9bb8483138ebbbab`.

- Current-head shared regression at `c26b7449b06697fcac52979e9bb8483138ebbbab`: 17 workflows / 17 success / 0 failure / 0 pending.
- Algorithm SQL Store `35432975461`: contracts + Real Chrome lineage success. This run covers the Effectiveness implementation code; later commits only fixed unrelated browser test project setup.
- Online Feedback Runtime push `35433393053`: Ubuntu / Windows / Real Chrome success.
- Online Feedback Runtime PR `35433395739`: Ubuntu / Windows / Real Chrome success.
- Remote Training `35433395670`, Node Agent `35433395713`, Material Import `35433395706`, Cleaning `35433395720`, Conversion `35433395702`, RKNN `35433395700`, Portable Deployment `35433395671`, Central Assignment `35433395650`, Task Runtime Truth `35433395684` all success.
- `VERSION.txt = 42.24.0` unchanged.

**NEXT / OPEN:** Evaluation Benchmark Scope v1. Snapshot v3 already persists
test_image_ids plus per-image content SHA256 and annotation hash. The next
evaluation-hardening phase should freeze a reusable benchmark identity from that
truth so that strict before/after comparability requires the same test cohort
and ground truth. Effectiveness v1 remains a descriptive comparison and does
not claim causal attribution.

Rockchip real RK3568/RK3576 physical-board acceptance remains independently
OPEN; software CI does not substitute for field NPU acceptance.

## Current closure — Supplement Candidate Set -> Revision / Snapshot / Training Lineage v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

A frozen version-owned feedback Candidate Set can now enter the existing
Dataset Revision -> Snapshot -> Durable TRAINING chain without introducing an
automatic retraining owner.

The frontend submits `supplement_candidate_set_id` only when the user's actual
training/test selection intersects the frozen candidate material IDs. The
control plane then rereads current MaterialRepository and AnnotationRepository
truth and fails closed if material SHA256, annotation hash, or annotation state
no longer matches the candidate evidence.

The final Snapshot, not the UI, defines adoption. It freezes only the candidate
materials that actually entered the snapshot and builds a deterministic
`adoption_id` plus candidate_set/action/source-version identity,
`adopted_feedback_ids`, `adopted_material_ids`, bounded candidate evidence,
and `automatic_execution=false`. Dataset Revision identity includes this
supplement provenance, and Snapshot carries the same provenance.

Local and Remote Agent training share the same contract. Remote preparation
copies the Snapshot supplement provenance into the portable training contract;
the Agent does not recalculate candidate adoption. Server-confirm writes that
same provenance into the persisted Algorithm Version training lineage.

Frontend Impact Review is complete. Persisted supplement actions restore the
data draft/weak-label context before candidate review. A frozen Candidate Set
resumes directly into Dataset truth after refresh rather than reopening the
candidate review. Training summary displays candidate source/adopted counts,
and no candidate action itself starts training.

Acceptance code HEAD:
`49becaf398403b76e4209ed35ca18aaa8ef860a1`.

- 18 relevant workflows: 18 success / 0 failure / 0 pending.
- Algorithm SQL Store `35431356487`: contracts + real-chrome-lineage success.
- Online Feedback Runtime push `35431356518` and PR `35431359456`: Windows /
  Ubuntu contracts + Real Chrome success.
- Remote Training Runtime `35431359366`: API + Windows/Ubuntu preparation
  contracts success.
- Training Input Integrity `35431359267`, Node Agent Executor
  `35431359353`, Remote Material Import `35431359273`, Remote Cleaning,
  Conversion, RKNN, Portable Deployment, Central Assignment and Task Runtime all
  succeeded.

**NEXT:** Feedback Adoption -> Iteration Outcome / Effectiveness v1. Build a
version-owned, descriptive before/after outcome from persisted source/new
evaluations plus supplement provenance. It must not automatically schedule
another training run. Physical RK3568/RK3576 acceptance remains independently
OPEN.

## Current closure — Feedback → Supplement Data Candidate v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Confirmed online feedback now enters a version-owned supplement-data candidate
workflow without introducing a second data or training owner.

Only confirmed feedback bound to the exact current algorithm/version is
considered. The backend joins feedback with current MaterialRepository and
AnnotationRepository truth and returns authoritative `eligible`,
`reason_codes`, and `candidate_digest` values. Pending/dismissed feedback is
excluded. A needs-correction sample remains ineligible until formal annotation
truth exists.

The user explicitly selects candidates. Freeze posts feedback IDs together with
the observed candidate digests; the server rereads current material/annotation
truth and fails closed when it changed. The resulting
`supplement_data_candidate_set` is stored on the Algorithm Version with a
deterministic candidate_set_id, feedback/material IDs, annotation hashes, and
model/input identities. Repeating the same set is idempotent; a different set
cannot overwrite the frozen version truth.

Frontend Impact Review is complete. The existing Dataset page is reused:
review candidate list → freeze → Dataset page candidate banner/filter. No
parallel page or owner was added, and the UI explicitly states that no Dataset
Revision, Snapshot, or TRAINING task exists yet.

Acceptance HEAD: `a54e0e735b27bde400b205fe1d07ede03903a973`.

- Online Feedback Runtime push `35428464451`：Ubuntu / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35428467030`：Ubuntu / Windows contract / Real Chrome 全部 success。
- 当前 code HEAD `a54e0e735b27bde400b205fe1d07ede03903a973`：17 个相关 workflows，0 failure / 0 pending；Node Agent Executor API / Ubuntu / Windows 也全部 success。
- `VERSION.txt = 42.24.0` 未修改。

**NEXT:** Supplement Candidate Set → Dataset Revision / Snapshot / Training
Lineage v1. Before training submit, revalidate candidate material/annotation
identities and carry only the actually selected feedback subset into revision,
snapshot, training lineage, and the produced Algorithm Version. Automatic
training remains forbidden.

## Current closure — Online Algorithm Sampling / Feedback v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Online sampling, test-publish feedback, and external SaaS/edge sample intake now
share one reviewed feedback contract. No second training owner or automatic
retraining path was introduced.

Feedback has only three durable states: `pending_review`, `confirmed`, and
`dismissed`. Each record is bound to prediction/external sample identity,
algorithm/version, model SHA256, input SHA256, detections, confidence, engine,
and source channel evidence.

External intake at
`/api/v63/projects/{project_id}/online-feedback/external-intake` verifies the
formal algorithm version and exact model SHA, validates the uploaded image and
bounded detection evidence, then stages `pending_review` only. It does not
write MaterialRepository, AnnotationRepository, Dataset Revision, Snapshot, or
TRAINING.

Explicit user confirmation is required before promotion:
- `correct` may confirm prediction boxes only when they do not overwrite
  different existing annotation truth;
- `false_positive` requires explicit all-active-label negative confirmation;
- `needs_correction` remains a manual annotation path.

Confirmed samples reuse material by content SHA when possible and otherwise
enter the existing MaterialRepository. AnnotationRepository remains the sole
formal annotation owner. Dismissed feedback has no material, annotation,
revision, or training side effect. Legacy v42 feedback/automatic iteration
writes are retired.

Frontend Impact Review is complete. Test Publish uses the v63 reviewed flow for
submit/review/confirm/dismiss/external intake. The legacy audit-connect alias
routes only to the new reviewed external-intake contract. Real Chrome verifies
the product flow and absence of automatic training/revision side effects.

Acceptance HEAD: `7a1ade605b6a55e1fe9027a86dc6756af795456b`.

- Online Feedback Runtime push `35427702717`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Online Feedback Runtime PR `35427704825`：Ubuntu contract / Windows contract / Real Chrome 全部 success。
- Product code HEAD `05ba04f132e746ac3bd96b05790f0b526acd0236` 的其他共享 workflows 均 success；当时唯一红项是 Online Feedback Runtime，根因仅为 focused CI 缺少 OpenCV 依赖和测试使用了不存在的 MaterialRepository.list()，均已在 acceptance HEAD 修正。
- `VERSION.txt = 42.24.0` 未修改。

**NEXT:** Feedback → Supplement Data Candidate / Dataset Revision Candidate v1.
Only confirmed feedback may enter a frozen supplement-data candidate set. The
user must explicitly confirm the selected material scope before the existing
Dataset Revision → Snapshot → Durable TRAINING chain is invoked. Every later
revision/snapshot/training lineage must remain traceable back to feedback IDs.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Iteration Decision → Confirmed Action v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The version-owned `iteration_decision` now drives one explicit, user-confirmed
`confirmed_iteration_action` contract. The algorithm version remains the
long-term owner. No second training/data owner and no frontend-derived action
state was introduced.

Confirmation is fenced to the current algorithm version and exact persisted
decision identity. Repeating the same confirmation is idempotent; attempting a
different action after confirmation fails closed.

The four formal actions are:

- `needs_data -> supplement_data`: freezes weak-label and FP/FN problem-sample
  evidence into a data draft. It does not mutate Dataset Revision or import/delete
  material automatically.
- `continue_training -> continue_training`: freezes a deterministic Durable
  TRAINING task ID and exact action/decision/evaluation/version/revision/snapshot
  lineage. The existing Scheduler, lease, generation and server-confirm owners
  remain authoritative. A real task starts only after user submit.
- `ready_for_business_validation -> business_validation`: persists a validation
  entry bound to decision/evaluation/version/revision/snapshot/model identities.
- `review_required -> manual_review`: persists a review entry with reason codes,
  recommendations and source lineage, without automatic execution.

New training lineage carries the confirmed action identity. Frontend Impact
Review is complete: the evaluation modal reads persisted
`evaluation + iteration_decision + confirmed_iteration_action`; after refresh
it shows the already-confirmed action and can resume supplement-data,
continue-training, business-validation or manual-review flows from version truth.
Real Chrome verifies confirm -> navigation -> transient-state reset -> version
refresh -> resume without a second confirm call, accidental `/train/start`, or
historical `/jobs` refetch.

Acceptance:

- Product code HEAD `d422fc21b3394edd71567a81bc34316d1172c652` shared regressions: 0 pending / 0 shared failure.
- Latest acceptance HEAD `4076f8adb376c24e32db78cf3bd15f83182ebcb4`: Algorithm SQL Store run `35424317881` contracts + Real Chrome success.
- Remote Training Runtime PR `35424280734`: API / Ubuntu / Windows success.
- Node Agent Executor PR `35424280790`: API / Ubuntu / Windows success.
- Remote Material Import PR `35424280896`: API / Ubuntu / Windows / Real Chrome success.
- Remote Cleaning Runtime PR `35424280779`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime PR `35424280823`: control-plane / Ubuntu / Windows / Real Chrome success.
- Portable Deployment `35424280766`, Central Node Assignment `35424280780`, Task Runtime Truth `35424280794`, Training Input Integrity `35424280757`, Remote RKNN Board Runtime Protocol `35424280702`, Storage Cache Governance `35424280744` all success.
- `VERSION.txt = 42.24.0` remains unchanged.

**OPEN / next:** Online Algorithm Sampling / Feedback v1. Production inference
sampling, FP/FN review and user feedback should enter as reviewable evidence bound
to source algorithm/version/model identity, then reuse the existing
Material/Annotation -> Dataset Revision -> Snapshot -> Durable TRAINING ->
Evaluation -> Iteration Decision -> Confirmed Action chain. Do not create an
automatic retraining owner or mutate dataset truth directly from online feedback.
Rockchip physical RK3568/RK3576 acceptance remains independently OPEN.

## Current closure — Training Evaluation / Iteration Decision v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing algorithm-version owner now persists both blind-test `evaluation`
truth and a deterministic `iteration_decision` v1. No second training owner,
evaluation database, or frontend-derived decision path was introduced.

`build_iteration_decision()` consumes the persisted evaluation plus the
training task's existing quality gate. It therefore reuses the already-defined
`eval_metric / continue_threshold / stop_threshold` semantics instead of
inventing a second threshold system.

The persisted decision states are:

- `review_required`: independent evaluation is absent/failed, its metric is
  unavailable, or no final stop threshold was configured.
- `needs_data`: weak labels are present or the final metric falls below the
  original continue threshold.
- `continue_training`: the metric is above the continue threshold but below
  the configured stop threshold.
- `ready_for_business_validation`: the stop threshold is reached and there
  are no weak labels.

The version also freezes metric name/key/value, both thresholds, ordered weak
labels, FP/FN/problem-sample signals, reason codes, recommended actions and a
stable decision ID. `automatic_execution=false` and
`requires_confirmation=true`: this closure does not create a new training
task, mutate data, or silently change conversion semantics.

Algorithm SQL Store round-trip preserves `iteration_decision`. Frontend Impact
Review is complete: the stable version evaluation modal reads only persisted
`version.evaluation + version.iteration_decision`, shows the backend decision
and recommended actions, and explicitly states that no next training run is
started automatically. Real Chrome verifies this without historical `/jobs`
refetch.

Acceptance code HEAD: `d11d0e16998e7630bbc5811a937ba3c21395548e`.

- 17 workflows: 17 success / 0 failure / 0 pending.
- Algorithm SQL Store push `35422469494`: contracts + Real Chrome success.
- Remote Training Runtime push `35422469499`: Windows / Ubuntu contracts + API success.
- Shared Training / Scheduler / Agent / Material / Cleaning / Conversion / RKNN
  / Deployment regressions are green.
- `VERSION.txt` remains `42.24.0`.

**OPEN / next:** Iteration Decision → Confirmed Action v1. Wire the persisted
decision to explicit user-confirmed product actions: weak-label/data supplement
draft, current-version retraining draft, business-validation entry, or manual
review. Every action must carry decision/evaluation/version/dataset/snapshot
identity into the next lineage and must reuse the existing Durable TRAINING and
data owners. Online algorithm sampling/feedback can then enter this same chain.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Training Lineage / Algorithm Version Provenance v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Algorithm versions now own stable training provenance instead of depending on
transient job/cache state. Both local training and Remote Agent training build
the same `training_lineage` schema v1.

The persisted lineage references the immutable Dataset Revision and Snapshot,
then records task identity, framework, selected base version/model/reason,
execution mode/worker/Agent node/generation, requested/assigned/actual device,
public GPU identity, requested/actual training parameters, verified model
artifacts and the final training outcome.

`platform_core/training_lineage.py` is public-safe by construction: persisted
fields are allow-listed primitives, model paths collapse to safe filenames, and
signed URLs/secrets/credentials are excluded. Dataset revision IDs are validated
as SHA256 identities.

Local archival and Remote Agent server-confirm both persist lineage on the
algorithm version. Algorithm SQL Store round-trip preserves the lineage, so
historical provenance survives job cleanup and restart.

Frontend Impact Review is complete. The stable algorithm-version renderer shows
“训练溯源” only when persisted lineage exists. The modal reads the version truth
directly and shows dataset revision, snapshot, task, base model/version,
execution/node/device, effective parameters and model artifact identity. Real
Chrome verifies the flow without refetching historical `/jobs`.

Acceptance at HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`:

- 当前代码 HEAD `c6c7289b3a13d20053e1a8aed44525a4901f5059`：21 个相关 workflow，21 success / 0 failure / 0 pending。
- Training Input Integrity、Remote Training Runtime、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、Remote RKNN Board Runtime Protocol 均 success。
- Algorithm SQL Store / Training Task Visibility / External Algorithm Platform / Publish 等共享回归 success。
- Real Chrome 已验证算法版本“训练溯源”来自持久化版本 truth，点击查看不会重新请求历史 job。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** build the formal post-training Evaluation truth on the existing
Durable TRAINING/version chain: frozen test-split evaluation, overall and
per-label metrics, FP/FN/weak-label evidence, and an explicit retraining/data
decision. Do not create a second training owner. Rockchip physical-board
acceptance remains independently OPEN.

## Current closure — Dataset Snapshot / Revision v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing Snapshot V3 path now owns a deterministic Dataset Revision v1.
No parallel snapshot system was introduced.

`dataset_revision_id` identifies the selected dataset truth independently of
the train/validation/test assignment. The same selected material, platform
annotation truth, Canonical Annotation Schema v1 provenance and label schema
produce the same revision across different split seeds, while `snapshot_id`
still changes with split/role truth.

Dataset Revision v1 freezes material/source identity, content SHA256,
storage-source/object identity, platform annotation state/scope/hash,
source labels/box count, canonical external annotation provenance and the
locked label schema. Revision persistence is immutable and fails closed if a
previous revision ID maps to different content.

Snapshot V3 now carries dataset revision schema v1 and canonical annotation
schema v1 alongside its existing split, duplicate-exclusion and negative-scope
truth. Legacy V1/V2 portable snapshots are deterministically upgraded with a
revision identity without changing their historical snapshot IDs.

Remote TRAINING contract v2 requires a valid revision SHA256. The Agent verifies
the downloaded bundle's snapshot ID and dataset revision before execution.
Server-confirmed results, model artifacts, algorithm-version metadata, durable
jobs and frontend runtime preserve the same revision identity.

Frontend Impact Review is complete. The training runtime center displays
backend-backed “数据版本” and “训练快照” truth; focused refresh/cache paths retain
both fields. Real Chrome verifies the visible lineage fields.

Acceptance at HEAD `5e330fd3de9a958c2eac1ad1f18c11cf81b381b6`:
- Training Task Visibility push `35415738121`：visibility-contracts + Real Chrome success。
- 父代码 HEAD `5e2a0959a3a822f5725f684bd9351350b150a6b1`：Remote Training、Training Input Integrity、Node Agent Executor、Central Node Assignment、Task Runtime Truth、Portable Deployment、Remote Material Import、Remote Cleaning、Remote Conversion、RKNN Board Runtime 等共享回归 success。
- Dataset Revision / Snapshot focused unit、API、frontend identity/cache tests success。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** use the revision/snapshot identities as the base for formal
Training Lineage / Algorithm Version Provenance, then build the automatic
evaluation/retraining loop on that immutable lineage. Rockchip physical-board
acceptance remains independently OPEN.

## Current closure — Canonical Annotation Schema v1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

YOLO, COCO and Pascal VOC external annotation evidence now shares one explicit,
versioned contract in `platform_core/annotation_schema.py`. Source-format
parsers remain unchanged and retain their existing ownership; the canonical
layer only owns deterministic evidence normalization and validation.

Schema v1 preserves the previous flat evidence shape and source-digest semantics,
so existing synchronized annotations do not become false CHANGED deltas merely
because the abstraction was formalized. The contract freezes source format,
object key, split, annotation status, source-object identities, class-catalog
digest and normalized boxes.

`ImportCandidateStore.annotation_source_evidence()` now delegates to the
canonical builder. Rescan delta construction validates freshly produced evidence,
and formal apply validates it again before any AnnotationRepository write.
Tampered digests, unsupported versions/formats, object-key mismatches and
request-format mismatches fail closed.

This does not create a second annotation owner. Canonical evidence remains
external-source provenance; AnnotationRepository remains platform truth.

Frontend Impact Review: no UI change was required because public task/API fields
and status semantics are unchanged. Real Chrome and shared runtime regressions
remain green.

Acceptance at code HEAD `e262819dd7c4eb7a245e43eefc91bc452a4060fc`:
- Remote Material Import push：Ubuntu / Windows / API / Real Chrome success。
- Canonical schema builder/validator 在 Ubuntu + Windows contract 中通过。
- source_digest legacy compatibility 对 YOLO / COCO / VOC 均通过。
- Consumer-side tamper / format mismatch fencing 通过。
- Node Agent Executor、Remote Cleaning、Remote Training、Remote Conversion、Central Assignment、Portable Deployment、RKNN Board Runtime 等共享回归全部 success。
- 当前代码 HEAD 共 16 个相关 workflow：16 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** extend the existing Snapshot V3 path into Dataset Snapshot /
Revision by freezing canonical annotation source/schema truth alongside content
SHA, annotation hash, split and label schema. Do not create a parallel snapshot
system.

## Current closure — Remote storage_rescan Phase 2C Pascal VOC Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles
Pascal VOC XML annotation changes through the same durable flow used by Phase 1
images, Phase 2A YOLO and Phase 2B COCO. No second VOC parser, TaskKind or
AnnotationRepository owner was introduced.

Local and Agent product truth is now `import_format=images|yolo|coco|voc`.
The Agent reuses `DetectionDatasetScanner`, the execution-fenced broker and
short-lived GET contracts. It freezes XML object identity (key, size, ETag and
SHA256), split, external class catalog, normalized boxes, quality issues and
per-image source digest without opening central SQLite/NFS or receiving
long-lived object-store credentials.

Image delta and annotation delta remain separate. VOC uses the shared
`ANNOTATION_NEW / CHANGED / REMOVED / UNCHANGED / CONFLICT / INVALID`
categories. XML deletion or XML/class/bbox/split changes are detected even when
image bytes are unchanged.

External source evidence remains distinct from platform AnnotationRepository
truth. Manual annotation edits after review are protected by stale-write
fencing. New images continue through the existing MATERIAL_IMPORT indexer and
rescan records provenance instead of creating a second annotation write path.
Ambiguous multiple VOC XML references for one image fail closed.

Frontend Impact Review is complete. Preflight, API schema and storage rescan UI
expose the same four formats. Pascal VOC uses backend task truth for image and
annotation counts, quality, external-class mapping, removal/conflict policy and
confirmation. Real Chrome covers the Agent VOC request/review/confirmation chain.

Acceptance at code HEAD `5a1c18c8fc18c783a95d55f4f6a3ad826ffef69a`:
- Remote Material Import push `35412658236`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35412660855`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor push `35412658140` / PR `35412660966`：success。
- Central Node Assignment push `35412658117` / PR `35412660834`：success。
- Task Runtime Truth `35412660757`：success。
- Remote Training Runtime push `35412658157` / PR `35412660756`：success。
- Remote Conversion Runtime push `35412658182` / PR `35412660808`：success。
- Remote Cleaning Runtime push `35412658119` / PR `35412660762`：success。
- Portable Deployment push `35412658228` / PR `35412660767`：success。
- Remote RKNN Board Runtime Protocol push `35412658162` / PR `35412660872`：success。
- Storage Cache Governance `35412660802`：success。
- 当前代码 HEAD 共 28 个相关 workflow：28 success / 0 failure / 0 pending。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** formalize the already-shared YOLO/COCO/VOC evidence as
Canonical Annotation Schema v1, then build Dataset Snapshot / Revision on top of
that versioned annotation truth. Rockchip physical-board acceptance remains
independently OPEN.

## Current closure — Remote storage_rescan Phase 2B COCO Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles COCO
annotation JSON changes in the same product/control-plane flow as Phase 1 image
objects and Phase 2A YOLO annotations. No second COCO parser, TaskKind or
AnnotationRepository owner was introduced.

Local and Agent rescan now share `import_format=images|yolo|coco`. COCO reuses
the existing `DetectionDatasetScanner` and task-owned `ImportCandidateStore`.
The Agent reads object storage only through the execution-fenced broker and
short-lived GET contracts; it never opens central SQLite/NFS and receives no
long-lived storage credentials.

COCO review freezes the real annotation JSON object identity (key, size, ETag,
SHA256), split, external category catalog, normalized boxes, annotation status,
quality issues and per-image source digest. Full source image inventory is kept,
including images not referenced by JSON, so annotation coverage is never
mistaken for image existence.

External source provenance remains separate from platform AnnotationRepository
truth. JSON changes/removals produce annotation deltas and require user
confirmation. A manual platform annotation edit after review is protected by
stale-write fencing. New images continue through the existing MATERIAL_IMPORT
indexer, then rescan records matching external provenance instead of creating a
parallel annotation write path.

COCO ambiguity now fails closed: conflicting category ID/name mappings, one
image across multiple splits, one image referenced by multiple COCO annotation
documents, or duplicate references to the same object key inside COCO metadata
are rejected instead of allowing first/last-write ambiguity.

Frontend Impact Review is complete. The storage rescan modal exposes COCO only
when backend preflight says it is supported, keeps data.yaml YOLO-only, and uses
the same backend task truth for image/annotation counts, mapping, quality,
removal/conflict policy and confirmation. Real Chrome validates the Agent COCO
request/review/confirmation path.

Acceptance at code HEAD `ac1470c9049f7151fb6ae78daf6d21802ea6a263`:
- Remote Material Import push `35411646993`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35411650317`：success。
- Node Agent Executor `35411650294`：success。
- Central Node Assignment `35411650355`：success。
- Task Runtime Truth `35411650324`：success。
- Remote Training Runtime `35411650292`：success。
- Remote Conversion Runtime `35411650281`：success。
- Remote Cleaning Runtime `35411650314`：API / Ubuntu / Windows / Real Chrome success。
- Portable Deployment `35411650458`：success。
- Remote RKNN Board Runtime Protocol `35411650309`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35411650330`：success。
- Training Input Integrity `35411650297`：success。
- 16/16 related workflows on the code HEAD succeeded; no failures or pending jobs.
- `VERSION.txt = 42.24.0`.

**OPEN / next:** Phase 2C Pascal VOC XML annotation delta, then formal Canonical
Annotation Schema versioning over the already-shared YOLO/COCO/VOC evidence.
Rockchip physical-board acceptance remains independently OPEN.

## Current closure — Remote storage_rescan Phase 2A YOLO Annotation Delta CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` owner now reconciles
YOLO annotation changes in addition to Phase 1 image-object changes. Local and
Agent execution consume the same request truth: `execution_mode`,
`import_format=images|yolo` and optional `dataset_yaml`.

For YOLO, the portable review freezes source-object evidence for label sidecars
and `data.yaml` (object key, size, ETag and SHA256), split identity, external
class catalog, normalized boxes and issues. The task-owned store derives a
per-image source digest and compares it with the previously synchronized
external provenance plus current AnnotationRepository truth.

Delta categories are `ANNOTATION_NEW / CHANGED / REMOVED / UNCHANGED /
CONFLICT / INVALID`. External provenance is not the platform annotation
authority. User confirmation explicitly controls existing-image updates,
external removals and manual-edit conflicts, plus external-class label mapping
and quality acceptance.

New images continue through the already-closed MATERIAL_IMPORT indexing owner,
including their YOLO GT. After indexing, rescan records the matching external
source provenance and synchronized annotation hash rather than flagging that GT
as pending review.

Two fail-closed concurrency rules are permanent:
1. durable rescan intent is frozen before any new project label is created;
2. before overwriting/clearing an existing platform annotation, the current
   annotation hash/state must still match the review snapshot. A manual edit
   after review forces a new rescan instead of being overwritten.

Frontend Impact Review was completed in the same batch. The storage rescan modal
shows one backend-backed execution/format truth, separate image/annotation delta
counts, label mapping, quality acceptance, removal policy and conflict policy.
The YOLO mapping rendering runtime error was fixed, and Real Chrome validates the
Agent request/review/confirmation chain.

Acceptance at code HEAD `6505c51e1916a8aab5d506387b51d01e413b7775`:
- Remote Material Import push `35410155924`：API / Ubuntu / Windows / Real Chrome success。
- Remote Material Import PR `35410158432`：API / Ubuntu / Windows / Real Chrome success。
- 父层 UI/确认顺序回归：
  - `9e8ada…` push Remote Material Import `35409879583` 全绿。
  - `c6ee2ab…` push/PR Remote Material Import 全绿。
- `VERSION.txt = 42.24.0` 未修改。

**OPEN / next:** Phase 2B COCO annotation JSON delta, then Phase 2C Pascal VOC
XML delta. After those, version the already-shared YOLO/COCO/VOC evidence as the
Canonical Annotation Schema instead of creating new parser owners.

Rockchip real-board acceptance remains independently OPEN.

## Current closure — Remote storage_rescan Phase 1 image objects CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The existing `MATERIAL_IMPORT + mode=storage_rescan` durable owner now supports a
real portable Agent execution path for **image-object reconciliation**. No new
TaskKind, database owner, or parallel storage importer was introduced.

The control plane freezes the current MaterialRepository source baseline into a
task-owned artifact before remote execution. An Agent can scan the complete
OSS/S3/MinIO source only under explicit `intent=storage_rescan`; ordinary
`storage_scan` still requires an explicit prefix. The Agent receives no
long-lived storage credentials and never opens central SQLite/NFS. It uses the
existing execution-fenced broker and short-lived GET contracts to inspect real
image bytes, dimensions, SHA256, size and ETag.

Server-confirmed review evidence is compared with the frozen baseline to produce
`NEW / MISSING / CHANGED / UNCHANGED` plus quality evidence. Rescan preserves
object identity: equal content hashes under different object keys are not
collapsed as duplicates. CHANGED classification includes SHA256, size and ETag.

The user must confirm the reconciliation policy. After confirmation, the same
task returns to the existing central `storage.rescan` worker for formal
MaterialRepository updates. The control plane revalidates Agent-reviewed objects
with provider stat identity (size/ETag/available SHA metadata) rather than
downloading and hashing all bodies again, so heavy image I/O remains remote.
Missing records are marked unavailable instead of deleted; changed records keep
their existing annotation truth but are marked for review.

Frontend Impact Review was completed in the same batch. The storage-source UI
shows Central Worker / Remote Agent, consumes real preflight node truth, displays
durable status/worker/wait reason and incremental counts, and restores the same
task after refresh. Real Chrome covers the remote rescan flow.

Acceptance at code HEAD `64dc87c6e295429f79adfc813093bff33ce61587`:
- Remote Material Import `35408027919`：API / Ubuntu / Windows / Real Chrome success。
- Node Agent Executor `35408027776`：API / Ubuntu / Windows success。
- Central Node Assignment `35408027804`：success。
- Task Runtime Truth `35408027769`：success。
- Portable Deployment `35408027802`：success。
- Remote Training Runtime `35408027815`：success。
- Remote Conversion Runtime `35408027785`：success。
- Remote Cleaning Runtime `35408027775`：API / Ubuntu / Windows / Real Chrome success。
- Remote RKNN Board Runtime Protocol `35408027782`：API / Ubuntu / Windows / Real Chrome success。
- Storage Cache Governance `35408027828`：success。

**OPEN / next code phase:** storage_rescan Phase 2 for YOLO `.txt/data.yaml`,
COCO annotation JSON and Pascal VOC XML deltas, followed by formal versioning of
the existing shared evidence as the Canonical Annotation Schema. These are
extensions of the closed import/review chain, not permission to create parallel
parsers or owners.

Rockchip physical-board acceptance remains independently OPEN. No CI result
proves that a user-owned RK3568/RK3576 board has passed hardware acceptance.


## Current closure — Remote MATERIAL_IMPORT Phase 6 COCO / Pascal VOC Agent server_zip CLOSED

Formal `VERSION.txt` remains `42.24.0`.

COCO and Pascal VOC now also run through the existing portable Agent
`server_zip` MATERIAL_IMPORT path. This does not create a second annotation
truth: the Agent safely downloads/extracts the task-owned ZIP, reuses
`DetectionDatasetScanner`, and emits the same candidate/class/normalized-box/
split/issue evidence used by the already-closed storage_scan path.

The ZIP variant embeds only the IMPORTABLE image payloads needed after user
confirmation. Server-confirm revalidates the review archive, payload
size/SHA256/dimensions, candidate coverage and detection evidence before any
formal material is indexed. Users still confirm external-class to platform-label
mappings; the local Storage Worker then publishes verified payloads and commits
the existing MaterialRepository / AnnotationRepository truth.

Long-lived object-store credentials and central SQLite/NFS never reach the
Agent. The source ZIP is staged as a task-owned verified object; review
publication remains generation-fenced and immutable. dataset_yaml stays
YOLO-only.

The server-ZIP UI now has an explicit Central Worker / Remote Agent execution
choice. Local execution retains the previous local-storage behavior and does
not expose COCO/VOC. Agent execution switches the target to an enabled
OSS/S3/MinIO source, requires an explicit format (no auto), and exposes
COCO/VOC. Real Chrome covers that exact switch and request body.

Acceptance at code HEAD `3f5c34ae587aee04971e8e5160073898f288cba4`:
- Remote Material Import `35357183468`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35357183397`: success.
- Central Node Assignment `35357183504`: success.
- Task Runtime Truth `35357183682`: success.
- Portable Deployment `35357183477`: success.
- Remote Training Runtime `35357183476`: success.
- Remote Conversion Runtime `35357183564`: success.
- Remote Cleaning Runtime `35357183532`: success.
- Remote RKNN Board Runtime Protocol `35357183788`: success.

## Current closure — Remote MATERIAL_IMPORT Phase 5 COCO / Pascal VOC CLOSED

Formal `VERSION.txt` remains `42.24.0`.

COCO and Pascal VOC are now real remote annotation formats for
`MATERIAL_IMPORT + storage_scan + execution_mode=agent`. This was the Phase 5
closure boundary; Agent server_zip for these formats is now separately CLOSED in
Phase 6 above.

A project-database-agnostic `DetectionDatasetScanner` reads only the brokered
StorageProvider and persists task-owned candidate/annotation evidence. COCO
preserves external category ids/names and split identity; VOC parses
object/bndbox XML with deterministic external class ids and rejects
DOCTYPE/ENTITY declarations. Image dimensions come from the real source object,
boxes are normalized for durable review, clipped/invalid boxes are represented
as quality evidence, and object/annotation/box counts are bounded.

Review archives remain metadata/annotation-only. Server-confirm revalidates the
review schema, prefix, candidate coverage, classes, normalized boxes and issue
evidence. Users then confirm external-class to platform-label mappings. The
local storage indexer re-stats source objects (size/ETag/SHA256) before writing
MaterialRepository and AnnotationRepository truth and converts normalized boxes
back to pixel coordinates. The Agent never creates labels or writes central
project databases directly.

The Phase 5 product UI exposed COCO and Pascal VOC for object-storage Agent scans.
Phase 6 now also exposes them for Agent server_zip; local directory and Central
Worker ZIP modes still disable those options. dataset_yaml remains YOLO-only.

Acceptance at code HEAD `9fb67096718e5ece1b72a2acf601662fe337e1d7`:
- Remote Material Import `35318574008`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35318574014`: success.
- Central Node Assignment `35318574002`: success.
- Task Runtime Truth `35318573876`: success.
- Storage Cache Governance `35318573935`: success.
- Portable Deployment `35318573871`: success.
- Remote Training Runtime `35318573869`: success.
- Remote Conversion Runtime `35318573929`: success.

## Current closure — Remote MATERIAL_BATCH/CLEAN Phase 1 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote cleaning now executes on scheduled Agent nodes without creating a
competing cleaning task owner. The sole durable truth remains
`TaskKind.MATERIAL_BATCH + operation=CLEAN`; local execution stays the default
and explicit `execution_mode=agent` is fenced with `agent.remote`.

The control plane preflights the exact requested material range and requires
durable object evidence, enabled OSS/S3-compatible storage (including MinIO),
and an online Agent with effective `cleaning` capability. The UI consumes this
truth and disables remote execution when it is not genuinely available.
Direct API requests fail closed too and do not leave an Agent task behind.

The Agent never opens central SQLite/NFS and never receives long-lived object
storage credentials. It pages the frozen exact selection through an
execution-lease-fenced broker, receives per-image short-lived GET contracts,
verifies source size/SHA256 and runs the real CleaningAnalysisRuntime locally.
Its output is task-owned metrics evidence only. The control plane re-runs
`metric_issues` with the existing `DurableHashIndex`, verifies the immutable
uploaded review, and commits results into the existing
`selection.sqlite3/clean_results` and MaterialRepository projection.

The legacy user-facing semantics are preserved: a successful scan remains
"awaiting confirmation" until the user chooses suggested removals/keeps and
confirms. The product UI now exposes a preflight-driven Central Worker / Remote
Cleaning Node picker and maps remote execution stages to Chinese runtime text.

Acceptance at code HEAD `b41f784a3765e09a2184453e03e895a1cda0271d`:
- Remote Cleaning Runtime `35324894972`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35324894991`: success.
- Central Node Assignment `35324894963`: success.
- Task Runtime Truth `35324895005`: success.
- Portable Deployment `35324894993`: success.
- Remote Material Import `35324894988`: success.
- Remote Training Runtime `35324895079`: success.
- Remote Conversion Runtime `35324894962`: success.

## Current closure — Remote MODEL_CONVERSION Phase 2 Rockchip RKNN CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Rockchip RKNN is now a real remote MODEL_CONVERSION target. ONNX keeps the
existing `conversion` capability while Rockchip uses the independent
`conversion.rknn` capability. The Agent reports that capability only after a
real RKNN-Toolkit2 import plus target-platform config probe; control-plane resource discovery also
requires the node to be online, Agent-connected, effective for
`conversion.rknn`, and to publish an available RKNN probe with supported chips.

The portable RKNN contract is deliberately bounded to RK3568 / RK3576, FP16,
batch=1 and static input shape. Unsupported chips, INT8 calibration, dynamic
shape or batch>1 fail before durable execution. The Agent downloads the verified
model object, executes the node-local conversion worker/RKNN-Toolkit2, requires
exactly one non-empty .rknn result, hashes it locally, uploads with generation
fencing, and waits for server confirmation.

The control plane re-downloads and verifies size/SHA256 and commits the artifact
to the existing deployment job artifact directory. RKNN remains
`converted_unverified`: `runtime_verified=false` and
`hardware_verified=false` until a real Rockchip board runs the model. The
product UI includes RK3576 and uses backend resource truth; it does not infer
RKNN availability from generic conversion capability.

Earlier references to RK3578 were corrected. The official RKNN-Toolkit2 support
list names RK3576 Series, not RK3578. Any device sold/labeled as “3578” must have
its real SoC identified before being mapped to an RKNN target.

Acceptance at code HEAD `5a02aa5ba03e94cc731bfd0e62437c57738efab1`:
- Remote Conversion Runtime `35330889750`: control-plane / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35330889657`: success.
- Central Node Assignment `35330889375`: success.
- Task Runtime Truth `35330889784`: success.
- Portable Deployment `35330889497`: success.
- Remote Material Import `35330889535`: success.
- Remote Training Runtime `35330889384`: success.
- Remote Cleaning Runtime `35330889291`: success.

## Current closure — Rockchip RKNN board runtime verification protocol CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The Rockchip board verification software/product path is now complete. A
separate `deployment-test.rknn` capability is reported only by an Agent that
is Linux arm64/aarch64, identifies an RK3568/RK3566-family or RK3576 SoC from
`/proc/device-tree/compatible`, and can import the node-local RKNNLite runtime.
The heartbeat publishes the board chip/runtime truth and assignment requires an
exact chip match.

Board verification reuses the existing DEPLOYMENT_TEST durable task. The
control plane verifies the source .rknn artifact against its conversion
manifest, stages verified model/input objects, and the Agent executes the
node-local `predict_rknn_lite_runner.py`. That runner performs real
`RKNNLite.load_rknn`, `init_runtime`, and `inference`; it returns inference
latency, output count and output shapes, but deliberately does not claim model
accuracy or decode model-specific YOLO outputs.

Result publication remains generation-fenced and server-confirmed. Before
publishing hardware truth, the control plane revalidates the original
conversion job/chip/model SHA256. Only matching successful RKNNLite evidence
may set `runtime_verified=true`, `hardware_verified=true` and
`validation_status=hardware_verified` on the existing deployment job and
manifest.

The deployment UI now exposes “板端验证” for Rockchip
`converted_unverified` jobs, accepts a real test image, polls the durable task,
and refreshes the original job to “实机已验证” with chip/inference/output
evidence. Real Chrome covers this product flow.

Acceptance at code HEAD `05c7b93339414ac028214fd3d046dfdf7977c0a1`:
- Remote RKNN Board Runtime Protocol `35335720990`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime `35335720906`: success.
- Node Agent Executor `35335720915`: success.
- Central Node Assignment `35335720909`: success.
- Task Runtime Truth `35335720969`: success.
- Portable Deployment `35335720910`: success.
- Remote Material Import `35335720921`: success.
- Remote Training Runtime `35335720913`: success.
- Remote Cleaning Runtime `35335721027`: success.

This is a software/protocol closure, not evidence that a physical user-owned
RK3568/RK3576 board has already passed acceptance. A specific model becomes
`hardware_verified` only after a real connected board Agent executes the
runtime task successfully.

## Current closure — Rockchip RKNN INT8 calibration portable transport CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote Rockchip conversion now supports real FP16 and INT8 execution on an
Agent. INT8 is exposed only when backend resource truth reports it in
`supported_precisions`; the UI does not infer quantization support itself.

Before creating the durable conversion task, the control plane freezes an
RKNN calibration snapshot bound to the requested dataset/split and current
MaterialRepository revision. Every calibration item contains an exact portable
object reference plus size/SHA256 evidence. Non-portable/local materials,
missing evidence or changed source objects fail before the Agent task is
persisted.

The start payload contains only the frozen snapshot and short-lived object GET
contracts. The Agent downloads every calibration image into its generation
workdir, verifies size/SHA256, checks snapshot/count/file-count consistency and
only then starts the node-local deployment worker. That worker creates the
RKNN dataset file from the downloaded images and performs the real
RKNN-Toolkit2 INT8 build.

INT8 publication uses the same immutable generation-scoped upload,
server-confirm and deployment artifact commit as FP16. A successful RKNN INT8
conversion remains `converted_unverified` with `hardware_verified=false`;
the already-closed Rockchip board runtime flow is still the only path that may
promote the model to `hardware_verified=true`.

The deployment UI now exposes dataset, split and calibration count for RKNN
INT8 and Real Chrome verifies a real Agent INT8 task submission.

Acceptance at code HEAD `314757c1601420640acedc074e9aeb795e8a2097`:
- Remote Conversion Runtime `35340943761`: control-plane / Ubuntu / Windows / Real Chrome success.
- Remote RKNN Board Runtime Protocol `35340943851`: success.
- Node Agent Executor `35340943850`: success.
- Central Node Assignment `35340943861`: success.
- Task Runtime Truth `35340943758`: success.
- Portable Deployment `35340943913`: success.
- Remote Material Import `35340943781`: success.
- Remote Training Runtime `35340943764`: success.
- Remote Cleaning Runtime `35340943815`: success.

## Current closure — Rockchip real-device onboarding tooling CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Rockchip board onboarding is now productized without weakening the existing
runtime truth. `node_agent.py --doctor` is a strict capability preflight:
requested capabilities that cannot actually be reported make the command exit
non-zero and include actionable issues. Existing `--check` behavior remains
compatible.

`tools/install_rockchip_agent.sh` installs the board Agent as a Linux systemd
service. It runs doctor before installation and through `ExecStartPre` on
service starts. The one-time Agent token is never embedded in the install
command or systemd `ExecStart`; it is read from a silent prompt/environment
and stored in a root-owned 0600 EnvironmentFile.

The Service Node UI now understands `conversion.rknn` and
`deployment-test.rknn`, offers a Rockchip-board preset, surfaces observed
SoC/RKNNLite/RKNN-Toolkit2 runtime truth, and shows board-specific doctor and
systemd onboarding commands in the one-time-token dialog. The generated
systemd command itself contains no token.

Acceptance at code HEAD `b8caf7753994988d5161321c2536ae75e64d3252`:
- Service Node UI `35342366446`: Ubuntu / Windows contracts + Real Chrome success.
- Remote RKNN Board Runtime Protocol `35342366573`: API / Ubuntu / Windows / Real Chrome success.
- Remote Conversion Runtime `35342369723`: success.
- Node Agent Executor `35342369838`: success.
- Central Node Assignment `35342369780`: success.
- Remote Training Runtime `35342369831`: success.
- Remote Material Import `35342369794`: success.
- Task Runtime Truth `35342369798`: success.
- Portable Deployment `35342369765`: success.

This closes the **software onboarding tooling only**. It does not prove that any
specific user-owned board has passed hardware acceptance.

Capability probing was hardened again at code HEAD `b20470c8f57ee99fcde3ff0da5f26a5be4b7124f`: `supported_chips` now comes from actual `RKNN.config(target_platform=...)` calls for RK3568/RK3576 rather than a Toolkit-version threshold. Remote Conversion `35344315905`, RKNN Board `35344315931`, Node Agent Executor `35344315955`, Central Assignment `35344316219`, Task Runtime Truth `35344315903`, and Portable Deployment `35344315907` all passed.

**OPEN / next:** Rockchip physical-board acceptance. A real RK3568/RK3576 (or a
device whose actual SoC is first identified) must run the Agent, become online
with effective `deployment-test.rknn`, and execute a real converted `.rknn`
through RKNNLite. Only that real task may promote that specific conversion to
`hardware_verified=true`. CI/mock/x86 execution is not hardware acceptance.




## Current closure — Remote MATERIAL_IMPORT Phase 4 storage_scan CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`MATERIAL_IMPORT + mode=storage_scan + execution_mode=agent` is now a real
cross-machine flow. The product UI exposes an object-storage-directory mode for
enabled OSS/S3/MinIO sources and submits the same durable mode/source/prefix/
recursive/import-format truth consumed by the control plane and Agent.

Long-lived object-store credentials remain control-plane-only. The Agent uses
execution-lease-fenced broker list/read APIs and short-lived GET contracts.
Both the broker and Agent enforce the durable prefix; object reads revalidate
size and ETag and verify SHA256 when available. The Agent continues to use
`YoloImportScanner` for YOLO datasets without central SQLite/NFS access.

Unlike ZIP import, storage-scan review bundles are metadata/annotation evidence
only: source images are not repacked into the review ZIP. After server-confirm
and user confirmation, the local indexer re-stats the original object and
checks size/ETag/SHA256 before committing MaterialRepository and
AnnotationRepository truth. Phase 3 staging GC therefore never treats the
formal source objects as temporary staging.

Frontend/backend task truth is aligned: execution_mode survives refresh, the
unified poll owner is retained, and canonical task status wins over stale stage
text (for example AWAITING_CONFIRMATION cannot still render as reviewing).
The classic app script now has a permanent `node --check` gate after this batch
found and fixed dangling async-function syntax that unit tests had not parsed.

Acceptance at code HEAD `639cded30a6a2fed67275f19450cb70b4e0a9128`:
- Remote Material Import `35316129031`: API / Ubuntu / Windows / Real Chrome success.
- Node Agent Executor `35316128986`: success.
- Central Node Assignment `35316128928`: success.
- Task Runtime Truth `35316128916`: success.
- Portable Deployment `35316129051`: success.
- Remote Training Runtime `35316128920`: success.
- Remote Conversion Runtime `35316129033`: success.

Phase 5 COCO / Pascal VOC is CLOSED above. Do not reopen the generic detection
review path unless a regression is proven. The next control-plane task is
Remote MATERIAL_BATCH/CLEAN Phase 1.

## Current closure — Remote MATERIAL_IMPORT Phase 3 Staging GC CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Remote material input/review objects now have durable, exact-reference lifecycle
governance. Server-confirmed review commit first persists the control-plane
review archive and candidate/annotation truth, then records a cleanup ledger.
Deletion is deliberately deferred until the task/result state is durable, so a
crash between commit and result-state publication cannot destroy the only
retryable remote review object.

The existing local storage Worker heartbeat owns the periodic sweep. It retries
immediately-eligible cleanup for AWAITING_CONFIRMATION tasks and applies a
default seven-day retention to FAILED/CANCELLED/BLOCKED orphan staging. Exact
orphan generation refs are recovered from task-owned upload-state artifacts.
Every delete revalidates task-owned key prefix, source id, size and SHA256.
Changed objects are CONFLICT and are not deleted; transient failures remain
PENDING. Missing objects are idempotently complete.

No prefix list/delete exists in the GC path and formal target material object
keys are never candidates. The reporter reuses WorkerInstance renew hooks with a
five-minute throttle and persisted pagination cursor, so there is no new timer
or competing scheduler.

Acceptance:
- Remote Material Import `35312109805`: API / Ubuntu / Windows success.
- Task Runtime Truth `35312109707`: Ubuntu / Windows success.
- Storage Cache Governance `35312109834`: success.

Phase 4 `storage_scan` is now CLOSED above; do not reopen or reimplement this
broker/list/read path unless a regression is proven. Remaining material-format
work continues with COCO / Pascal VOC.

## Current closure — Remote MATERIAL_IMPORT Phase 2 CLOSED

Formal `VERSION.txt` remains `42.24.0`.

The real Agent MATERIAL_IMPORT path now covers both plain-image server ZIP
review and YOLO dataset review. In YOLO mode the Agent reuses the hardened
`YoloImportScanner` against its task-local extracted tree. It parses the
dataset YAML, image/label pairing, external classes, normalized boxes,
confirmed-empty samples and bounded issue evidence without accessing central
SQLite/NFS.

The immutable review ZIP carries candidate metadata/content plus
`yolo/annotations.jsonl`. The control plane re-downloads and verifies that
bundle before accepting it as durable task truth: task/project/generation,
target source/prefix, dataset YAML identity, external classes, candidate
coverage, annotation status, box counts, class IDs and normalized coordinates
are all checked fail-closed.

User confirmation freezes object selection, label mapping, optional label
creation and quality acceptance. The local `storage.import` indexer then
publishes only selected verified image bytes, rechecks object-store size/hash,
maps external class IDs to still-active platform label codes, converts YOLO
coordinates to pixels and writes MaterialRepository plus AnnotationRepository.
Confirmed-empty samples are persisted as formal negative annotation truth;
missing/invalid sidecars cannot erase an existing annotation.

A permanent end-to-end integration now exercises:
Agent-style YOLO review → server commit → explicit label mapping → local object
publication → MaterialRepository → AnnotationRepository, including a positive
sample with two mapped boxes and a confirmed-empty sample. The API contract was
updated to treat Agent YOLO import as supported rather than the old
unimplemented-mode expectation.

Final acceptance:
- Remote Material Import run `35311171823`: API / Ubuntu / Windows success.
- Temporary draft PR #17 was closed without merge.

**OPEN / next:** remote staging-object lifecycle/GC, then Agent storage_scan,
then COCO/VOC format expansion. GC must delete only task/generation-owned
temporary input/review objects that are outside their retention/retry window;
it must never prefix-delete or remove formal target material objects.

## Current closure — Remote MODEL_CONVERSION / ONNX Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`MODEL_CONVERSION` is now the third real cross-machine Agent task kind. The
closed remote target is ONNX only. Vendor conversions such as TensorRT, RKNN,
Sophon and Ascend remain environment-specific and must not be inferred as
remote-capable from this closure.

The deployment resource model now accepts explicit `mode=agent`. Agent resource
health is derived from the Service Node Registry: the resource is ready only
when at least one fresh enabled Agent has effective `conversion` capability.
Creation rechecks that state and portable staging failures fail closed rather
than silently falling back to a local conversion.

The durable conversion request keeps verified object references, source trace,
portable ONNX params and an Agent execution-mode marker. A dedicated Worker
capability fence prevents the legacy path-bound ConversionHandler from claiming
an Agent conversion while Central Scheduler assignment owns it.

`AgentConversionRunner` is database-free. It verifies model downloads against
size/SHA256 evidence, resolves Python and `deployment_worker.py` locally on the
node, persists ProcessIdentity before running a real subprocess, renews the
execution lease, forwards bounded logs/progress, and kills the exact process
tree when cancellation/fencing/shutdown wins. Runtime startup recovery is
fail-closed; unresolved stale conversion processes make the runner unready and
heartbeat withdraws the conversion capability.

Success requires the local worker to report `status=done`,
`runtime_verified=true`, `validation_status=runtime_verified`, a verified
ONNX manifest, and exactly one non-empty ONNX artifact. The Agent recomputes
output hash/size, uses generation-scoped immutable prepare/PUT/confirm transport,
and enters finalization only after server confirmation.

A further usability gap is closed on the server: after the finalization fence,
the control plane downloads the verified object again, checks size/SHA256, and
commits `deploy/jobs/<task>/artifacts/model.onnx`, `manifest.json`, and
`job.json`. Existing deployment artifact listing/download packaging therefore
continues to use the same local deploy-job truth instead of exposing a second UI
result model.

A real executor race discovered by the conversion tests was also fixed: a
globally supported task kind is no longer enough to call `start_execution`.
The loop now checks that this concrete Agent still has the corresponding
effective capability and a ready runner before acquiring the execution lease.
A stale assignment to an Agent whose runtime became unsafe therefore remains an
assignment/retry problem, not a false RUNNING execution.

Final acceptance:
- Remote Conversion Runtime `35306100598`: control-plane / Ubuntu / Windows success.
- Node Agent Executor `35306100599`: API / Ubuntu / Windows success.
- Central Node Assignment `35306100621`: API / Ubuntu / Windows success.
- Portable Deployment `35306100612`: production API / Ubuntu / Windows success.
- Remote Training Runtime `35306100615`: production API / Ubuntu / Windows success.
- Temporary draft PR #15 was closed without merge.

**OPEN / next:** Remote MATERIAL_IMPORT Runtime. Move large archive/image import
work to a real material-import Agent without granting access to central
MaterialRepository/SQLite/NFS. The Agent should safely unpack/parse, identify
label formats, perform deterministic conversion/basic validation, upload
immutable source/material objects to configured object storage, and let the
control plane commit only server-confirmed metadata/object refs.

## Current closure — Remote TRAINING Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`TRAINING` is now the second real cross-machine Agent task kind after
`DEPLOYMENT_TEST`. The control plane does not use the old remote-train ZIP
server as execution truth and the Agent never opens central SQLite or requires
shared NFS.

A remote request creates the durable TRAINING task plus an isolated
`TRAINING_PREPARE` task. Preparation freezes the split/snapshot, builds or
restores the verified v3 portable dataset bundle, safely archives it, records
SHA256/size/member-count/snapshot evidence, uploads it to configured
OSS/S3/MinIO and revalidates provider metadata. Explicit remote training cannot
fall back to a local node while this contract is still PREPARING.

Base-model semantics remain strict: a first run may use an allow-listed official
Ultralytics reference; an iterative run must resolve the current/latest
trainable previous version and publish/reuse its verified ModelArtifact object.
Control-plane absolute model paths are not executable Agent inputs.

`AgentTrainingRunner` downloads and verifies the portable bundle/base model,
uses node-local Python plus node-local `train_worker.py`, starts a real
subprocess, renews the execution lease, forwards bounded logs/progress, and
terminates the exact process tree when cancel/fencing/shutdown wins. Process
identity is persisted without execution secrets. Natural worker exit is not
enough to publish success: descendant/process-group cleanup must also be
provable. Cleanup uncertainty fails closed and makes the runner unready.

Agent capability reporting is runtime-safe:
`SUPPORTED_AGENT_EXECUTOR_CAPABILITIES` includes
`deployment-test` and `training`, but `effective_capabilities()` removes
training whenever its runner reports unsafe recovery state. Heartbeat advertises
that effective set, so a node with unresolved stale training processes cannot
claim another training task.

Successful training recomputes local best/last SHA256 and size, requests
generation-scoped immutable upload contracts, uploads and confirms each model,
then publishes a manifest-only training result bundle. The server verifies
result/model evidence before the finalization gate and only then commits the
verified model assets/algorithm-version truth. Old generations cannot publish
current terminal state.

A real production bug discovered by the subprocess tests was fixed:
portable scalar parameters that are absent or explicitly null now use their
defaults rather than propagating `None` into `int()`/numeric conversion.

Final acceptance on the verified implementation:
- Remote Training Runtime `35303815439`: Ubuntu / Windows / API success.
- Node Agent Executor `35303815460`: Ubuntu / Windows / API success.
- Central Node Assignment `35303815499`: Ubuntu / Windows / API success.
- Portable Deployment `35303815438`: Ubuntu / Windows / production API success.
- Temporary draft PR #14 was closed without merge.

**OPEN / next:** Remote MODEL_CONVERSION Runtime. Existing conversion payloads
still carry control-plane path-bound fields such as job_dir/worker_path/python_path.
Refactor conversion to verified model object inputs, node-local tool/SDK/runtime
resolution, execution-lease/process-tree fencing, immutable output upload and
server-confirmed finalization. Do not expose conversion as a remote Agent
capability until its real runner and permanent Windows/Linux gates exist.

## Current closure — Agent-side Real Deployment Runtime CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`node_agent.py` now runs the first real cross-machine task kind:
`DEPLOYMENT_TEST`. The Agent only reports capabilities implemented by its
current executor build; at this closure that is `deployment-test` only.
The single-concurrency executor starts only after the first successful control
plane heartbeat, claims central assignments, obtains the one real execution
lease/generation, and dispatches `AgentDeploymentRunner`.

The deployment runner is database-free and NFS-independent. It verifies object
downloads against durable size/SHA256 evidence, accepts only allow-listed
official model references or verified model objects, resolves Python and runner
paths from the node itself, launches a real subprocess, renews the central
execution lease, forwards bounded logs, and terminates the exact local process
tree when cancellation, lease fencing, or Agent shutdown wins.

Successful output follows the closed hash-bound publication protocol:
local hash/size → prepare → generation-scoped signed PUT → confirm →
begin-finalization → finish. Stale generations never publish a terminal state.
The task-local execution workdir is cleaned after success, failure, cancellation
or fencing.

A permanent-CI gap was also closed: `node_agent.py`,
`node_agent_executor_loop.py`, the single-concurrency tests and entrypoint
integration tests are now included in both relevant workflows.

Latest acceptance:
- Node Agent Executor run `35297453169`: API / Ubuntu / Windows success.
- Portable Deployment run `35297453136`: production API / Ubuntu / Windows success.

**OPEN / next:** Remote TRAINING Runtime. TRAINING is still not executable by
the remote Agent and is deliberately filtered out of reported capabilities.
The next implementation must transport a verified portable dataset/bundle,
run the node-local training runtime, preserve lease/cancel/process/GPU fencing,
return logs/metrics to central task truth, publish verified model artifacts,
and only then pass finalization. Do not use shared SQLite/NFS as a shortcut.

## Current closure — Portable Deployment + Fenced Result Publication CLOSED

Formal `VERSION.txt` remains `42.24.0`.

Deployment test is now the first task kind with a real version-1
`object-storage-v1` portable contract. Durable task truth keeps only object
references and content evidence. Temporary signed transport URLs are minted
just in time and never stored in Scheduler truth.

Remote output publication is execution-fenced. The Agent must compute local
SHA256 and size before requesting `result-upload/prepare`. S3/MinIO and OSS
PUT signatures bind size, SHA256 metadata, content type and no-overwrite
semantics. Actual output keys are scoped by execution generation. The control
plane then verifies the uploaded object through provider `stat()`, requires
matching size and SHA256 metadata, and uses the existing finalization
transaction as the atomic cancellation-vs-commit gate.

Confirmed durable truth lives under
`remote-results/<generation>/upload.json` and
`remote-results/<generation>/result.json`; signed URLs are not persisted.
Portable remote deployment cannot finalize or finish successfully before
confirmation. A successful finish ignores any Agent-provided result_ref and
uses the current generation's confirmed server result.

Validation:
- Portable transport closure run `35292400487`.
- Result publication Agent run `35295427105`.
- Result publication Portable run `35295427110`.
- Central regression run `35295427100`.
All directly relevant API / Ubuntu / Windows jobs passed. Temporary CI PRs
were closed without merge.

**OPEN / next:** implement the real database-free Agent-side deployment runner,
then integrate it into `node_agent.py`. The runner must verify downloads,
use node-local runtime/runner paths, kill the exact local process tree on
cancel/fence, compute output evidence, execute prepare/PUT/confirm, finalize,
finish, and clean the task-local workdir. Real cross-machine deployment test
is not CLOSED until that path is exercised.

## Current closure — Remote Portability Gate + Production Runtime Mount CLOSED

Formal `VERSION.txt` remains `42.24.0`.

`CentralTaskAllocator` now fails closed for `connection_mode=agent`: an Agent
node is ineligible unless the task payload contains an explicit version-1
`remote_execution` contract whose task kind and supported transport match.
Legacy path-bound payloads remain eligible for `local` nodes but are never
implicitly treated as portable. Scheduler truth stores only the allow-listed
version/task_kind/transport metadata; arbitrary credentials, signed URLs and
control-plane paths from the task payload are not copied into assignment truth.

This gate passed Central Node Assignment run `35290891091` and Node Agent
Executor run `35290891208` on API, Ubuntu and Windows.

A separate production integration gap was also closed: `app.py` now mounts
`training_recovery_router(get_project, shared_task_repository,
shared_task_artifacts)` exactly once. That composed router is the single owner
of training recovery, material picker, service nodes, central scheduler and
node executor. `tests/api/test_runtime_router_app_mount.py` uses AST/source
contracts to prevent a missing mount, duplicate mount, or scattered direct
subrouter ownership.

Production mount validation passed Central run `35291195275` and Agent run
`35291195262` on API, Ubuntu and Windows. Temporary validation PRs were
closed without merge.

**OPEN / next:** make one task kind actually portable end-to-end. Deployment
test is the preferred first target because the existing model artifact layer
already uploads verified model artifacts to configured OSS/S3/MinIO. The next
work must provide remote-safe input/output transport and a real Agent-side
runner; no shared SQLite/NFS or control-plane absolute path translation.

## Current closure — HTTP Agent Executor Control Protocol CLOSED

Development branch remains `feature/external-algorithm-publishing`; formal
`VERSION.txt` remains `42.24.0`.

`platform_core/agent_execution.py` now provides the control-plane execution
protocol for centrally assigned remote tasks. Node identity/authentication,
assignment ownership, and execution ownership are deliberately separate:
Node Token authenticates the registered node; Assignment Lease Token authorizes
one start; Execution Lease Token plus `tasks.attempt` generation fences all
heartbeat/log/finalization/finish mutations.

Execution start performs the one real `QUEUED -> RUNNING` transition under
`BEGIN IMMEDIATE`, revalidates the current Node Token hash, enabled/fresh
node state and capability, increments the existing task generation, and
releases the central assignment with `release_reason=execution_started`.
The protocol does not create a second task status model. Cancellation and
finalization continue to use the existing TaskRepository/FencedTaskRepository
truth.

The API exposes claim, start, heartbeat, log append, begin-finalization and
finish under `/api/v63/node-executor/{node_id}`. Remote logs are server-owned
and execution-fenced. A disabled node cannot accept new work but an already
owned execution can still report/finish, preventing a desired-state change
from needlessly wedging the task until lease expiry. Missing task payloads
cannot transition a task to RUNNING. Token rotation is rechecked inside the
start transaction, closing the pre-authentication rotation race.

Permanent workflow `.github/workflows/node-agent-executor.yml` passed API,
Ubuntu 24.04 and Windows latest in validation run `35288805083`. Tests cover
duplicate start, invalid assignment token, cross-node execution use, disable
semantics, cancellation precedence, finalization, log fencing/size bounds,
expired-generation takeover, Node Token rotation race, missing payload,
structured generation validation, VERSION guard and source guards.

**OPEN / next:** Agent-side Remote Execution Runtime + Object Storage
Transport. `node_agent.py` does not yet consume this executor protocol and
run a remote task handler, so real cross-machine training/material execution
is NOT CLOSED. The Agent client must not open control-plane SQLite or require
shared NFS; large task inputs/results must use object storage or an explicit
artifact transport. It must kill its local process tree when execution fencing
or cancellation wins.

Detailed handoff: `docs/NODE_CONTROL_PLANE_V42_25.md`.

## Current closure — Service Node Control Plane + Central Assignment CLOSED

Current development branch: `feature/external-algorithm-publishing`. Formal
`VERSION.txt` remains `42.24.0`. Older branch-state sections later in this
file are historical snapshots; live branch/HEAD must always be re-read before
editing.

Service-node control plane is implemented through
`platform_core/service_nodes.py`, `platform_core/node_agent_runtime.py`, and
`node_agent.py`. The management UI is implemented by
`static/modules/service-node-runtime.js`. Node identity, heartbeat,
allowed/reported/effective capabilities, CPU/RAM/disk/GPU/Torch/CUDA/process
telemetry and one-time Agent token handling are now real backend/frontend
contracts, not simulated UI state.

Central durable task-to-node assignment is implemented in
`platform_core/task_node_assignments.py` and composed through the existing
single additive runtime-router integration point. An active assignment is
durable control-plane truth and is protected by a partial unique index.
`AssignmentAwareFencedTaskRepository` prevents legacy Workers from
self-claiming a centrally assigned queued task. Allocation and claim paths use
`BEGIN IMMEDIATE`; schema scripts are initialized before the scheduling
transaction so SQLite implicit commit cannot break allocator atomicity.

Permanent Central Node Assignment workflow run `35288111906` passed API,
Ubuntu 24.04, and Windows latest contracts. It covers node eligibility,
training node/GPU selection, execution snapshot persistence, MATERIAL_BATCH
capability mapping, concurrent single-assignment fencing, claim/reclaim,
release generation, legacy Worker fencing, API contracts, VERSION guard and
`git diff --check`.

**OPEN / next:** HTTP Agent Executor Protocol. A remote Agent must not open the
control-plane SQLite or depend on NFS in order to claim work. The next protocol
must authenticate the node, claim its assignment, atomically acquire the one
real TaskRepository execution lease/generation on the control plane, exchange
execution inputs/artifact references over HTTP/object storage, and return
progress/log/result/cancel/failure updates to the same durable task truth.

Detailed handoff: `docs/NODE_CONTROL_PLANE_V42_25.md`.

## Current closure — Task Runtime Truth v2 CLOSED

Product implementation: `cc8981888bc4b27ee9594290455bd08e61713c9d`.
Permanent Task Runtime Truth gate expansion: `38aa8f736ee11ae419042fa2e90127bd45937ac5`.
Formal `VERSION.txt` remains `42.24.0`.

The shared durable-task frontend contract now covers training, AI annotation,
material batches, storage scan/import, server material import, resource discovery,
video processing, and deployment tests. For those durable payloads, `task_status`
wins over compatibility `status`, `phase` wins over `task_stage` / `stage`, and
`progress_percent` wins over legacy `progress`; the browser does not derive a
new durable percentage from domain counters.

A numeric `resource_queue_position` is displayed as “队列第 N 位” only when the
backend also returns `resource_queue_position_exact === true`. Candidate order,
priority order, or an inexact numeric position is never presented as an exact
Worker/hardware queue position. Domain-specific diagnostics such as scanned file
counts, extracted bytes, current paths, and wait reasons remain visible.

The permanent `Task Runtime Truth` workflow runs the expanded backend/frontend
contract on both Ubuntu and Windows. The closure run passed both OS jobs, and the
existing Frontend Runtime workflow passed frontend unit/owner guards plus Real
Chrome runtime regressions. The existing cleaning frontend queue/progress truth
closure remains authoritative and was not reopened by this batch.

Detailed handoff: `docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md`.


## Product closure — Training Bundle Snapshot Cache CLOSED

Training Bundle Snapshot Cache is implemented at product commit `b0868a7409ec019365e74355b46f21643d0da2a3`.
It reuses only a project-scoped portable bundle whose Snapshot ID is derived
from the durable material index and whose previous run reached final dataset
verification. The cache lives under
`<data_dir>/cache/training-bundles/<project_id>/<snapshot_id>`; entries are not
shared across projects.

The fast path is intentionally ahead of source materialization. When every
selected material already has a locked SHA256 and positive indexed size, the
Worker rebuilds the deterministic split manifest/Snapshot from durable material
and annotation truth first. If a matching cache entry exists, source files are
not reread merely to rediscover the same hashes. A miss keeps the previous
behavior: every selected source is materialized/verified, the manifest and
Snapshot are rebuilt from those verified bytes, and the task-local portable
bundle is constructed normally.

Cache entries are published only during successful training finalization, after
the existing `verify_portable_dataset()` full image/label SHA256 gate has passed
and after the official algorithm version has been attached successfully. An
incomplete/failed training run therefore cannot seed this cache. Cache
publication failure is recorded as optimization evidence and cannot turn an
otherwise verified model result into a failed training result. Cache-hit
admission re-hashes the small Snapshot, label and data-YAML files while large
images use their locked size/manifest evidence; finalization still performs the
full image SHA256 gate on every run.

Each training task still receives its own `work/bundle`; the trainer never runs
directly inside the shared cache. Cache schema v3 restores trainer-writable image
inputs with `shutil.copy2()` rather than writable hard-links, so Ultralytics or
other trainer-side mutations cannot modify the persistent cache inode. Legacy
schema-v2 cache entries are fenced because their prior hard-link isolation cannot
be assumed clean. The finalization gate still re-hashes the task bundle on every
run before accepting the model artifact.

Permanent contracts cover project isolation, cache marker/manifest identity,
missing-member rejection, verified-file-count fencing, hard-link reuse,
cross-device copy fallback, indexed hash/size eligibility, and the production
TrainingHandler wiring. Formal `VERSION.txt` remains `42.24.0`; no tag, release
or `main` merge is part of this closure. A800 / genuine 10k timing remains
unverified and no performance percentage is claimed.

## 1. Branch / release state

```text
branch:                                  refactor/frontend-runtime-stabilization
local scoped product HEAD:               de0c37dd93ecc3396935bf9ad6159568d77a03da
remote HEAD last verified:               ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
ahead / behind last verified:            2 / 0
push status:                             PENDING — GitHub 443 unavailable during Phase 1A handoff
latest remotely accepted state:          ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
latest local scoped product implementation: de0c37d (GPU Runtime Truth Phase 1A)
latest full-suite acceptance:            ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4
formal VERSION.txt:                      42.24.0
visible frontend version:                v42.24.0
internal UI build metadata:              42.25.0-dev
app.js cache:                            42.25.99
main.mjs cache:                          42.25.99
NavigationStability:                     422512
UI state runtime:                        422500
PollRegistry:                            422518
TrainingDraftRuntime:                    422516
TrainingLabelRuntime:                    422513
TrainingSubmitRuntime:                   training-submit-422504
TrainingTaskRuntime:                     training-task-runtime-422522
AutoLabelPollRuntime:                    422501
```

The latest remotely accepted branch state is `ca8d80cba3cbfa1282e4ff4d9b0a1c341cbd73a4`. GPU Runtime Truth Phase 1A is committed locally at `de0c37dd93ecc3396935bf9ad6159568d77a03da`; push and GitHub CI remain pending because GitHub port 443 was unreachable during handoff. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## Product status — GPU Runtime Truth Phase 1A

```text
GPU Runtime Truth Phase 1A
IMPLEMENTED + BASIC TESTS
REAL MULTI-NODE NVIDIA ACCEPTANCE PENDING
```

Implementation commit: `de0c37dd93ecc3396935bf9ad6159568d77a03da`.
This phase extends the existing Worker Runtime and GPU resource owner; it does
not add a second Worker registry, heartbeat, task queue, Scheduler, or GPU
assignment path.

Node identity resolves in this order: explicit `MC_NODE_ID`; otherwise a
hashed node-local Windows MachineGuid or Linux machine-id; when those are not
available, a generated identity persisted under `MC_NODE_STATE_DIR` or the
OS-local application state directory. Hostname is display metadata only.
Node identity is never written to shared `MC_TRAIN_DATA_DIR`. Containers that
need identity across replacement should set `MC_NODE_ID` or mount a node-local
`MC_NODE_STATE_DIR`.

`worker_instances` now has an additive `node_id` column. New Worker leases
write the resolved node through the existing `WorkerInstanceService.acquire()`
and existing heartbeat. `GET /api/v62/workers` returns `node_id` with the
existing sanitized runtime fields. Existing rows migrate to
`legacy-unscoped`; no existing lease secret becomes public.

The existing `gpu_inventory` and `gpu_samples` tables are migrated
transactionally from global `uuid/gpu_index` rows to node-scoped
`(node_id, gpu_uuid)` identity and `physical_index`. Inventory now records
`model`, `total_bytes`, `free_bytes`, `utilization`, `sampled_at`,
`telemetry_source`, `telemetry_available`, and `mig_mode`. Old rows remain
recoverable as `legacy-unscoped` until a real Worker observes that UUID and
adopts it for its Node. The former global
`UPDATE gpu_inventory SET healthy=0` refresh is retired: a Node only upserts
its own observations, and missing reports become stale through `sampled_at`.

`worker_gpu_visibility` records the many-to-many runtime relationship
`worker_id + node_id + gpu_uuid + logical_cuda_index + observed_at`.
`CUDA_VISIBLE_DEVICES` order is applied only to the Worker logical index;
physical index and GPU UUID remain separate. NVML is preferred, nvidia-smi is
the second telemetry source, and Torch fallback contributes identity only:
it never fabricates memory or utilization. Hardware health is not inferred;
the public `health_status` remains `unknown` while
`telemetry_available`, `metrics_fresh`, and `mig_mode` carry the proven facts.

`GET /api/v62/gpu-runtime` is a read-only projection returning `nodes`,
`workers`, `gpus`, `worker_gpu_visibility`, and telemetry counts. It neither
samples hardware nor writes task/Scheduler state. Reservations are deliberately
not exposed as node truth because `gpu_reservations` is not node-scoped yet.
The existing local `/api/v62/gpu-resources` compatibility endpoint remains.

Minimum verification passed on Windows: focused Worker/GPU schema, migration,
Node isolation, visibility reorder, stale telemetry, Torch identity-only,
no-GPU behavior, read-only API, Scheduler and recovery contracts `22/22`; the
affected Python modules compiled successfully. Real multi-Node NVIDIA, A800,
MIG, and container/NFS deployment remain **NOT VERIFIED**.

Phase 1B explicitly retains: node-scoping `gpu_reservations`, resolving the
global `worker_slot UNIQUE` conflict, binding assignments to
`node_id + gpu_uuid + physical_index + logical_cuda_index`, Worker/server
binding, remote routing, and GPU automatic scheduling. None of those claims
are closed by Phase 1A.

## Product closure — Training Queue Readiness Truth CLOSED

Training task queue readiness is closed at scoped product implementation
`bfe9f7d`, with remote acceptance recorded at
`92b8275e5a75167b040738d21a153f487f799b9b`. The earlier local-only/pending-push
state is resolved: local and remote are synchronized at `0 / 0`, and all four
directly related workflows passed. This batch consumes the already-closed Worker
Runtime Truth and the existing durable TaskRepository/Scheduler state; it does
not add another queue,
Worker registry, Scheduler, durable task status, or frontend polling owner.

For a local durable `TRAINING` task whose persisted status is `QUEUED`, the GET
projection now evaluates the current `worker_instances` lease snapshot. No
online Worker returns `WAITING_RESOURCE / 当前没有在线 Worker`; online Workers
without the `TRAINING` task kind return `当前没有可执行训练任务的 Worker`; online
Training Workers missing any required capability return
`当前在线 Training Worker 不支持 <capability>`. A provably compatible Worker with
an existing Scheduler/GPU admission wait preserves the authoritative
`resource_wait_reason`. Otherwise the public state remains `QUEUED`. The read
path never writes `tasks.status`, `stage`, or wait reasons.

The current compatible local pool is deliberately limited to durable Worker
truth that is already proven: online lease, registered `TRAINING` task kind,
and a capability superset of the task's `required_capabilities`. The requested
`resource_key` remains the resource boundary. `training:remote:<server_id>` is
not matched to an arbitrary local Training Worker because current Worker truth
does not store server binding or resource affinity and the current handler
rejects non-local targets. Remote tasks therefore expose
`指定远程服务器的 Worker 路由尚未建立` until a later Worker/server-binding batch.

`resource_queue_position` remains the existing resource-scoped numeric value;
it is not represented as a universally exact Scheduler rank. The backend now
returns `resource_queue_position_exact`. Exactness is conservative and is only
proved for a single compatible CPU Worker when its current claimable queue has
no cross-resource candidate and the Scheduler scan position equals the
resource-scoped position. GPU auto/concrete GPU, multiple compatible Workers,
cross-resource competition, and remote routing remain non-exact. The training
UI displays `队列第 N 位` only when this proof flag is true; otherwise it shows
the backend pool label plus `排队中` without a fabricated number.

Backend-owned display metadata is:

```text
resource_pool_key
resource_pool_label
resource_queue_position_exact

training:cpu      -> CPU
training:auto     -> GPU 自动
training:cuda:N   -> GPU N
training:remote:* -> 指定远程服务器
```

The training UI now renders public `waiting` as `等待资源`, prioritizes the
server-provided wait reason, and never parses `resource_key` to infer resource
availability. Worker recovery and queue changes continue to arrive through the
already-closed page-scoped two-second PollRegistry one-shot; no new timer or
request endpoint was added. The jobs-list path reuses one Worker runtime and
queued-candidate snapshot for the response rather than issuing those full
queries once per visible task.

Core files:

```text
app.py
platform_core/task_runtime/__init__.py
platform_core/task_runtime/public.py
platform_core/task_runtime/repository.py
static/modules/training-task-runtime.js
static/main.mjs
static/index.html
tests/unit/task_runtime/test_public_projection.py
tests/api/test_training_unified_task_overlay.py
tests/frontend/training-task-runtime.test.mjs
docs/superpowers/specs/2026-09-14-training-queue-resource-truth-design.md
docs/superpowers/plans/2026-09-14-training-queue-resource-truth.md
```

Minimum verification passed: focused backend queue/Worker/admission contracts
`13/13`; focused TrainingTaskRuntime rendering and existing list-refresh
contracts `12/12`; affected Python compilation and JavaScript syntax checks.
The first backend run was blocked before test setup by the known Windows global
Temp permission issue; the identical focused tests passed with a worktree-local
temporary directory, which was removed afterward.

This batch did **not** implement GPU Runtime Truth, GPU automatic scheduling,
GPU memory/affinity changes, Worker/server binding, remote affinity, designated
GPU/machine selection, Scheduler claim changes, Worker registration schema
changes, ETA, pause/resume changes, SSE, or a new polling owner. Linux/A800,
real multi-Worker concurrency, and remote-server routing remain **NOT
VERIFIED**. Formal `VERSION.txt` remains `42.24.0`.

## Product closure — Worker Runtime Truth CLOSED

Worker Runtime Truth is complete at implementation HEAD `a5acc6bf9b3de3bab0bd2231a40c9fe8436f1816`. The existing `worker_instances` lease row now durably records `worker_id`, `hostname`, `pid`, the running Worker's resolved `build_id`, actually registered roles, registered task kinds, registered capabilities, `started_at`, `heartbeat_at`, and `expires_at`. SQLite migration is additive and gives existing rows safe defaults; it does not rebuild or discard the table.

Durable truth remains single-owner: `task_worker.py` obtains handlers and capabilities from the existing `worker_registry`, then writes that actual registration into `worker_instances` through `WorkerInstanceService.acquire()`. The existing lease renewal remains the only heartbeat. `WorkerInstanceService.list_runtime()` derives `online` only when a valid heartbeat exists and `expires_at` is later than the query's UTC time; it never uses PID liveness to judge remote Worker availability. `GET /api/v62/workers` returns the sanitized durable runtime list and does not expose `owner_token` or `instance_key`.

Modified files:

```text
app.py
task_worker.py
platform_core/worker_registry.py
platform_core/task_runtime/repository.py
platform_core/task_runtime/worker_instances.py
tests/unit/task_runtime/test_worker_runtime_truth.py
tests/unit/task_runtime/test_worker_registry.py
tests/api/test_worker_runtime_truth.py
docs/superpowers/specs/2026-09-14-worker-runtime-truth-design.md
docs/superpowers/plans/2026-09-14-worker-runtime-truth.md
docs/CODEX_CURRENT_STATE.md
```

Minimum verification passed: affected Python modules compiled successfully; focused Worker Runtime Truth, actual registry metadata, read-only API, and existing Worker lease connection-lifecycle tests passed `7/7`. Linux/A800 deployment and real distributed Worker heartbeat behavior were not executed in this Windows development environment and remain **NOT VERIFIED**. Formal `VERSION.txt` remains `42.24.0`.

> Build claim fencing、Worker readiness admission、training 503 拦截和前端 Worker readiness 尚未实现，留待后续独立批次。

### CI follow-up — Material Annotation Atomicity

The `Material Annotation Atomicity` failure at `cbc9d5c9e4678160d2acf18124b8c06b1a104702` was an existing test-orchestration mismatch, not a Worker Runtime Truth regression. `f43631e16a51167cf75bb8e2ec545566f226609f` had already moved cleaning execution out of the Web process into the durable `MATERIAL_BATCH` Worker, while `test_upload_to_selected_storage_source_enters_unified_pool` still waited for `awaiting_confirmation` without running a materials Worker. The workflow's previous successful run predated that durable-cleaning migration; the Worker Runtime Truth `app.py` change merely caused this workflow to run again and expose the stale assumption.

The test now drives the existing real `FencedTaskRepository` / `Scheduler` materials registration before asserting the same terminal business truth. No production cleaning, storage, training, Worker Runtime Truth, workflow timeout, or application behavior changed. Focused verification passed the formerly failing storage-upload test and the existing real fenced material-worker regression (`2/2`). GitHub Actions Run `34825337016` passed on fix commit `6abb63a1cb1de2da209879974bfca6c70d0a0c45`.

## Product closure — Training task status/progress auto-refresh CLOSED

Training task list auto-refresh is complete at implementation HEAD `753416e`. The visible list continues to use the existing batch truth endpoint `GET /api/projects/{project_id}/jobs`; `enrich_job_runtime()` projects the persisted training job and metrics together with durable `TaskRepository` status, progress, queue, Worker, epoch, elapsed-time, and terminal truth. The frontend does not synthesize status, percentage, Epoch, or elapsed time.

`TrainingTaskRuntime` remains the focused request/state/table-patch path and updates only the task table plus tab counts. `PollRegistry` remains the only training timer owner: `training-jobs` is now a page-scoped 2-second one-shot for `queued`, `waiting`, `pending`, or `running`. Every completed request re-arms from the latest backend response; a transient request failure retries only while the last-known state is still dynamic. Paused tasks remain in the activity list but paused-only state has no pending timer. `done`, `finished`, `completed`, `failed`, `stopped`, `cancelled`, and `canceled` do not re-arm. Leaving `训练任务` clears the timer, `检测台` is no longer an owner, and re-entering restores polling from freshly loaded state. Resume keeps the existing immediate forced refresh, after which PollRegistry restores the one-shot only if the returned state is dynamic.

Core files:

```text
static/modules/poll-registry.js
static/main.mjs
tests/frontend/poll-registry.test.mjs
tests/frontend/training-task-runtime.test.mjs
docs/superpowers/specs/2026-09-14-training-task-auto-refresh-design.md
docs/superpowers/plans/2026-09-14-training-task-auto-refresh.md
docs/CODEX_CURRENT_STATE.md
```

Minimum verification passed: focused PollRegistry and TrainingTaskRuntime frontend contracts `22/22`; JavaScript syntax checks for PollRegistry, TrainingTaskRuntime, and `main.mjs`; existing durable training overlay API regression `2/2`. The first API attempt was blocked before test setup by the known Windows global Temp permission issue; the same test passed using a dedicated worktree-local pytest temp directory, which was removed afterward. Real Chrome and Linux/A800 execution were not run and remain **NOT VERIFIED**.

This batch did not implement GPU Runtime Truth or scheduling, Worker readiness admission, pause/resume feature changes, machine selection, ETA redesign, training-detail refactoring, deployment-center changes, creation-modal changes, SSE, or backend training changes. Formal `VERSION.txt` remains `42.24.0`.

### CI follow-up — Browser navigation training polling guard

The browser navigation guard is synchronized with the current training polling lifecycle. In `delayed request from previous page cannot jump back over the current page`, the initial training `/jobs` request is intentionally held before any dynamic task truth exists, so the correct PollRegistry state is no `training-jobs` timer. The test no longer expects the removed `检测台` owner or unconditional polling; it still verifies that completing the stale training request cannot navigate away from the current dataset page. This follow-up changed only `tests/browser/navigation-stability.spec.mjs`; no product business code or workflow changed.

Focused Playwright verification passed `1/1`. GitHub Actions Run `34830800955` completed successfully, including `browser-navigation` success, on guard commit `23e53363ec9a1a94143ecc25d052f56c66cc242a`.

## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Historical sequencing note: at this closure point, storage import polling ownership was recorded as the subsequent batch. That statement is retained only as history and is not a current work instruction.

## Product closure — Cleaning frontend queue/progress truth CLOSED

The final cleaning tab now subscribes to the durable v47 cleaning projection instead of flattening server truth into a generic local row. The backend already exposed `status_text`, `progress`, `processed_images`, `total_images`, `flagged_images`, `resource_queue_position`, `resource_wait_reason`, and worker identity; this batch makes the final visible clean-tab owner preserve those values through both initial rendering and managed refresh.

Closed semantics:

```text
status text: consume server status_text; WAITING_RESOURCE compatibility projection remains “等待资源” instead of being flattened to “排队中”
queue metadata: show real resource_queue_position + resource_wait_reason when present
progress: use server progress / processed_images / total_images only; no browser-simulated percentage
worker metadata: running rows may show the real worker_id supplied by the server
polling owner: PollRegistry owns clean-tasks-v47 as a page/tab-scoped 2200 ms one-shot
refresh owner: refreshCleanOps427Delta refreshes only the cleaning task list and patches clean rows
terminal truth: awaiting_confirmation is terminal for list polling; the clean timer is not re-armed
navigation/tab change: PollRegistry clears the clean timer; switching back to AI annotation also clears it immediately
legacy recursive setTimeout(renderOps427, 2200): retired
backend queue order / claim / progress generation / worker execution: unchanged
```

`static/modules/cleaning.js` now owns the pure `cleanTaskView()` / `isActiveCleanTask()` projection. `static/main.mjs` exposes those helpers through `PlatformCore.cleaning`. `static/modules/poll-registry.js` owns `clean-tasks-v47`, and the final v427 clean branch in `static/app.js` consumes that view-model. The v47 public compatibility contract permanently requires the queue metadata fields to exist; their values remain dynamic server truth (for example, an immediately queued task may legitimately report position `1`).

Permanent guards:

```text
tests/frontend/clean-task-view.test.mjs
  - waiting-resource status/queue/progress truth
  - running worker/progress truth
  - final app.js wiring consumes cleanTaskView + PollRegistry
  - retired direct recursive clean-list timer cannot return

tests/frontend/poll-registry.test.mjs
  - clean-tasks-v47 one-shot lifecycle
  - re-arm only while active
  - stop at awaiting_confirmation
  - clear on navigation

tests/api/test_clean_unified_execution_truth.py
  - v47 public queue metadata fields are permanent
  - dynamic queue position is accepted as server truth, never forced to a frontend assumption
```

Evidence:

```text
valid RED commit:           cf3f2c4fec639903435379b3419dbaadad82c949
valid RED run:              34793075909 (245 frontend tests: 242 PASS; exactly 3 intended cleaning truth assertions RED)
focused/full GREEN run:     34793282831 PASS (focused cleaning contracts + full frontend unit + wiring guard)
product commit:             9f6f329393018623807cb4fea04707f3b5350676
formal accepted clean HEAD: 736b2acdbf2560be657011035de173cde67517d0
Release Regression:         34793457861 PASS
Navigation Action Fencing:  34793457872 PASS (Real Chrome PASS)
Frontend Runtime:           34793457920 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

The temporary frontend migration helper/workflow were physically deleted before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Deployment-test durable queue/progress truth is CLOSED. The storage-import polling work that followed this historical closure is no longer a current instruction. Genuine 10,000-image processing acceptance remains explicitly deferred.

## Product closure — Cleaning durable execution truth CLOSED

The active v47 manual-clean and v55 upload-batch clean entry points now publish one durable `MATERIAL_BATCH/CLEAN` task into the shared `TaskRepository`. The Web/API process no longer owns cleaning execution through legacy daemon threads, and Web startup no longer resurrects those retired workers. Real execution is owned by the registered `materials` worker through `FencedTaskRepository` / `Scheduler` truth.

Closed semantics:

```text
manual v47 create -> prepare + publish one MATERIAL_BATCH/CLEAN durable task
v55 upload-batch decision -> the deterministic clean_task_id points to that same durable task truth
real execution -> materials Scheduler / fenced WorkerContext, never Web daemon execution
prepare -> publish crash window -> reuse the already-frozen semantic request without treating its freeze-time repository_revision as a new user intent
FAILED retry -> same task id is re-queued through TaskRepository retry; no duplicate task identity
successful scan awaiting confirmation -> durable task remains SUCCEEDED/succeeded; v47 compatibility alone projects awaiting_confirmation/review
corrupt image with corrupt_check -> successful flagged cleaning finding for review
source content changed after indexing -> remains SOURCE_CONTENT_CHANGED storage-integrity failure, not disguised as image corruption
```

A real-worker defect was also closed: `MaterialBatchHandler` had called a private artifact validation method that does not exist on the real `FencedArtifactStore`, causing Scheduler execution to fail before processing any material. The handler now validates `project_id` as a safe single path component while preserving fenced artifact access. Corrupt findings are excluded from the hash/dedup index unless real `sha256` and `dhash` metrics exist.

Permanent guards include `tests/api/test_clean_unified_execution_truth.py`, `tests/api/test_upload_clean_flow.py`, `tests/unit/test_material_batch_public_truth.py`, and the Release Regression path/test scope. The final guard explicitly proves that reading the v47 compatibility result may show `awaiting_confirmation / review` while the underlying durable record remains `SUCCEEDED / succeeded`.

Evidence:

```text
valid RED commit:           3f41cdae0d4234bf5171f2aa80111513c223407c
valid RED run:              34790397474 (intended durable-clean execution assertions RED)
focused durable migration:  34792422835 PASS (4 durable contracts + 32 upload-clean regressions)
product commit:             f43631e16a51167cf75bb8e2ec545566f226609f
formal accepted clean HEAD: 3931a9a2d529845f9e698b22f62fe950a7a8b42f
Release Regression:         34792673327 PASS
Navigation Action Fencing:  34792673293 PASS (Real Chrome PASS)
Frontend Runtime:           34792673296 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All one-shot cleaning migration/diagnostic helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Historical sequencing note: cleaning frontend queue/progress truth was subsequently closed, followed by the storage-import and deployment-test queue/progress audits. This is historical context, not current scope.

## Product closure — Plain image upload whole-task progress truth CLOSED

The final live ordinary-image upload owner is the storage61 `doUploadImages426` path posting to `/api/projects/{project_id}/images`. The endpoint is synchronous HTTP, but after browser request bytes are sent the server still performs temporary-file handling, image validation, selected-storage object write, SHA256 calculation and material record commit. Therefore browser `xhr.upload` byte completion is not whole-task completion.

Closed semantics:

```text
browser byte transfer: 0% -> 85%
byte transfer complete: hold at 85%, show “文件已上传，正在服务器入库”
server-side synchronous commit: no fabricated percentage animation
successful HTTP completion after material commit: 100%, show “服务器入库完成”
network/non-2xx failure: never claims terminal 100%
```

This batch deliberately does **not** invent a durable background task, fake queue, or fake server progress for a synchronous endpoint. Terminal 100% is fenced to the authoritative successful HTTP completion. Permanent behavior guard: `tests/frontend/image-upload-overall-progress.test.mjs`; Release Regression includes that test in its permanent path scope.

Evidence:

```text
valid RED commit:          03be0050644af80709bddb97321f1a4ec0b1528c
valid RED run:             34788264443 (237 existing tests PASS; 2 intended new assertions RED)
focused migration/GREEN:   34788320142 PASS
product commit:            259d76d753993f2dd10e1963ee1a9a13887209ad
accepted clean code point: bae90eae4b3768d365d20344c1f2db9a75795ac8
Release Regression:        34788383779 PASS
Navigation Action Fencing: 34788383742 PASS (Real Chrome PASS)
Frontend Runtime:          34788383772 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

The one-shot product migration workflow was removed in the product commit. No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product closure — Video resource queue truth CLOSED

The live v424 video task page already reads `/api/v33/projects/{project_id}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: 32284a8972faec46775144b8c47406e67edee014
valid RED run:              34789541200 (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     34789628840 PASS
product/self-cleanup:       c0fee2b7c8dfbf03481cbc6dfb1019f922293576
formal clean HEAD:          cb81ca39016aea0fc53ed52090f0b0199d39109a
Release Regression:         34789701814 PASS
Navigation Action Fencing:  34789703315 PASS (Real Chrome PASS)
Frontend Runtime:           34789704610 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.

## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          186005b428f361e88553555b3a86013d206f11b3
valid RED run:             34788748122 (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            ddb1168a8f3457fef3d875ceec79e618b75acee9
accepted clean code point: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7
Release Regression:        34788824842 PASS
Navigation Action Fencing: 34788824910 PASS (Real Chrome PASS)
Frontend Runtime:          34788824849 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## 2. Current priority

> **LIVE OVERRIDE:** 当前优先级以本文顶部 `LIVE CURRENT STATE — 2026-09-20` 为准。下面旧 priority block 仅保留历史演进背景，不得据此跳过当前 GPU 部署 + 畅联真实 E2E。

```text
TECH-DEBT CLEANUP PAUSED BY USER REQUEST
→ Worker Runtime Truth CLOSED
→ Training Task Status / Progress Auto-Refresh CLOSED
→ Training Queue Readiness Truth CLOSED
  product implementation: bfe9f7d
  remote acceptance: 92b8275e5a75167b040738d21a153f487f799b9b
→ GPU Runtime Truth Phase 1A IMPLEMENTED + BASIC TESTS; push/CI and real multi-Node NVIDIA acceptance pending
→ NEXT AFTER PHASE 1A REMOTE ACCEPTANCE: GPU Runtime Truth Phase 1B (only when explicitly resumed)
→ genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction
→ SSE/event stream evaluation DEFERRED
→ non-blocking Navigation Action Fencing final scan remains DEFERRED
→ Resource Lifecycle production soak / non-SQLite resource classes
→ backend regression / A800 RC only when explicitly resumed
```

A800 RC remains deferred unless the user explicitly resumes it.

### 当前产品主线 — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.

## 2026-09-20 — 标注统一 + 显式新建平台标签（IMPLEMENTED / CI PENDING）

产品规则已澄清：批量导入或 AI 候选复核时，如果平台没有合适标签，**允许用户在当前确认流程中显式创建新的正式平台标签**；但外部数据集类别名不得因为上传/确认而被系统隐式创建成 canonical label。

当前合同：

- YOLO / COCO / VOC 等外部类别先进入“外部类别 → 平台标签”人工确认；支持多对一，例如 `toukui1`、`toukui2` → `helmet`。
- ZIP、Storage Import、Storage Rescan、AI Candidate Review 都提供“＋ 新建平台标签”。
- 新建动作复用配置中心标签管理的 canonical API：`POST /api/projects/{project_id}/labels`；后端同时校验 canonical code 只能以英文字母开头，并由英文、数字、`_`、`-` 组成。
- 新建成功只会新增标签元数据并自动选中当前映射；**不会直接写 Ground Truth**。用户仍必须点击当前导入/AI 审核确认，之后才进入正式入库。
- 导入/审核确认 payload 继续保持 mapping-only；旧 `create_labels` 确认旁路继续 fail-closed，禁止通过外部名字静默 `ensure_label()`。
- 映射确认成功后才学习别名；例如新建 `helmet` 并确认 `toukui1`、`toukui2` → `helmet` 后，这两个外部名称才成为 `helmet.aliases`。
- AI 仍保持 Candidate → `AWAITING_CONFIRMATION` → Human Review → Durable Commit → AnnotationRepository；候选结果不会绕过人工确认直接写正式标注。
- 标签转换 / 导入等长任务的进度仍以现有 Durable Task / v19 backend truth 为准，不新增浏览器自造进度 owner。
- `VERSION.txt` 继续保持 `42.24.0`；未 merge main、未 tag、未 release。

本批主要实现提交从 `ecb466a` 起，包含四入口 UI、canonical API 复用、API/前端测试、缓存版本和 Label Normalization Contract 永久守卫。最终 GitHub Actions 结论必须以最新 HEAD 的实际 run 为准；queued 不等于通过。



---

<!-- CHANGLIAN_AUTOMATIC_DELIVERY_CURRENT_2026_09_20 -->
## 2026-09-20 — 当前新畅联自动交付合同

本节为当前 live contract，后续接手不要恢复旧兼容行为。

```text
TRAINING SUCCESS
  -> 本地算法版本 truth
  -> Model Artifact truth
  -> 自动上传算法产物存储（OSS/S3 等）
  -> stable public_url
  -> 新畅联 algorithm-version/add
  -> 新畅联 algorithm-weight/add (original model)

CONVERSION SUCCESS
  -> Model Artifact truth
  -> 自动上传同一算法产物存储
  -> 同一 remote algoVersionId 下追加 weight
  -> 不重复创建版本
  -> 不重复创建已同步权重
```

关键规则：

- 回退不是“切 current 指针”；**回退就是删除当前版本**。外部算法先删新畅联远端版本，成功后再执行本地原子删除/切换。
- `rollback_algorithm_version()` 服务层也强制删除，旧 `delete_current_version=False` 不能绕过。
- 新畅联删除成功但本地事务失败必须显式报 divergence error，不能伪装成普通失败。
- 外部模式主数据固定每 60 秒主动同步；当前官方 OpenAPI 无 webhook/subscription。
- 训练和转换结果自动归档不能关闭。
- 远程 conversion 的 `deploy/jobs` 与历史/local `deployment/jobs` 都是正式发现来源；必须有 algorithm/version source lineage。
- 远程训练已经存在于 canonical model storage 的同 SHA 对象直接复用，避免重复占 OSS。
- 畅联云 weight `filePath` 使用长期 `public_url`；临时签名 URL 禁止入库。
- “测试存储”必须同时证明凭据读写和最终长期 URL 实际可读。
- 新畅联训练资格仍严格为 `status=1 AND analysisType=1`；缺失、禁用、预留、大模型均 fail closed。
- 新畅联业务接口鉴权以当前 31 项 OpenAPI 汇编为准：`Authorization: Bearer <accessToken>`。
- `VERSION.txt = 42.24.0`，不 merge main、不 tag、不 release。

当前生产前仍需 live E2E：

```text
真实 OSS 长期 filePath 可读取
algorithm-version/add 返回/反查
algorithm-weight/add 返回/反查
version remove 实际副作用
超时后的幂等反查恢复
最新 HEAD Actions 全部 completed success
```

---

<!-- CHANGLIAN_REMOTE_CONVERSION_COLLISION_2026_09_20 -->
## 2026-09-20 — Agent 转换 dual-root 同 ID 冲突已加固

- 真实 Agent 转换会先在 `deployment/jobs/{task_id}` 写控制面 job，durable 结果提交后再在 `deploy/jobs/{task_id}` 写包含真实输出的 committed job；两者 **task/job id 相同**。
- Model Artifact 与 External Publish 发现器继续同时兼容两个根，但去重时必须优先读取 `deploy/jobs`。如果旧 `deployment/jobs` 先被加入 `seen`，其陈旧 `queued` / 空 outputs 会遮住 durable `done` / RKNN 输出，造成远程转换结果漏归档、漏追加畅联云权重，并可能把已完成转换误显示为仍在进行。
- 当前已把两个发现器的 root 顺序固定为：`deploy/jobs` → `deployment/jobs`，同 ID 时 durable committed result 为权威结果，旧根只作兼容兜底。
- 新增永久回归：
  - `test_auto_upload_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots`
  - `test_publish_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots`
- `External Algorithm Publish` CI 已固定 root precedence 和两条回归测试名称，禁止后续又退回旧根优先。
- 这次属于后端结果发现/同步修复，不改变前端字段或交互；`VERSION.txt` 仍为 `42.24.0`。
- 当前 GitHub Actions 仍必须以最新 HEAD 的实际 completed 结果为准；queued 不等于通过，也不具备部署资格。
# 2026-10-08 current override — R0 Material / Annotation lifecycle

VERSION `42.24.300` adds one project-scoped coordination fence between canonical Material lifecycle mutations and formal AnnotationRepository commits. Dataset delete claim/finalize, Storage Rescan content replacement, manual/AI/import formal writes and label remap reuse existing owners. Material annotation projections are version-monotonic and remain rebuildable derived state. Deferred structured imports preserve explicit `confirmed_empty`; plain uploads remain explicitly `unannotated`; batch contracts require Material identity before formal GT and target the versioned projection owner. See `docs/codex-handoff.md` for verification and CI status.
## 2026-10-08 AUDIT-084 / AUDIT-168 当前状态（最高优先级）

- 候选版本 `42.24.301`。Canonical MaterialBatch destructive publication、Training admission、Agent RKNN INT8 calibration admission 已接入同一个既有 Material lifecycle fence。
- 活动依赖来自 TaskRepository 的 `QUEUED / RUNNING / CANCEL_REQUESTED` 与已有 task artifacts；终态自动释放。删除任务的 selection 使用其现有 SQLite manifest 做 bounded membership lookup，不建立第二份依赖 truth。
- `DELETE_SOURCE` 用 MaterialRepository payload 中的内部 destructive claim 跨越锁外 provider I/O；一旦 provider delete 可能成功，索引/GT finalize 不再被 cancellation 打断。模糊失败保持 fail-closed，使用原 task retry 恢复。
- RKNN 最终入队重验 frozen calibration identity。删除端同时匹配 image ID 和 storage source/object reference。
- 本地相关测试已通过；精确提交 HEAD CI 尚待推送后读取。真实 OSS/RKNN/GPU/生产恢复为 `PENDING USER UAT`。
- 下一批只进入 AUDIT-178 Storage Source config/secret lifecycle；不要在本批新增 storage generation owner。

## 2026-10-08 AUDIT-178 当前状态（最高优先级）

- 候选版本 `42.24.302`。Storage Source 破坏性 PATCH 与 Import/Rescan、MaterialBatch CLEAN/AI、AI Annotation、TRAINING/PREPARE、RKNN calibration 的最终 durable admission 使用同一短 Source lifecycle fence。
- 活动引用从 TaskRepository + 既有 artifacts + MaterialRepository bounded query 派生；不保存第二份 pin/dependency truth。仍可能读取源字节的 QUEUED/RUNNING/CANCEL_REQUESTED 以及 Import/Rescan AWAITING_CONFIRMATION 保护 Source；已只剩证据确认、不再 materialize 的 review stage 释放，terminal 释放。
- name-only 允许；disable/config/credential replace/clear 活动期间 409。Import/Rescan/RKNN staging 在锁外，publish 时核验 runtime generation。
- credential replace 使用 versioned Secret ref，SQLite publication 失败不覆盖旧 Secret generation；没有向 task artifact 复制 credential。
- 本地 focused tests 已通过；精确 HEAD CI 待推送后读取。真实 OSS/Keyring/Agent/RKNN/GPU 为 `PENDING USER UAT`。
<!-- CURRENT_STATE_UNIFIED_PAGINATION_PHASE1_2026_10_08 -->
> ## 2026-10-08 统一分页第一阶段
>
> `VERSION.txt=42.24.303`。训练 compatibility 重复正式 Material/Annotation IO 已通过 revision-complete disposable projection 消除；最终训练 admission/Prepare/Snapshot 不使用该缓存。唯一公共分页 UI 为 `static/modules/pagination.js`，首批接入训练 picker、兼容性问题和任务 input issues。训练 picker 后端支持真实 page/page_size，cursor consumer 保留。相关 Python 125、frontend 39、Real Chrome 1、1k/10k/20k lightweight 3 均通过；精确 HEAD CI 和生产部署仍 PENDING。全平台迁移状态见 `docs/PAGINATION_INVENTORY_V42_24_303.md`。
>
<!-- CURRENT_STATE_PAGINATION_PHASE1_CI_FOLLOWUP_2026_10_08 -->
> ## 2026-10-08 分页 phase 1 CI follow-up
>
> `VERSION.txt=42.24.304`。仅将两个精确静态 cache-key 测试从旧 `main 42.25.294 / picker 422548` 同步到 phase 1 的真实 `main 42.25.303 / picker 422603`；`42.24.303` frontend 其余 842 项通过。产品实现仍为下节所述，最新精确 HEAD CI 待推送核验。
>
<!-- CURRENT_STATE_PAGINATION_PHASE_2A_2026_10_08 -->
> ## 2026-10-08 统一分页第二阶段 A 批
>
> VERSION `42.24.305`：数据集 MaterialRepository 真页码、训练任务 canonical snapshot 视图和 AI CandidateStore offset 审核均接入唯一 `pagination.js`。cursor consumer 保持兼容，未新增业务 owner。清洗/导入/模型及 phase 3 仍待后续独立批次；精确 HEAD CI 与生产部署为 PENDING。
>
## 2026-10-13｜VNext 模型质量工作台（LOCAL VERIFIED / PRODUCTION UAT OPEN）

- 基线 `30f83c48`，唯一 owner 不变：`training_evaluation.py` 负责评测事实，`TrainingRecoveryRuntime` 负责训练详情，`trainingReportCore425` 负责训练报告；没有新增评测引擎、训练状态 owner、轮询器、素材库或标注流程。
- P0 冻结图片读取按 Evaluation → Snapshot Test ID → SHA256 → 已验证 Bundle/Storage 实际字节闭环；拒绝同名替代、Snapshot 漂移、哈希变化与悬空检测框，安全错误码区分恢复/重试。隔离环境已验证，生产历史对象与真实 OSS 尚未验证。
- 评测工作台包含总览、类别/真实混淆、Top200 错误图片、真实 Confidence 采样、严格同基准版本对比；同图并排还要求相同 Image ID 与实际字节哈希。训练详情沿用原 runtime 四 Tab，训练报告区分执行、停止、独立评测和业务验收。
- 本地证据：Python 208 passed / 1 Linux-only skipped；Node 24 frontend 947/947；Real Chrome 51/51；1920×1080、1440×900、1366×768、375×812 的评测、图片、训练详情和报告均截图核验。正式 `VERSION.txt=42.24.355` 未改；未 push、未部署、未执行 GPU 训练。
- P2 明确保留：全量错误索引、完整场景切片、全量尺寸统计、PDF 导出需要新增可靠证据或迁移；旧记录缺证据时只提示重新评测，不回算或虚构。
- 本轮交付止于本地提交；GitHub CI、生产历史数据与 GPU 训练仍为 `NOT VERIFIED`。

## 2026-10-13 VNext review-fix closure

- Frozen diagnostic image identity now resolves explicit Image ID or one unique frozen `stored_name`; filename stem is never identity. Snapshot/test/SHA/bundle/storage/response-byte checks remain fail-closed. The bounded 20k identity projection cache holds metadata only and invalidates on file stat change.
- Training detail keeps one `TrainingRecoveryRuntime`: history is opt-in once per project/task, compact polling merges only latest epoch/resource summary, terminal tasks do not re-arm the 1.5s timer. Synthetic 1000/720 result: 296,333 B full versus 428 B compact. For the same 40 total requests, legacy is `40×full=11.3042 MiB`, current is `1×full+39×compact=0.2985 MiB` (-97.36%); the first full history is included.
- Strict comparison is keyed by `class_id`; ambiguous legacy duplicate labels are non-comparable. Navigation, missing delta, A/B controls, ARIA tabs and responsive visual hierarchy are covered by Node/Chrome regression.
- Final differential evidence: focused Python 60 passed / 1 skipped; Node 24.19 952/952; focused Chrome 7/7 and auth-config Chrome 2/2. Fresh Windows full pytest is 2325 passed / 12 skipped / 62 failed; the clean detached `30f83c48` worktree reproduces all 62 with the same exception class and first failing location. Clean baseline full Chrome is 142 passed / 6 failed; final VNext Node 24 full Chrome is 143 passed / 6 failed with the same six names and breakpoints. The extra label-management failure was a stale fixture race (request started versus cache committed) and now passes repeat 5/5 plus the 22-test material slice; the baseline-reproducible service-node startup fixture now passes repeat 3/3. No production code or business assertion was relaxed. See `docs/VNEXT_FINAL_DIFFERENTIAL_AUDIT_2026_10_13.md`. CI, production OSS/history and GPU remain NOT VERIFIED.

## 2026-10-13 multi-file upload queue closure

- ZIP selection now registers every file synchronously before fingerprinting or session creation. One shared two-slot limiter owns browser transfer FIFO across successive selections; merge, scan and label confirmation release the slot and continue on the existing durable server import queue.
- The existing upload task center shows every active file with size, real progress, queue position, reason and state-specific actions. Active rows are never truncated by terminal-history retention. Browser-only rows become explicit re-selection requests after refresh; persisted sessions retain the existing resume/cancel boundary. Project switches isolate local queue ownership.
- Per-file invalid, duplicate-content, fingerprint, session and transfer failures remain visible and do not stop siblings. Same-name/different-content ZIPs are accepted. Ordinary material upload remains in its existing chunk owner and accounts for all selected files.
- Formal `VERSION.txt` is `42.24.356`; cache keys for the changed entry points are aligned. Fresh local evidence: Node 24 frontend 962/962, Python affected contracts 35/35, Chrome 16/16 including 3/5/10 ZIPs, active/queued cancellation and 65 ordinary images. GitHub CI and production network/storage remain NOT VERIFIED; no push, main merge or deployment.


## 2026-10-14｜训练失败智能诊断（REMOTE PUSHED / LOCAL CI FIX READY）

- 事实源保持唯一：现有 Worker 在训练进程异常退出时只执行一次有界 Kernel journal 读取，并仅保存与 PID、进程创建时间及任务时间窗匹配的结构化 OOM 摘要；详情 API 不扫描系统日志，也未新增轮询器、诊断 Owner 或自动重试。
- `training_recovery_truth` 输出后端判定的 `diagnosis`（code/certainty/title/summary/evidence/possible_causes/suggestions/checkpoint_message）。`HOST_MEMORY_OOM` 需要任务关联 Kernel 证据；cgroup 还要求同生命周期 `oom_kill_delta>0` 和 scope identity；纯 `SIGKILL/-9` 固定为 `SIGKILL_CAUSE_UNKNOWN`，CUDA OOM、租约丢失、取消、SQLite lock 等保持独立。
- 对外诊断与折叠技术详情会脱敏路径、Bearer、token/password/secret/API key。旧任务只按已有证据投影，不回写状态或原始 artifact。没有可信恢复合同固定显示“当前没有可恢复的训练断点，需要重新创建训练任务。”，不出现恢复按钮。
- 训练详情沿用现有四 Tab 和 `TrainingRecoveryRuntime`；桌面将依据/可能原因/建议紧凑分栏，窄屏回到单列。缓存标识和 Training Recovery Guard 同步，正式 `VERSION.txt=42.24.356` 不变。
- 远端 HEAD `ab470e8c` 的 44 个实际 Actions 已终态：42 success、2 failure、0 running；Training Recovery Guard 与其余训练关键工作流通过。两项失败分别为 Frontend Runtime 守卫仍硬编码旧 `upload-task-center-3`，以及 ZIP Chrome 测试在标签确认模态框拥有交互焦点时点击其后方任务中心。最小测试/工作流修复已在本地完成并复验 Node 964/964、ZIP Chrome 14/14、诊断 Python 33/33，尚未获准再次 push。真实 Linux journal 权限、生产历史任务和 GPU 训练仍为 NOT VERIFIED。

## 2026-10-14 training creation feedback

- The sole `TrainingSubmitRuntime` now projects canonical execution into three human stages and renders an accessible in-dialog feedback layer only when work is slow. Fast completion keeps the existing button-level loading path.
- Success remains gated by durable task identity. A lost POST response is reconciled by the planned Task ID; an unresolved outcome is explicitly non-retryable until the user checks the task list.
- Node 968/968, affected Python 69/69, and focused Real Chrome 1/1 passed. Four responsive viewports plus reduced motion were checked. Formal version remains 42.24.356; CI/production are not verified.

## 2026-10-15 material integrity governance

- Full Audit remains the evidence source. A server-side SQLite plan now freezes full-scope duplicate groups, revisions, SHA256, annotation digests, keeper choices and DELETE actions; the browser receives only counts and a bounded 20-group preview.
- SAFE_ALL auto-includes only exact-image/exact-annotation groups. Annotation conflicts require a manual keeper; scan failures/anomalies and groups with multiple protected history references are skipped. Training/conversion history, active input tasks, snapshots, algorithms/models and evaluation records are treated as fail-closed references.
- Execution revalidates the whole plan, freezes the existing MaterialBatch selection, and publishes normal `DELETE_INDEX`. The worker rechecks keeper/delete identity and newly protected references before deletion. It removes index plus formal annotation only, never a shared source object, label dictionary or history record.
- Local evidence: Python governance 11/11, related batching 19/19, Node 970/970, Real Chrome 1/1 at 1366×768. Scale cases cover 501 planned deletions and 120 groups across API pagination. VERSION remains 42.24.356; GitHub CI, production history/OSS and large-production performance are NOT VERIFIED.

## 2026-10-15 training feedback CI follow-up

- Run 38711917017 found one real Chrome regression: a retry-safe validation error left the new failure overlay intercepting every later configuration click. Training submission and the Ubuntu/Windows static contracts were otherwise successful.
- Failure feedback is now an in-flow, non-blocking panel; only working/success states retain the modal scrim. Uncertain POST outcomes still disable retry through the existing runtime contract. Styles cache marker is 42.25.379; VERSION stays 42.24.356.
- The exact failing test was observed RED, then passed 1/1; the workflow's full local Chrome command passed 12/12 and Node passed 970/970. Remote retest is pending.
- Remote SHA 3718807f completed 35/36 workflows successfully. The sole Frontend failure proved that the long-form error panel could leave the viewport and that its guard still expected the retired MaterialBatch build 422403. The panel is now viewport-bound without a scrim and remains click-through, the exact guard follows build 422405, and two browser fixtures wait for canonical startup truth before injecting test state. The styles cache marker is 42.25.380. Fresh local evidence: Frontend Chrome 84/84, Training Create Chrome 12/12, Node 970/970; remote repair retest remains pending.

## 2026-10-15 automatic resource/OOM guard and training detail modal

- Auto resource resolution now samples the execution Worker host plus cgroup-v2 headroom and jointly budgets batch, loader workers, prefetch, image size, effective precision, cache and concurrent reservations. Manual overflow fails; the second pre-Trainer guard validates frozen host/GPU budgets without mutating parameters.
- Runtime memory evidence is task/node scoped and reports host/cgroup plus process-tree current/peak memory. USS/PSS is additive; RSS fallback is root-only to avoid shared-page double counting. A Kernel OOM for another PID in the same window remains suspected concurrent evidence, never a confirmed cause for this task.
- The existing TrainingRecoveryRuntime owns a centered 1180px/94vw desktop dialog with internal scrolling, fixed header/footer, in-place refresh, four stable tabs, Escape/focus restoration, fast-reopen fencing and reduced-motion. Requested/resolved/runtime and host/cgroup/process-tree truth are shown without fabricated zeroes.
- Fresh local evidence: Node 971/971; focused Python 99 passed / 1 Linux-only skipped; Real Chrome 4/4 at 1920×1080, 1440×900, 1366×768 and 375×812. VERSION remains 42.24.356. Real A800/GPU, Linux journal permissions, production cgroup/OSS and GitHub CI are NOT VERIFIED; no push, merge or deployment.

## 2026-10-15 first CI follow-up for resource and training detail changes

- The first Training Recovery Guard run exposed an obsolete static assertion for `oldDialog.replaceChildren` and a real Ubuntu Chrome geometry gap (68px tab width). The guard now requires `patchTrainingDetailDom` and rejects the retired whole-tree replacement; detail tabs have an explicit 80px minimum width.
- Existing Remote Training Runtime now has a named Ubuntu-only step that reads real cgroup-v2 `memory.max/memory.current` truth and executes the `/proc/self/fd` stability test. No second workflow was added.
- Fresh local evidence: Node 971/971, focused Windows Python 99 passed / 2 Linux-only skipped, Real Chrome 5/5. CSS cache marker is 42.25.382; VERSION stays 42.24.356. Remote repair CI and A800/GPU UAT remain pending.
- Repair SHA 39157527 exposed an obsolete Linux-only exact assertion before the named evidence step. Even with a fully frozen 31 GiB snapshot, the new joint Batch×Workers×Prefetch budget safely selects 8 rather than the old fixed 12. The test now proves GPU count independence, reservation-aware reduction and both plans staying within memory budget, without replacing 12 with another fixed number. The separate Linux test still reads real cgroup files.

## 2026-10-16｜独立评测图片预览专项（LOCAL VERIFIED / PRODUCTION OPEN）

- 历史无 Image ID 的规范化 Bundle 名通过 Snapshot、manifest Image ID、源 SHA256 和评测字节 SHA256 闭环恢复；同名冲突、归一化证据丢失和内容变化继续拒绝。
- JPEG/PNG/WebP/BMP 按真实格式返回 MIME；EXIF 仅产生保留原哈希的内存展示派生，保持冻结像素坐标。StorageManager.read_only 禁止预览补写正式素材元数据。
- 列表与详情统一错误码、单图重试和失败隐藏框；仅错误样本 Tab 当前页最多 24 张。Snapshot、Bundle 和历史素材名称投影复用原上限 8 的元数据缓存，文件身份/素材 Revision 变化时失效，响应逐次校验实际字节。
- Chrome 覆盖四视口、24/20k 按页请求、跨版本迟到结果、错误原因与重试。生产历史对象、OSS/A800 仍为 NOT VERIFIED；现场只读命令：`python -m scripts.diagnose_evaluation_previews --project-id ID --algorithm-id ID --version-id ID`。
- VERSION=42.24.356，静态入口缓存=42.25.384；保留先前本地 1de328cc，不推送、不部署、不改历史评测或 Snapshot。详细证据见 docs/EVALUATION_DIAGNOSTICS_P0_2026_10_12.md。
## 2026-10-29｜训练素材状态及可新增标签范围修复（42.24.412，CI 待核）

唯一长期开发分支 `feature/external-algorithm-publishing`；本轮从已确认远端 `95ebbe5a3afa82aa88a8b5d0c6e8a8ee9bbcda49` / `42.24.411` 继续，目标 VERSION `42.24.412`，准确新提交 SHA、是否推送及全部 CI 应在提交后核实，**未部署生产**。唯一权威需求、RED/GREEN、根因、代码、风险和本轮验收状态见 [训练工作台专项](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)。原 `selection-summary` 现独立返回仅选中素材有效正式 GT 正样本的 `positive_label_codes`；新增标签不再来自全项目字典，选材变化撤销无证据勾选；上一版本继承排序和 class_id 原合同不变；普通 Picker 不再以笼统待审核代替标注状态，按目标确认负样本与正式 preflight 仍安全保留。12k 隔离素材回归已新增；Node/Python、浏览器准确 SHA 最终状态需按提交证据更新。后续按原 [P0 性能记录](performance/2026-10-29-p0-followup.md) 继续真实 HAR、跨 Worker、芯片探测现场验收；不得因本次 UI 修复宣称生产 P95 已验。
> **2026-10-30 / 42.24.430**：429 `a3cee98c` 完整 Actions 38 成功/1 失败，Chrome 唯一 `refresh-error` 是成功关窗后后台列表刷新失败被新归属保护误抑制；430 仅允许原 DOM 根与任务 ID 未变时提示，仍隔离替换训练弹窗。Node 59/59，本次新 SHA CI 待核；唯一台账 [P0 进度](performance/2026-10-29-p0-followup.md)，未部署。
