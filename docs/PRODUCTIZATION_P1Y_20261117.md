# P1Y 资源与统一配置中心

基于bd6e3e401a765bc04c0367cb5b4995961b5b0c8d接续，唯一长期分支，VERSION42.24.592保持。准确新SHA CI/制品推送后核实。

## 实现与真实合同

增量扩展原ServiceNodesOverview/ServiceNodeCard，原GET /api/v63/service-nodes和ServiceNodeRepository保持：allowed是管理员允许、reported是Agent上报、effective是启用且可达时交集。原Vue卡片误把effective标成当前可调度能力，现改“当前有效能力”；独立“当前可调度能力”明确未提供调度准入证据。在线/GPU上报不代表训练可用或空闲量。原CPU/内存/磁盘/显存/系统架构/心跳/Agent/Worker/持久任务证据继续保留，无数据仍未上报，不引入硬件白名单或第二调度状态。

新增ConfigurationCenter.vue和类型，opt-in vue_configuration=1同时允许原Vue节点总览；节点工具区进入统一配置中心，9个真实入口按计算资源、模型与标注、模型交付与存储、基础字典分类，可本地搜索。对应原NavigationStability页面和原AdvancedNavigation.selectAdvancedSection公开接口；Prompt直接选择原模型配置页prompts，存储/训练/转换资源选择各自原正式section，不点击隐藏DOM或修改其内部状态。保留旧页面、返回完整节点管理及全部原写功能。

原训练资源 /api/train_servers、training_options/v62training-devices；转换资源v39deploy/resources；模型/Provider与Prompt v35；存储v61storage-sources及ModelArtifact；平台v63ExternalAlgorithmPlatform；字典原v39操作及回执，各自原Owner不变。配置中心本身不读取整份配置/密钥，不复制配置库，不启动SDK、测试连接、驱动安装或同步。实际修改/启停、Token轮换、SecretStore/Keyring、引用保护仍原表单与Owner；节点写入缺统一持久回执，未在Vue复制高风险写操作。没有新增后端API/Repository/schema。

资源配额、完整训练/转换环境准入没有统一节点字段或独立可靠结论；本轮只提供可信原资源配置入口，不能宣称已新增统一配额管理或实机环境验收。Agent安装、远程命令、Supervisor权限及生产服务生命周期不迁移。

## 验证与工程

直接桥接/白名单/迟到项目与8缓存合同共52/52 Node通过。原服务节点Chrome唯一相关用例通过：三类能力、独立无调度证据、未知GPU、手动刷新/筛选、退出取消与秘密sentinel不渲染；未重跑无关浏览器全量。TypeScript/Vite1723模块通过。入口styles/app/main统一42.25.621，catalog桥及Vue资源调用缓存同批更新，正式版本与无关模块缓存不动。

frontend/tests/real-resource-configuration.acceptance.mjs在8041全新临时库复用真实登录/原节点心跳API、Vue节点→配置中心、搜索不发HTTP、原Prompt/存储/节点完整页面访问，所有配置写请求0、探测0。初次Prompt只导航到原模型页时其模板tab默认隐藏，实际截图确认后改为原公开selectAdvancedSection，未绕过原Owner；最终通过。六宽1920/1600/1440/1366/1024/768配置截图6张，另原节点用例截图2张及收据保存在仓库外delivery-evidence/20261117/P1Y-real-entry，768实际查看，无文档横向溢出。

准确P1X CI的Label Normalization Contract两条自动触发工作流在Permanent source guards失败，原因是仍精确期望原taskApi()而本轮冻结项目改为taskApi(null,ownerProject)。只替换该条精确源码期望，保留所有其他标签/历史/唯一路径断言；从原YAML提取同一Python步骤原样执行通过，不新增工作流或改业务标签规则。旧bd6e3e4不能写为全绿。

P1W准确CI离线artifact14304071718已下载、GitHubdigest/CRC通过，准确源码+CI真实JS/CSS包含包及vendor/licenses完整。但CI与此前working build原始JS/CSS SHA不同，尺寸相同，已明确记录MISMATCH而非伪造一致。检查发现本地编辑产生6个CRLF SFC，仓库既有.gitattributes明确frontend/src/**/*.vue eol=lf且Vue scopeID依源字节。已按原规则仅恢复本地SFC LF（Git无其他内容diff），本批重建；最终准确CI SHA/hash需实际比较，尚不将推断当验证。

## 未验与后续

生产资源、真实GPU/NPU/Ascend/配额、真实连接/SDK检测/节点启停/密钥保存/Token轮换/现场离线安装均未验证。旧配置表单为保全原完整功能而继续委托，不宣称所有表单Vue重写。新SHA CI/离线包含待推送核对；隔离与CI不等于生产部署。

P1Z最后评估同一Vue运行时复用和mount生命周期，按原唯一导航Owner渐进统一工作台，默认旧入口保持；不机械合并SPA/Router或大拆app.py。linux/amd64/arm64/CUDA/Ascend扩展约束保留，不实施硬件适配。
