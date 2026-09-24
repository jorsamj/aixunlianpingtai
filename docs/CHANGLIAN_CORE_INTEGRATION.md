# 畅联云核心对接契约与手动验收主线

更新时间：2026-09-19  
分支：`feature/external-algorithm-publishing`  
正式版本：`VERSION.txt = 42.24.0`

> 本文只定义畅联云与算法训练平台当前最重要的生产主链。开始开发或联调前仍必须先读取 GitHub 远端真实 HEAD。

## 1. 当前产品边界

当前优先级是**手动闭环真实可用**，不是自动迭代或自动发布。

主流程：

```text
配置 Base URL / AccessKey / AccessSecret
→ 测试连接
→ 手动同步品目 / 算法产品 / 分析方式 / 算力环境
→ 使用畅联云同步进来的算法手动训练
→ 独立评测
→ 手动模型转换
→ 手动“同步到新畅联”
→ 新增算法版本
→ 登记转换权重
→ 回到畅联云核验版本、算力环境、芯片与文件
```

自动同步、自动发布代码可以保留，但第一阶段不是验收门槛；自动迭代 / 自动训练继续 Deferred。

## 2. 应用鉴权

训练平台长期调用畅联云内部接口使用应用凭据，不依赖人员每次登录畅联云网页。

### 2.1 签名联调桥

```text
POST /internal/auth/test-sign
query:
  access_key
  access_secret
```

返回核心字段：

```text
timestamp
nonce
signature
```

注意：

- 这是联调辅助接口。
- 当前平台使用 `auth_mode=test_sign_bridge`。
- `AccessSecret` 不允许写入公开配置或交互日志。
- 待畅联云提供正式签名算法完整规范后，再切换为平台本地生成 timestamp / nonce / signature。

### 2.2 获取 Token

```text
POST /internal/auth/token

Headers:
Access-Key
Timestamp
Nonce
Signature
```

响应核心字段：

```text
data.accessToken
data.tokenType
data.expiresIn
```

用户提供的完整 OpenAPI 汇编已经覆盖全部内部算法相关接口。正式合同为：

```text
Authorization: Bearer <accessToken>
```

该 Header 用于品目、产品、分析方式、算力环境、算法版本、算法权重以及内部应用登出。登出描述中的“Access-Token”是令牌语义，不是 HTTP Header 名。Token 获取仍使用 Access-Key / Timestamp / Nonce / Signature。

平台允许在“配置中心 → 平台对接”手工填写 Base URL、AccessKey、AccessSecret。测试连接使用当前页面草稿，不要求先保存；保存后的 AccessSecret 不回传浏览器明文。

## 2.3 完整 Apifox 接口目录

用户提供的 31 个新畅联官方 Apifox 文档条目已完整登记：

```text
docs/CHANGLIAN_APIFOX_API_CATALOG.md
```

完整汇编中的 31 个接口已经逐项读取；除人员网页登录 `POST /login` 仅作参考外，其余 30 个内部接口均已进入 Provider contract。版本/权重的新增、修改、删除、分页、按产品/分析方式/版本查询和详情接口全部有正式 Method / Path。

“测试连接”只执行鉴权和只读查询，不会用测试动作去新增、修改或删除畅联云数据。

## 3. 主数据同步必需接口

| 能力 | Method | Path | 本平台用途 |
|---|---|---|---|
| 算法品目树 | GET | `/internal/base/category/tree` | 品目同步、算法筛选 |
| 算法产品列表 | GET | `/internal/algorithm/product-ai/listAll` | 算法主数据同步 |
| 产品分析方式 | GET | `/internal/algorithm/algorithm-analysis/listByProduct/{productId}` | 冻结训练对应 analysisId |
| 算力环境列表 | GET | `/internal/base/compute-platform/listAll` | 转换产物发布映射 |

同步后的核心身份必须长期保存：

```text
external_product_id
external_analysis_id / external_analysis_ids
external_category_id
external_compute_platform_ids
provider_type = CHANG_LIAN
source_type = EXTERNAL
```

