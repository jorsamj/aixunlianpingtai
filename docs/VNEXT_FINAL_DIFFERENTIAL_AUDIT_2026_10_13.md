# VNext 最终测试差异审计（2026-10-13）

## 1. 审计边界与环境

- VNext：`ede115e476d70ac21cb4bade288b84f8a55b2f2a`。
- 旧基线：独立干净工作树、detached `30f83c48bab39b9b8aca07f95b8481a3fbb672ec`；未切换或重置 VNext 工作树。
- Windows 11 `10.0.26200`，Python `3.12.7`，pytest `8.4.2`，FastAPI `0.138.2`，Starlette `1.3.1`，httpx `0.28.1`，Pydantic `2.13.4`。
- Node 本机默认 `20.12.2`；CI 对齐运行使用 Codex bundled Node `24.19.0`；Playwright `1.62.1`、Google Chrome channel。
- `requirements.txt` 与 lockfile 在两工作树内容一致；基线执行 `npm ci` 后使用相同 Playwright 版本。
- WSL2 Ubuntu 22.04 可用但只有 Python 3.10、无项目 Node/Python 依赖；本机无 Docker。因此本轮没有把 WSL 结果伪装成 GitHub Ubuntu/Python/Node 24 CI，远端 Linux CI 仍为 `NOT VERIFIED`。

补充：Node 24 Windows 执行 package script `node --test tests/frontend` 会把目录当模块并报 `MODULE_NOT_FOUND`，旧基线脚本同样如此；GitHub workflow 实际使用 Linux shell 展开的 `node --test tests/frontend/*.test.mjs`。本轮用 Node 24 直接执行同一显式文件模式，结果 `952 passed`，没有为了本地 launcher 差异新增包装器或改生产代码。

证据目录：`C:\Users\jorsam\.codex\visualizations\2026\10\13\01a1331b-b427-7bf1-9454-b0d48376c22c\final-differential-audit`。

## 2. 数量口径纠正

新鲜全量 Windows pytest 为 `62 failed, 2325 passed, 12 skipped`，不是旧报告中的 `64 failed, 2323 passed, 12 skipped`。旧报告没有留下可反查那两项的 JUnit/完整终端清单，因此不能编造已经消失的两个名称；本轮 JUnit XML 是当前可复核的权威清单。

新鲜 VNext 全量 Chrome 首轮为 `7 failed, 142 passed`；旧基线同顺序全量为 `6 failed, 142 passed`。Trace 证明多出的标签管理项在首个 usage 请求尚未成功写入缓存时就跳页，浏览器中止请求后回访产生第二次 GET，而旧夹具只等“请求已发出”。夹具改为同时等待正式 `label414UsageLoadedAt` 有效，再保留原请求次数断言；连续重复 `5/5`、相关素材集合 `22/22`、最终 Node 24 全量 `143 passed, 6 failed`。生产缓存代码未修改。

## 3. Python 62 项归因统计

