# P1S 完整训练创建工作台（实施中）

接续基线4c5281fbef9aff3097767c5630e78faf2ca1976c，远端fetch一致，原changlian-vue干净工作区；D盘wip目录保持不动。唯一长期分支feature/external-algorithm-publishing。正式VERSION42.24.592保持。

用户授权P1S–P1Z顺序连续开发，本文件只记录P1S实际进度；后续不得提前称完成。

## 设计与实施步骤

1. 核对原三步、四模式、TrainingDraft/Label/Picker/Submit以及公开任务操作Owner。已核对原withLiveControls和Submit根节点/任务身份栅栏，不能保留两套同ID控件或复制业务draft。
2. 新增Vue三步训练展示及最薄presenter，原标签与复杂参数子树明确单一DOM归属；复用原Picker挂载及服务器冻结引用，禁止全量ID下载。
3. 选择/参数变化只委托原Draft/mode Owner；确认和submit委托原Submit，保持原request_id、冻结、标签、GT准入和未知恢复；原页面默认及回退保留。
4. 仅针对变化做Node、TypeScript/Vite、隔离Chrome关键链（HTTP创建拦截/合成响应，绝不启动训练），查看1920/1600/1440/1366/1024/768布局；随后提交/推送/准确SHA CI与离线制品核验。
5. 记录完成/未验证项后接续P1T，不因小功能暂停。若执行限制，准确交接未完阶段。

## 安全及待验边界

无生产训练、正式GT/模型/OSS/数据库更改，无SDK或Worker/Agent/Supervisor生命周期修改。当前代码/浏览器/CI验收尚未完成，不以计划代替交付。P1T–P1Z尚未开始；不切默认入口，不迁移数据库，不新增调度器或Repository。

## P1S实际代码与核验（提交前）

Vue TrainingCreate负责三步导航、单滚动布局、事实摘要和原节点slots；新training-create-vue-runtime仅DOM/订阅/退场适配，不新建draft/API/算法枚举。原完整三步控件（四模式、分组参数/增强/资源、标签、独立Test、最终确认）和footer/feedback原节点迁入独占容器，原ID/监听/Owner保存；Vue卸载精确还原。原反馈节点包含未知结果查询按钮，必须随footer保留。新页面禁用时不挂载，按原项目/算法/root验证迟到结果；外部关闭/pagehide释放。项目/算法选择和本地算法新增仍从已交付的项目上下文/算法管理进入，原迭代和母版本规则不复制。

TrainingTasks只新增原日志/操作诊断公开入口；进入旧任务详情后才能按原权限执行取消/恢复，未在Vue复制无回执的控制POST，不建立第二状态机。原TrainingRecoveryRuntime仍管日志、checkpoint资格、取消/恢复。

新增只读参数快照排除内部路径字符串，模型仅basename。设备读取失败明示error，UNKNOWN不能当已创建。HTTP Schema列出bf16但固定训练运行时明确拒绝，最终precision下拉保持auto/fp16/fp32；BF16受原运行时合同阻断，模式与默认值继续原Submit。时长原normalizeTrainingTimeLimit(0)确实返回null（留空/0不限），0.05原拒绝；本轮不改这一既有业务合同，不由Vue自行放行。

真实浏览器发现原独立Test切回random后null经Number(null)变0，导致Submit拒绝。新定向RED证明0!=原默认20，最小修原training-draft.js只对null/undefined复用原20默认，显式0仍保持0并由原校验拒绝，不放宽测试。draft/runtime26通过；原Submit/Draft/桥接/新适配器此前95通过，入口和最新适配器/路径保护29通过（含重叠，不叠加宣称总覆盖）。TypeScript/Vite1704模块通过，入口三资源统一615，改变的draft模块缓存615；未改VERSION或未变业务模块缓存。

隔离fixture复用原tools/test_vue_productization_server.py，仅新增MC_VUE_TRAINING_CREATE_COVERAGE=1的合成新算法无历史覆盖，调用原TrainingMaterialUsage.mark_coverage，默认行为不变。真实Chrome原登录/项目/算法入口、Vue3steps、Train2/Test1互斥、125真实JPEG及正式合成GT经原Picker服务器冻结（无ID数组）、原标签、quick/full/complex/custom30/150/250/手动、FP32、time合同通过。原train/start全部在浏览器abort，捕获仅1POST，未知404GET不清回执、不第二POST，再以明确合成QUEUED回执验证恢复。新脚本frontend/tests/real-training-create.acceptance.mjs可复现。6宽×3步共18图/receipt在test-results/p1s-training-create，已查看768截图，无横溢/底栏遮挡；fixture资源展示未提供不假装现场可用。8032临时服务停止。真实训练、checkpoint执行、资源分配和生产效果未验证。

后端无业务修改/Router抽取：本阶段关键依赖是原浏览器DOM与业务Owner，抽app.py无证明收益，故不拆。未来linux/amd64、linux/arm64、CUDA/Ascend等由原后端能力证据决定，本轮无硬件适配。P1T–P1Z尚未实施；准确新SHA CI/下载制品与最终离线ZIP尚待提交后核验，不能将本地测试当生产验收。

## 首轮准确SHA反馈

业务SHA0f81ce9f3be5c2fb15bae42627a458748bd28b41：Frontend job1724/1724、VueChrome19/19，制品14292334712已实物下载CRC正确，JS944393/CSS137541字节与本地构建一致；源码+Vue ZIP也通过CRC。该SHA的Training Create First Open发现旧浏览器断言仅允许3个precision选项，实际新增Schema已有BF16共4项；更新为精确4项并补BF16/AMP canonical验证，单条真实Chrome1/1通过，没有删除或放宽断言。

同SHA的Release Regression另在未改动test_process_control.py:73立即观察suspend后状态偶得running而非stopped。原代码/断言不变，已仅重跑失败runtime-contracts job，结果以远端实际回执为准，未改进程/Worker/Agent逻辑，未本地扩大该无关测试。最终收尾SHA仍须独立CI验收，禁止将首次红灯写成全绿。

## 精度运行时合同纠正

Remote Training Runtime CI的Permanent guard揭示：HTTP TrainReq Schema虽然列出bf16，但实际platform_core/training_precision.py的SUPPORTED_TRAINING_PRECISIONS只有auto/fp16/fp32，normalize_training_precision明确拒绝BF16。先前只核对Schema便增加BF16可选项是本轮判断错误，已撤回；不是修改/放宽CI guard。恢复精确三个可用选项，浏览器额外验证BF16选项不存在。前文“补齐BF16”及第二次四项断言是被纠正的中间过程，不代表最终交付。用户要求的BF16目前受原运行时合同阻断，不能通过前端假装支持；本轮不升级Ultralytics或实施硬件适配。最终收尾SHA重新核验所有被触发的CI，首次红灯不冒充成功。

## 准确P1S收尾SHA验收

e83a60c807fdd09081c079245d1fd630c76e5c75最终36/36自动工作流成功。原进程挂起观测及导航清空回调失败均在不改原代码/断言的失败job复验后成功，保留原失败记录，不称首次全绿。下载该SHA制品14294007527，ZIP3176002字节、CRC正确，JS/CSS逐字节匹配本地；源码+Vue包source-with-vue-e83a60c.zip通过CRC。回执在test-results/p1s-delivery。正式训练、BF16运行时支持、现场节点性能及断网目标安装仍未验证；BF16明确受固定运行时阻断。后续P1T接续，不改上述已验业务。
