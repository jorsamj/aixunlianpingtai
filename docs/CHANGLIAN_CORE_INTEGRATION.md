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

后续业务接口：

```text
Authorization: Bearer <accessToken>
```

平台允许在“配置中心 → 平台对接”手工填写 Base URL、AccessKey、AccessSecret。测试连接使用当前页面草稿，不要求先保存；保存后的 AccessSecret 不回传浏览器明文。

## 3. 主数据同步必需接口

| 能力 | Method | Path | 本平台用途 |
|---|---|---|---|
| 算法品目树 | GET | `/algorithm-category/tree` | 品目同步、算法筛选 |
| 算法产品列表 | GET | `/algorithm-product/listAll` | 算法主数据同步 |
| 产品分析方式 | GET | `/algorithm-product-analysis/listByProduct/{productId}` | 冻结训练对应 analysisId |
| 算力环境列表 | GET | `/compute-platform/listAll` | 转换产物发布映射 |

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

## 4. 训练身份

若一个算法产品只有一个分析方式，可以使用其默认 analysisId。

若有多个分析方式，创建训练任务时必须明确选择；后端必须验证所选 analysisId 属于当前 productId。

训练完成后的 Algorithm Version 必须保留真实 product / analysis provenance，发布时不得重新猜测来源。

## 5. 训练成果发布必需接口

### 5.1 新增算法版本

```text
POST /algorithm-version/add
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
GET /algorithm-version/listByProduct/{productId}
```

请求超时后必须先反查已存在版本，不能盲目重复创建。

### 5.2 新增算法权重

```text
POST /algorithm-weight/add
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
GET /algorithm-weight/listByVersion/{algoVersionId}
```

权重反查至少使用：

```text
fileName
computePlatformId
chipCode
```

避免网络超时后重复登记。

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

自动同步 / 自动发布放在高级设置，不作为第一阶段主操作。

## 8. 当前验收状态

软件 contract 已覆盖：

- Secret 安全存储与不回显；
- draft 凭据测试不先保存；
- test-sign query contract；
- Token / Bearer 调用链；
- 品目 / 产品 / 分析方式 / 算力环境同步；
- external product / analysis 训练绑定；
- Algorithm Version 创建；
- Algorithm Weight 创建；
- 版本 / 权重超时后反查恢复；
- 模型资产存储；
- RK3568 / RK3576 产品示例。

**仍未 CLOSED：真实畅联云生产/联调环境 E2E。**

最终必须使用真实 Base URL、AccessKey、AccessSecret 和真实畅联云 Product/Analysis/ComputePlatform 跑通：

```text
连接 → 手动同步 → 畅联云算法训练 → 评测 → 转换 → 手动发布 → 畅联云核验版本与权重
```

在这条链实际完成前，不得把“畅联云对接可用”标记为 CLOSED。
