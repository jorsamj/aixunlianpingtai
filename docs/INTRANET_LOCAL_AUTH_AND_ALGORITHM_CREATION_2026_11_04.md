# 42.24.530｜算法训练本地登录与内网独立算法创建

> **后续 42.24.531 补充**：本文件中的“须人工切换为本地模式”已经由「平台对接」页面顶部持久总开关提供直达操作，并在后端增加所有新畅联 provider 请求及 Worker 外部清理派发围栏。具体见 `docs/INTRANET_MODE_MASTER_SWITCH_2026_11_04.md`。独立 OSS、外部 URL、远程计算资源等可选能力仍须分别配置。

日期：2026-11-04。目标分支：`feature/external-algorithm-publishing`。前版基线：42.24.529／`ad63fd3666c0f78c2d80abb6f191c731f5560320`（GitHub 远端，21/21 可查询 CI 成功）。本次不修改生产数据、不部署、不合并 main。

## 需求及实际代码核验

| 功能 | 修复前实况 | 42.24.530 修复 |
| --- | --- | --- |
| 浏览器登录 | `/api/auth/login` 始终向畅联云发起网络请求；无网无法登录 | 同一 API 增加 `provider=local/changlian`，**默认 local**；前端默认本地登录，畅联云是显式可选项。无远程认证依赖 |
| 本地凭据 | 无本地用户入口 | 初始账号 `jiangjs`、密码 `123456`；可在服务启动时以 `MC_LOCAL_USERNAME`、`MC_LOCAL_PASSWORD` 覆盖。密码不发到外部服务、不写明文配置；服务内派生 PBKDF2-HMAC 摘要，8 次失败后按客户端暂限 60 秒 |
| 会话与退出 | 已有签名 Cookie、续期、持久撤销 | 复用原 Owner 与路由；签名会话加入 `provider` 标识，续期继承；本地用户不显示伪造的上游 Token 信息，历史畅联云 Cookie 兼容 |
| 首页和登录品牌 | 左上角、折叠导航、登录桌面/手机端均引用中南企业 PNG | 全部切换为 `算法训练` 文字+本地 CSS 的 AI 标识；标签页、首页标题、启动文字及 API 平台名称统一。历史素材 PNG 不再被正式页面引用 |
| 内部算法创建 | 按钮及 SQL 本已存在，**external 模式被 `assert_local_algorithm_create_allowed()` 直接 409 拒绝** | 沿用单一弹窗、单一 API 和 `AlgorithmSqlStore`；即使配置外部平台也可新建 `source_type=LOCAL`、`master_data_readonly=false` 的独立算法，不调用外部平台。同步导入的 `EXTERNAL` 算法仍只读 |

注意：出于安全原因，不在登录页自动填写密码。初始弱密码仅用于初次内网部署，**实际投用前务必通过 `MC_LOCAL_PASSWORD` 更换高强度密码并重启 Web**。在 HTTP 内网中密码仍会在传输途中明文可见，跨网段部署应由反向代理提供 HTTPS。该账号为单一管理员身份，不属于多用户 RBAC 系统，不能以此冒充细粒度用户权限管理。

## 内网启用与验证

