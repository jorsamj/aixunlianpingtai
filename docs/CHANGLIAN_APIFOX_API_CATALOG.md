# 新畅联官方 OpenAPI 契约目录

更新时间：2026-09-20  
来源：用户提供的《新畅联 接口文档汇编》完整 OpenAPI 规范  
正式版本边界：`VERSION.txt = 42.24.0`

## 1. 当前结论

本仓库不再根据接口名称猜 Path/Header。用户提供的汇编已经给出 31 个接口的正式 Method / Path / 参数 / Schema，因此当前 Provider contract 以该汇编为准：

- 31 个接口条目全部登记。
- 其中人员 `POST /login` 只作参考，不参与训练平台机器对机器主链。
- 其余 **30 个内部接口已进入 ChangLian Provider contract**。
- 内部业务查询/版本/权重接口按 OpenAPI 使用 `Authorization: Bearer <accessToken>`。
- `test-sign → token` 仍是当前应用凭据换 Token 链；Token 请求使用 Access-Key / Timestamp / Nonce / Signature。
- 测试连接只运行鉴权和只读查询，不执行新增、修改、删除。

## 2. 完整接口矩阵

| # | 分组 | 接口 | Method | Path | 当前状态 |
|---:|---|---|---|---|---|
| 1 | 登录验证 | 登录方法 | POST | `/login` | 参考（人员登录，不参与机器发布主链） |
| 2 | 应用鉴权 | 内部应用鉴权获取Token | POST | `/internal/auth/token` | 已接入 |
| 3 | 应用鉴权 | 内部应用签名测试 | POST | `/internal/auth/test-sign` | 已接入 |
| 4 | 应用鉴权 | 内部应用登出 | POST | `/internal/auth/logout` | 已接入 |
| 5 | 算法权重文件管理 | 修改算法权重文件 | POST | `/internal/algorithm/algorithm-weight/edit` | 已接入 |
| 6 | 算法权重文件管理 | 新增算法权重文件 | POST | `/internal/algorithm/algorithm-weight/add` | 已接入 |
| 7 | 算法权重文件管理 | 删除算法权重文件 | GET | `/internal/algorithm/algorithm-weight/remove/{weightIds}` | 已接入 |
| 8 | 算法权重文件管理 | 查询算法权重文件列表(分页) | GET | `/internal/algorithm/algorithm-weight/list` | 已接入 |
| 9 | 算法权重文件管理 | 查询某算法版本下全部算法权重文件 | GET | `/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}` | 已接入 |
| 10 | 算法权重文件管理 | 按算法产品查询算法权重文件 | GET | `/internal/algorithm/algorithm-weight/listByProduct/{productId}` | 已接入 |
| 11 | 算法权重文件管理 | 查询算法权重文件详细信息 | GET | `/internal/algorithm/algorithm-weight/getInfo/{weightId}` | 已接入 |
| 12 | 算法版本管理 | 修改算法版本 | POST | `/internal/algorithm/algorithm-version/edit` | 已接入 |
| 13 | 算法版本管理 | 新增算法版本 | POST | `/internal/algorithm/algorithm-version/add` | 已接入 |
| 14 | 算法版本管理 | 删除算法版本 | GET | `/internal/algorithm/algorithm-version/remove/{algoVersionIds}` | 已接入 |
| 15 | 算法版本管理 | 查询算法版本列表(分页) | GET | `/internal/algorithm/algorithm-version/list` | 已接入 |
| 16 | 算法版本管理 | 查询某算法产品下全部算法版本 | GET | `/internal/algorithm/algorithm-version/listByProduct/{productId}` | 已接入 |
| 17 | 算法版本管理 | 查询某分析方式下全部算法版本 | GET | `/internal/algorithm/algorithm-version/listByAnalysis/{analysisId}` | 已接入 |
| 18 | 算法版本管理 | 查询算法版本列表(不分页) | GET | `/internal/algorithm/algorithm-version/listAll` | 已接入 |
| 19 | 算法版本管理 | 查询算法版本详细信息 | GET | `/internal/algorithm/algorithm-version/getInfo/{algoVersionId}` | 已接入 |
| 20 | 算法产品管理 | 查询算法产品列表(分页) | GET | `/internal/algorithm/product-ai/list` | 已接入 |
| 21 | 算法产品管理 | 查询算法产品列表(不分页) | GET | `/internal/algorithm/product-ai/listAll` | 已接入 |
| 22 | 算法产品管理 | 查询算法产品详细信息 | GET | `/internal/algorithm/product-ai/getInfo/{productId}` | 已接入 |
| 23 | 算法产品分析方式管理 | 查询分析方式列表(分页) | GET | `/internal/algorithm/algorithm-analysis/list` | 已接入 |
| 24 | 算法产品分析方式管理 | 查询某算法产品下全部分析方式 | GET | `/internal/algorithm/algorithm-analysis/listByProduct/{productId}` | 已接入 |
| 25 | 算法产品分析方式管理 | 查询分析方式列表(不分页) | GET | `/internal/algorithm/algorithm-analysis/listAll` | 已接入 |
| 26 | 算法产品分析方式管理 | 查询分析方式详细信息 | GET | `/internal/algorithm/algorithm-analysis/getInfo/{analysisId}` | 已接入 |
| 27 | 算力环境管理 | 查询算力环境列表(分页) | GET | `/internal/base/compute-platform/list` | 已接入 |
| 28 | 算力环境管理 | 查询算力环境列表(不分页) | GET | `/internal/base/compute-platform/listAll` | 已接入 |
| 29 | 算法品目管理 | 查询算法品目树 | GET | `/internal/base/category/tree` | 已接入 |
| 30 | 算法品目管理 | 查询算法品目列表(分页) | GET | `/internal/base/category/list` | 已接入 |
| 31 | 算法品目管理 | 查询算法品目列表(不分页) | GET | `/internal/base/category/listAll` | 已接入 |

