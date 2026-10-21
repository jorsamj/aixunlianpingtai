## 2026-10-21｜动态厂商/芯片稳定ID一对一映射（本地限定验收完成 / 待最终SHA CI）

基线bb1fed555b60409109b9c62c875b30b72e6c31c5 / VERSION367，fetch/pull干净且远端一致，其他同库会话未活动，原工作区WIP不动。上轮23/59最终CI独立回执已核验归档，不代表本轮。用户完整需求来源附件6b2e342e：本地字典动态展示，local_vendor_id/local_chip_id与新畅联parentId分类树双向一对一；通用original/onnx/paddle独立，原始模型必发；历史配置/Weight/SHA/Tags/参数事实保留，生产迁移/写入/部署不授权。

根因已读代码确认：target_mappings以Adapter为key、chip_mappings以SDK字符串为key；前端固定硬件列表和手工新增编码；原芯片校验没有反向唯一性，已有Weight改挂保护仅部分映射触发。本地ModelArtifact已经保存local IDs，可复用，无需再建资产层。

本轮设计/实施计划（原Owner内增量）：
1. 原target_mappings增加vendor:<稳定厂商ID>记录，local_vendor_id明确身份，chip_mappings使用稳定芯片ID；generic旧目标保持。旧Adapter记录作为兼容/迁移证据保留，不与新稳定绑定竞争。public_config返回原本地字典、逐项绑定状态和只读旧配置迁移建议，不按名称自动写绑定。
2. 原Repository同一fence中校验完整合并配置、revision并发、原子保存与有限历史快照；旧客户端部分PUT不会抹掉未提交项。回退采用原PUT的受控完整映射替换，必须带当前revision、通过同样校验，不执行远端操作。
3. Service验证厂商/芯片本地存在归属、远端有效根/具体子分类与反向唯一性；停用/失效的原绑定保留诊断，不因保存无关项清空。SDK Adapter与业务厂商分离。
4. 原artifact映射先验证任务/资产稳定身份及SDK一致性，新式绑定不回落到其他厂商；无ID历史仅在已验证SDK合同和本地字典关系唯一时兼容，歧义阻断。已有Weight映射变化一律保留旧ID/回执并待复核，不能跨平台自动edit/add。
5. 原厂商对应表改为通用区+本地动态硬件区；无手工输入型号、已有占用禁选、父级改变保留并标记错误子绑定。草稿/并发/刷新/页面归属与单次事件检查；无新Observer/轮询/Owner。
6. 先限定RED，再最小修复、相关Python/API/Node/Chrome；不跑全仓或无关转换训练素材清洗；既有CI正常触发、不增加大型工作流。完成后版本按最终远端一次递增，更新字典/发布/接续文档并普通推送核验实际SHA。

### 实施、接口与历史兼容

已在原实现完成上述六项。原GET/PUT `/api/v64/external-publish/config`扩展，不新增API Owner或数据库。GET新增`local_catalog`（来自ModelArtifactRepository原conversion_catalog，含停用项/SDK模板Adapter事实）、`mapping_diagnostics.vendors/legacy_proposals`；PUT新增`expected_revision`、`expected_catalog_revision`、`replace_target_mappings`。新增稳定映射或回退必须带revision；旧部分PUT仍合并保留未提交项。错误为409 `EXTERNAL_MAPPING_REVISION_CONFLICT/REQUIRED`、`EXTERNAL_LOCAL_CATALOG_REVISION_CONFLICT`及具体本地身份、父子分类、反向占用错误，不假报保存成功。原始模型强制启用，通用ONNX/Paddle不依附硬件厂商。

保存示例：`target_mappings["vendor:vendor-s"]={local_vendor_id:"vendor-s",compute_platform_id:"remote-parent",chip_mappings:{"chip-s":"remote-leaf"},enabled:true}`。本地型号/SDK编码不修改，远端叶子必须属于所选有效根厂商，不能把同名当同一身份。生效厂商父ID及芯片子ID双向唯一。停用/缺失的历史芯片原样绑定可透传，改变的绑定严格校验，实际发布选中项始终严格校验。绑定及有限回退快照纳入原引用扫描，不能删除/改挂受引用身份。

