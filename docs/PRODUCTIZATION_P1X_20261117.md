# P1X AI 标注创建与任务操作

接续P1W dba78b4e8b92e6df97ff33251f97c651bdabd0a2，唯一长期分支，VERSION42.24.592保持。准确新SHA CI和离线制品须推送后核实。

## 实际交付

新增AiAnnotationCreate.vue/types/ai-create-vue-runtime；opt-in vue_ai_create=1，原AI任务列表或原素材/上传治理入口仍调用唯一createAiLabel429/Core429。Vue组织素材范围、模型与配置、核对与创建三步；原configuration/materials/advanced/hydration/confirmation/footer/recovery节点独占移交，卸载恢复同一原节点，原控件与原Submit唯一。没有复制Provider适配、选择器、推理引擎、坐标白名单、候选库或正式GT Owner。

素材按原分页、annotation-selections引用及summary处理，不下载全量ID；模型服务、模板、标签仍原v35/v12读合同。WeVisOne检测Query和通用Prompt按原保存适配器区分，既有Ollama/vLLM等协议不改；不按模型名猜坐标，不在Vue存配置对象、Base64或密钥。单图试跑原显式入口保留，本轮不调用。AI任务列表/失败分页/差量重试/导出/审核继续既有P1O原Owner和可信完整详情入口，不新增全量任务重试或执行POST。

原submit仍先服务端素材摘要、真实选项确认，再第二次明确创建；实际POST /api/v60/projects/{p}/annotation-tasks、回执GET /by-request/{request_id}及TaskRuntime保持。正式预测候选/人工GT仍CandidateStore/AnnotationRepository与Annotorious3.9.5，均不改。

## 原Owner恢复及错误合同

修复请求编号只在内存、刷新或新表单可误发新POST的问题。原Owner durable journal ai-create-operation:{encodedProject}只project_id/request_id，POST前写后回读失败拒绝提交，不持久payload/Prompt/图片/密钥。原任务id响应或匹配by-request回执才清精确journal。网络、超时、冲突、缺id和404查询保留UNKNOWN；跨刷新或改变表单后仍禁止第二创建，只有显式查询。查询去重并有原modal请求controller，退出取消读取，迟到回执不关闭新项目或替换层；POST不随页面关闭取消后台任务。

原路由先_annotation_create_payload校验，再atomic request.json/TaskRepository.create：明确HTTP400/422属于创建前拒绝，可清本次journal、保留原配置并重新核对；409可能是同ID绑定/准备文件/并发创建，仍UNKNOWN。未把所有失败都当未知或成功。后端没有新增receipt端点/Repository/调度/schema；本轮只修原前端Owner，不改Worker/Agent/Supervisor。

## 实际验证

原AI Owner/retirement及新增恢复共28/28 Node通过，包含存储quota/静默丢写、零重复POST、缺id、跨项目、迟到读回、去重/owned abort、明确400/422拒绝可纠正及409禁止重发。原静态断言按固定ownerProject路径和公共by-request helper更新，保留先确认再唯一POST、标签资格和旧入口断言。

TypeScript/Vite1720模块通过，最终本地JS1019575/CSS157179字节，SHA在仓库外build回执。入口三缓存统一42.25.620；8个相关缓存/Owner文件39/39通过，覆盖字面量及转义正则，未修改正式版本或无关模块缓存。

frontend/tests/real-ai-create.acceptance.mjs使用8039原index/真实登录/全新临时库125图、真实分页/服务端冻结引用与summary。模型配置和任务回执明确合成：全选125后image_ids=[]、selection_ref有值；原通用Prompt与原WeVisOne Query控件切换；阈值0.37/标签smoke及真实确认数量；唯一创建POST在浏览器发往服务器前abort，未知跨刷新两次GET、404保留/匹配回执清除并交回原任务Owner，原创建界面回退。推理/GT/正式任务创建0，无生产服务。

六宽1920/1600/1440/1366/1024/768×三步18图，原收据和最终布局补取分别保存在仓库外delivery-evidence/20261117/P1X-real-entry。实际查看768配置、1366确认，发现任务名日期误中路径隐藏后收紧路径边界；步骤切换保留旧滚动位置已改为Vue自身正文重置顶部。最终布局补取仅选择/ref/summary，无创建POST或推理；正文在独立footer上方、无横向溢出。自动化先错误直接填折叠高级控件、后直接点被装饰i覆盖radio，均改为用户实际展开summary/点击可见label，没有force或弱化准入。

## P1V/W CI收尾

P1W dba78b4实际37/38工作流成功，Frontend unit/build已通过，唯一browser-navigation1里旧loading-recovery-supplement发布pending/rejected两例未处理新增confirm，其余126例通过；不是平台全部验收。补显式确认且保留原pending超时GET-only/POST1、422拒绝重试POST2严格断言，原2Chrome定向通过8.4秒。原publisher路由无执行期422，422为进入Owner前schema拒绝，恢复原可纠正语义；409/网络/POST成功后读回失败仍UNKNOWN。新增publisher定向25/25通过，不放宽未知结果保护。相关caller缓存同步本批。d9b3ff2/7195旧CI红灯不能改写为绿色；本批准确SHA继续核对。d9b3ff2无CI Vueartifact已记录UNAVAILABLE；dba78b4 CI制品与源码包含另外按准确SHA恢复核查。

## 未验证 / 后续

真实Provider、模型推理、任务执行、差量重试执行、人工GT及生产部署未验；合法零框/失败/非法输出保持原Owner，本轮未用Mock冒充真实预测。UNKNOWN且服务端一直404时需要后端/管理员核验，页面不提供绕过保护或清除后新建。现场离线安装、实际硬件/NPU/GPU未验证。准确新SHA CI和CI资源包含仍待推送核实。

P1Y将补节点有效/可调度语义与资源/配置入口，P1Z最后评估统一工作台；尚未完成不记交付。原模块化单体和linux/amd64/arm64/CUDA/Ascend扩展约束保留，本批不抽app.py/新Repository/数据库迁移。
