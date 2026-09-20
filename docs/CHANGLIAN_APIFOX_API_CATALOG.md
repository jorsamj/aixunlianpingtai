# 新畅联 Apifox API 契约目录

更新时间：2026-09-20  
来源：用户提供的新畅联官方 Apifox 分享清单  
正式版本边界：`VERSION.txt = 42.24.0`

> 本文件防止平台只接少量接口后误以为“新畅联只有这些接口”，也防止后续开发根据接口名称自行猜 Method / Path。**只有“已绑定”项允许当前代码直接调用；“文档已纳入”项必须先逐页读取对应官方文档，再补 Method、Path、参数、Header、请求体和响应字段。**

当前总数：**31 个官方 Apifox 文档条目**。

状态说明：
- **已绑定**：当前代码已有明确 Method / Path，并已用于主链。
- **文档已纳入**：官方文档来源已登记，但当前代码不猜接口、不自动调用。
- **参考文档**：登录类背景资料，不属于当前机器对机器生产主链。

| # | 分类 | 官方接口文档 | Apifox | 当前绑定 | 状态 |
|---:|---|---|---|---|---|
| 1 | 登录验证 | 登录方法 | [439653047e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/439653047e0.md) | — | 参考文档 |
| 2 | 应用鉴权 | 内部应用鉴权获取Token | [515307570e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307570e0.md) | `POST /internal/auth/token` | 已绑定 |
| 3 | 应用鉴权 | 内部应用签名测试 | [515307571e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307571e0.md) | `POST /internal/auth/test-sign` | 已绑定 |
| 4 | 应用鉴权 | 内部应用登出 | [515307572e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307572e0.md) | — | 文档已纳入 |
| 5 | 算法权重文件管理 | 修改算法权重文件 | [515837707e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837707e0.md) | — | 文档已纳入 |
| 6 | 算法权重文件管理 | 新增算法权重文件 | [515837708e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837708e0.md) | `POST /internal/algorithm/algorithm-weight/add` | 已绑定 |
| 7 | 算法权重文件管理 | 删除算法权重文件 | [515837709e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837709e0.md) | — | 文档已纳入 |
| 8 | 算法权重文件管理 | 查询算法权重文件列表(分页) | [515837710e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837710e0.md) | — | 文档已纳入 |
| 9 | 算法权重文件管理 | 查询某算法版本下全部算法权重文件(含算力环境名称/编号) | [515837711e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837711e0.md) | `GET /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}` | 已绑定 |
| 10 | 算法权重文件管理 | 按算法产品查询算法权重文件(算法调度用) | [515837712e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837712e0.md) | — | 文档已纳入 |
| 11 | 算法权重文件管理 | 查询算法权重文件详细信息 | [515837713e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837713e0.md) | — | 文档已纳入 |
| 12 | 算法版本管理 | 修改算法版本 | [515837714e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837714e0.md) | — | 文档已纳入 |
| 13 | 算法版本管理 | 新增算法版本(analysisId 与 productId 二选一；传 productId 时自动定位该算法产品下的视觉智能分析方式) | [515837715e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837715e0.md) | `POST /internal/algorithm/algorithm-version/add` | 已绑定 |
| 14 | 算法版本管理 | 删除算法版本(同时删除其下全部算法权重文件) | [515837716e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837716e0.md) | — | 文档已纳入 |
| 15 | 算法版本管理 | 查询算法版本列表(分页) | [515837717e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837717e0.md) | — | 文档已纳入 |
| 16 | 算法版本管理 | 查询某算法产品下全部算法版本(含权重文件数量) | [515837718e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837718e0.md) | `GET /internal/algorithm/algorithm-version/listByProduct/{productId}` | 已绑定 |
| 17 | 算法版本管理 | 查询某分析方式下全部算法版本(含权重文件数量) | [515837719e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837719e0.md) | — | 文档已纳入 |
| 18 | 算法版本管理 | 查询算法版本列表(不分页) | [515837720e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837720e0.md) | — | 文档已纳入 |
| 19 | 算法版本管理 | 查询算法版本详细信息 | [515837721e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837721e0.md) | — | 文档已纳入 |
| 20 | 算法产品管理 | 查询算法产品列表(分页) | [515837722e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837722e0.md) | — | 文档已纳入 |
| 21 | 算法产品管理 | 查询算法产品列表(不分页) | [515837723e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837723e0.md) | `GET /internal/algorithm/product-ai/listAll` | 已绑定 |
| 22 | 算法产品管理 | 查询算法产品详细信息 | [515837724e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837724e0.md) | — | 文档已纳入 |
| 23 | 算法产品分析方式管理 | 查询分析方式列表(分页) | [515837725e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837725e0.md) | — | 文档已纳入 |
| 24 | 算法产品分析方式管理 | 查询某算法产品下全部分析方式(含关联明细) | [515837726e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837726e0.md) | `GET /internal/algorithm/algorithm-product-analysis/listByProduct/{productId}` | 已绑定 |
| 25 | 算法产品分析方式管理 | 查询分析方式列表(不分页) | [515837727e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837727e0.md) | — | 文档已纳入 |
| 26 | 算法产品分析方式管理 | 查询分析方式详细信息(含关联明细) | [515837728e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837728e0.md) | — | 文档已纳入 |
| 27 | 算力环境管理 | 查询算力环境列表(分页) | [515837729e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837729e0.md) | — | 文档已纳入 |
| 28 | 算力环境管理 | 查询算力环境列表(不分页) | [515837730e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837730e0.md) | `GET /internal/base/compute-platform/listAll` | 已绑定 |
| 29 | 算法品目管理 | 查询算法品目树(父节点含所有子节点数量) | [515837731e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837731e0.md) | `GET /internal/base/algorithm-category/tree` | 已绑定 |
| 30 | 算法品目管理 | 查询算法品目列表(分页) | [515837732e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837732e0.md) | — | 文档已纳入 |
| 31 | 算法品目管理 | 查询算法品目列表(不分页) | [515837733e0](https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837733e0.md) | — | 文档已纳入 |

