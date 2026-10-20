# 转换 Weight 发布身份恢复专项｜2026-10-20

## A 最新基线、范围与证据

已fetch/prune、pull --ff-only，最新长期分支a3a99ec1760366ddda5193ca60b200c3b719c2d5，VERSION42.24.359，工作树初始干净。其他工作树保持；可见会话未发现另一活动仓库开发；不代表能发现未连接客户端，提交前再次fetch核对。上轮动态字典、tags/元数据、Sophon全部已推送；其47/47 Actions、128/128 Checks及34关键Jobs实际绿色附件已读回验证：dynamic-conversion-ci-final-20261020.json（visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e），仅归档历史，不代替本轮。

### 用户提供的真实生产事实（永久保留，尚未由本轮远端读回）

版本345fabc92b7e，外部Version2109729657292197888。两目标旧/新同名但不同SHA，均已上传，不是同一文件，禁止重绑合并。

| 目标 | Artifact ID | SHA256 | 本地发布事实 | Weight ID |
|---|---|---|---|---|
| BM1684X旧 | c7cd54c0bb0ad83fe9e53a385b1272f6 | 0ec0791884d76fc2ea73725ebbb5c1229f108812dc96b491537e26e2aff70d36 | UPLOADED/SYNCED | 2112456166616469504 |
| BM1684X新 | ff7c1ebb1425c5fef7cc4297944d4d22 | d084a4d6916d93fa8d8960fd4a046565fb1a1db2111df5d8761f519a91d085e0 | UPLOADED/UNKNOWN，exact=0;related=1 | 空 |
| RK3568旧 | 4d960090d9fc09a35789a571adb2283e | c6ae3bb35cd77e7a9f115a18df4698d84e35e1bedc79251ac15cfe2d593e7f58 | SYNCED | 2112374852420767744 |
| RK3568新 | 1dc2248d2163583070b0689d5701a377 | 720c9e5a7e2e0e58ba06d1b1aff57c9e15cca4dc42ee3572ce8f68863f7e3e11 | UPLOADED/UNKNOWN，exact=0;related=1 | 空 |

BM文件00_train_train_ca4fdc6396bc43ff9c28bb49_best_bm1684x_fp16.bmodel；新旧OSS对象SHA不同，不能按文件名去重。历史RK版本f4dfedadcce7、4ef40723d87e、3ea046f276b0报EXTERNAL_WEIGHT_PLATFORM_REMAP_REVIEW_REQUIRED。

生产config.json已有通用2102998777790074880、Sophon父2000200697139826688及BM1684子2112437878675083264/BM1684X子2112437908475613184、Rockchip父2040048638935306240及RK3568子2111000350159933441；master-data-cache21项。禁止清空/重建。本轮未确认实时分类有效性。

### 已确认代码行为与尚未证实事实

- ModelArtifact原本以版本/目标/芯片/SHA区分，保留独立资产；原上传使用SHA对象键，不重传已验证对象。不同任务输出目录可同名，此命名本身不是文件身份冲突根因。
- 共享_recover_weight_from_rows对同名同平台同chip不同filePath一律related，exact=0;related=1与现场完全一致；即使出现新路径精确候选，旧related仍使其失败。不得用删旧Weight或宽松文件名匹配解决。
- ensure_artifact_publication保留父子分类改挂保护；本轮不能删除保护或自动迁移。需要原映射事实、可读审核计划及明确远端核验。
- 版本PARTIAL原auto_retry_due会按时间重试；不可自动消歧的Weight UNKNOWN可能反复只读恢复并计attempt。前端缺Weight ID/Artifact/上传与读回清晰投影。
- 附带：request_external_auto_publish_if_enabled先record_version_model_metadata，异常被同一except吞掉并阻止请求标记/Event。生产已有多次attempt，这不是其主根因。
- 只读SSH BatchMode连接a800-server失败（Connection refused，退出255），未建立会话、未读取生产DB/凭据，未发送任何新畅联/OSS请求。真实任务ID、source SHA、配置、有效成果选择、远端Weight仍存在与列表过滤均NOT VERIFIED，禁止猜测。

## 产品规则与架构决策

保留原ModelArtifactRepository、ExternalPublicationRepository、同一发布Worker/Owner、原上传/UNKNOWN/审计机制；不加库/队列/轮询。不同SHA绝不rebind。明确策略前保持待审核，不自行删除旧Weight、add新Weight或edit替换。用户最终确认：每算法版本/芯片原则上一个当前Weight；本地保留多SHA历史，用户明确选择或可信规则确定意向。此业务合同不代表edit接口支持或生产写入授权；未核验接口、唯一身份和授权前保持审核，不退回多Weight并存。历史父分类记录不改写；新成果仍用当前子分类；迁移只能身份确认、分类有效、唯一Owner、审计后由原edit受控完成并读回。

