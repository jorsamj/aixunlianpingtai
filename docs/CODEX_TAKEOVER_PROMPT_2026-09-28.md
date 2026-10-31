# CODEX TAKEOVER PROMPT — 2026-09-28

继续处理 GitHub 仓库：

`jorsamj/aixunlianpingtai`

长期开发分支：

`feature/external-algorithm-publishing`

项目：

**畅联云算法训练平台**

这是上一轮持续开发会话的续接。不要重新设计架构，不要重复已经 CLOSED 的工作，也不要根据本提示词中的 SHA 直接假定当前真实状态。

## 一、开始前必须重新读取 GitHub 当前真实状态

第一步必须重新确认：

1. `origin/feature/external-algorithm-publishing` 当前真实 HEAD；
2. `VERSION.txt`，必须仍为 `42.24.0`；
3. 最近至少 20 个 commits；
4. 当前 HEAD 的全部 GitHub check-runs / Actions；
5. 所有 completed failure 的真实 job log；
6. 当前相关生产代码、测试、workflow；
7. 最终实际生效的 runtime / owner。

本提示词生成时的**代码 cutoff**是：

`ce383fcc1af6ee5420860a42e65181a594545c5e`

提交：

`test: align AI recovery guard with journal catch-up`

该代码 cutoff 当时的 CI：

- total: 58
- success: 57
- failure: 1
- queued: 0
- in_progress: 0

**不要把这个 SHA 或 CI 数字当作新会话开始时的当前状态。必须重新读取。**

当前交接文档：

- `docs/codex-handoff.md`：优先读取最上面的
  `2026-09-28 当前真实接管点：AI 标注闭环 / 训练标签投影 / CI 仅剩 1 个 Browser 红灯`
- `docs/PROJECT_HANDOFF_CURRENT.md`：读取最上面的 2026-09-28 当前接手入口。

## 二、当前唯一已知 CI 红灯

在上述 cutoff，唯一失败是：

`Frontend Runtime Stabilization / browser-navigation`

job id：

`108840375284`

真实 Playwright 结果：

`76 tests -> 75 passed / 1 failed`

失败 case：

`tests/browser/material-workflows.spec.mjs:518`

名称：

`label management create and edit stay page-scoped without loading the full material pool`

失败点约 line 577：

点击“编辑标签”弹窗里的“保存”后，测试等待：

`getByRole('dialog', { name: '编辑标签' })`

变 hidden，但 5 秒后仍 visible。

### 处理要求

优先 focused reproduce 这个 case，并查：

- 保存 API 是否真正成功；
- 是否 4xx/409/500；
- 成功后是否被某个 authoritative refresh 阻塞；
- modal close 是否被遗漏/条件错误；
- 标签保存后是否错误触发 full material reload；
- 页面是否应该只 patch 标签列表/局部 truth。

禁止：

- 直接把 timeout 加长当修复；
- 为了让测试通过恢复 full material pool；
- 保存失败时假装关闭弹窗；
- 删除/放宽这个 browser contract。

正确语义：

- 保存成功 -> modal 关闭 -> page-scoped 标签列表更新；
- 保存失败 -> modal 保持打开并显示真实 error；
- 标签 create/edit 不应重新加载完整素材池。

修复后：

1. 先跑 focused browser case；
2. 再跑 Frontend Runtime Stabilization / browser-navigation；
3. 再重新读取最新 HEAD 的全部 check-runs；
4. 只有当前 HEAD 的全部 completed checks 都 success，才能写“全绿”。

## 三、近期已经 CLOSED，不要重复设计

### 1. 新畅联同步

已完成：

- Manual / Auto 共用单一 sync operation truth；
- `analysis_list_all()` 在可证明 product ownership 时作为一次性 summary index，消除 N+1；
- 无法证明 ownership 时回退 per-product list；
- 每个 analysis 的训练资格仍必须走 authoritative detail/getInfo；
- 只有 `status == 1 && analysisType == 1` 才可训练；
- listAll 只能优化，不能覆盖 detail truth。

### 2. ZIP 导入

已完成：

- selected image 导入不再先全 extract 再复制 selected tree；
- annotation/config 仍保留，不能破坏 YOLO/COCO/VOC 解析；
- merge/verify/scan/extract/annotation/db-commit 的进度由服务端 durable truth 发布；
- 浏览器不再为新 job 自造固定权重百分比；
- bytes/entries/counters/ETA 是服务端事实；
- VERIFY / SCAN 已分离。

### 3. AI 标注

正式流程必须保持：

`AI inference -> CandidateStore -> AWAITING_CONFIRMATION -> 人工审核/编辑/接受/拒绝 -> Commit -> AnnotationRepository`

已完成：

