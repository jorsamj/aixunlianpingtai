# 算法级负样本池：阶段 B/C 实施与验收

## 需求与安全边界

图库原图仍由 MaterialRepository 唯一管理，入池不是正式 GT。现有素材加入、图片直接上传、ZIP 通过原持久导入任务进入同一池；成员关联目标算法。原全局成员不自动继承为任意算法的已确认负样本。分类为项目级管理信息，不是负样本资格。

## 实现

- 原素材数据库新增关系表 negative_pool_algorithm_members，以 algorithm_id/material_id 为键，依赖原池成员，不复制文件、不建立第二素材仓库。读取未初始化的池不会创建关系表；实际写操作沿用原生命周期锁及事务。无生产迁移执行。
- members、query、candidate_ids、上传意图接受 algorithm_id。API 核验算法真实存在；移出当前算法不删除其他算法成员或正式标注。全局移出遇算法关系拒绝并解释；重复移出返回真实 affected/already_absent。
- UI 增加目标算法、目标范围和确认入口。当前算法已有版本时复用 resolve_training_label_contract，目标范围不得缩成另一个任意子集；新算法没有冻结合同，只能明确选择本次目标，结果标注 requested_labels，不称整个算法已合格。
- 页内资格由 AnnotationRepository 正式记录和 training_material_role 判定；DTO 带目标范围、GT版本/摘要、源SHA、annotation revision。确认调用原 review-negative，每批最多50，原 actor/CAS/来源围栏与其他类别 GT保留。确认后变化重新投影，最终训练仍用原准入。
- ZIP 仍使用 ZipImportRuntime、multipart session、原任务扫描/确认/Worker。上传开始冻结 upload_algorithm_id；start拒绝换算法，Worker按冻结身份入池，原图仍未标注，不能以入池代替确认。ZIP/图片混合选择要求分批；归属丢失不会默认切到当前另一算法。
- 修复真实 Chrome复现的永久Loading：正式审核后图库迟到 decorateOriginal 调用使池请求 epoch失效（HTTP200但结果不绘制）；池处于活动状态时不允许原图库装饰器废弃池Owner。

## 已执行验证

- 定向单元：negative_pool + reviewed_negative_projection：37 passed。
- pool/ZIP frontend：54 passed。
- training_negative_review + v19_label_mapping：21 passed（最终当前代码，含新增四项链路定向；2026-11-04重跑20.02秒）。
- API两个入口实际链路：现有素材/上传意图 → 算法成员 → 原审核CAS → 正式GT资格 → snapshot.json及portable dataset → Ultralytics YOLODataset真实读取背景空标签；2 passed，无训练Epoch、无模型下载、GT不变。
- ZIP会话冻结与真实RAW ZIP导入：2 passed，导入后算法池可查，正式GT仍unannotated。
- Chrome新算法池确认回归：1 passed；pending与confirmed真实截图位于 docs/images/negative-samples-20261028/algorithm-pool-pending.png 和 algorithm-pool-confirmed.png。

## 待综合验收

上述自动化只覆盖隔离数据，不能称生产、真实OSS、20万池查询或GPU验收完成。ZIP UI完整上传/恢复、全部三视口与目标范围变更浏览器矩阵由综合阶段继续核验。没有提交、推送、部署或修改正式数据。

## 阶段 G：负样本池工作台收敛与浏览器验收

2026-11-04：保留原 Pool/图库 Owner 与 CSS Token，主区仅显示目标算法、目标范围、搜索；分类、日期、正式标注状态进入原生“高级筛选”展开区。批量栏仅保留两个选择动作、确认与加入草稿，分类/移出/清空放入“更多操作”。卡片默认只有文件名、图片、资格；来源、原标签、审核与历史折叠展示。控件最小44px，Hover/Focus无尺寸变化，手机优先图片，底部固定确认/草稿，不引入框架或新缓存。

- 真 Chrome 最终 **2/2 passed，10.7秒**，`npx playwright test tests/browser/target-negative-workflow.spec.mjs -g 'algorithm-scoped|scoped ZIP' --output artifacts/test-runs/pool`。
- 1440×900、1280×800、768×1024、390×844 检查文档无水平溢出、确认操作可见；截图 `docs/images/negative-samples-20261028/algorithm-pool-confirmed-{1440,1280,768,390}.png`。已人工查看1440与390截图。
- ZIP真实浏览器：池上传ZIP → 原multipart任务持久冻结算法 → 刷新浏览器 → 从原任务中心重新打开相同任务 → 明确负样本分类 → 正式导入 → 指定算法池只有一张新原图。没有复建ZIP处理Owner；打开原确认界面前关闭池上传层，避免叠层。
- Node池及ZIP回归最终 **54/54**。最终`git diff --check`限定本阶段文件无空白错误。
- 后端资格读取另经主代理补上素材/GT/Pool修订围栏，变更必须失败重读；原算法合同解析保留。

测试数据全为隔离fixture。生产OSS/断连/磁盘满、20万池查询与真实GPU仍非本阶段浏览器结论。
