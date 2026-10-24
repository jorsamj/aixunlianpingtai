# 大模型自动标注 API 协议兼容专项（已完成待CI验收）

## 基线与范围

2026-10-24 fetch后本地/远端80663002fa033dd5d5cb16747e05a743fbfab4f4，VERSION42.24.384，长期分支feature/external-algorithm-publishing；仅两份既有未跟踪训练模板测试，保留5944祖先/其他工作树。用户授权最小协议适配、前后端配置、Mock HTTP测试、正常提交推送及最终SHA CI；不部署、不调用收费模型、不改GT/存储/划分/训练/Worker/发布转换。

## 需求与真实审计

已证实openai_vision._chat_endpoint把完整/responses拼成/responses/chat/completions；body固定messages/response_format，parser固定choices；所有400无条件再请求json_object，错误只给通用Key/地域提示。配置V35ModelConfigReq/最终M4视图没有协议字段。连接测试v35_saved_test和正式annotation_runtime.prepare_request都使用auto_label.provider_factory，结果都通过原parse_candidate_response；正式候选/人工确认/GT Owner继续复用。

用户合同：auto/chat_completions/responses；准确URL路径识别，完整端点不重复拼接，历史/api/v3仍Chat，显式协议优先，自定义地址保留并告知确认。Responses input_text/input_image、URL/Data URL、非流式、只取最终output_text、拒绝/空/非文本/未完成不作为有效标注。Chat response_format、Responses text.format；不支持结构化才受控降级，认证/权限/模型/普通400不重试。原内部字段/类别/坐标校验继续强制。HTTP分类、服务端code/request_id脱敏保留，密钥不变；配置新增/编辑/保存/刷新一致。

## 官方核验（2026-10-24）

