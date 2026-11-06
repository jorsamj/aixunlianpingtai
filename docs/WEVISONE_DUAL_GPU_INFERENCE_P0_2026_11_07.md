# WeVisOne 双实例与跨 Provider 安全推理｜42.24.556

状态：平台侧开发与隔离验收；4070 内网、生产部署与 GPU 吞吐 **NOT VERIFIED**。
起点：长期分支 `feature/external-algorithm-publishing`，42.24.552，
`34a287efee0d1f35fb9e818fb90acb898f00dad1`；起点准确 Actions 41 success。
开发使用原隔离克隆，未覆盖两个已有 WIP 工作区。没有登录或修改 A800、4070，
没有改生产数据、模型、服务、Nginx 或启动参数。

## 需求、现状与缺口

已有：548 审核工作台、逐图失败诊断、差量重试、草稿 CAS、负样本转入/撤销，
以及 Worker Lease / generation fence、CandidateStore 唯一候选存储、人工确认后正式 GT。
本轮没有重建任何一项。552 素材库及 ZIP 流程保持原所有权。

原执行器逐图串行，恢复要求候选按输入形成严格前缀；把线程数直接改为 2 会破坏该前提。
原 Provider 未统一区分临时限流/账户额度，确定性请求协议错误不在批次快停集合中。
原调度按模型配置资源串行任务，但不同配置指向同一服务/账户没有逐请求共享容量约束。

| 需求 | 接入位置 | 本轮结果 |
| --- | --- | --- |
| 配置冻结、缺证据串行 | annotation_runtime / inference_policy | 服务器运维证据绑定规范化配置指纹及期限；浏览器不能授信 |
| 双实例有界推理 | run_ai_annotation / annotation_inference | 最大在途窗口取冻结策略；默认 1，可信配置上限 8，双 2B 配置为 2 |
| 多任务、多进程共享 | 原 TaskRepository SQLite | 同库短事务层级许可、共享 RPM/冷却；保留原任务调度及资源键 |
| 乱序恢复 | 原 CandidateStore.generation_state | 按 image_id 集合及冻结顺序摘要恢复；成功/空检出不重做 |
| GT 与租约安全 | 原 write_session / WorkerContext | 主线程唯一候选写入；提交前原 fence；推理不写 GT |
| 失败与重试 | 原 ProviderRequestError / 原任务详情 | HTTP 分类、Retry-After、受控尝试、逐图追踪；不跨模型回退 |
| 配置与审核入口 | 原模型弹窗、任务详情、诊断抽屉 | 中文容量状态、按需检查、执行指标、实际请求/实例标识 |

## 执行与一致性合同

网络调用在数据库事务之外。线程只处理各自图片、生成结果；协调线程通过原
CandidateStore.write_session 的逐图短事务写入，再写 Checkpoint。候选先提交而
Checkpoint 未更新时，以候选数据库为准。新 generation_state 允许乱序，校验全部
ID/status 与不可变输入摘要；原 generation_prefix 保留，历史调用与测试不被删除。
失败续跑迭代器与派发窗口有界，不一次解码并排队所有失败图片。

取消立即停止派发和重试；已在途 HTTP 的容量许可仍由实际调用线程持有，返回后释放。
迟到结果没有候选/GT 写入路径。Worker 失租或容量续约无法确认时，不发布结果。
硬错误停止后，已在途的有效结果仍经同一受控写入器保存，真实失败证据不会被误吞。

原 TaskRepository Schema 3 → 4 为**同一数据库的增量表**：inference_permits 与
inference_domain_state；没有新数据库、任务引擎、调度中心或前端请求中心。
许可按实际服务+不可逆账户身份取得基础域；可信跨地址账户 scope 取得附加共享域，
两域原子取得，任一容量不足均等待。证据过期不会更换基础域，下一次派发降至 1。
未知配置不能清除同域已知 RPM；混合策略采用更保守的容量/有效期内频率。
同一配置仍保留原任务级排队，不额外开放并行 Worker 或训练 GPU 分配。