旧配置不会在读取时自动重写：唯一Adapter厂商、明确SDK目标与具体远端分类证据同时满足才生成READY建议；用户采用至草稿并保存才生效。多厂商共享SDK或缺少可靠证据显示待核验；原Adapter配置保留高级只读证据。回退只恢复上一版草稿并经过同一revision/校验/原子PUT，不恢复生产数据或远端Weight。

发布和当前交付分组使用稳定厂商/芯片身份；旧selection只有原Artifact+SHA和唯一身份吻合才兼容。recover、sync、readback共用远端候选过滤，仅排除明确绑定到其他业务厂商的分类，未知分类仍阻断；不同厂商不会共享同芯片发布Owner。已有Weight分类变化（含历史父→子）进入独立审核，保留原ID、payload回执与成功历史；本轮禁止自动迁移。相同分类内新SHA自动更新仍沿原Owner/原Weight edit/读回机制，Tags/withTags/可选元数据合同保持。

ModelArtifact原canonical唯一键不重建：同SHA再次登记若携带与原资产冲突的已知稳定ID，409 `MODEL_ARTIFACT_LOCAL_IDENTITY_CONFLICT`且原记录不变；不改SHA/Artifact ID规避冲突。该保守边界意味着相同SDK目标、完全相同文件跨多个业务身份的历史异常须先核对可信任务，不自动拆分资产。不同SHA继续保留原独立资产。

### UI与生命周期

原平台对接→厂商对应表直接替换固定硬件/手工编码编辑器：通用区+动态厂商折叠卡片+所属芯片表格，显示本地稳定ID、SDK目标、远端完整路径/ID和诊断。父级变更保留无效子选择并提示，不静默清空；已占用选项禁用只是交互辅助，后端仍统一校验。旧记录/停用项只读保留，空态和未绑定项真实展示，无新弹窗/Observer/轮询。

单panel事件委托且仅一次PUT；GET singleflight，旧revision迟到不回滚新配置。离页保留草稿，刷新主数据不覆盖未保存草稿；保存期间新进入panel同样锁定，结束后只更新当前页面。保存失败保留草稿，成功读回失败单一提示且不误报写失败。空硬件行不自动生成canonical空映射，保证旧配置兼容及回退正确。

### RED→GREEN及限定验收（2026-10-21）

- 首批真实RED：稳定映射/反向唯一性/动态投影6失败1通过；修复后7通过。另同SDK多业务厂商交付分组与远端恢复分别RED→GREEN。新增身份、revision/回退、引用保护、停用历史、只读迁移及HTTP真实路由隔离测试。
- 发布模块先190通过，最终共享路径修改后192项出现191通过1失败：失败是旧测试期待映射变化自动父→子edit，与本轮用户明确禁止自动改挂冲突。两项旧业务期望按当前合同改为更强的零edit、原Weight ID/分类/成功回执保持、PARTIAL且审核原因可见断言；失败项单独复测1通过。随后新增迁移/API2通过。最终去重发布194项全部有GREEN证据，无删除/skip；不为全绿降低安全校验。
- 直接依赖限定`test_model_artifacts.py`中稳定身份/冻结元数据2项，`test_conversion_catalog_crud.py`中引用/并发7项，共9通过；其余无关测试未执行。
- Node原发布文件19通过、版本缓存9通过，共28。Chrome原发布spec定向`-g "stable vendor mapping"`1场景通过，覆盖正式tab/动态双厂商、稳定ID payload、旧配置保留、离页草稿、保存中返回锁定、单次PUT、刷新持久化、409失败草稿保留及回退不产生空绑定。首次浏览器夹具正则误匹配保存按钮已修正为正式tab locator，不改产品逻辑。
- Python最终成功去重203例（发布194+资产/引用9）；Node28；Chrome1；语法编译、JS语法及`git diff --check`通过。仅受影响模块，不运行无关训练/素材/清洗或全仓测试。额外单进程RED日志打印遭Windows GBK编码异常，guard已finally恢复，后续GREEN有效；不把日志异常计作产品缺陷。
- 定向Chrome使用隔离后端+明确的本地HTTP夹具，不代表真实新畅联/生产持久化验收。截图`stable-vendor-mapping-20261021.png`在本任务既有visualizations附件目录，已实际查看布局。