畅联云主数据在训练平台中只读；畅联云不再返回的算法只标记 inactive，不删除历史训练版本。

### 3.1 Internal API 命名空间与旧配置迁移

当前正式内部接口按模块命名空间固定：

```text
/internal/auth/*       应用鉴权
/internal/base/*       基础信息（算法品目、算力环境）
/internal/algorithm/*  算法产品、分析方式、版本、权重
```

平台不再把这些 Provider endpoint 暴露给普通用户编辑。历史版本曾保存的旧裸路径（例如 `/compute-platform/listAll`）仅在与平台已知旧值完全匹配时自动迁移到正式 internal 路径；其他自定义路径不强制覆盖。

## 3.2 视觉分析训练边界

完整 OpenAPI 明确：`analysisType=1` 为视觉智能分析，`analysisType=3` 为大模型智能分析，且 `status=1/0` 表示启用/禁用。

本训练平台的 YOLO 训练只允许绑定：

```text
analysisType = 1
status = 1
```

同步仍保留产品下全部分析方式作为远端事实，但训练资格必须由分析明细同时证明 `analysisType=1` 且 `status=1`。字段缺失、空值、预留类型、大模型类型、禁用状态，以及仅有旧 `external_analysis_ids` 无明细佐证时全部 fail closed。

## 4. 训练身份

若一个算法产品只有一个分析方式，可以使用其默认 analysisId。

若有多个分析方式，创建训练任务时必须明确选择；后端必须验证所选 analysisId 属于当前 productId。

训练完成后的 Algorithm Version 必须保留真实 product / analysis provenance，发布时不得重新猜测来源。

## 5. 训练成果发布必需接口

### 5.1 新增算法版本

```text
POST /internal/algorithm/algorithm-version/add
```

当前核心 payload：

```text
versionName
versionNo
analysisId 或 productId（二选一）
```

当训练已经绑定明确 analysisId 时，优先发送 analysisId。

幂等恢复：

```text
GET /internal/algorithm/algorithm-version/listByProduct/{productId}
```

请求超时后必须先反查已存在版本，不能盲目重复创建。

### 5.2 新增算法权重

```text
POST /internal/algorithm/algorithm-weight/add
```

当前核心 payload：

```text
algoVersionId
computePlatformId
chipCode
fileName
filePath
```

幂等恢复：

```text
GET /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

权重反查至少使用：

```text
fileName
computePlatformId
chipCode
```

避免网络超时后重复登记。

### 5.3 完整版本 / 权重管理接口

除发布主链使用的“新增 + 幂等反查”外，Provider 已完整实现：

```text
版本：
POST /internal/algorithm/algorithm-version/edit
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/remove/{algoVersionIds}
GET  /internal/algorithm/algorithm-version/list
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
GET  /internal/algorithm/algorithm-version/listByAnalysis/{analysisId}
GET  /internal/algorithm/algorithm-version/listAll
GET  /internal/algorithm/algorithm-version/getInfo/{algoVersionId}