| 根因 | 数量 | 分类 | 同基线结果 | 关键证据 |
|---|---:|---|---|---|
| Windows 路径长度 / 测试临时根目录过长 | 30 | Windows、路径环境 | 30 项同样失败 | `C:\pV4` 下训练缓存/输入 `18 passed, 1 skipped`；`C:\rV3` 下远端素材 9/9；`C:\mV4` 下模型归档/发布相关 6/6 |
| Annotation 夹具引用未注册/非活动标签 | 14 | 旧夹具与正式标签合同不一致 | 同样失败 | `annotation_repository.py:402` fail-closed |
| 标签 usage/scope 旧期望 | 2 | 旧测试合同 | 同样失败 | 实际 `scope_images` / `usage_images` 与旧断言不同 |
| v47 已退役接口 | 1 | 旧测试合同 | 同样失败 | HTTP 410，正式入口为 v60 durable review/decisions |
| Annotation projection 同版本冲突 | 1 | 旧夹具合同 | 同样失败 | `material_repository.py:1143` 拒绝同 version 不同 digest |
| FakeArtifacts 缺正式 artifact API | 1 | 测试替身不完整 | 同样失败 | 缺 `artifact_path` |
| Windows 分隔符断言 | 1 | Windows 专有测试断言 | 同样失败 | 测试同时错误匹配混合 `/` 与双反斜杠 |
| Multipart monkeypatch 函数签名过期 | 2 | 测试夹具合同 | 同样失败 | 正式调用为 `v19_scan_zip(path, progress_cb)`，替身只接收一个参数，后台线程在 set Event 前即 TypeError |
| 缺少真实 `yolo11n.pt` | 1 | 测试依赖未准备 | 同样失败 | E2E 显式 prerequisite 断言 |
| 真实训练夹具缺 annotation CAS | 1 | 测试夹具合同 | 同样失败 | POST annotation 422；请求缺 `expected_version` 与 `source_content_sha256` |
| YOLO 扫描错误处理合同变化 | 1 | 旧测试合同 | 同样失败 | 现实现把读取期 `YoloImportError` 记录为 invalid issue，测试仍要求异常冒泡 |
| Windows SQLite 打开文件 unlink | 2 | Windows 文件锁环境 | 同样失败 | `WinError 32` |
| 外部发布 Event 被唯一 Owner 消费 | 1 | 测试夹具/并发竞态 | 同样失败 | 请求已 durable 标记，但运行中的 owner 在线程测试断言前清空 wake event |
| POSIX mode 位 | 1 | Windows 平台差异 | 同样失败 | Windows 得到 `0666`，测试硬断言 `0644` |
| 中文 display alias 被 canonical-code 合同拒绝 | 1 | 旧测试合同 | 同样失败 | `auto_label.py:119` 拒绝 `明火`，正式候选只接受 canonical code |
| POSIX SIGKILL | 1 | Windows 平台差异 | 同样失败 | Windows 无 `SIGKILL` 映射 |
| Windows loader workers 上限 | 1 | Windows 平台合同 | 同样失败 | 手动 6 workers 被正式上限 4 拒绝 |
| **合计** | **62** | VNext 新增回归 **0** | **62/62 同根因失败** | 基线失败项定向 JUnit `62 failed` |

### 3.1 每项名称、失败签名、堆栈位置和运行条件

以下编号对应新鲜 VNext JUnit。每个分组给出共同运行条件与首个业务堆栈；条目后给出该用例的实际失败签名。

#### P01：旧 API / 标签与标注夹具（18 项）

运行条件：Windows 全量 pytest、默认 pytest temp；旧基线同命令同失败。主要堆栈：`platform_core/annotation_repository.py:402::_assert_active_label_codes`、`platform_core/material_repository.py:1143::patch_annotation_projections`。