本轮限定计划：
- [x] 同名不同SHA隔离复现，明确单Weight合同；保护精确身份与单Owner，异名也不重复add；真实替换仍待审核。
- [x] 不可恢复UNKNOWN停止无意义自动重试，保留人工安全只读重试/新成果触发，公开审核原因与计划；不将UNKNOWN标SYNCED。
- [x] 历史父分类兼容/待审核投影与无写dry-run，原保护不删除；不实现未经业务确认的自动替换/新增。
- [x] 附带元数据异常不阻断发布唤醒且可诊断，不改变转换done。
- [x] 原UI显示Version/Weight分别状态、ID/芯片/上传/读回/审核；只测改动相关unit/Node/Chrome。
- [ ] 提交前重新fetch核对，按最终最新VERSION递增一次、同步正式入口与必要缓存；文档与受控测试证据一起普通FF推送。
- [ ] 最终实际SHA CI独立验收，不用历史绿色。

## B-F 进度与未完成

当前已完成限定实现与首次回归，最终限定复验/本轮SHA CI待完成。无真实远端验证或迁移结果；生产写入/部署/重启/重训/重转换/OSS仍未授权。本地开发不能冒充生产已修复。后续补每阶段测试/文件函数/精确SHA及受控dry-run；详细记录只维护本专项，接续入口放摘要链接。


## B/C 已复现缺口与最小修复

1. 共享链路不仅同名会related歧义，变更文件名还可能创建第二个Weight（两个芯片×同名/异名4项RED）。现按版本/目标/芯片检查已登记Owner与不同SHA，保留旧SYNCED、新成果UNKNOWN待审核，禁止复传/重复add/edit，不把不同内容rebind。
2. 转换恢复若远端既无filePath又无匹配SHA，只凭名称/平台/chip可能走edit；新增RED，仅转换目标要求实际路径或一致SHA。可用algoVersionId/远端SHA矛盾拒绝；原original历史缺地址修复及平面分类维护已有合同保留，不扩大重构。
3. ModelArtifact原多SHA独立、不可变OSS键和已上传复用已有。稀疏发布metadata会丢source_sha256与转换/验证状态，RED后加入同一Repository既有可信保留名单。未修改转换命令/调度/产物生成。
4. 不可自动消歧UNKNOWN/分类审核不再触发PARTIAL按时无限重复发布。publication_requires_sync仍检测新成果与正常可执行差异；人工“重新同步”仍进入原Owner只读恢复，不能直接add。
5. 历史芯片父分类不自动改挂，原ensure保护保留。状态展示原computePlatformId、目标子分类及REVIEW_PLATFORM_MIGRATION，旧SYNCED不变，Version/Weight显示PARTIAL/待审核事实，远端身份未读回不称已验收。旧平面映射维护的现有edit合同保持原测试。
6. 当前成果只由原版本payload_json中的external_publish_artifact_selection保存每target/chip唯一意向，记录Artifact/SHA/完成任务/时间及选择前后历史；版本交付锁+expected_selection防覆盖其他选择。原页面增加行内选择，无新弹窗/Owner/轮询。选择只写本地意向，不唤醒或授权远端替换。
7. 无历史Weight且多个候选时不按时间选新；用户选定后，仅“明确审核标记+0尝试+无确认payload+无活动Weight”的从未远端写入情形可经原完整读回前置条件走首次登记。真实写入UNKNOWN/已登记旧Weight不能被选择动作解除保护。未选历史记录保留并退出当前交付范围。
8. 本地元数据登记异常原先阻止Event唤醒（修正测试夹具后在原HEAD真实RED1项）；现独立记录异常日志，继续原请求标记/Event，成功转换状态不改。不是现场主根因。

实现复用external_algorithm_publish服务/Repository/原版本SQL payload、model_artifacts和原Worker，未新增队列/数据库/调度/第二套芯片发布逻辑。register_version_metadata拆出已有锁内主体以复用，避免在原publish版本锁内再次获取同一FileLock；无新同步Owner。

## D 限定测试记录