## 3. 算法版本正式合同

平台已实现：

```text
POST /internal/algorithm/algorithm-version/edit
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/remove/{algoVersionIds}
GET  /internal/algorithm/algorithm-version/list
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
GET  /internal/algorithm/algorithm-version/listByAnalysis/{analysisId}
GET  /internal/algorithm/algorithm-version/listAll
GET  /internal/algorithm/algorithm-version/getInfo/{algoVersionId}
```

新增版本 payload：

```text
analysisId 与 productId 二选一
versionName
versionNo
```

修改版本时 `algoVersionId` 必填。

删除版本是**破坏性操作**，新畅联合同明确会同时删除该版本下全部算法权重，因此平台只提供显式管理 API；测试连接、主数据同步、自动诊断不得调用删除。

## 4. 算法权重正式合同

平台已实现：

```text
POST /internal/algorithm/algorithm-weight/edit
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/remove/{weightIds}
GET  /internal/algorithm/algorithm-weight/list
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
GET  /internal/algorithm/algorithm-weight/listByProduct/{productId}
GET  /internal/algorithm/algorithm-weight/getInfo/{weightId}
```

新增权重发布 payload：

```text
algoVersionId
computePlatformId
chipCode
fileName
filePath
```

平台发布流程继续坚持：

```text
本地训练版本
→ 转换产物
→ 模型资产存储
→ 稳定 public URL
→ 创建/恢复远端算法版本
→ 新增/恢复远端算法权重
→ 写回 external_algo_version_id / external_weight_id
```

## 5. 发布幂等与官方返回值

官方新增版本、权重接口的响应 `data` 是整数 ID。当前代码同时支持：

```json
{"code":0,"data":501}
```

以及历史兼容对象形态，不再因为 `data` 为标量而误判“没有 algoVersionId / weightId”。

网络结果未知时：

- 算法版本：按 `productId` 反查版本，并结合 `versionName/versionNo/analysisId` 恢复。
- 算法权重：按 `algoVersionId` 反查权重，并用 `fileName + computePlatformId + chipCode` 匹配。
- UNKNOWN 状态下禁止盲目重复创建。

## 6. 主数据正式路径

完整文档纠正了此前两条旧路径：

```text
算法品目:
旧 /internal/base/algorithm-category/tree
新 /internal/base/category/tree

分析方式:
旧 /internal/algorithm/algorithm-product-analysis/listByProduct/{productId}
新 /internal/algorithm/algorithm-analysis/listByProduct/{productId}
```

旧配置只在命中已知历史值时自动迁移；普通用户不编辑 Provider endpoint。

## 7. 本平台 Provider 管理 API

后端现在提供受控 Provider API：

```text
/api/v63/external-algorithm-platform/provider/categories/*
/api/v63/external-algorithm-platform/provider/products/*
/api/v63/external-algorithm-platform/provider/analyses/*
/api/v63/external-algorithm-platform/provider/compute-platforms/*
/api/v63/external-algorithm-platform/provider/versions/*
/api/v63/external-algorithm-platform/provider/weights/*
```

版本/权重新增、修改、删除必须显式调用。连接测试和联调诊断只读。

## 8. 测试连接范围

只读测试顺序：

```text
test-sign
→ token
→ 算法品目
→ 算法产品(productType=3)
→ 算力环境
→ 首个算法产品分析方式
→ 首个算法产品版本
→ 首个算法版本权重
```

没有产品/版本时对应步骤标记 skipped，而不是制造假数据进行测试。
