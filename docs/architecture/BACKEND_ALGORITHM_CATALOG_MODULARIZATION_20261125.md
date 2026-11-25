# 算法库与版本生命周期模块化（2026-11-25）

开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。运行期、完整 OpenAPI 展开与生产未验收。

## 工程身份与本轮范围

起始 21fb70de23c3be40006cb27579a031ca487abf60：用户已独立核验 22/22 PR workflow SUCCESS，既有 P0-01C 与资源准入不重新开发。
A 实现 dd8ee530924e79b87ed876d309b4dc0017d650bc，重启恢复合同见[资源等待记录](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。
B 实现 da45ae7a46458cad0c8ce469f6083ae6c4613c21。最终含文档 SHA 和一次性 CI 快照见交付消息。

本轮完成算法库目录与版本生命周期这一完整子域，未声称迁完算法训练、评测、转换或发布域。

## 业务与模块边界

|模块|职责与唯一 Owner|
|---|---|
|algorithm_catalog_api.py|原 v12 HTTP 路由、签名、参数与原返回；调用目录 Service。|
|algorithm_catalog_contracts.py|原 AlgorithmReq、AlgorithmVersionReq、VersionPatchReq、AlgorithmVersionRollbackReq，字段/默认值/Literal 不变。|
|algorithm_catalog_service.py|目录与版本业务唯一实现：查询投影、历史/计数、引用保护、版本清理、回退、dry-run 及下载编排。|
|原 algorithms / AlgorithmRepository provider|继续拥有算法/版本持久读写、CAS 与事务；不新增 Repository，不增加 SQL，不启用 U1/PostgreSQL 切换或 fallback。|
|原 Task/Artifact/反馈/存储/发布服务|继续拥有对应记录、资源和外部操作；新 Service 只调用原访问器与既有锁。|
|app.py|Router 装配、动态依赖访问器和仍被其他域/测试调用的兼容入口；不保留两份业务实现。原 bootstrap 快照与锁仍由原应用生命周期 Owner 持有。|

14 个原接口原位注册，URL/Method 不变：

- 算法列表、创建、详情、编辑、删除（5）。
- 项目待归属模型查询；原手工版本归属拒绝入口（2）。
- 版本备注、版本删除、回退（3）。
- 激活 dry-run、回退 dry-run（2）。
- 清理失败重试、授权版本下载（2）。

原手工归属继续 409，外部 CHANG_LIAN 版本退役禁令、expected_current_version_id、活动引用阻断、删除回执、远端清理幂等及 dry-run 零写入断言保持。授权下载仍走原受控业务文件入口。原 App 兼容函数仅调用同一个 Service 实现，不重复注册路由；内部无引用的旧辅助转发已移除。

## 共享状态与一致性

依赖为显式、晚绑定访问器，不反向 import app，不复制 DATA_DIR、bootstrap 字典、锁、任务缓存或 Repository 实例。旧测试/业务替换存储 provider、目录读取器或数据根目录时仍经过相同入口。

bootstrap 列表只读复用与发布仍检查原项目、SQL revision、原锁及提交前 revision，回写由 app 的单一状态 Owner 完成。其余 28 个业务/辅助函数经依赖名还原的 AST 逐项比较，语句结构保持不变；未修改 Repository 事务或外部操作顺序。

## 必要验证与数量

- app.py 29,124 → 28,264 行（减少 860 行）。
- 直接 HTTP 声明 330 → 316，新 Router 原位补回 14。其他 Router 注册未改；展开新 Router 后，静态有序 Method/URL/签名/默认值/响应注解/说明与原注册序列逐项一致。这是静态证据，未冒充本机实际应用路由枚举。
- 原 4 个请求模型 AST 保持一致；新增 Router 的 FastAPI 导入、依赖字段/装配参数对应、未定义全局名称和新模块循环引用检查通过。
- 复用原 CRUD、模型视图、版本回退/清理/API 测试；现有 test_algorithm_flow 增加按旧声明冻结的 14 接口 OpenAPI operationId、query 默认值、请求模型和 dry-run 说明检查，交 CI 执行。
- 原外部退役安全守卫转向真正的 Service/Contracts/API Owner，保留全部断言；原 Algorithm SQL Store HTTP Job 增加运行现有版本回退测试。无新 workflow。
- 本机仅修改文件语法、AST/符号等定向静态检查及 git diff --check 通过。未导入运行 app，未执行 pytest、测试函数、浏览器、服务、Docker/WSL、GPU 或构建。运行期断言全部待现有 GitHub CI。

## 现状与剩余真实边界

|域|当前状态与后续边界|
|---|---|
|外部平台/发布、在线反馈|已有 Router/Service/Repository，继续复用，未重复开发。|
|算法库目录与版本生命周期|本轮 Router、契约和业务已迁出，持久化沿原 provider；训练结束自动归档等训练域调用留原 Owner。|
|训练创建/报告、素材 Picker/负池、智能审计|已有独立 API/Service 或专业模块；不能据此宣称全部训练/素材 HTTP 与业务已迁完。|
|素材、标签、人工 GT、AI 创建/审核|仍有 app 路由和编排；复用已有 MaterialRepository、AnnotationRepository、CandidateStore/annotation_task_service。后续需按标签/GT 锁、审核修订、冻结选择与批量提交边界迁移，不拆出第二写入 Owner。|
|训练管理与转换/质量/部署|仍有 app 任务控制、历史与联动编排；转换/旧 v42 组共享 _v42_*、产物及执行边界，应按完整业务单元迁，不能只搬两三个接口或改调度。|
|认证、bootstrap、存储/系统配置及生命周期|应用根仍持有 Session、快照、密钥/存储工厂和启动装配；新 Service 注入这些 Owner。尚未进行本轮范围外的生命周期重构。|

前端未修改，算法卡片、素材人工标注入口、AI 三栏、菜单和业务流程保持。保护文档/VERSION/AGENTS 未改，未访问 A800/4070/生产或启用双槽、自动清理、supervisor-required、PostgreSQL 正式切换。

本轮完成后停止，交 GPT 独立审计；CI_PENDING 不等于验收通过。