### 质量、版本、交付与未验证

实际审查了原入口/调用链/事件/异步归属/引用/危险写入。审查发现并修复停用历史阻塞修改及保存迟到覆盖新面板两项P2；最终静态复核无新的必修P1/P2。未新增Owner/Service/Repository/数据库/队列/框架/监听器/轮询/wrapper链；旧固定编辑器已退役，发布JS净减代码。无循环渲染；UI配置和API校验以真实后端合同为准。保留历史生产证据及其他会话已交付功能，原D盘WIP不动。

最终fetch仍bb1fed55 / VERSION367，本轮一次递增VERSION42.24.368；正式前后端显示原本就读VERSION后端真值，必要main/styles415及发布模块64014，未改app.js413。修改文件：VERSION.txt、static/index.html/main.mjs/modules/external-algorithm-publish.js/styles.css；platform_core/external_algorithm_publish.py/model_artifacts.py/conversion_catalog_references.py；原发布Python/Node/Chrome测试、资产Python/版本Node；本专项、字典专项、CODEX_CURRENT_STATE及AGENTS。

实际最终SHA及每项Actions/Checks/关键Jobs不能自引用进同一提交；推送后按既有规则写独立回执`stable-vendor-mapping-ci-final-20261021.json`（既有visualizations目录），下一会话先读取该回执并对照远端HEAD。本段不预先声称CI成功；CI失败必须修复实际原因并核验后续最终SHA。

生产配置/字典/DB/OSS/Weight/SDK/训练转换/部署/重启均未操作。尚未验证：生产字典是否满足双向唯一性、历史多业务厂商缺稳定ID的具体范围、真实新畅联分类状态/已有Weight归属及迁移。上线前只读核对并导出旧配置；先审阅READY/REVIEW建议，不批量改写历史。实际Weight迁移须另行授权，先给出原/目标分类、原Weight/Artifact/SHA/filePath/真实远端核验及回滚方案。

---

## 2026-10-20｜自动单Weight交付合同（替代旧人工选择策略）

同算法版本/目标芯片仅一个当前远端Weight，本地不同SHA历史独立保留。ModelArtifact统一发现和校验，可信带时区任务完成时间（或绑定源/任务/产物的Manifest UTC）加任务ID/SHA确定顺序；原版本fence与selection/history保证迟到回调不回滚，OSS确认后才推进意向。

复用原发布Owner、Repository、add/edit及UNKNOWN恢复：已有唯一真实ID核对Version/chip/分类后同ID edit；列表及历史ID详情确认不存在后唯一首次add。官方OpenAPI已核验支持filePath/computePlatformId/chipCode/扩展元数据，实际服务拒绝时保留原错误，不delete/add绕过。写前持久化before/desired，写后list/getInfo读回成功才SYNCED并原事务切换单一活动Owner；历史映射仍保留成功回执和superseded关系。未知写（含其他同芯片Artifact）先只读恢复，禁止重复写。元数据仍可选、未知tags省略，不能用[]清空；文件完整性/核心映射严格保留。

UI按同一后端投影显示自动当前、历史、真实Weight ID/上传/读回/异常；无常规手选或人工审批入口。生产历史批量替换、生产数据库/OSS/接口写入及部署仍须单独授权。完整官方来源、原始故障证据、限定测试及接续见[专项](CONVERSION_WEIGHT_PUBLISH_RECOVERY_2026_10_20.md)顶部；后续旧段落仅作历史决策记录。

# 外部算法平台 Phase 2：训练成果发布 / 回退 / 对账 / GC 当前合同