## 当前鉴权硬约束

```text
POST /internal/auth/test-sign
→ POST /internal/auth/token
→ data.accessToken
→ 后续业务接口的 Header 必须逐接口遵循各自官方 OpenAPI
```

当前真实联调与官方文档已证明：

- `HTTP 200 + code=0 + msg=操作成功` 是成功，不得把数值 `0` 因 falsy 规则转换为空值。
- `HTTP 200` 不等于业务成功；例如 `code=99999` 必须作为业务失败，并保留远端 `msg`。
- **不得再把某一个接口的鉴权 Header 推广成全部内部接口的统一规则。**
- 官方文档 `515837723e0`（查询算法产品列表，不分页）明确路径为 `GET /internal/algorithm/product-ai/listAll`，并声明请求头 `Authorization`，示例值 `Bearer {{access_token}}`。
- 该产品列表接口的 Query 参数（如 `productType`、`productName`、`categoryId` 等）在 OpenAPI 中均为非必填；因此“空 Query”本身不是本次 `99999` 的合同错误。
- “内部应用登出”页面提到 `Access-Token`，只能说明该登出接口的合同，不能据此推断所有算法业务接口都使用 `Access-Token`。

## 当前已绑定的生产主链

```text
POST /internal/auth/test-sign
POST /internal/auth/token
GET  /internal/base/algorithm-category/tree
GET  /internal/base/compute-platform/listAll
GET  /internal/algorithm/product-ai/listAll
GET  /internal/algorithm/algorithm-product-analysis/listByProduct/{productId}
POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}
POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
```

## 接口测试边界

“测试连接”只允许执行：

```text
鉴权
算法品目查询
算法产品查询
算力环境查询
产品分析方式查询
```

测试连接**不得**自动执行新增、修改、删除算法版本或权重等有副作用接口。

其余 CRUD / 分页 / 详情 / 删除 / 修改接口必须以表中对应 Apifox 原文为准后再进入代码。不得因为现有命名模式看起来像 `/update`、`/delete`、`/page` 就直接实现。