1. `tests/api/test_auto_label_candidates.py::test_auto_label_candidates_do_not_modify_annotation_until_confirmed` — HTTP 410：旧 v47 AI 标注接口已退役，要求 v60 durable review/decisions。
2. `tests/api/test_label_integrity.py::test_full_audit_uses_annotation_truth_without_fake_material_selection` — `AnnotationLabelStateError: ... head`。
3. `tests/api/test_label_integrity.py::test_audit_samples_use_current_annotation_truth_and_only_source_boxes` — `AnnotationLabelStateError: ... head`。
4. `tests/api/test_label_integrity.py::test_orphan_repair_revalidates_current_gt_and_freezes_only_still_affected` — `AnnotationLabelStateError: ... head`。
5. `tests/api/test_label_integrity.py::test_full_audit_includes_legacy_fallback_and_annotated_scope_only` — `AnnotationLabelStateError: ... scope_orphan`。
6. `tests/api/test_label_integrity.py::test_orphan_repair_rejects_target_that_is_no_longer_active` — `AnnotationLabelStateError: ... head`。
7. `tests/api/test_label_integrity.py::test_batch_repair_aggregates_mappings_per_image_and_writes_once` — `AnnotationLabelStateError: ... Helmet, No_Helmet, head`。
8. `tests/api/test_label_integrity.py::test_audit_exposes_final_active_merge_target_but_never_defaults_orphan` — `AnnotationLabelStateError: ... Helmet, head`。
9. `tests/api/test_label_integrity.py::test_batch_repair_submits_only_configured_sources_and_keeps_external_cas` — `AnnotationLabelStateError: ... head, unconfigured`。
10. `tests/api/test_label_integrity.py::test_repair_admission_holds_one_project_lock_through_freeze_and_create` — `AnnotationLabelStateError: ... head`。
11. `tests/api/test_label_integrity.py::test_repair_worker_treats_externally_resolved_stale_record_as_noop` — `AnnotationLabelStateError: ... head`。
12. `tests/api/test_label_integrity.py::test_merged_scope_fixture_repairs_once_and_stays_clean_across_full_audits` — `AnnotationLabelStateError`，多个未注册历史别名。
13. `tests/api/test_label_integrity.py::test_full_audit_reports_the_same_duplicate_gt_blocker_as_training` — `AnnotationLabelStateError: ... target`。
14. `tests/api/test_label_schema_performance.py::test_material_repository_aggregates_existing_label_usage` — usage 结果中 `scope_images=1`，旧断言为 0。
15. `tests/api/test_label_schema_performance.py::test_label_schema_get_uses_existing_material_index_without_annotation_io` — `smoke[usage_images]` 实际 0、旧断言 2。
16. `tests/api/test_material_integrity.py::test_material_integrity_audit_groups_duplicate_annotation_conflicts` — `AnnotationLabelStateError: ... target`。
17. `tests/api/test_material_integrity.py::test_durable_index_delete_removes_annotation_truth_but_keeps_shared_object` — `AnnotationProjectionConflictError`：同 material/version digest 冲突。
18. `tests/api/test_material_integrity.py::test_filtered_dog_delete_removes_only_dog_material_and_its_annotation_files` — `AnnotationLabelStateError: ... dog`。

#### P02：测试替身、路径断言与后台签名（4 项）

运行条件：Windows 单测，旧基线同失败。主要堆栈：`app.py:_v19_finalize_multipart_upload` 调用二参数 `v19_scan_zip`，测试替身位于 `tests/api/test_v19_multipart_background_finalize.py:61/108`。

19. `tests/api/test_material_response_performance.py::test_clean_confirmation_updates_only_frozen_selection_without_full_table_mutate` — `AttributeError: FakeArtifacts has no attribute artifact_path`。
20. `tests/api/test_v19_import_fifo.py::test_project_formal_import_lock_is_a_filesystem_lock` — Windows 路径后缀断言失败。
21. `tests/api/test_v19_multipart_background_finalize.py::test_multipart_complete_returns_before_background_scan_finishes` — `scan_started.wait(2.0) == False`；一参数 monkeypatch 在后台调用处先 TypeError。
22. `tests/api/test_v19_multipart_background_finalize.py::test_job_read_recovers_interrupted_multipart_finalize` — 同上。

#### P03：真实 E2E 前提/请求夹具（2 项）

23. `tests/e2e/test_real_onnx_conversion.py::test_real_yolo_checkpoint_exports_and_loads_as_onnx` — `AssertionError: 真实 ONNX 验收需要已准备的 yolo11n.pt`；运行目录及父目录均无 checkpoint。
24. `tests/e2e/test_real_yolo_training.py::test_real_cpu_training_produces_verified_version_and_report` — annotation POST 422；`tests/e2e/test_real_yolo_training.py:56-60` 没有提交正式 CAS 字段。

#### P04：Windows 路径长度（30 项）

运行条件：默认 `C:\Users\jorsam\AppData\Local\Temp\pytest-of-jorsam\...`。表层错误包括 `WinError 206`、安全解包验证失败、模型上传 PARTIAL/failed；把相同测试放到 `C:\pV4`、`C:\rV3`、`C:\mV4` 后相应集合转绿，因此不能仅凭表层报错归为产品逻辑错误。