权重：
POST /internal/algorithm/algorithm-weight/edit
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/remove/{weightIds}
GET  /internal/algorithm/algorithm-weight/list
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
GET  /internal/algorithm/algorithm-weight/listByProduct/{productId}
GET  /internal/algorithm/algorithm-weight/getInfo/{weightId}
```

删除版本会按新畅联合同同时删除该版本下全部权重，因此删除只允许显式管理调用，不参与测试连接、主数据同步或自动诊断。

## 6. 模型文件与转换结果

畅联云只登记模型文件的业务信息和可访问地址，不接受本机路径作为正式交付。

```text
TRAINING / CONVERSION artifact
→ Model Artifact Storage
→ SHA256 / size 校验
→ 稳定下载入口
→ algorithm-weight filePath
```

当前瑞芯微第一阶段正式目标：

```text
RK3568
RK3576
```

转换完成不等于板端验证完成；真实硬件状态必须来自 RKNN board runtime server-confirm。

## 7. 配置页第一阶段 UX

普通用户主路径固定为：

```text
1. 填写 Base URL / AccessKey / AccessSecret
2. 测试连接
3. 保存配置
4. 立即同步
```

“测试连接”至少检查：

```text
应用鉴权
算法品目
算法产品
算力环境
产品分析方式（存在可测试产品时）
```

外部模式下自动同步和自动发布由服务端强制启用：主数据每天按北京时间 08:00、12:00、15:00 各拉取一轮，训练成功后的原始模型及后续转换产物自动进入交付链。页面只展示自动同步/自动发布状态，不提供关闭开关或同步间隔选择；“立即同步”保留为用户主动提前触发一次主数据对账的操作，且不会占用后续固定自动同步时段。

## 8. 当前验收状态

软件 contract 已覆盖：

- Secret 安全存储与不回显；
- draft 凭据测试不先保存；
- test-sign query contract；
- Token + `Authorization: Bearer <accessToken>` 业务调用链；
- 品目 / 产品 / 分析方式 / 算力环境同步；
- external product / analysis 训练绑定；
- Algorithm Version 创建；
- Algorithm Weight 创建；
- 版本 / 权重超时后反查恢复；
- 模型资产存储；
- RK3568 / RK3576 产品示例。

**仍未 CLOSED：真实畅联云生产/联调环境 E2E。**

最终必须使用真实 Base URL、AccessKey、AccessSecret、真实畅联云 Product/Analysis/ComputePlatform 和真实算法产物存储跑通：

```text
保存配置 / 测试连接
→ 立即同步，并分别观察北京时间 08:00 / 12:00 / 15:00 固定自动同步
→ 绑定真实 Product / Analysis 创建训练
→ 训练成功
→ 原始模型自动归档 OSS，并保存稳定 public_url
→ 自动创建/恢复畅联云 Algorithm Version
→ 自动创建/恢复原始模型 Algorithm Weight
→ ONNX / RKNN 转换完成
→ 转换产物自动归档 OSS
→ 复用同一 algoVersionId 追加转换权重
→ 畅联云侧核验版本、权重与 filePath
```

破坏性删除需在可控测试数据上单独验证 `algorithm-version/remove` 的真实副作用；远端删除结果不确定时本地必须保持 fail-closed。

在这条链实际完成前，不得把“畅联云对接可用”标记为 CLOSED。


---

<!-- CHANGLIAN_LIVE_DEPLOYMENT_2026_09_20 -->
## 9. 2026-09-20 Live Deployment / Codex Handoff

本节记录**当前运行现场**，用于新会话 / Codex 直接接手；接口业务契约仍以前文为准。

本次 Live Handoff 记录的代码 HEAD（文档提交前）：`02645ecd48e1e2200da70dabb36c3ce79c3ebdb8`

当前正式版本：`VERSION.txt = 42.24.0`

上述代码 HEAD 的 Actions 快照（2026-09-20 14:41 +08:00 核对）：
- total: 18
- queued: 18
- in_progress: 0
- completed success: 0
- completed non-success: 0
- **queued != passed；在当前 HEAD 的永久 workflow 实际完成前，不得写“全绿”。**

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

业务接口鉴权 Header 以各自官方 OpenAPI 为准；算法产品 `listAll` 已确认使用 `Authorization: Bearer <accessToken>`。

### 当前真实验收门槛

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

### 部署回滚边界

现有 `/data/platform/releases/ea1b6f198f81` 是当前可回滚版本。部署当前代码时必须新建 release 目录，再原子切换 `/data/platform/current`；不得覆盖旧 release。健康检查使用真实生产接口：

```text
GET /api/health
```

只有真实环境完成以下链路后，才能把本文件第 8 节的 live E2E 标为 CLOSED：

```text
保存配置
→ 测试连接
→ 手动同步
→ 训练绑定真实 Product / Analysis
→ Evaluation
→ Conversion
→ 手动发布 Algorithm Version / Weight
→ 畅联云侧核验
```