- [方舟创建模型响应](https://docs.volcengine.com/docs/ark/create-model-responses-api?lang=zh)：Responses input/content类型、图像URL/Data URL、text.format、完成状态及output协议。
- [方舟结构化输出](https://docs.volcengine.com/docs/ark/responses-api-structured-output?lang=zh)：json_schema/json_object按能力启用。
- [官方SDK使用说明](https://github.com/volcengine/ark-runtime-python/blob/main/docs/usage.md)：遍历output里的message/output_text，reasoning可能在前，不能假设output[0]或只读顶层output_text。
- [模型列表](https://docs.volcengine.com/docs/ark/model-list?lang=zh&redirect=1)及[思考说明](https://docs.volcengine.com/docs/ark/deep-thinking?lang=en)：存在用户指定glm-5-3-flash-260828，多模态；该型号思考始终启用，不强制thinking.disabled，也不把思考当标注。没有真实Key/付费调用，真实该账户模型权限/视觉效果仍NOT VERIFIED。

## 设计、取舍与实施计划

选原OpenAICompatibleVisionProvider内协议分支，不复制provider；工厂仅透传配置，原VisionProviderResult/候选DTO继续复用。替代：重建Responses provider会复制HTTP/错误/鉴权/解析；按模型名硬编码接口会破坏自定义代理，均不采用。

URL以urlsplit路径末段识别/responses或/chat/completions，保留query；显式协议可转换已知端点后缀；根或版本base追加唯一端点。auto未知自定义路径保留保存，返回确认协议提示；显式协议将未知完整路径视为自定义端点，不擅改。选择字段高级设置、默认auto，旧文件不强制迁移/改密钥。structured_output默认auto，可显式schema/object/prompt表述能力，避免按模型名猜测。

auto结构化依次schema/object/提示词+后置校验，只在明确unsupported format的400下降一级，上限3次；普通400/401/403/404/429/5xx不重复；显式格式不静默变化。Responses不设置模型专属thinking/temperature；Chat既有参数兼容。错误不回显服务端自由文本/请求body，仅静态分类及校验脱敏的code/request_id；复用ProviderRequestError和PlatformError可选字段。

- [x] A 审计调用链/文档/真实基线，报告根因。
- [x] B 添加端点、请求、返回/错误/受控fallback RED，再实现原provider最小分支。
- [x] C API配置持久化/连接测试字段、正式同适配器和无效结果不入GT验证。
- [x] D 原M4高级配置/保存/刷新编辑，必要Node及真实Chrome配置冒烟。
- [ ] E 版本/缓存/原相关CI、最小回归、文档及正常提交；最终SHA独立核验。

每阶段记录真实测试/修改/提交/风险，不以Mock成功冒充收费模型实测；现有测试不删除/降断言，不重跑无关全仓/GPU。实施按writing-plans/TDD执行，已确认的用户合同无需再次审批。

## 测试与交付证据

实现文件：platform_core/providers/openai_vision.py（同一provider的端点/请求/解析/错误/受控fallback）；base.py与errors.py仅扩展原结果/错误元数据；auto_label.py工厂透传及错误脱敏，原候选字段/标签/坐标校验不变；app.py原V35配置/测试共享helper及原Bootstrap模型投影；static/app.js原M4高级设置/保存，index缓存；既有相关CI、测试及接续文档。VERSION42.24.385，入口app/main/styles缓存42.25.433。

新增api_protocol与structured_output保存于原model_configs.json；旧客户端PUT未传新字段保留已存值，Key空值保留原secret_ref。列表只补默认投影，无历史文件强制迁移。完整/responses老配置以auto推断，原文件字节不变已验证。无法识别的auto自定义地址保存原值并返回protocol_warning；显式协议使用自定义完整路径。已有URL内认证形式保持原请求兼容，错误证据过滤其凭据；不扩大或重建鉴权。

补充真实缺口：保存后刷新读到旧Bootstrap模型配置投影，重编辑会落到默认值。Chrome先RED；仅在V35新增/修改/删除时用原脱敏mutation结果更新既有snapshot.model_configs，不全量重建、增轮询或新建缓存。新增API投影RED→GREEN及Chrome刷新用例已验。原初始化并发构建期间/多进程缓存一致性未新建协调，现有Bootstrap/文件持久化架构边界保留，不声称分布式一致性已重构。

保存与未保存VLM连接测试均调用同一个_v35_test_annotation→provider_factory→provider.annotate→原parse_candidate_response；非VLM旧health能力保留。正式annotation_runtime冻结整份模型配置已有能力直接保留新字段，Scheduler实际使用同工厂。测试API保持平台业务错误HTTP400，使用code/upstream_status区别上游401/403等，避免把模型账户401当成本平台登录失效；request_id/server_error_code按可选字段保留。没有把HTTP200直接作为成功。

脱敏：上游自由错误文本/图片不回显，仅静态分类+安全code/request_id；超时不包含原网络异常。候选Pydantic错误去掉input并抑制原异常cause，未知标签不回显模型原值，防止失败日志带出Data URL/Key；校验规则未放宽。

### 本地RED→GREEN记录

|范围|RED/发现|最终证据|
|---|---|---|
|协议核心|新35项初始34失败/1通过，端点/输入/输出/错误/降级缺口|最终tests/unit/test_openai_vision_protocol.py 43/43通过（0.24s），0失败/跳过|
|V35配置/原正式E2E|新增7项RED，原3项通过|10/10通过（6.31s）；含成功/非法标签/未完成三种输出真实Scheduler执行，不直接写GT，失败确认被拒绝|
|投影/历史/测试同适配器|snapshot新增投影1项RED；后补老文件不重写及未保存测试同provider|test_model_configs.py最终9/9通过（1.14s），0失败/跳过|
|原Chat/Ollama/冻结runtime|复用原测试，不改旧协议输出合同|test_fake_vision_provider.py 6项+test_annotation_runtime.py 8项通过；与初轮协议35合跑49/49；最后降级分支受影响单例补跑1/1通过|
|错误安全/标签合同|模型字段/未知标签原值泄漏2项RED；原异常链1项RED|脱敏2/2 GREEN，最终43包含这两例；原标签别名5项亦通过（与当时协议40合跑45/45）|
|受控降级与URL兼容|纯文本明确unsupported不能降级、模型名含json_schema误重试、旧认证URL被新校验阻断均RED|已在同一43项内GREEN；自动最多schema/object/prompt三次，显式模式不改写，普通400/鉴权/权限/模型/额度不重试|
|前端Owner/缓存|不新增源码镜像测试|原4文件18/18 Node通过；Node syntax/py_compile/diff check通过|
|真实Chrome|高级协议字段缺失RED；刷新落回默认URL二次RED|新model-api-protocol.spec.mjs最终1/1通过（7.1s），真实本地API保存/刷新/重编辑/改auto及原URL保留，0 pageerror，成功清除仅自身隔离配置|

不将各轮重复用例相加冒充独立数量。最初尝试的test_auto_label_candidates.py包含已退役v47接口，原用例返回410；该文件保持原样，没有删除测试/恢复旧流程/放宽断言。本轮正式验证移至已有test_persistent_ai_annotation_e2e.py的v60+Scheduler+CandidateStore路径。

CI：原AI Annotation Recovery增加provider/核心与新测试paths、43项跨平台单元及原API job运行相关配置/集成；cryptography已是项目依赖，补入该job安装以验证原secret能力；原Frontend Runtime增加单个真实Chrome用例。无新工作流、依赖体系或测试框架。代码提交8d806032a706f9dba94d6ac47c6facab94badbc4已正常推送；准确该SHA CI正在核验，本地通过不代表远端CI成功。

### 兼容收尾及最后回归

最后配置/正式E2E合跑13/13通过（5.80s），无失败/跳过。进一步核对原v42/v44测试入口发现保存的secret_ref没有通过V35ModelConfigReq传给原测试，VLM新协议请求会丢失鉴权；新增两个Mock HTTP测试先RED，原两个入口现仅对VLM委托v35_test_saved_model_annotation，非VLM继续原health行为，2/2 GREEN（0.19s）。因此最终配置组为11项（原9+这2），正式持久化E2E为4项；不将不同轮重复相加。协议核心最终43/43 GREEN（0.24s），包括历史URL认证形式未被新的协议判断无端禁止。Chrome最终1/1 GREEN（7.1s），清理只针对自身隔离配置，18项原Node Owner守卫通过。

平台原API错误HTTP400语义及登录认证不变，上游401/403等通过原错误DTO的可选证据字段分类；v35/v42/v44已保存VLM、未保存VLM和正式Worker都复用同一adapter/字段校验。未新增收费接口调用、后台探测或定时测试。

最终证据兼容复核：平铺网关HTTP错误的code此前未被保留，新增单例RED；元数据提取现同时兼容标准error对象及平铺code/request_id，仍不回显message。该修正不改变请求/候选/GT逻辑，需按修正后新SHA核CI；最终协议用例44项。顺带规范本文件EOF，不保留多余空行。

旧UI返回形状复核：testAutoModel422仍展示r.status_code；统一VLM探测后需保留原ok/status_code字段，避免旧入口出现HTTP undefined。原两个密钥别名测试增加这两个断言先RED，统一helper成功返回只在图像/标注校验均通过后提供ok=true/status_code=200；不会以HTTP200绕过校验。两项定向GREEN后正常修正提交，必须核验最新SHA。

### 接续与发布边界

E阶段剩余：正常提交、push前fetch，核验准确新SHA CI；结果回填本节，文档自身新HEAD亦核Checks。真实glm收费调用/该账户权限、地域/额度、网络及模型标注效果仍NOT VERIFIED；本轮不提供生产已可用承诺，不索要公开Key、不执行生产部署。受控发布前应使用平台原安全保存的Key，在用户授权环境做一次真实图片标注验证。后续从本文件及原provider/M4/V35工厂继续，不另建provider、GT或任务Owner。
