# 2026-11-09｜42.24.564 WeVisOne-VL 原生 Detection 类别归属与提示词 P0

## 需求、基线和现场事实

- 本轮基线：唯一长期分支 `feature/external-algorithm-publishing`，远端 HEAD `acc9c835ef4aea3022bf651404819fd1e92ba232`，版本 `42.24.563`，工作区起初干净。
- 只修复 WeVisOne-VL-2B 的有框但类别归属失败，以及实际推理配置展示；不改模型质量/召回、生产数据或独立现场模型服务。
- 用户现场任务 `aibe533dcfc41944852620` 的 38 条失败 CSV 均为 HTTP200、`response_parse`、`MODEL_LABEL_NOT_ALLOWED`、`parser_source=structured_boxes`、`label_match_status=not_allowed`；`returned_label` 全为两段英文查询描述合成的一条字符串。每图仍有 1～7 个结构化检测框；37 条仅一个原生 `<ref>`，1 条有两个。已确认零框图片本来就没有目标。

## 官方协议审计和决策

1. 腾讯官方 [README](https://github.com/Tencent/WeVisOne-VL/blob/main/README.md) 把 `detection` 定义为类别列表→boxes，把 `referring` 定义为一条自然语言定位描述→boxes/None；官方 Detection 示例是短类名列表。
2. 官方 [`wevisone_vl/prompts.py`](https://github.com/Tencent/WeVisOne-VL/blob/main/wevisone_vl/prompts.py) 的 Detection `build_prompt` 使用 `". ".join(labels)`。这证明查询可能被合成一条提示，但**不能证明独立 FastAPI 如何将原始 `<ref>/<box>` 变成 `boxes[].label`**。
3. 当前平台 Provider 过去一次发送两个完整英文描述 `query=[A,B]`；现场 FastAPI 的独立 `/data/ai-runtime/wevisone-service/app.py` 不在本仓库，本轮不能审计它是否重新拼 query，也不能证明 `referring` 端点存在。现有 `/v1/vision/detect` 的 `image=Data URI`、`query=list[str]`、`coordinate_system=xyxy_pixel`、`bbox_xyxy` 契约已有现场报告。
4. 因 `referring` 实机端点/输出未知，而现有 Detection 有正常框，**本轮选择逐标签 Detection，不切换 Referring**。每正式标签单独发送 `query=[对应的冻结描述]`，按同一冻结描述/合法别名映射回 code；不依据组合字符串任意选择 `person` 或 `tangzhe`。

## 代码修复前后

| 场景 | 以前 | 42.24.564 |
| --- | --- | --- |
| 两个正式标签有独立长描述 | 单 HTTP 送 `[A,B]`，可能收到一条组合标签，白名单正确拒绝 | 同一 detect 端点按 `person`、`tangzhe` 各调用一次，成功后合并，禁止合成标签归到任一类别 |
| 只选一个标签或未配描述的正常短类别 | 原 Detection | 原合同不变，保留正常多标签返回 |
| 原生 `<ref>` 中有未知/合成标签但结构化框标注合法 | 结构化框可绕开原生 ref 标签核验 | 原生结构完整可解析时也检查其冻结白名单，组合类仍报错 |
| 第一类有框、第二类失败 | 原一请求无法隔离 | 整张图失败，**先成功的子结果不写 CandidateStore**，仅后续差量重试失败图片 |
| 两类有框且高度重叠 | 可能并列供审核 | 跨类 IoU 大于 0.5 时 `MODEL_LABEL_AMBIGUOUS` fail-closed，不猜类别；防止错误框入训练数据 |
| 两次都是零框 | 合法空目标 | 仍然是 `empty`，不造框、不自动转负样本 |
| 单图片原始图像坐标 | 解析为原图像素 XYXY | 两次推理共用一份内存中 EXIF 校正后图像；保持 `pixel/xyxy/top_left/original_input` 和原严格坐标验证，不二次归一化 |
| 并发/RPM | 每图一次已有许可 | 每个真实 HTTP 独立经过原 `call_with_policy` 的共享容量/RPM/取消和受控重试，单图最终一次提交；不新建限流器 |
| AI 创建/详情展示 | 通用 JSON Prompt 被误当真实 WeVisOne 提示词 | 同一创建面板显示 native Detection、query/code、协议、坐标；任务详情从后端实际**冻结 snapshot** 派生只读配置；不展示图片 Base64/Token/Key；其他模型通用 Prompt 保持 |

## 数据安全、测试和进度

- 原 CandidateStore 单图事务、审核、GT、差量重试防覆盖、负样本与任务 Owner 不更换。任何子请求失败和跨类冲突都不可发布半张图的成功候选。原生响应若仍含无法校验的标签，继续显式拒绝。
- 针对性测试包含原生多个 ref/单 ref 多框、正常多标签/单标签、组合查询、未知标签、标点等价、结构化/原生矛盾、零框、不同原图尺寸的坐标、逐标签许可与结果合并、第二请求失败、跨类冲突、冻结配置展示、通用 Prompt 不回退。
- 本地验证：Python 6 组原 Provider/推理许可/任务/候选/配置/请求元数据回归 **225/225 通过**；Node 全部前端单测 **1582/1582 通过**（包括 native 配置展示和通用 Prompt 保留）；Python 编译及 `node --check static/app.js` 通过。新增 Worker + CandidateStore 回归明确验证第二标签失败时整图仅保存 failed、不保存局部框，同任务其他成功图不受影响。**本地模拟协议通过不等于真实 WeVisOne-VL-2B 验收。**
- **现场验证待完成**：部署后仅对既有任务失败图片差量重试，对比成功有框、正确空框、跨类冲突、同图已成功候选未被覆盖；逐标签检查 FastAPI 的请求数组、原生 `<ref>`、结构化 `boxes[].label`、坐标与实例/请求 ID。
- **独立 FastAPI 边界仍开放**：未获得现场服务端源码。若单条 query 仍被服务端转换为无法验证的结构化类别，必须检查现场服务实现并提供兼容补丁；不能只放宽平台解析器声称端到端已修复。不切换 4B、不重启/修改现场服务、不擅自部署 A800/4070。

修改文件涵盖 `platform_core/providers/wevisone_vision.py`、`platform_core/annotation_inference.py`、`platform_core/annotation_task_service.py`、`app.py`、`static/app.js`、`static/index.html`、`VERSION.txt`、定向测试及需求/进度 handoff 文档。最终准确 Commit SHA 和远端 CI 另行记录。
