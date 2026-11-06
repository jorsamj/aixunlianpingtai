> 2026-11-06 / 42.24.549：素材库/图片详情/ZIP入口解耦接续已实现，详细需求、设计、测试与限制见 `MATERIAL_LIBRARY_ZIP_2026_11_06.md`。548审核/草稿/转池/恢复只复用，不重复建设；生产未动。

# 素材工作台 P0：合并需求、设计与验收台账

基线：42.24.531 / 01a424ffa1351b2e994b8e181e443cc985e5c83e。
唯一开发分支：feature/external-algorithm-publishing。阶段按 A→H 推进；已有明确反例可提前修复，不等待所有性能采样。生产数据和部署不在范围内。

## 统一需求与不变量

- 图库、选择器、审计使用原素材仓储、正式 GT、训练历史、请求生命周期和有界缓存，不创建第二套权威存储或前端框架。
- 可见性与可选性分离；历史 Train 可按策略复用，历史未知保留事实，独立 Test/来源关联组保护不能由开关绕过。
- 负样本池是算法关联；旧全局成员不自动确认为任何算法的负样本。确认使用现有正式审核 Owner 和目标范围/修订证据。
- 普通图片/ZIP 上传不自动生成无目标 GT；移出池不删除原图、GT 或历史快照。真正删除继续执行原引用保护。
- 选择必须沿 Draft→API→冻结快照→任务工作包→YOLO 加载保持一致。
- 审计复用现有确定性保留、退休回执和增量复核；不能以 UI 缓存代替服务端执行前校验。

## 阶段及验收门禁

| 阶段 | 交付 | 门禁 |
|---|---|---|
| A | 最小复现、分段基线 | 记录数据规模、缓存条件、环境和未验证项 |
| B | 状态与删除一致性 | 单项/批量/重复请求/引用/失败恢复 |
| C | 算法负样本完整链 | 已有素材及上传→确认→选择→快照→bundle→加载 |
| D | 历史复用和统一资格 | 单选/批选/严格切换/Test/重复组回归 |
| E | 查询与缩略图 | SQL/IO/DOM 分段、P50/P95、20万隔离规模 |
| F | 连续审计 | 返回10次、批量、跳过原因、增量失效 |
| G | 三页统一交互 | Chrome 桌面/iPad/窄屏截图、Focus/Touch/失败态 |
| H | 集成与交付 | 自动化/文档/版本/提交/远端SHA/CI，生产不动 |

## 设计依据

参考 Arco Pro 的控件密度、Semi 的状态/键盘/焦点规范、FiftyOne 的图库筛选、Supervisely 的 Gallery/Table、Ultralytics 的可解释准备状态。沿用平台 Token、单层详情与稳定ID，不复制其他品牌资源。

官方资料：https://arco.design/ 、https://semi.design/ 、https://docs.voxel51.com/user_guide/app.html 、https://docs.supervisely.com/data-organization/project-dataset/gallery-table-views 、https://docs.ultralytics.com/platform/data/datasets/ 。
Tabulator 仅作为候选，未引入；原生分页先测量。无新增运行时依赖。

## 已取得的本地证据

- A：初始历史SQL/负样本池 Python 基线9/9通过，临时目录fixture。
- 提交浮层：真实Chrome先RED（错误反馈position=fixed），修改唯一后置CSS规则后GREEN。提交生命周期35/35通过，包含4xx/5xx、响应丢失、回执恢复、重开与重复提交保护。失败反馈回到表单流，未知提交仍保留查询动作；不清空草稿。
- 既有默认历史SQL微基准：100/1k/10k素材旧全池冷态31.52/57.39/442.76ms，SQL冷态15.91/32.28/153.22ms，热态9.42/15.27/28.60ms。仅3次规模各单样本，不是P95；不代表本轮新增优化或生产OSS效果。
- 200k元数据21次采样已通过，完整记录在 docs/evidence/workbench-metadata-baseline-20261104.json。无图片字节的SQLite基准不能冒充缩略图、浏览器端到端或生产性能。

## 环境与未验收边界

Python3.12.7；浏览器测试使用任务级npm缓存Node22.23.4，系统Node20未改。已安装lockfile中的前端依赖，未修改lockfile；真实Chrome运行tools/test_server.py，其数据根由tempfile独立创建。
未部署生产、未运行生产迁移。GPU实际Epoch、真实OSS冷热、Safari和生产20万数据验收不可由fixture或CI替代。实现与本地验收已按A→G推进；H的远端提交与CI以精确提交记录为准。不能将隔离证据称为生产交付验收。

