# 2026-10-21｜畅联云权重完整详情与 Tags 查询（本地验收通过 / 最终SHA CI待核验）

基线 `22587dd7d4f7550f6634e08a9a2a511f9bc1da89` / VERSION42.24.366；fetch/pull一致、干净工作树，其他会话无同库活动，原D盘WIP不动。上轮26/26 Actions、70/70 Checks独立回执已读取，不替代本轮。正式VERSION本轮一次递增42.24.367，必要main/styles缓存414，原浏览模块import缓存63002；未修改app.js及其413缓存。

## 用户需求、合同与事实来源

原畅联云数据页面每份Weight增加「查看详情」，原产品→版本→Weight结构及手动刷新保留，无全量getInfo预加载。复用 `ChangLianDataBrowserRuntime`、`ChangLianClient`、原provider详情/分页路由及认证/审计，无新Client/API/Repository/Owner/轮询/框架。

用户追加提供的2026-10-21正式OpenAPI明确：`GET /internal/algorithm/algorithm-weight/list` 接收必填pageNum/pageSize及可选productId/analysisId/algoVersionId/computePlatformId/chipCode/fileName/withTags；withTags为query字符串，默认false，要求标签时明确发送`true`。响应为code/msg/data数组/total/reason。**合同已确认，不等于真实生产请求成功。** getInfo未正式声明该参数，DTO说明不能当作请求参数已支持的证据。

原详情路由 `GET /api/v63/external-algorithm-platform/provider/weights/{weight_id}` 新增可选bool withTags，原Client `weight_info(...,with_tags=None)` 默认完全不传；显式传值才使用候选getInfo query，业务/HTTP失败不隐式回退或重试。UI默认普通getInfo，tags字段不存在时才调用原 `/provider/weights/page?pageNum=1&pageSize=50&algoVersionId=完整版本ID&withTags=true`。getInfo明确返回null/[]也属于实际返回，不擅自填本地标签。

只读SSH `ssh -o BatchMode=yes -o ConnectTimeout=8 a800-server pwd` 仍Connection refused，未执行服务器命令；getInfo候选参数实测、正式list生产行为、车辆样本ext_chang_lian_bf868cb214dc7f8d / 345fabc92b7e / 42c43fd314ac及历史17/7回执均NOT VERIFIED。没有修改生产数据库、OSS、Weight、密钥或部署/重启。

## 实现与24字段映射

| 详情分组 | 官方字段 |
|---|---|
| 模型基本信息 | weightId、productId、analysisId、algoVersionId、versionName、versionNo、fileName、yoloVersion、imageWidth、imageHeight |
| 算力环境 | computePlatformId、computePlatformName、computePlatformCode、chipCode |
| 文件属性 | filePath、fileSize、fileSha256 |
| 标签信息 | tags |
| 创建更新 | createBy、createTime、updateBy、updateTime、delFlag |
| 备注 | remark |

原宽版单modal，顶部身份/列表路径/版本/芯片/算力/删除状态，完整24字段分组；640×384组合并保留独立宽高、字节数与易读单位、完整SHA/URL复制、合法HTTP(S)下载；时间按原值显示，不重复换时区。delFlag 0正常/2删除保留原值。缺字段、null、空字符串、[]分别展示；Tags原数组大小写与顺序保留，Car不改为car。未知字段保留在完整原始响应折叠区；原redact递归掩盖Token/Secret/Authorization等键，所有远端字符串HTML转义。仅Provider浏览投影将超安全整数转十进制字符串；Python原Client及发布请求的int64协议不变。

getInfo原始响应与list标签响应分开保存/展示，不将list标签伪装为getInfo返回。按完整WeightID精确匹配，校验返回产品/版本身份；列表与详情基础字段及Tags冲突明确显示各自旧新值，不反写列表。getInfo缺tags才分页，命中后停止；未命中时按total或无total的尾页判断，重复页/重复ID/异常total/提前空页明确报错，1000页安全上限超限报告未完成，不冒充全量。

缓存按刷新epoch/完整WeightID/query/产品版本上下文；同快照成功详情复用，失败不缓存为成功；单请求并发复用、手动刷新失效。单一view委托事件，modal自身单次绑定；详情对象与root归属隔离，切换/关闭/离页/销毁后不能重绘或开始迟到分页。详情关闭保持原展开状态。保存错误只进仍live的详情错误区，不在新页面toast旧错误；只有用户明确重试才再查询。

## 发布读回审查与安全边界