- RED：weight-recovery-red.log（同名/异名两芯片4项业务失败；元数据用例最初夹具缺project_id不计业务证据）；weight-wake-red.log（修正夹具后在原HEAD1项真实RED）；weight-selection-red.log（选择/父子分类投影2项）；weight-provenance-red.log（源SHA丢失1项）；weight-ui-red.log（Node17通过/1失败）；weight-dry-red.log（新只读报告合同1失败/既有Owner保护1通过）；weight-first-selection-red.log（首次明确选择不能恢复1项）；weight-identity-red.log（无filePath/SHA仍被恢复1失败，版本/SHA矛盾保护2原本通过）。日志均C:/Users/jorsam/.codex/tmp/。
- 首次限定Python119通过（0失败/跳过，111或112 deselected仅选择范围，不是跳过）；本机Windows长临时目录导致新Sophon本地存储夹具超过路径限制，改短basetemp后通过，不改实际对象键。一次旧平面映射测试失败后收窄至本次芯片父子映射，原断言全保留。
- Node原发布规格18通过0失败0跳过；Chrome原发布规格新增审核/选择一项后4通过0失败0跳过，验证PUT selection payload/零发布写入、历史Weight和UNKNOWN/PARTIAL/OSS事实同屏。隔离夹具不等于新畅联真实验收。最终复验日志待补。
- 最终正式版本以重新fetch后的42.24.359为基准一次递增42.24.360；main模块缓存42.25.408、发布模块64011，app/styles407不变。所有正式入口继续读同VERSION文件；独立UI build标识不作为正式显示版本。

## E/F 只读dry-run、生产边界与接续

沿用scripts/audit_weight_metadata.py（不新建同用途工具）：默认mode=ro读本地ModelArtifact/发布Repository/配置/缓存，校验源文件真实SHA、只展示任务/源SHA/参数/SDK/验证状态；共享weight_recovery_plan输出原ID、原/目标分类、旧/新filePath/SHA、建议、风险和回滚。可用`--remote-weight-snapshot`载入经授权只读导出的 `{algoVersionId,weights}` JSON，必须Version、Weight ID、chip、平台、fileName、非空filePath及可用SHA一致才标MATCHED_READ_ONLY；这不证明edit支持文件替换，automatic_write_allowed永远false。缓存父子关系标CACHED_VALID_PARENT_CHILD，不能冒充实时主数据验证。

生产只读命令示例（另在现场执行，不会发送网络请求）：

```sh
python scripts/audit_weight_metadata.py --data-dir /data/platform-data --project <真实项目ID> --output /tmp/conversion-weight-review.json
# 有合法只读导出时再加 --remote-weight-snapshot /tmp/version-weight-readback.json
```

不要传--apply-local；该参数是原上一任务显式本地修复功能，本轮未授权在生产使用。真实项目/算法ID、两份新旧任务ID/source SHA/实际params/SDK与时间、旧新URL完整值尚未获得，保持null/NOT VERIFIED。用户提供的四Artifact和两个Weight/版本/分类/SHA如上全部保留，不因HEAD变化丢弃；不能宣布它们已被真实远端修复。

下一步现场先取得上述只读报告及新畅联Weight列表/详情（核实过滤范围与旧ID是否存在）、edit真实OpenAPI/字段支持，再审核用户当前交付意向。旧模型保留、不同SHA不合并；已有Weight用同ID edit的后续能力仅在合同与唯一身份核实、迁移前后审计及明确生产写入授权后开放。若接口不支持替换，先报告限制，禁止转为多Weight方案。写结果不确定时只读恢复，禁止盲目回滚或再写。

最终SHA CI按本项目既有协议保存独立附件 `C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/conversion-weight-recovery-ci-final-20261020.json`，下一受验证提交归档，避免自引用SHA另造未验收提交。当前尚未推送/生成，不预称绿色。


### D 最终本地验收（正式VERSION42.24.360）

- 主限定Python2文件：`python -m pytest -q tests/unit/test_external_algorithm_publish.py tests/unit/test_model_artifacts.py -k 'weight or publication or auto_publish or metadata or chip or discover or manifest or identity'`，**122 passed /0 failed /0 skipped，112 deselected**，71.42s；日志weight-recovery-final-python2.log。deselected是范围筛选，未跳过失败用例。未执行无关训练/素材/清洗测试。
- 真实路由TestClient选择JSON合同、报告核心身份匹配、原metadata CLI只读/幂等：3通过，weight-recovery-api-audit2.log；新增HTTP用例只在创建原router期间关闭测试后台线程，随后恢复Thread.start，未禁用产品Owner。最初测试夹具错误关闭TestClient线程导致等待，已纠正，不是产品RED。
- 两芯片×同/异名4项补验只读报告任务ID、params及输出文件SHA关联，4通过，weight-recovery-audit-pair.log（与主集合重叠不重复累加）。
- Node原发布规格+正式版本Owner：27通过，0失败0跳过，weight-recovery-final-node2.log。Chrome原发布规格4通过（原3+新审核选择1），weight-recovery-final-chrome.log；全为隔离环境，不能作为新畅联真实写验收。
- Python/Node语法、git diff --check、原发布两段永久守卫GuardExit=0（weight-recovery-guards.log）。临时数据目录实测VERSION/backend/health/app_info/OpenAPI/remote/remote OpenAPI七入口均42.24.360，无部署环境修改。
- 源文件缺失历史分支亦保持旧SYNCED事实/未验证提示，并按唯一交付意向投影HISTORICAL/退出当前交付范围，不抹掉旧记录。最后相应定向复验见最终CI附件。