本文记录新畅联训练成果发布链的**长期技术合同**。会话级 SHA、VERSION 和 CI 状态以 `docs/codex-handoff.md` 最新章节和实时 GitHub 为准，不在本文写死历史版本。

## 1. Canonical owner 与总链路

发布链继续复用现有 owner，不建立第二套模型产物或发布生命周期：

`training version`
→ verified `ModelArtifact`
→ immutable object storage
→ external Algorithm Version
→ original Weight
→ conversion artifact
→ conversion Weight
→ RKNN board validation / metadata promotion
→ drift reconciliation / rollback / exact-ref GC。

唯一 owner 约束：

- `AnnotationRepository`：Annotation Ground Truth；
- `ModelArtifactRepository / ModelArtifactService`：canonical 模型产物；
- `ExternalPublicationRepository + existing auto-publish worker`：external publication / reconciliation；
- `RemoteExecutionStagingLifecycle`：task-owned remote staging GC；
- `version_operations`：version rollback/delete 后 cleanup retry journal；
- `model_delivery_version_fence`：version retirement 与新引用创建并发 fence。

禁止新增第二 ModelArtifact、第二 publication worker、第二 conversion artifact identity 或第二 staging GC owner。

## 2. 原始模型发布合同

训练成功且模型产物完整性验证通过后：

1. 发现/注册 canonical ModelArtifact；
2. 上传到配置的算法与转换结果存储；
3. 使用 immutable object key；
4. 校验 `size_bytes + SHA256`；
5. 生成稳定 `public_url`，不能使用临时 signed URL 作为外部长期地址；
6. 对可访问 URL 执行必要的 HTTP Range GET probe；
7. original 上传成功后才允许创建/恢复 external Version；
8. Version + original Weight 都成功后才进入正式 PUBLISHED / SYNCED 语义。

发布失败不能反向污染本地训练成功 truth。

通用 original Weight 可空 `chipCode`；有明确厂商/芯片的转换 Weight 必须使用真实映射。

## 3. Conversion / RKNN 合同

ONNX / RKNN 等转换产物只能作为已有 algorithm version 的追加 Weight，不能重复创建 Version。

当前产品 Rockchip canonical 转换目标：

- `RK3568`
- `RK3576`

当前产品合同明确不开放：

- `RK3578`
- `RK3588`

RKNN 转换完成但尚未实板验证时保持 `converted_unverified`。板端验证成功后只提升**同一 canonical ModelArtifact** 的 validation metadata：

`converted_unverified → hardware_verified`

不得复制出 verified 第二 artifact identity；原 `artifact_id / object_key / sha256` 保持同一身份。

## 4. External Version / Weight 幂等与 reconciliation

网络超时、返回丢失或进程重启时，禁止盲目重复 POST。

现有 publication owner必须优先：

- 按 canonical Version identity 反查/恢复 Version；
- 按 canonical Weight identity 反查 Weight；
- 找到唯一 Weight 后，继续通过既有 edit owner 对齐 `computePlatformId / chipCode / fileName / filePath`；
- 远端缺失 Weight 时只恢复缺失 Weight，不重复创建 Version；
- 整个远端 Version 缺失时先清 stale provider IDs，再由原 publish owner 恢复 Version + Weight。

低频 drift reconciliation 继续由**同一个 auto-publish worker**执行，不新增第二监控器：

- 正常检查窗口保持 bounded；
- 失败采用退避；
- 单轮数量有上限；
- 同 product 的 Version list 要复用；
- Weight list 按 Version 读取，禁止逐 Weight N+1。

若同一 canonical Weight identity 在远端出现多个候选：

- publication / mapping 进入 `UNKNOWN`；
- auto-publish blocked；
- 不允许任意 edit；
- 不允许再 create 第三个 Weight；
- 必须先人工消歧。

## 5. External delete / local rollback 合同

本地 version rollback/delete 不能因为删除了 publication row 就假定远端 Version 已删除。

正式顺序继续 fail-closed：