25. `tests/integration/test_storage_import_worker.py::test_agent_yolo_review_label_mapping_writes_annotation_repository` — `RemoteMaterialImportError: review archive could not be safely verified`。
26. `tests/integration/test_storage_import_worker.py::test_agent_coco_voc_storage_scan_confirmation_writes_annotation_repository` — 同上。
27. `tests/integration/test_training_input_integrity_chain.py::test_mixed_jpeg_normalization_cache_restore_and_trainer_mutation_are_isolated` — `WinError 206`。
32. `tests/unit/test_external_algorithm_publish.py::test_durable_remote_conversion_root_is_discovered_and_appended` — `PARTIAL != PUBLISHED`；短路径通过。
33. `tests/unit/test_external_algorithm_publish.py::test_publish_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots` — 同上；短路径通过。
34. `tests/unit/test_model_artifacts.py::test_auto_upload_archives_original_and_conversion_for_local_algorithm` — uploaded 实际 1、期望 2；失败对象路径过长，短路径通过。
35. `tests/unit/test_model_artifacts.py::test_auto_upload_is_idempotent_and_keeps_one_index_per_content` — 同上。
36. `tests/unit/test_model_artifacts.py::test_auto_upload_discovers_durable_remote_conversion_root` — failed 实际 2、期望 0；短路径通过。
37. `tests/unit/test_model_artifacts.py::test_auto_upload_prefers_durable_remote_conversion_when_job_id_exists_in_both_roots` — 同上。
40. `tests/unit/test_remote_material_import.py::test_storage_scan_coco_review_commits_generic_detection_truth` — 安全解包验证失败；短路径通过。
41. `tests/unit/test_remote_material_import.py::test_detection_zip_review_round_trip_commits_embedded_annotation_truth[coco]` — 同上。
42. `tests/unit/test_remote_material_import.py::test_detection_zip_review_round_trip_commits_embedded_annotation_truth[voc]` — 同上。
43. `tests/unit/test_remote_material_import.py::test_storage_rescan_root_yolo_review_keeps_annotation_evidence_and_object_identity` — 同上。
44. `tests/unit/test_remote_material_import.py::test_storage_rescan_root_coco_carries_verified_json_source_evidence` — 同上。
45. `tests/unit/test_remote_material_import.py::test_storage_rescan_root_voc_carries_verified_xml_source_evidence` — 同上。
46. `tests/unit/test_remote_material_import.py::test_large_storage_scan_review_streams_verified_rows` — 同上。
47. `tests/unit/test_training_bundle_cache.py::test_verified_bundle_cache_restores_isolated_trainer_writable_images` — `WinError 206`。
48. `tests/unit/test_training_bundle_cache.py::test_cache_resolve_rejects_missing_member_without_rehashing_images` — `WinError 206`。
49. `tests/unit/test_training_bundle_cache.py::test_cache_restore_never_attempts_image_hardlinks` — `WinError 206`。
50. `tests/unit/test_training_bundle_cache.py::test_cache_publish_requires_final_verified_file_count` — `WinError 206`。
51. `tests/unit/test_training_bundle_cache.py::test_cache_is_project_scoped` — `WinError 206`。
52. `tests/unit/test_training_bundle_cache.py::test_cache_resolve_rejects_tampered_label` — `WinError 206`。
53. `tests/unit/test_training_bundle_cache.py::test_cache_resolve_rejects_tampered_data_yaml` — `WinError 206`。
54. `tests/unit/test_training_bundle_cache.py::test_cache_resolve_rejects_in_bundle_symlink_component` — `WinError 206`；短路径下 Windows 合理 skip symlink 项。
55. `tests/unit/test_training_bundle_cache.py::test_cache_resolve_refreshes_lru_access_metadata` — `WinError 206`。
56. `tests/unit/test_training_bundle_cache.py::test_cache_ttl_expiry_blocks_reuse_and_maintenance_evicts` — `WinError 206`。
57. `tests/unit/test_training_bundle_cache.py::test_cache_quota_evicts_lru_entry_but_protects_new_publish` — `WinError 206`。
58. `tests/unit/test_training_bundle_cache.py::test_cache_maintenance_skips_locked_active_entry` — `WinError 206`。
59. `tests/unit/test_training_bundle_cache.py::test_cache_schema_v2_is_rejected_after_writable_hardlink_fix` — `WinError 206`。
60. `tests/unit/test_training_bundle_cache.py::test_cache_restore_preserves_dataset_revision_evidence` — `WinError 3`；短路径通过。