## 集成复核增量

- 图库来源徽标改为稳定material_id关联，乱序/退休卡片测试通过；页内标签限制3个及+N，完整标签保留详情。
- 负样本池筛选使用原库EXISTS成员/算法/分类索引，不先构造全池ID；禁止candidate_ids调用的反例先RED后GREEN，API+历史SQL53通过（随后新增用例继续以最终报告为准）。
- 独立复核发现池列表到资格投影间素材修订漂移；补素材/标注/池修订一致性围栏，变化返回409，不向界面返回旧已确认状态。Pool12单测通过。
- 完整回归暴露既有Windows缩略图并发问题：原路径多次resolve在原子创建期间返回DOS与扩展DOS拼写，误判越界。只归一化标准DOS/UNC别名，保留junction/symlink及真实越界拒绝。新增Windows确定性反例先RED再GREEN；缓存12测试通过，80轮×8线程每轮只读源一次、缓存身份一致、真实越界仍拒绝。
- 前端全量首跑1533项发现一处既有CRLF源码片段测试误判；仅在该测试读取时规范换行，运行时AI重试逻辑未变，11项生命周期回归通过。
- 全Python初跑覆盖到约40%后中止定位失败，不能声称全量通过；缓存问题修复后395项通过时暴露旧TaskKind白名单漏列基线已有MODEL_INSTALL/DEPLOYMENT_PREPARE/EXTERNAL_ALGORITHM_CLEANUP，仅补测试合同不新增运行时任务类型。广泛回归继续核验。

## 42.24.532 收尾记录

- 统一入口缓存键42.25.532，正式版本VERSION.txt=42.24.532，两者用途不同。
- 新增图库标签名称/编码检索，候选DOM最多40条；卡片最多3标签+N，稳定ID绑定来源；网格/列表继续使用同一原分页/选择状态。Chrome图库5/5、提交35/35通过，图片为标明用途的640×480隔离场景。截图见 docs/evidence/material-workbench-20261104/gallery-*.png。
- 三页视觉/交互与审计跳过、算法池图片/ZIP确认链的最终验收见关联专项：TRAINING_PICKER_WORKBENCH_2026_11_04.md、NEGATIVE_POOL_ALGORITHM_SCOPE_2026_11_04.md、AUDIT_WORKBENCH_CONTINUITY_2026_11_04.md。
- 选择器公有列表框投影最多12框，box_count仍为完整数量，明确preview_only/truncated；详情和训练始终读正式GT，1000框不因显示优化丢失。
- >50000的全筛选选择在原BatchSelection/ArtifactStore冻结，浏览器仅存引用与计数；项目/算法/角色/策略/合同及五修订绑定，Worker核验引用和真实IDs。新大范围浏览器场景200000条引用提交体<5KB，没有向客户端下发全量IDs。旧数组接口保留原上限；新引用不是第二素材数据库。
- 本地Python3.12.7、Ultralytics8.4.127、Torch2.12.1、Core Ultra7 255H/16逻辑CPU、Windows11。磁盘基准为本地SQLite，未测生产OSS和GPU。性能表不能跨条件比较或冒充生产P95。
- 全前端曾1533/1533；此后只对新增引用/包装边界作定向验证，避免无意义重复全量测试。新引用、Worker包装、训练幂等和浏览器结果以选择器专项最终记录为准。
- 全Python首次1804pass/15fail停止：13项外部发布/归档在Windows长临时路径失败，改用短的独立测试根后相关284/284通过，不修改该运行时模块；符号链接1314缺权限明确skip；固定诊断名称旧断言已与基线真实行为对齐。第二次短路径全量运行按用户减少测试指令中止，**不声称完整Python套件通过**。本轮以关键链路定向验证及精确SHA CI交付。
- 独立代码复核两轮发现并关闭：池资格修订漂移、审计跳过/计划TOCTOU、引用重放幂等顺序与清单读写边界。正常失败撤销本次预占；不能确认的硬崩溃意图保守保留，不删除活动或历史证据。
- 未新增前端框架/请求中心/素材主库；未下载大模型、未训练Epoch、未部署或操作正式数据。原WIP工作区未修改。

远端结果入口：https://github.com/jorsamj/aixunlianpingtai/actions 。必须以本次精确提交为准；CI通过不等于生产断网、GPU和真实OSS验收。