许可默认保留 900 秒，实际调用存活时每 30 秒续约；崩溃后保守到期回收，
不是在任务取消或 30 秒 Worker Lease 到期时立即释放。原生/本地扩容证明要求
服务端真实执行截止 ≤600 秒。客户端 requests 的 read timeout 仅约束网络无活动，
**不能证明远端 GPU 停止**。云服务的实际请求寿命仍依赖供应商合同，现场需要核对。
数据库不可用期间无法证明续约时，拒绝发布；不把超时当作安全成功。

## 配额、凭据和错误

新任务冻结模型、标签/描述、坐标合同、提示词版本、容量策略与账户身份。
运行时不重读另一模型配置替换任务模型。历史无策略任务保持串行；凭据可用时按
真实凭据投影旧账户身份，以便和新配置共享限额。冻结后凭据发生变更时明确拒绝执行，
避免旧任务使用新账户却沿用旧配额。API/日志不输出密钥、图片 Base64 或原始响应正文。

| 返回 | 行为 |
| --- | --- |
| HTTP 200 / 0 框 | 合法 empty，等待人工审核；不构成识别准确或双卡证明 |
| 400 / 422 | MODEL_REQUEST_CONTRACT_INVALID，快速停止新派发 |
| 401 / 403 / 404 | 鉴权、权限、资源错误，停止并保留逐图证据 |
| 429 临时限流 | 读取有效 Retry-After 秒数/日期，作用域共享冷却，有界重试 |
| 429 明确计费/额度码 | MODEL_QUOTA_EXCEEDED，停止，不能无意义重试 |
| 500 / 502 / 503 / 504 / 网络暂时故障 | 同模型受控尝试、共享连续故障冷却；三次连续服务错误停止批次 |
| 非法输出/几何 | 沿用原解析与坐标错误合同，不能偷偷变成 empty |

默认总尝试 1；可信配额可配置最多 3。额外尝试的等待和重新派发受最多 30 秒重试预算限制，
已发出的网络调用另有既有有限无活动超时；不能声称客户端对远端计算具有严格墙钟截止。Retry-After 大于重试预算时不重发；同域暂停保留。
原 OpenAI 自动格式协商最多三次 HTTP，属于明确不支持结构化格式时的既有协商；没有 SDK
隐藏重试，没有换模型。一次任务尝试和 HTTP 格式协商次数不是同一指标。

## Provider 兼容性验收矩阵

| Provider / 配置 | 原行为 | 新行为及并发 | 自动化证据 | 实际服务 |
| --- | --- | --- | --- | --- |
| WeVisOne 双 2B / 有可靠原生网关证据 | 单请求串行 | 冻结并发 2、同模型网关分流 | 两个独立 HTTP 服务屏障证明真实重叠；候选与指标持久化 | 4070 未验证 |
| WeVisOne 单实例/未知容量 | 串行原生 detect | 1；image/query 原生字段不变 | 同一双服务测试容量 1 无重叠、原生描述回归 | 未验证 |
| Qwen / Gemma / vLLM 单服务 | OpenAI 兼容 | 缺证据 1；确认服务容量后才扩容 | 协议、错误、配置冻结和共享许可测试 | 未验证 |
| Ollama | /api/chat、非流式 | 默认 1；可信服务容量才扩容 | 真实本地 HTTP 的 images/schema/stream 合同及失败分类 | 未验证 |
| 火山/阿里/其他 OpenAI 云服务 | 既有 chat/responses | 默认 1；可信账户配额配置并发/RPM | 正常调用、格式协商、429临时/额度、401/403/422/5xx | 未验证 |
| 未知 Provider / 历史任务 | 原串行/原适配校验 | 1；不凭名字推断 GPU | 无证据、过期、伪造、旧配置、凭据变更测试 | 不自动启用 |
| 同后台多任务/多进程 | 配置级任务排队 | 原排队 + 同库层级许可 | 真正 multiprocessing spawn 争抢、释放、scope 隔离 | 多机共享数据库/网关现场未验 |