- canonical v60 + shared `annotation_runtime`；
- submit-time 冻结正式模型配置与 revision；
- secret value 不写 task request，只保存 secret reference；
- 普通用户从统一模型配置选择，不使用临时 endpoint owner；
- 标签必须用户显式选择当前有效 canonical code；
- 中文名/alias/历史 alias 不自动转换；
- 参考图只做视觉 example，不自动读取 bbox 替用户扩张 labels；
- AI Review formal write 后 journal catch-up 不被新 cancel 截断；
- AI Review 写 Ground Truth 使用 `expected_version` CAS，不能覆盖并发人工编辑；
- AI 仍不得未经人工确认直接写正式标注。

### 4. 训练标签投影准确性

当前产品语义：

- 迭代训练继承上一版本 label contract；
- 用户本次训练可以显式选择哪些 canonical labels 参与；
- 图片可以继续参与训练，即使图片里还有本次未选择的标签；
- 未选择的标签不能作为本次算法正类被学习。

为了避免“未选择对象”作为隐性正样本泄漏，bundle 会 redaction excluded object。

当前 canonical policy：

`redact_excluded_objects_v2_preserve_selected`

v2 规则：

- 先遮掉未选择标签对象；
- 再恢复 selected positive bbox 区域原始像素；
- 避免未选标签的大框覆盖已选标签的小框后，把正样本像素一并抹掉；
- legacy `redact_excluded_objects_v1` 必须继续支持 frozen historical task replay。

不要回退到 v1 作为新任务默认。

## 四、长期主流程优先级

在唯一 Browser 红灯关闭、最新 HEAD CI 重新确认后，继续做主流程审计，优先保证：

1. 训练创建 / input freeze / 迭代版本 / stale-base CAS / accurate label contract；
2. 批量素材上传 / ZIP / 1k-20k 性能；
3. confirmed_empty / 空素材正式负样本；
4. 手工标注；
5. AI Candidate review + commit；
6. 数据清洗；
7. 新畅联同步、训练后发布、转换权重追加、外部删除回收；
8. 真实 GPU/OSS/Agent/RKNN 现场验收。

不要为了“快”牺牲训练准确性；训练数据语义、标签冻结、excluded-object redaction、base checkpoint lineage 都必须 fail-closed。

## 五、不能破坏的架构/技术债约束

- 不 merge main；
- 不 tag；
- 不 release；
- 不 force push；
- `VERSION.txt` 不改，保持 `42.24.0`；
- 不删除测试；
- 不放宽测试来换绿灯；
- queued / in_progress 不算通过；
- 每个 completed failure 必须读真实 job log；
- Windows 11 开发，Linux/NVIDIA 生产；
- Web 监听保持 `127.0.0.1:8010`；
- 禁止写死 Windows 路径；
- 不新增第二套 AnnotationRepository / CandidateStore / ZIP owner / TrainingSubmit / PollRegistry；
- 不恢复 retired legacy owner；
- 前端、后端、worker、持久任务合同必须一致；
- loading/progress 必须来自真实 durable/server truth，不造假成功、不造假百分比。

## 六、新畅联长期业务合同

继续保持：

- 外部算法只有 `status == 1 && analysisType == 1` 可训练；
- 前后端训练前都实时做 external truth preflight；
- 训练成功 -> 原始模型上传 OSS -> 创建畅联算法版本 -> 创建原始权重；
- ONNX/RKNN 转换完成后只追加权重，不重复创建算法版本；
- 外部删除成功 / 再同步已不存在 -> 本地删除对应算法/版本/训练成果，不显示成“已下架”代替删除；
- 原始/转换产物都保存 public_url；
- 厂商映射当前优先 Rockchip RK3568/RK3578，后续 RK3576；不要额外加 RK3588；
- 通用映射用于未转换原始模型，允许空 chipCode 的合同不要回退。

## 七、标签治理长期合同

- 导入 / AI 标注不得自动替用户决定 canonical mapping；
- 用户可以把多个外部标签手工映射到同一个 canonical label；
- 外部 class_id、canonical project class_id、training class_id 必须分层；
- 训练最终 class id 必须重新压缩为 0..N-1；
- unmapped / inactive / dangling labels 训练前 fail-closed；
- confirmed_empty 是正式 Ground Truth 负样本；
- schema change 时不做 strict optimizer resume，只允许 previous weights init；
- 不新增第二套 label owner。

## 八、完成本轮后更新文档

每次完成关键 P0/P1 后更新：

- `docs/codex-handoff.md`
- `docs/PROJECT_HANDOFF_CURRENT.md`

内容必须写当前真实 HEAD、VERSION、CI 状态、CLOSED/OPEN、下一步，不得把 queued 当 success。