### 实际修改文件/函数

- external_algorithm_publish.py：共享weight_recovery_plan、单意向选择及审计历史、_artifact_review、_sync_weight、_recover_weight_from_rows、_bind_recovered_weight、publication_requires_sync、publication_status、原publish转换循环和selection原router增量。
- model_artifacts.py：可信元数据保留名单及既有register_version_metadata锁内主体复用；external_publish_request.py：独立记录登记异常后继续原唤醒。
- scripts/audit_weight_metadata.py：mode=ro报告、源Job事实、可选只读远端快照与缓存父子关系，零网络/生产写入。
- static/modules/external-algorithm-publish.js：原行内详情状态及选择；main/index缓存及VERSION；对应unit/Node/Chrome/版本断言。原转换Worker/SDK/字典/训练/tags合同均不重建。
- CODEX_CURRENT_STATE/AGENTS仅摘要链接；原前端Owner图、审计与技术债文档记录归属。上轮动态字典完整47/128绿色在本轮接续归档，本轮需自己最终SHA全部CI。


### 最终身份边界补验

只读复核发现同一故障的丢失本地回执分支：远端旧Weight在父分类、新产物在子分类且改了文件名时，旧恢复逻辑因平台不同忽略旧记录，可能再次add。新增weight-parent-identity-red.log真实RED；转换目标现在同chip跨平台也进入相关候选审核，不能绕过父子迁移保护。原PT缺地址修复行为保持。对应最终定向GREEN见weight-parent-identity-green.log；不扩展到其他模块。

用户生产证据的独立只读审核清单已生成：`C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/conversion-weight-production-evidence-review-20261020.json`。明确标记USER_PROVIDED_PRODUCTION_EVIDENCE_REVIEW_ONLY，不是假装已连接生产执行dry-run；四Artifact/两个Weight/全部SHA和3个迁移版本保留。实际项目/算法/任务/完整URL未知均null，remote_identity NOT_VERIFIED、零网络写入。可由现场原只读工具补完整后提交审核。


### 提交前收口

最终差异只读审查未发现可确认P0/P1，包含同chip跨平台恢复保护；审查未改文件/跑测试/联网。最后涉及selection/历史源文件缺失/状态/dry-run的12项通过（weight-recovery-final-focus.log），跨平台与旧恢复/两芯片/唯一Owner/父子分类12项通过（weight-parent-identity-green.log），均与主集合有重叠，不累加为独立总数。真实selection路由API用例另覆盖PUT JSON合同。Python/Node语法、正式版本/缓存、差异检查通过。

提交前再次fetch：远端仍a3a99ec1760366ddda5193ca60b200c3b719c2d5，无新增提交，未覆盖其他版本变更。可见项目会话只有本会话active及历史notLoaded会话；未声明能发现离线客户端。其他worktree不修改。正式版本42.24.360只递增一次；接下来普通FF推送，再核验本轮完整SHA所有实际Actions/Checks及关键Jobs。


### 首次SHA CI反馈：无效超时夹具的唯一ID修正

首个提交af3d4f331a245819ff6eb69996083e2f15637862的Algorithm SQL Store CI在原发布规格157通过/1失败：RecoveringPublishingClient两次create_weight将PT与RKNN都返回同一个recovered-weight ID，新单活动Owner保护拒绝跨资产认领，版本因此PARTIAL。属于旧隔离夹具不满足唯一Weight ID合同，不是生产远端响应或丢失路径；禁止为过测放宽Owner保护。现夹具首次仍recovered-weight、第二次recovered-weight-2；原PUBLISHED/版本恢复/第一个ID/一次Version和两次Weight创建断言全保留，新增全部成果两个唯一ID及远端ID集合断言。超时恢复/重复Owner/UNKNOWN不重发/两芯片7项复验通过（weight-recovery-ci-timeout.log）。只修改测试夹具与本文档，VERSION42.24.360不再次递增。最终以修正后完整SHA的全部CI验收。