现场网关须确认 `/v1` 和 `/wevis2/v1` 哪一项是**原生检测**入口；两种前缀均由
既有 endpoint 解析保留，不猜测改写。直连 18000/18003 和网关 18002 的可达性、
模型修订、实际实例标识、query 格式与真实图片结果，不能从本地 127.0.0.1 推断。

## 验证记录

- 既有恢复与新策略聚合单测（CI 精简依赖相同入口）：231/231 通过；涵盖共享 RPM、跨进程许可、证据过期与冻结凭据。
- 配置/任务/审核/草稿/转池/预览/持久化 API 与隔离 HTTP 集成：117/117 通过；新增终态指标 API 另验 3/3（等待审核、取消、完成）。
- 完整原生 JS：最终 1558/1558 通过；Python 编译、JS 语法、版本一致性、diff 与原恢复 source guard 通过。
- Chrome：配置容量、模型协议、审核真实 API 往返、原生描述编辑器最终合并重跑 4/4 通过；Windows CRLF 夹具统一换行，产品断言保持。
- 候选恢复 20 万乱序行走有界标量分页，既有 1280×960、660×440、横竖图/EXIF 坐标回归复用。
- Provider 分类/协议最后定向复核 127/127；WeVisOne、双 HTTP/CLI、取消与共享许可补充聚合 78/78 通过（与上面单测有重叠，不重复加总）；两个独立 HTTP 服务和 CLI 验证属于调度模拟，**不是两块真实 GPU 的性能报告**。
- 已知基线问题：test_provider_parsing.py 的中文显示别名映射断言 9 通过/1 失败。
  两个相关文件没有本轮修改；隔离执行 HEAD 原始 parser 源码可复现。未混入范围外修改。
- 本机旧 Ollama 断开端口测试在 Windows 可能超时而非立即拒绝；仅该失败映射夹具改为
  明确 ConnectionError，保留严格错误码断言，正常 Ollama 请求仍由真实本地 HTTP 验证。

## 现场只读验证与部署

容量证明合同见 [运维证据说明](INFERENCE_CAPACITY_EVIDENCE_2026_11_07.md)。检查 API
`POST /api/v35/model-configs/{id}/capacity-check` **只核对运维证明**，不是自动探测 GPU。
运维证明未配置/过期/不匹配时，默认 1，不会因为两条地址或 /models 200 提升并发。

交付只读工具 tools/probe_inference_capacity.py；不写任务、标注、GT、配置或容量证明。
现场人员取得明确允许的测试图片后，可分别以 workers=1 / 2 运行以下命令：

```powershell
python tools/probe_inference_capacity.py --base-url http://GATEWAY:18002/wevis2/v1 --direct-base-url http://HOST:18000/v1 --direct-base-url http://HOST:18003/v1 --image APPROVED_LOCAL_IMAGE.png --model EXACT_MODEL_ID --labels person,tangzhe --workers 2 --repeat 10 --timeout 60
```

地址/模型/标签必须替换为现场真实合同；不同入口前缀不能照抄。API Key 仅通过显式
`--api-key-env ENV_NAME` 获取，不能作为明文参数。每次最多 20 张、最多 2 并发，不自动重试。
结果含平均/P50/P95/吞吐/成功/空/失败、实际请求/模型/实例 ID；缺失身份返回 unknown。
空白图只能证明协议链路，识别质量需要明确有目标的图片与人工核对。

记录模板：时间、平台版本/配置指纹、三个实际路径、模型修订、样本 SHA、workers1/2 的
指标、实例请求证据、GT 未变、正常取消与差量恢复结果。故障验证应使用隔离代理注入
错误，不停止在用模型服务。没有现场数据不得填 GPU 利用率或倍速。