#### P05：剩余平台/夹具合同（8 项）

28. `tests/unit/storage/test_yolo_import.py::test_yolo_text_identity_rejects_known_hash_change_with_same_size` — `DID NOT RAISE YoloImportError`；`scan_annotations` 当前把读取错误转为 invalid issue，旧测试仍要求异常冒泡。
29. `tests/unit/test_audit_v19_partial_import.py::test_auditor_reports_missing_annotation_db_and_report_identity_errors` — `WinError 32` unlink 已打开 SQLite。
30. `tests/unit/test_changlian_login_auth.py::test_logout_fails_closed_if_durable_revocation_store_is_missing` — `WinError 32` unlink 已打开 SQLite。
31. `tests/unit/test_external_algorithm_publish.py::test_auto_publish_request_only_marks_external_version_when_enabled` — durable 标记成功，但 `wait_for_external_publish_owner(0)` 得到 False；后台唯一 Owner 已消费 Event。
38. `tests/unit/test_production_upgrade.py::test_restore_only_git_tracked_file_modes_and_ancestor_directories` — Windows mode `0666 != 0644`。
39. `tests/unit/test_provider_parsing.py::test_candidate_parser_maps_unique_chinese_display_alias_to_label_code` — `ValueError: ... 标签库之外的标签：明火`；正式候选合同只接收 canonical code。
61. `tests/unit/test_training_final_validation_oom_hardening.py::test_real_incident_shape_is_recoverable_final_validation_failure` — Windows `process_signal is None`，旧断言要求 POSIX `SIGKILL`。
62. `tests/unit/test_training_startup_performance_contract.py::test_manual_workers_are_not_coupled_to_batch` — `RESOURCE_MANUAL_INVALID: Windows supports at most 4 loader workers`；夹具手动请求 6。

## 4. Chrome 差异结论

| 用例 | VNext 首轮 | 旧基线全量 | Trace / Network / Console 结论 |
|---|---|---|---|
| `changlian-login-auth...refresh...` | fail | fail | 默认 config 启动 8011 预认证测试服务器，而用例硬编码期望 8012 未登录态；使用 `playwright.auth.config.mjs` 后 2/2 通过 |
| `changlian-login-auth...mobile...` | fail | fail | 同上；默认服务器页面并非登录页 |
| `model-and-conversion...vision providers...` | fail | fail | 创建 AI 任务对话框没有旧夹具刚 POST 的模型文本；基线同断点，未见 VNext pageerror |
| `model-and-conversion...compiler resources...` | fail | fail | Trace 中 deployments 请求到真实服务器返回 404，版本转换对话框未创建；基线同断点 |
| `navigation-action-fencing-r2...clean confirmation...` | fail | fail | 旧 result fixture 不足以生成现合同的“确认应用清洗”按钮；基线同断点 |
| `navigation-action-fencing-r2...v60 AI...` | fail | fail | Trace pageerror：`review.labelMapping is not iterable`（`static/app.js:6902`）；手工构造 review 缺正式 `labelMapping`，POST 因此未发出；基线同断点 |
| `material-workflows...label management...` | 首轮 fail；修复夹具后 pass | 全量 pass | 首个 usage GET 已发出但尚未完成时跳页会触发 `net::ERR_ABORTED`；回访的第二次 GET 是正确恢复。夹具现等待正式 cache timestamp 后再验证 A→B→A，原“GET 次数不增加”断言不变；repeat 5/5、素材集合 22/22、最终全量 pass |
| `service-node-management...creates Agent credentials` | 独立运行曾 fail；修复夹具后 pass | 全量 pass；独立运行同断点 fail | 点击“展开高级功能”可早于启动重绘并被初始化状态覆盖；夹具在导航前显式写入同一正式 localStorage 开关。VNext repeat 3/3，最终全量 pass；业务导航和页面断言不变 |