1. 部署前配置独立的 `MC_TRAIN_DATA_DIR`。生产 A800 和 4070 测试机不要共用同一数据根、SQLite、模型和任务队列。
2. 启动服务前设置强密码：`export MC_LOCAL_USERNAME=jiangjs`、`export MC_LOCAL_PASSWORD='替换为内网强密码'`。不设置时按用户要求使用 `jiangjs/123456`。
3. 浏览器打开 `/login`，默认显示“本地登录”，提交 `provider: local`，不需要畅联云、验证码和外网。
4. 登录后在“算法列表 → 新建本地算法”填写名称、场景与类型；直接进入列表，可以编辑并继续配置训练。验证返回 `source_type=LOCAL`。
5. 如果由旧系统迁入了畅联云配置，在“配置中心 → 平台对接”明确选为 **本地模式**。原有 `mode=external` 会按固定时间表尝试外部同步，无法保证严格零出站；本地新算法不依赖它，但既有外部算法仍是只读。
6. 上传本地 ZIP/原始图像和标注、登记本地 `.pt` 母模型，选择本机/内网 GPU Worker，存储选本地磁盘。`platform_core/training_precision.py` 已禁止训练时静默下载不存在的 `.pt`，缺少母模型会明确失败，**必须事先随离线包提供**。
7. 内网机器需要预装生产 Python wheels（含 torch/ultralytics/OpenCV）、驱动、转换芯片 SDK、前端静态资源和本地模型。可选 OSS、远端 AI 服务、畅联云发布、外部素材 URL 只有在显式配置并使用时才可工作，离线环境不保证这些服务可访问。

## 回归验证范围

- `tests/unit/test_local_login_auth.py`：默认登录、环境变量覆盖、限速、签名会话续期/撤销。
- `tests/unit/test_intranet_algorithm_creation.py`：本地算法与外部只读算法共存、SQL 身份与可修改权限。
- `tests/frontend/intranet-mode-contract.test.mjs` 和 `tests/frontend/changlian-login-ui.test.mjs`：API 无外部拦截、选择器/旧 Logo 消失。
- `tests/browser/changlian-login-auth.spec.mjs`：真实 Chrome 默认本地登录、错误提示、首次创建/列表查询、刷新、退出，以及切换到远程畅联云认证。
- GitHub Actions 既有 `.github/workflows/changlian-login-auth.yml` 同步纳入新增用例。提交后须以准确 SHA 验证其 Python/Chrome 作业，不能把本地无依赖环境当成全绿。

开发侧本地实跑：前端 Node **1498/1498 通过**（排除 4 个当前机器缺少 Uppy/Annotorious 包的测试文件），登录/算法定向前端 8/8 通过，Python 源码编译和独立 `LocalLoginVerifier` 的默认/错误密码试验通过。本机 `pytest`、FastAPI、`filelock` 缺失，故 Python 自动测试与真实 Chrome 未在当前机器执行，后续以 GitHub CI 的准确 SHA 为准。

## 独立内网能力审计及边界

| 领域 | 审计结果 / 仍需验收 |
| --- | --- |
| 登录 | 修复：内网认证不请求云端；原登录 URL、会话 Cookie 和鉴权中间件继续复用 |
| 训练算法主数据 | 修复：新增不需要云产品；本地 SQLite 是唯一主数据存储。外部同步算法继续按照来源权限隔离 |
| 前端资源 | 首页/登录页由 `/static` 本地提供 CSS/JS；不引用外部企业 Logo 或 CDN |
| 外部同步 | 新数据根默认为 `mode=local`、`auto_sync_enabled=false`；**从生产拷贝 external 配置时须人工改回 local**。其他主动外部能力不应在断网下启用 |
| 模型/训练 | 已有离线母模型防下载约束；缺少预置权重、Python wheels、NVIDIA 驱动或本地 GPU Worker 仍可能影响训练，必须在目标机验证 |
| 转换与发布 | 对外厂商 SDK、依赖与 BMRuntime 等不随 Web 代码天然齐全；云端模型服务、OSS、畅联云发布均不是本地训练的前提，但离线不可调用。转换可用性由设备/SDK 实际证据决定 |
| 真正断网验收 | 仍需目标 4070/A800 在断开外网或严格防火墙下做：本地登录→新建算法→导入素材→预检→训练→模型入库→本地评测→退出；检查服务日志/网络连接无意外出站。**未在生产或离线实机执行** |

开发边界：不引入第二个登录中心、算法数据库或请求中心；不创建弹窗嵌套；不修改旧算法版本/GT/正式训练记录。本批仅修复与测试，不将未验证的外部功能宣称为可离线使用。