回滚：本轮 Schema 只增加表，不改历史任务/GT；旧版 Repo 拒绝新 Schema，不能直接换回
旧二进制并强行降版本。部署前应按原维护流程备份任务库，回滚以部署前一致备份恢复，
不能删除生产候选表或运行中许可表。本轮没有执行生产迁移或部署。

## 技术参考与解释边界

[腾讯官方 WeVisOne 仓库](https://github.com/Tencent/WeVisOne-VL) 的检测示例使用类别 query 列表；
原生 HTTP 包装层仍以本平台适配器的既有合同为准，不能把官方 Python 示例当作现场网关配置。
[vLLM 官方数据并行说明](https://docs.vllm.ai/en/stable/serving/data_parallel_deployment/) 区分独立实例及
外部负载均衡；据此采用请求级等价实例分流，不把 TP=2 和两个独立 2B 实例混同。

提交与精确 SHA CI：发布后在最终交付消息核对；文档不预先称新提交 CI 全绿。

## 本地复核命令

```powershell
python -m pytest --confcutdir=tests/unit -q tests/unit/test_annotation_candidates.py tests/unit/test_annotation_task_service.py tests/unit/test_annotation_inference_execution.py tests/unit/test_inference_policy.py tests/unit/test_inference_resource_leases.py tests/unit/test_provider_retry_metadata.py tests/unit/test_openai_vision_protocol.py tests/unit/test_annotation_coordinate_contract.py tests/unit/test_annotation_comparison.py
npx -y node@24 --test "tests/frontend/*.test.mjs"
npx -y node@24 node_modules/@playwright/test/cli.js test tests/browser/inference-capacity-config.spec.mjs tests/browser/model-api-protocol.spec.mjs tests/browser/wevisone-native-query-isolated.spec.mjs tests/browser/ai-review-api-roundtrip.spec.mjs
```

阿里同名 `insufficient_quota` 可能表示 TPM 限流，不能套用其他 OpenAI 服务的计费语义；按显式 Provider 区分，免费额度耗尽/欠费仍停止。依据 [阿里 Model Studio 官方错误码](https://help.aliyun.com/en/model-studio/error-code-start) 与 [免费额度说明](https://help.aliyun.com/en/model-studio/new-free-quota)。新增定向回归覆盖该差异。

## 42.24.554 HTTP200 解析失败证据收口

553已通过正常Git快进推送，提交 c1d9b866ca12dcf0134117c8f545e45c2aa10837，其49项CI在后续收口时尚未全部完成。最终检查补齐 WeVisOne/Ollama HTTP200 但JSON/内容结构非法时的HTTP状态、实际请求及实例标识；错误归入解析阶段，不转换为空检出，不自动重试，不回显原始正文。新增两类畸形响应断言，Provider聚合最终129/129通过。此改动不改变成功请求体、并发/租约/GT路径；新SHA CI仍独立核对。

## 42.24.555 准确 CI 引入项修正

553 Linux AI Annotation API 因新增可选身份探测提前依赖无 Keyring 的安全后端，8失败/127通过；Release Regression 运行合同因两条旧Schema3断言，2失败/617通过/1跳过。这些是本轮引入，不能当作既有红灯。冻结引用的身份探测现在捕获明确 SecretStoreUnavailable，未知账户保持串行，运行时获取密钥仍严格校验；可执行后按实际账户基础域协调限额，不凭新证明升级旧任务。更新旧迁移断言为4并新增v3→v4任务与统计精确保留测试，原任务/统计/作用域断言不降低。定向回归52通过，最终准确新SHA CI待独立核对；未变更生产环境或为测试放松鉴权。

## 42.24.556 取消显示语义

555准确提交cc8361c9的AI Annotation Recovery和Release Regression已成功，修复的Linux身份探测及Schema迁移红项已恢复。最后核对取消指标后，API保留取消任务的执行指标，但不把主动取消投影为模型连续故障；新增/强化终态接口断言与原取消/并发执行回归12/12通过。未改变租约、候选写入或GT。最终提交CI仍按准确SHA核对。