VNext Node 24 定向真实 Chrome：质量评测/冻结图片/报告/场景跳转/严格对比/四档布局 + 训练恢复共 `7 passed`。认证专用 config `2 passed`。最终 Node 24 全量为 `143 passed, 6 failed`；仅余上表前六项，均有截图、Network/Console 与 Trace。

## 5. 重点业务复核

- 冻结图片：显式 Image ID、唯一 legacy `stored_name`、Snapshot ID、Test membership、bundle/source SHA 和实际响应字节 SHA 均 fail-closed；重复 stored name、同名不同图、Snapshot 漂移、内容漂移、缺 Snapshot 均有回归。20k Snapshot 命名索引复用与文件变更失效通过。
- 图片失败框层：Chrome 409 `snapshot mismatch` 用例确认图片错误时不保留 GT/预测 overlay；可验证 BMP 正常读取，框几何与同一原图尺寸映射一致。
- 场景算法实测：真实 Chrome 点击后落到 `质量中心` / `detect`，目标 Tab DOM 可见。
- 新 Epoch：历史只取一次；三次 compact polling 后 Epoch `[1,2]`，重开详情不再重复完整历史。
- 严格比较：按 `class_id`，相同 benchmark / protocol / input binding 才可比；退化类别显示，缺失 delta 为“未记录”，真实零为 `0.0 pp`。
- 训练报告：缺失资源、计数、指标保持 `null/未生成/未记录`，不转换为 0；实际 Batch/Workers/Precision 取 runtime truth。

## 6. 1000 Epoch / 720 采样传输口径

实测 payload：全量 `296,333 B`，compact `428 B`。统一按同一请求数计算：

- 首分钟总计 40 次状态请求：旧实现 `40 × 296,333 = 11.3042 MiB`；新实现 `1 × 296,333 + 39 × 428 = 0.2985 MiB`，完整历史首次加载已计入，下降 `97.36%`。
- 若表述为“首次打开 + 随后 40 次轮询”：旧实现 `41 × 296,333 = 11.5868 MiB`；新实现 `296,333 + 40 × 428 = 0.2989 MiB`，下降 `97.42%`。
- 稳态后续一分钟 40 次：旧 `11.3042 MiB`；新 `40 × 428 = 0.0163 MiB`，下降 `99.86%`。

此前文档中“旧 40 次”对比“新 1+40 次”的写法请求数不一致，本轮改为上述一致口径。SQLite 历史查询仍由全量每轮 4 次降为 compact 每轮 1 次。

## 7. 发布前结论

- VNext 相对 `30f83c48` 的 Python 新增回归：`0`。
- 6 个确定性 Chrome 失败：`30f83c48` 全量同名同断点复现；VNext 新增确定性回归：`0`。
- 首轮多出的标签管理项已定位为夹具过早跳页；另一个服务节点独立运行竞态也在旧基线复现。两者均只同步真实 UI 前置条件，不增加超时、不重试业务请求、不放宽断言。最终全量只剩与基线一致的 6 项。
- 本轮未修改生产代码；仅修改两处浏览器夹具和审计文档，不为旧失败盲目回退正式合同。GitHub Ubuntu CI、生产历史素材、真实 OSS、GPU/真实训练仍未执行，不能标记通过。
- 具备推送长期开发分支并让远端 CI 验证的条件；不具备发布/部署生产的充分条件。
