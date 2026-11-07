# 42.24.531｜平台对接总开关、内网独立模式出站保护与登录安全补缺

日期：2026-11-04。仓库：`jorsamj/aixunlianpingtai`。唯一分支：`feature/external-algorithm-publishing`。基线：42.24.530（远端等价树）。**生产数据、正式 GT、已训练权重和实际运行服务未修改，本轮不部署。**

## 本轮已编码

| 核查项 | 原有状态 | 本轮修复与真实边界 |
| --- | --- | --- |
| 平台对接模式 | 存在 `config.mode=local/external`，但仅藏在「连接配置」中的单选框，关闭前还可能被配置锁挡住 | 「平台对接」顶部增加唯一的、无需进入编辑态的总开关，明确显示“独立部署模式”/“外部平台对接模式”；通过原仓库 `PUT /api/v63/external-algorithm-platform/mode` 原子更新，前后端读写同一 `mode`，没有第二套配置库或弹窗 |
| 旧配置遗留 | 只要 `mode=external`，后台定时同步与自动发布会按旧地址和凭据继续执行；某些手动接口即使 mode 为 local 仍可调用外部服务 | 升级前拷贝来的旧 `mode=external` 配置若没有新的 `mode_confirmed_at`，**生效模式安全降为 local，等管理员显式打开总开关才允许出站**；连接测试、诊断、所有 `/provider/*` 路由从服务端拒绝；预先建好的真实 `ChangLianClient` 在**每个 HTTP 请求前**复核当前开关；已有发布客户端同样复核，发布上传起点也加模式检查；旧浏览器表单保存配置也不能覆盖总开关状态 |
| 旧清理任务 | Worker 心跳在判断同步计划前仍派发旧外部产品清理 outbox | 总开关关闭时暂缓后台外部清理 outbox 派发，保留已提交持久意图以供后续人工核验/重新开启；未清理、未删除正式数据 |
| 配置保留 | 管理员担心关闭后丢失 API 地址与凭据 | 切换只改 `mode`、`auto_sync_enabled`、`auto_publish_enabled` 和时间戳，保留已存地址、凭据引用、接口定义、历史；切回 external 需要检查凭据及连通性，系统不伪称已连接 |
| 原始浏览器 CORS | `allow_origins=['*']` 搭配 `allow_credentials=True` | 默认只允许同源浏览器调用；跨源部署通过 `MC_CORS_ALLOWED_ORIGINS` 显式列出来源，明确 Method/Header，避免泛域带 Cookie |
| 本地密码轮换 | 有效期内签名 Cookie 未绑定本地密码版本 | 本地 session 带持久签名密钥 HMAC 派生的 opaque `credential_revision`；每次会话认证复核当前密码，轮换后旧本地 Cookie 不再被接受；远端登录 session 不受影响，续期保留版本，重启但密码不变可延续 |
| 本地登录限流 | 只在旧记录超时后清理，4096 个活跃 IP 仍可能无上界增加 | 失败记录固定 4096 上限，最久未用项逐出；原 8 次/60 秒限速不变 |
| CI 现有两项 Chrome 误断言 | 530 原登录测试在切换远端提供商后仍期待高级区域隐藏，算法入口测试仍期待旧“新建算法”文案 | 回归更新为真实当前可见状态和“新建本地算法”文案，同时新增总开关前端/后端/浏览器测试 |

## 运行语义与出站边界

**总开关关闭（独立部署，持久 `mode=local`）：**

1. Web 与 Worker 不会因已保存的新畅联地址/凭据而自行发起主数据同步或版本/权重发布；缓存、同步历史及本地算法继续可读。
2. 新畅联 provider 专用 API、人工连接测试、联调诊断收到 `409 EXTERNAL_PLATFORM_NOT_ACTIVE`，不触发外部请求。
3. 先前构造的真实 provider Client 在下一次鉴权/业务 HTTP 前重新读取 mode；并发时**已经实际发出的网络请求无法倒流或强制撤回**，需要结合防火墙做严格零出站验收。
4. 原持久外部清理意图暂时不派发、未删除，避免独立部署时误清理迁入数据。
5. 现有本地算法创建、上传素材、YOLO 训练、本地评测与本地模型管理不需要对接开关。
6. **升级迁移行为**：旧 config.json 即使存着 `mode=external`，只要没有本版主动启用证据 `mode_confirmed_at`，也按 local 执行；不改动旧文件字节和凭据。原来确实需要对接的生产实例在升级后，管理员必须明确开启一次总开关，不能期待旧任务自行恢复。这是有意的离线安全优先选择。

**总开关开启（`mode=external`）：**

恢复已有新畅联 Provider 对接与固定北京时间 08/12/15 时主数据同步，以及符合原有发布条件的训练/转换结果自动发布。当前实际实现的 Provider 仍为新畅联；页面不虚假宣称已经完成其他平台协议适配。若未配置有效地址与 Secret，则状态仍为“待配置”，不能同步。

**明确不在这个开关覆盖范围内的独立网络能力：** 可选远程训练/转换 Worker（通常为内网节点）、OSS/对象存储、独立 AI 标注或推理 API、外部 URL 素材导入、远端模型下载、用户显式选择的畅联云人员登录。这些分别有自己的存储/资源/导入/登录配置；**关闭对接开关不等于全机断网或操作系统级网络防火墙**。若目标 4070 完全无互联网，应选择本地存储与本地模型，禁用或不配置对应远端服务，并在网络层限制出站，避免依赖误报为“已隔离”。

## 验收证据

- Python 源码 `compileall`：已通过。
- `tests/frontend/external-algorithm-platform.test.mjs`、`tests/frontend/intranet-mode-contract.test.mjs`：30/30 通过。
- `tests/unit/test_external_algorithm_platform.py`：新增关闭后已创建客户端、草稿测试与诊断均不可发起请求；重新打开保留地址/密钥、损坏配置不可覆盖。
- `tests/unit/test_external_algorithm_auto_sync.py`：新增独立模式不派发旧清理 outbox 的回归。
- `tests/unit/test_local_login_auth.py`：新增重启/换密签名凭据版本与限流记录硬上限回归。
- `tests/browser/external-algorithm-platform.spec.mjs`：新增总开关启闭、按钮禁用、原配置保留且仅调用 mode API 的交互回归。
- 本地缺 `pytest`/FastAPI/filelock/requests，以及部分 Uppy 依赖；**上述新增 Python、完整 Chrome、GitHub 新 SHA CI 待真实执行**。不得把静态核对等同生产网络验收。

## 部署提示与回滚

1. 4070 或其他内网机器更新代码后，使用本地 `jiangjs` 管理员登录；正式环境先设置强 `MC_LOCAL_PASSWORD`。
2. 进入 **平台对接 → 总开关**，确认显示“独立部署模式／已关闭”，刷新页面后再次确认。原 API 地址和凭据不用清除。
3. 如果浏览器前端与 API 反向代理不同源，设置 `MC_CORS_ALLOWED_ORIGINS=https://实际前端域名`（多个以英文逗号分隔；**不允许 `*`**），重启 Web。
4. 在完全隔离的网络上执行本地登录、新建算法、素材导入、训练、模型版本、场景实测，抓取 Web/Worker 的出站目标，确认没有新畅联流量，同时复查可选远端功能。
5. 恢复对接时管理员主动打开总开关并复测新畅联连接、同步与发布，**不能默认重放旧同步或清理任务无害**，先查看历史与待办状态。

本轮仅在唯一长期开发分支进行代码与测试变更，不 merge main、不 release、不 force push、不修改正式业务数据。