1. 对 external Version/Weight 做 provider delete / reconciliation；
2. 删除结果不确定时反查；
3. 只有能确认远端状态后才允许继续本地 version retirement；
4. local version metadata retirement 后，精确清理该 `project_id + algorithm_id + version_id` 的 ModelArtifact / publication mapping / storage object / conversion delivery；
5. 任一清理步骤失败都记录到既有 `version_operations`；
6. 后续通过同一 cleanup journal 幂等续清理，不重建 version metadata，也不重复执行已确认的远端 Version 删除。

immutable storage object 删除失败时必须保留 canonical ModelArtifact row，禁止数据库先删、远端对象状态未知。

## 6. Reference fence / TOCTOU

version retirement 与以下新引用创建必须复用同一 `model_delivery_version_fence`：

- 迭代训练；
- conversion；
- 普通 deployment test；
- RKNN board validation；
- ModelArtifact upload/retry；
- external publish。

拿锁后必须重新读取 version truth：

- version 已退役 → fail-closed；
- 迭代训练 base/current version 已变化 → stale fail-closed。

因此形成双向保证：

- reference 先创建，retirement 能看到 active reference 并拒绝；
- retirement 先完成，后续 reference 创建会发现 version 已不存在并拒绝。

## 7. Remote staging / orphan GC 合同

唯一 owner：`RemoteExecutionStagingLifecycle`，运行在 storage Worker，复用现有 heartbeat；禁止新增独立 timer/thread/scheduler。

普通 task-owned staging 只允许 exact：

`remote-execution/{project_id}/{task_id}/...`

删除必须具备：

- `storage_source_id`
- exact `object_key`
- `size_bytes`
- `SHA256`

删除前必须重新 `stat` 校验。禁止：

- `list_objects` 推断 orphan；
- prefix delete；
- 只凭文件名/目录猜 identity；
- provider/identity 不确定时强删。

以下对象不属于普通 task staging GC：

- canonical ModelArtifact immutable object；
- `remote-training` shared dataset bundle；
- formal material object；
- external Weight / publication mapping；
- version 存活期间仍是 durable evidence 的 RKNN board output。

conversion 本地 orphan、remote training provisional delivery orphan、RKNN board task-owned staging 都继续扩展这一个 lifecycle / fence 体系，不另建 janitor。

## 8. RKNN board durable evidence

active RKNN board validation 会从 `source_conversion_job_id → source_trace` 回溯 version，QUEUED / RUNNING / CANCEL_REQUESTED 时 version retirement 必须拒绝。

成功板端验收后：

- hardware verification 写回 conversion manifest/job；
- board output 的 exact storage identity 作为 durable evidence；
- version 存活时不由普通 staging GC 删除；
- version retirement 时由既有 version cleanup owner精确删除；
- 删除前再次校验 size/SHA256；
- 删除后保留审计 metadata，并明确标记 evidence 已不可用/已删除。

## 9. 性能与失败语义

所有 reconciliation / GC 继续满足：

- bounded page / bounded batch；
- 不做 N+1 OSS HEAD；
- 不做无界 remote list；
- 不做全量 JSON hydration；
- 不引入 O(N²) Python 状态；
- provider/network 异常 fail-closed；
- queued / in_progress 绝不当 success；
- publication retry 不得改变 canonical artifact identity。

## 10. 验证边界

永久 CI 继续覆盖：

- upload / Version / Weight create；
- timeout recover / idempotent retry；
- Weight edit / drift reconciliation；
- ambiguous Weight UNKNOWN；
- rollback/delete cleanup retry；
- ModelArtifact identity 与 RKNN validation promotion；
- exact-ref staging / orphan GC；
- version retirement reference fence；
- frontend publication / conversion contracts。

CI 通过只代表仓库合同验证。生产验收仍应单独取得真实证据：

- 正式 OSS PUT / STAT / Range GET / DELETE；
- 新畅联生产 Version / Weight create / recover / edit / delete / drift；
- Linux / NVIDIA 真实训练与推理；
- RK3568 / RK3576 实板 RKNNLite。

出现真实生产证据与本文合同冲突时，先记录接口/对象/任务 exact evidence，再修改现有 owner；不要先扩架构。