本轮未改外部发布执行/写接口。原 `_confirm_weight_readback` / `_remote_weight_contract_matches` 仍保留Weight唯一身份、原ID、SHA/UNKNOWN保护；确认请求回执不冒充远端Tags，真实未返回字段的 `remote_tags_status=NOT_RETURNED` 与文件交付SYNCED可并存。检查及3项直接相关回归通过，无需为只读详情重构发布或增加自动分页读回负载。没有执行真实add/edit/remove或历史补齐。

## RED→GREEN、测试与UI证据

- 初始Client 7失败/1通过（可选参数不存在、非法ID未拦截），Node新增详情1失败/原2通过；补最小实现后通过。安全URL校验RED1→GREEN；旧请求迟到开始分页与列表差异RED2→GREEN；独立review发现迟到失败toast，新增RED1→GREEN；Tags接口冲突诊断RED1→GREEN。安全断言未删除/降低。
- Python：Client/路由新15项通过；原Client/主数据直接模块81项及发布读回/HTTP仅成功不可SYNCED3项通过；独立现有路由HTTP1项通过。**去重100项**，命令为分批 `pytest tests/unit/test_external_algorithm_platform.py` 对应-k、两项直接发布读回参数化、`tests/api/test_changlian_weight_details.py`。无关训练转换素材清洗未运行。
- Node：原页面Runtime最终23项、必要版本标识9项通过，**32项**。覆盖官方Query/分页/大ID/缓存/重复点击/迟到/失败/null/缺失/[]/冲突/销毁，无轮询或隐式写入。
- Chrome：原手动只读场景1、完整24字段+分页Car+长URL/SHA/XSS/复制/缓存/刷新1、null/缺失/失败重试/关闭迟到/导航返回1，**3个不同场景通过**。完整详情及原手动页面夹具曾在导航初始化前查菜单而超时，补显式高级菜单就绪等待后通过，未放宽功能断言。1366×768/1440×768无内容横溢出，实际截图已查看。隔离协议fixture不是生产/真实SDK证明。
- JUnit、截图、最终CI回执均在既有visualizations目录：`weight-detail-local-tests-20261021.json`、`changlian-weight-details-top.png`、`changlian-weight-details.png`、`weight-detail-ci-final-20261021.json`。最终SHA/Actions/Checks待普通推送后实际核验，禁止借用基线绿色；按既有接续规则独立回执避免自引用文档提交循环。

## 首SHA CI回归与边界修正

首推 `9d2cdd48e49f654b0bb9dad2b8c19eac56a2650e` 实际CI检出共用Client新加int64校验破坏原发布协议测试的兼容性，26项既有wire/历史17项等失败；不是远端故障。严格校验放错层是本轮回归，已修正为**原Provider详情入口在创建Client前拒绝非法int64**，共用Client恢复原默认调用合同，可选with_tags仍保持None时不传query。没有修改任何原发布夹具、断言或Owner。

新增默认Client兼容回归先RED1→GREEN；本轮新加的非法ID断言改在正确的浏览器API边界执行，并加强为连Client创建都不得发生，RED5→GREEN5，不是放松网络安全。仅重验直接受影响的Client9、真实HTTP1及CI明确失败的26项发布协议，全部通过；不重复跑未变化的Node/Chrome。Python最终去重127项（原100 + 新兼容1 + CI直接失败回归26），Node32、Chrome3不变。VERSION367及缓存不二次递增，最终后续SHA CI仍待实际核验。

## 质量审查、修改文件与接续

已直接检查唯一Owner/数据源/API、单次事件绑定/重复请求、缓存/异步归属、ID/HTML/敏感数据及历史安全。独立只读review的P2迟到toast已RED→GREEN关闭，复核无新增明确P2；无新wrapper/Observer/定时器/轮询/业务数据库。原页面全量产品/版本列表水合的既有规模债未扩围重构，新增详情仅按需。本轮不声称全仓无历史技术债。

修改：`platform_core/external_algorithm_platform.py`、`static/modules/changlian-data-browser.js`、`static/main.mjs`、`static/styles.css`、`static/index.html`、`VERSION.txt`；对应Client/API/Node/Chrome及版本断言；本合同目录、Tags专项、CODEX_CURRENT_STATE、AGENTS接续。仅这些直接路径。

本轮精确修改清单：

- `AGENTS.md`
- `VERSION.txt`
- `docs/CHANGLIAN_APIFOX_API_CATALOG.md`
- `docs/CODEX_CURRENT_STATE.md`
- `docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md`
- `platform_core/external_algorithm_platform.py`
- `static/index.html`
- `static/main.mjs`
- `static/modules/changlian-data-browser.js`
- `static/styles.css`
- `tests/browser/changlian-data-browser.spec.mjs`
- `tests/frontend/changlian-data-browser.test.mjs`
- `tests/frontend/version-marker-owner.test.mjs`
- `tests/unit/test_external_algorithm_platform.py`
- `tests/api/test_changlian_weight_details.py`

下一步：最终SHA CI；生产恢复只读连接后用同Weight比较普通getInfo与官方list?withTags=true，记录实际raw/query/ID/Tags/错误并核对网站。getInfo候选参数仍单独NOT VERIFIED，不强制启用。真实历史7项补齐或任何Weight写入、生产部署须单独授权。代码验收与生产读回明确分开。

---

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
analysisId 与 productId 二选一（官方新增身份要求）
versionName（平台保留为稳定幂等身份）
versionNo（可选；有值则发送，无值不阻断创建）
```

平台本地会尽量持久化 `versionNo`，但不会把它误当成新畅联新增接口的强制字段。
幂等恢复时，有 `versionNo` 使用 `versionName + versionNo + analysisId`；无 `versionNo` 时使用
`versionName + analysisId` 唯一恢复，多条候选仍 fail-closed。

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
algoVersionId      # 新增 Weight 必须有
computePlatformId  # 平台业务映射要求
fileName           # 平台交付要求
filePath           # 平台交付要求，长期 OSS/CDN 地址
chipCode           # 官方可选；RKNN/rockchip 等芯片相关产物由平台业务强制要求
```

通用 original 训练模型允许 `chipCode` 为空；平台不得在调用新畅联 API 前因为空
`chipCode` 拒绝 `.pt` 权重。

平台发布流程按“原始模型优先、转换后追加”执行：

```text
本地训练成功
→ original (.pt) 上传模型资产存储
→ 创建/恢复新畅联 Version
→ 创建/恢复 original Weight
→ Version 至少达到 PUBLISHED

随后独立追加：
ONNX / RKNN / TensorRT / Ascend / Sophon / Paddle Inference
→ 各自产物成功且映射可用时追加到同一个 algoVersionId
→ 某个转换未映射或尚未成功，不阻断 original
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


## 10. 主数据同步时效结论

当前完整 31 项 OpenAPI 中没有发现以下能力：

```text
Webhook
事件回调
订阅接口
SSE / WebSocket 推送
算法产品/版本变更通知
消息队列订阅
```

因此新畅联 → 本平台主数据同步目前只能由本平台主动拉取，不能宣称服务端推送式“实时同步”。平台支持：

- 手动立即同步；
- 外部模式自动同步由服务端强制启用，每天按北京时间 08:00、12:00、15:00 各执行一轮 Provider 主数据拉取；
- 后台 Worker heartbeat hook 负责触发固定时段到期检查，Web/API 进程不持有自动同步 daemon timer；
- `auto_sync_due()` 以当天最近一个已到固定时段为真相：同一时段自动同步最多尝试一次；手动立即同步不占用后续固定时段；若 Worker 在时点短暂离线，恢复后补执行当天最近一个尚未执行的时段；
- 远端网络 I/O 使用一次性、FileLock 保护的后台执行，不阻塞 Worker lease heartbeat。

若后续新畅联新增 Webhook/事件订阅文档，应优先升级为事件驱动，并保留定时拉取作为兜底对账。

## 9. 视觉训练与删除安全边界

新畅联分析方式合同定义：

```text
analysisType=1  视觉智能分析
analysisType=2  空置（预留）
analysisType=3  大模型智能分析
status=1        启用
status=0        禁用
```

本平台 YOLO 训练仅允许同时满足 `analysisType=1` 且 `status=1` 的分析方式。任何其他组合（包括字段缺失、空值、analysisType=2/3、status=0，以及仅存在旧本地分析 ID 而缺少这两个字段的明细）都禁止训练；这些分析方式仍可作为远端事实保留在主数据详情中。

算法产品同步默认请求：

```text
productType=3
status=1
```

即仅同步“算法产品 + 上架中”，远端下架后本地历史版本保留并转为不可新训练状态。

远端删除安全边界：

```text
DELETE /api/v63/external-algorithm-platform/provider/versions/{ids}?confirm=true
DELETE /api/v63/external-algorithm-platform/provider/weights/{ids}?confirm=true
```

未显式提供 `confirm=true` 时本平台拒绝远端删除。尤其算法版本删除会由新畅联同时级联删除其下全部权重文件。
