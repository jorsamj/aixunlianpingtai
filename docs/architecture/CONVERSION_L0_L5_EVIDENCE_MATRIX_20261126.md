# 转换一致性 L0–L5 证据矩阵（代码实况）

日期：2026-11-26。分支：`feature/external-algorithm-publishing`，基线 `2bc8a01f`。
本文只描述**当前代码实际做了什么**，每条结论给出 `file:line`。凡"代码只计算指标但没有门禁""只有编译/结构证据""没有实现"的，一律标为 **GAP** 或 **HARDWARE_PENDING**，不写成既有合同。

历史文档映射：任务给定的四份路径全部存在，无需 glob 替换：

- `docs/MODEL_CONVERSION_DETECTION_CONSISTENCY_2026_11_04.md`（L2/L3 原始设计、`compare_yolo_detections` 与阈值跨越）
- `docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md`（L1/L4 Sophon 编译合同与 NOT VERIFIED 边界）
- `docs/CONVERSION_VENDOR_FAILURE_AND_NUMERIC_GATES_2026_11_10.md`（厂商失败分类、`--compare_all`、RKNN 阶段码）
- `docs/ONNX_FP16_TOPOLOGY_FIX_2026_11_12.md`（L1 拓扑修复、FP16 余弦高但最大误差大的证据）

---

## 0. 端到端链路与唯一 Owner

```
PT/ONNX/Paddle 源
  └─ L0 源身份      conversion.build_source_manifest + deployment_worker.build_conversion_source_manifest
      └─ L1 ONNX    deployment_worker.prepare_onnx → onnx_topology.repair_onnx_topology → validate_onnx_runtime
          └─ L4 厂商产物   build_sophon / build_rockchip / build_ascend / build_tensorrt（只编译）
              └─ L2/L3 数值与检测    numeric_consistency.verify_images（PT vs ONNX，可选 ONNX vs BMODEL）
                  └─ 证据         numeric-validations/<nv_id>/evidence/<verification_id>.json（不可变）
                      └─ 摘要     jobs/<job_id>/job.json  numeric_status/publication_status/numeric_validation
                          └─ L5 交付准入   model_artifacts.delivery_artifact_quality_preflight
                                            → numeric_consistency.assert_delivery_quality_eligibility
```

下单点：转换任务仍是 `MODEL_CONVERSION` durable 任务（`platform_core/deployment/conversion_tasks.py:141`），数值验证是同一 TaskKind 的独立 `execution_mode=numeric_verification` 运行（`conversion_tasks.py:242`），不新增第二套任务/数据库。

---

## 1. 汇总表（先看结论）

| 级别 | 现有合同（代码真的做） | 真的门禁在哪 | 结论 |
|---|---|---|---|
| L0 | 源 SHA256/大小/文件名、export 参数、产物 SHA/大小、manifest 不可变摘要；Sophon 额外冻结 `label_codes`/`label_schema`/`label_binding` | `build_source_manifest` 强制 64-hex；`SOURCE_IDENTITY_MISMATCH`；`conversion_identity` 重算实际字节并判 conflict | **部分**：源身份强；类别集合只在 Sophon 冻结（GAP G1） |
| L1 | ONNX Checker + ONNX Runtime 空输入真实加载、真实输入/输出 shape/dtype、opset；仅节点顺序的安全拓扑修复 | Checker/Runtime 失败即 `ConversionError`，不登记产物 | **已完成（软件）**：不证明 PT 精度（明确记录 `pt_onnx_numeric_validation=not_performed`） |
| L2 | 同图 LetterBox RGB 张量的 PT 原始输出 vs ONNX Runtime：MAE/P95/max/归一化 MAE/余弦，容忍度 fp32 0.005、fp16 0.05、bf16 0.07 + 余弦≥0.999 | `compare_tensors.within_tolerance`；未知精度直接不可比 | **已完成（CPU）**：全局指标可被大 max_abs_error "稀释"（GAP G8） |
| L3 | 外部类别感知 NMS 后的框/类别/置信度/IoU 对照、阈值跨越、新增/缺失框、按类统计 | `compare_yolo_detections.within_tolerance` → `verify_images.verdict` | **已完成（仅单输出 YOLO11 布局）**；阈值跨越只提示不门禁（GAP G4） |
| L4 | Sophon 编译（合成输入官方数值对照）+ `model_tool` 芯片结构；RKNN 编译阶段码；RKNN 板端验收记录校验；Ascend 只编译 | `hardware_verified` 未真实验证时厂商目标一律 `BLOCKED_BY_HARDWARE` | **HARDWARE_PENDING**：无任何真实 BM1684/BM1684X/BM1688/RKNN/Ascend 板端证据（G3/G6） |
| L5 | 不可变证据 + 身份/摘要/样本集/投影绑定 + 冻结结论 + 运行时验证 +（本轮新增）BMODEL 自身证据 | `assert_delivery_quality_eligibility` + `delivery_artifact_quality_preflight` | **部分**：BMODEL 缺口本轮关闭；标签身份缺失仍放行（G1）；RKNN/TRT/OM 无目标级数值（G6） |

---

## L0 源 / 模型身份（PT SHA、大小、格式、标签集合）

| 项 | 内容 |
|---|---|
| 输入 | 源模型文件（`.pt/.pth/.onnx/.pdparams…`）、算法版本冻结信息、转换参数 `target/params` |
| 输出 | `source_manifest`（`schema_version=1`）：`source{sha256,size_bytes,file_name,algorithm_id,version_id,artifact_id[,label_codes,label_schema,label_binding,training_lineage,sha256_recheck]}`、`export{opset,dynamic,simplify,batch,imgsz,precision,half,reused_existing_onnx}`、`tool{name,version,python_path,dependencies}`、`onnx{...}`、`outputs[{name,sha256,size_bytes}]` |
| 权威 Owner | `platform_core/conversion.py:129 build_source_manifest`（唯一 schema）；写入口 `deployment_worker.py:777 build_conversion_source_manifest`；读取/重算身份 `platform_core/deployment/numeric_consistency.py:849 conversion_identity` |
| 验证方法 | ① SHA256 必须 64-hex（`conversion.py:39`）；② `export` 七个字段缺一即拒绝（`conversion.py:185-198`）；③ 产物名/SHA/大小强校验，空产物或 >512 拒绝（`conversion.py:108-126`）；④ 不可变投影排除可变交付字段后重算摘要（`conversion.py:16-22,240-268`）；⑤ 转换前源字节复核（`deployment_worker.py:862-880`）；⑥ 验证前按实际字节重算 PT/ONNX/目标产物 SHA 并与请求/manifest 交叉比对（`numeric_consistency.py:879-1024`） |
| 实际错误码 | `ValueError`：`"...必须是 64 位 SHA256 摘要"`、`"source manifest 必须包含至少一个真实产物"`、`"manifest 含无法规范编码的字段"`（无稳定业务码，属内部合同）；`ConversionError('SOURCE_IDENTITY_MISMATCH')`（`deployment_worker.py:868`）；`ConversionError('MODEL_CLASS_IDENTITY_MISMATCH')`（`deployment_worker.py:574`，Sophon 编译前 PT `names` 与冻结顺序逐项比对）；`numeric_consistency.validate_paths` 的 `ValueError("…SHA256 不一致…")`（`numeric_consistency.py:428`）；`conversion_identity` 的问题码（非异常）：`SOURCE_PT_SHA_MISMATCH`、`SOURCE_PT_ARTIFACT_MISSING`、`ONNX_SHA_MISMATCH`、`ONNX_ARTIFACT_MISSING`、`CONVERSION_LAYOUT_UNAVAILABLE`、`CONVERSION_JOB_RECORD_MISSING/UNREADABLE`、`CONVERSION_JOB_ID_MISMATCH`、`CONVERSION_PROJECT_MISMATCH`、`MANIFEST_DIGEST_MISMATCH`、`MANIFEST_DIGEST_CONFLICT`、`TARGET_ARTIFACT_SHA_MISMATCH`、`TARGET_ARTIFACT_MISSING`（`numeric_consistency.py:868-1023`） |
| 证据位置 | `jobs/<job_id>/artifacts/manifest.json`（`manifest_digest`、`manifest_integrity`、`source_manifest`）；`jobs/<job_id>/job.json` 的 `source_trace/source_sha256_recheck/manifest_digest`；数值证据 `identity` 块（`numeric_consistency.py:1205-1229`） |
| 恢复 / 重试 | manifest 摘要不一致 = conflict → 身份 `stale`，拒绝覆盖已发布摘要并保留旧证据（`numeric_consistency.py:1313-1365,1423-1433`）；重试只会重新投影同一身份，不会静默改写 |
| CI 覆盖 | `.github/workflows/remote-conversion-runtime.yml`（`control-plane` 跑 `tests/unit/test_conversion_tasks.py`、`tests/api/test_conversion_portable_contract.py` 等）；`.github/workflows/v42.25-release-regression.yml`（`runtime-contracts`）；`.github/workflows/external-algorithm-publish.yml`（`contract`） |
| 真实硬件 | 不涉及 |
| 缺口 | **G1（标签集合）**：`label_codes/label_schema/label_binding` 只在 `target == "sophon"` 时写入 `source_trace`（`platform_core/conversion_management_service.py:803-819`）。ONNX/RKNN/TensorRT/Ascend 转换的 manifest `source` 没有标签证据；数值验证随后得到 `label_identity.status="unknown"`（`numeric_consistency.py:303-323`），L5 仍放行（`numeric_consistency.py:1905` 只拒 `conflict/mismatch`）。这与 42.24.523 文档里"P0 类别身份、需要独立补证流程"一致，属**已知未解决缺口**，不是合同。 |

---

## L1 结构（ONNX 导出参数、拓扑顺序、Checker）

| 项 | 内容 |
|---|---|
| 输入 | 源模型 + export 参数（opset/dynamic/simplify/batch/imgsz/precision/half）+ 目标芯片合同 |
| 输出 | 真实 ONNX 文件、`manifest.onnx{opset_imports,input_shapes,input_types,input_names,output_shapes,output_types,output_names,output_inferred_shapes,output_dtypes,floating_tensor_types}`、`execution_evidence.onnx_topology{status,applied,node_count,moved_nodes,checker,runtime}` |
| 权威 Owner | `deployment_worker.py:203 export_pt_to_onnx`（导出）、`:349 prepare_onnx`（拓扑→颜色适配）、`platform_core/onnx_topology.py:51 repair_onnx_topology`、`deployment_worker.py:409 validate_onnx_runtime`（Checker + ORT） |
| 验证方法 | ① 导出参数冻结进 manifest，缺字段拒绝（`conversion.py:185-198`）；Sophon 强制 `opset=12/simplify=false`（`conversion.py:445-446`）、静态输入/`batch=1`/`num_core=1`（`conversion.py:440-444`）；② 拓扑：建立生产者/消费者索引，检查 SSA 唯一性、输入/输出完整性，用稳定 Kahn 排序；稀疏权重、外部权重、控制流/子图、重复生产者、循环一律拒绝自动修复（`onnx_topology.py:31-48,68-125`）；只重排 `NodeProto` 顺序，前后各跑一次 `onnx.checker`，原文件保留、修复副本独立命名（`onnx_topology.py:126-155`）；③ Checker 后仍用 ONNX Runtime 真实 `session.run`（空白输入）加载并记录实际 shape/dtype（`deployment_worker.py:409-481`） |
| 实际错误码 | `ONNX_GRAPH_TOPOLOGY_INVALID`、`ONNX_GRAPH_REPAIR_FAILED`（`onnx_topology.py:17-28`）；`ONNX_GRAPH_TOPOLOGY_INVALID` / `ONNX_RUNTIME_LOAD_FAILED` / `ONNX_RUNTIME_INFERENCE_FAILED` / `ONNX_VALIDATION_FAILED`（`deployment_worker.py:483-493`）；环境/工具类 `TENSORRT_NOT_FOUND`、`ATC_NOT_FOUND`、`RKNN_TOOLKIT_NOT_FOUND`、`TPU_MLIR_NOT_FOUND/UNAVAILABLE`（`deployment_worker.py:373-406`、`sophon_runtime.py:17`） |
| 证据位置 | `manifest.onnx.*`、`manifest.execution_evidence.onnx_topology`、`jobs/<id>/work/*.onnx`（原始导出保留） |
| 恢复 / 重试 | 拓扑只在"可证明安全"时重排；失败即 `ConversionError`，不登记产物；旧的同名 `.rknn/.bmodel` 在重试前显式删除，避免复用失败产物（`deployment_worker.py:589-591,722-723`） |
| CI 覆盖 | `.github/workflows/remote-conversion-runtime.yml` 的 `control-plane` 显式运行 `tests/unit/test_onnx_topology.py`；`.github/workflows/isolated-pt-export-cpu.yml`（真实 CPU 导出合同） |
| 真实硬件 | 不涉及 |
| 缺口 | 无。**明确边界**：Checker + 空输入 ORT 通过只证明"可加载/可跑"，代码自己把 `pt_onnx_numeric_validation` 记为 `not_performed`（`deployment_worker.py:1014`），不冒充 PT 精度一致。 |

---

## L2 张量 / 数值一致性（ONNX Runtime、FP16 容忍度、余弦/差异）

| 项 | 内容 |
|---|---|
| 输入 | 1–12 张真实图片；PT + ONNX；冻结 `precision`、`confidence`、`nms_iou`、`input_shapes/frozen_imgsz/frozen_batch`、`preprocessing`、`label_codes/label_schema` |
| 输出 | 每图：`comparable`、`shape/element_count`、`mean_abs_error`、`p95_abs_error`、`max_abs_error`、`normalized_mae`、`cosine_similarity`、`within_tolerance`、`normalized_mae_limit`；汇总：`raw_verdict`、`metrics{normalized_mae_max,cosine_similarity_min,max_abs_error_max,within_tolerance}` |
| 权威 Owner | `numeric_consistency.py:69 compare_tensors`、`:586 verify_images`、`:476 _resolve_input_contract`、`:1075 verification_parameters`、`:1114 verification_summary` |
| 验证方法 | 同一 LetterBox（OpenCV `INTER_LINEAR`、RGB、0..1、NCHW，`numeric_consistency.py:351-389`）张量分别喂 PT（float32）与 ONNX Runtime（按图输入 dtype 转 fp16/fp32，`:658`）；比较 fp32 0.005 / fp16 0.05 / bf16 0.07 的**归一化 MAE** + 余弦≥0.999；NaN/Inf/形状不一致/非数值/未知精度一律 `comparable=false`（`:69-98`）；动态图无冻结尺寸、batch≠1、形状冲突、超范围分别给出稳定码（`:476-556`） |
| 实际错误码 | `DYNAMIC_INPUT_WITHOUT_FROZEN_IMGSZ`、`NON_SINGLE_IMAGE_BATCH`、`DYNAMIC_BATCH_WITHOUT_FROZEN_BATCH`、`INPUT_SHAPE_CONFLICT`、`INPUT_SIZE_OUT_OF_RANGE`、`NON_RGB_INPUT_NOT_COMPARABLE`（`numeric_consistency.py:27-28,492-556,589-600`）；运行时缺失抛 `ValueError("PT/ONNX 数值比较需要已配置的 torch/ultralytics 运行时…")`（`:631-639`） |
| 证据位置 | `numeric-validations/<nv_id>/result.json`（每图指标）；不可变证据 `evidence/<verification_id>.json` 的 `result_summary.metrics` + `parameters.digest`；`runtime_versions`（真实导入版本或显式 null） |
| 恢复 / 重试 | `run_verification_directory`：已完成且带 evidence 的结果只重试幂等发布，不重算（`numeric_consistency.py:1539-1560,1505-1514`）；进程死亡由 `reconcile_numeric_verification` 收敛（`:1517-1537`）；同身份不同结论拒绝覆盖（`VerificationEvidenceConflict`，`:756-760,1252-1287`） |
| CI 覆盖 | `.github/workflows/remote-conversion-runtime.yml` 的 `control-plane` 运行 `tests/unit/test_conversion_numeric_consistency.py`、`tests/api/test_conversion_numeric_validation.py`；真实 PT/ONNX 集成测试 `tests/integration/test_real_pt_onnx_numeric.py` **没有被任何 workflow 的显式清单引用**（本机依赖齐备时可运行，见 §7、§9）；只有运行整个 `tests` 的 job（`pytest.ini` 的 `testpaths = tests`）才会顺带收集它，缺依赖时模块级 skip（`tests/integration/test_real_pt_onnx_numeric.py:29-42`） |
| 真实硬件 | 仅 CPU ONNX Runtime；`hardware_verified=false` 恒为 False（`numeric_consistency.py:703`） |
| 缺口 | **G8**：容忍度是全局归一化 MAE + 余弦，`max_abs_error` 只记录不门禁；`docs/ONNX_FP16_TOPOLOGY_FIX_2026_11_12.md:9` 已记录"余弦 0.99999996、最大绝对差 0.807"的情况。检测层（L3）是设计上的兜底，不是张量层门禁。 |

---

## L3 检测结果一致性（框/类别/置信度/IoU/NMS/阈值跨越/新增缺失/类别顺序）

| 项 | 内容 |
|---|---|
| 输入 | 同图 PT 与 ONNX（以及可选 BMODEL）原始输出张量；`class_count`；冻结 `confidence`、`nms_iou`、匹配 IoU；LetterBox geometry 与原始尺寸 |
| 输出 | `detection_status`；每图 `detection{before_nms_*,after_nms_*,threshold_crossings,unmatched_reference,unmatched_converted,matched_pairs,mean_matched_iou,matched_confidence_drifts,per_class[],reference_detections[],converted_detections[],original_coordinates{status,mapped,unmapped,error_codes}}`；汇总 `detection{matched_pairs,unmatched_*,threshold_crossings,mean_matched_iou_min,original_coordinates_status,within_tolerance}` |
| 权威 Owner | `numeric_consistency.py:116 compare_yolo_detections`；类别顺序 `:303 verify_label_identity`（依赖 `platform_core/model_metadata.py:52 frozen_weight_labels`）；最终判定 `:586 verify_images`（`:693-706`） |
| 验证方法 | 仅支持**明确的单输出 YOLO11 XYWH + 类别分数**布局；外部类别感知 NMS（同类别 IoU>0.7 抑制）；每图候选上限 512、保留上限 300（超限即不可比，不截断冒充一致）；类别/框 IoU≥0.95 且置信度差≤0.02 才算匹配；`threshold_crossings` 统计阈值前后跨越；检测框可按 geometry 还原到原图像素（复用 `platform_core.auto_label.adapt_coordinates`，`:101-113`） |
| 实际错误码 | 无可抛异常码；不可比原因写入 `reason`（"不是相同形状的单输出 YOLO 检测张量""输出不是唯一可识别的 XYWH + 类别分数布局""超过单图 512 个候选框…""NMS 后超过 300 个框…"`，`numeric_consistency.py:126-186`）；坐标还原失败码 `PREPROCESSING_GEOMETRY_UNAVAILABLE` / 适配器异常码（`:106-107,268-275`） |
| 证据位置 | `result.json` 的 `images[].detection`；不可变证据 `result_summary.detection`（只保留有界聚合，不是每图全量） |
| 恢复 / 重试 | 同 L2：证据不可变、同身份冲突拒绝覆盖；`numeric_status` 投影可重试（`numeric_consistency.py:1505-1514`） |
| CI 覆盖 | `.github/workflows/remote-conversion-runtime.yml` 的 `control-plane`（`test_conversion_numeric_consistency.py` 覆盖阈值跨越/类别映射/NMS 压制）；前端质量中心另有 Node/Chrome 用例（`tests/frontend/conversion-numeric-workbench.test.mjs`） |
| 真实硬件 | 不涉及 |
| 缺口 | **G4**：`threshold_crossings` 只统计/展示，不参与 `within_tolerance`（`:299`）。设计意图是"被 NMS 压制的无害跨越不判不一致"（`test_yolo_detection_comparison_does_not_fail_on_suppressed_duplicate_anchor`），因此只有**最终 NMS 集合**变化才算失败。**G5**：融合 NMS/多头/多输出布局一律"不可比"，不是通过。**G1**：类别顺序只在 Sophon manifest 冻结标签时可证；否则 `verify_label_identity` 返回 `unknown`，PT/ONNX 内部一致仍算 `consistent`。 |

---

## L4 真实硬件（BM1684/BM1684X/BM1688 BModel、RKNN、Ascend）

| 项 | 内容 |
|---|---|
| 输入 | ONNX + 芯片/精度/校准 + 厂商 SDK 资源（显式 `python_path`/`tool_root`）；RKNN 板端另需在线匹配节点与测试图 |
| 输出 | 厂商产物（`.bmodel/.rknn/.om/.engine`）、`sophon_validation.json`、`manifest.hardware_verification`（仅 RKNN 板验）、`blocked_by_hardware` 任务状态 |
| 权威 Owner | Sophon：`platform_core/sophon_runtime.py:67 probe_sophon_toolchain`/`:135 require_sophon_toolchain` + `deployment_worker.py:579 build_sophon`；RKNN 工具：`platform_core/rknn_runtime.py:31 probe_rknn_toolkit` + `deployment_worker.py:699 build_rockchip`；RKNN 板端：`platform_core/rknn_board_runtime.py:15 detect_rockchip_soc`/`:49 probe_rknn_board_runtime` + `conversion_management_service.py:960-1168` 的验收记录校验；Ascend：`conversion.py:484-496` + `deployment_worker.py:656 build_ascend` |
| 验证方法 | Sophon：工具自检（`model_transform/model_deploy/model_tool --version`、chip/quantize choices 交集）、`model_transform --test_input/--test_result` + `model_deploy --test_input/--test_reference` 的**合成张量**官方数值对照（`:536-558,602-627`）、`model_tool --info` 唯一芯片结构检查（`:629-635`）、PT 类别名与冻结映射逐项比对（`:561-576`）；RKNN：config/load_onnx/build/export_rknn 阶段码（`deployment_worker.py:160-186`）、非空产物 + SHA（`:734`）；RKNN 板验：`hardware_verification` 必须含 chip/task_id/node_id/engine=`rknn-lite2`/model SHA+size/input SHA+size/inference_ms/output_count/execution_generation（`conversion_management_service.py:1060-1156`）；Ascend：仅 ATC 编译（`deployment_worker.py:656-695`） |
| 实际错误码 | `TPU_MLIR_NOT_FOUND`、`TPU_MLIR_UNAVAILABLE`（`sophon_runtime.py:17,71,131`）；`SOPHON_COMPARE_ALL_UNAVAILABLE`、`SOPHON_REFERENCE_INPUT_TOO_LARGE/SHAPE/DTYPE`、`SOPHON_MODEL_CHIP_MISMATCH`、`SOPHON_OFFLINE_REFERENCE_FAILED`、`SOPHON_DEPLOY_TIMEOUT`、`SOPHON_DEPLOY_FAILED`（`deployment_worker.py:128-158,539-549,596,634`）；`RKNN_ONNX_DEPENDENCY_INCOMPATIBLE`、`RKNN_CONFIG_FAILED`、`RKNN_LOAD_ONNX_FAILED`、`RKNN_BUILD_FAILED`、`RKNN_EXPORT_FAILED`、`RKNN_CONVERSION_TIMEOUT`、`RKNN_CONVERSION_FAILED`、`RKNN_TOOLKIT_NOT_FOUND`（`rknn_runtime.py:12`、`deployment_worker.py:160-186,388-405`）；`TENSORRT_NOT_FOUND`、`ATC_NOT_FOUND`（`deployment_worker.py:378-382`） |
| 证据位置 | `manifest.sophon_validation`（`structure=passed`、`model_validation_status=incomplete`、`compiler_numeric_status=passed_synthetic_reference|unavailable`、`offline_reference{protocol,input,reference,compare_all,comparison_scope}`，`deployment_worker.py:636-652`）；`manifest.inference_contract`（`caller_acknowledged=false`，`:1042-1058`）；`manifest.hardware_verification`（RKNN 板验）；数值验证里的 `bmodel_numeric_status`/`bmodel_detection_status`（`numeric_consistency.py:710-711`） |
| 恢复 / 重试 | 厂商失败按阶段分类后重试（`docs/CONVERSION_VENDOR_FAILURE_AND_NUMERIC_GATES_2026_11_10.md`）；重试前删除同名旧产物；`blocked_by_hardware` 由 `conversion_tasks.py:62-76` 映射为 `TaskStatus.BLOCKED_BY_HARDWARE`，不会被标成成功 |
| CI 覆盖 | `.github/workflows/remote-conversion-runtime.yml`（`control-plane`：sophon/rknn 单元与 API 合同）；`.github/workflows/remote-rknn-board-runtime.yml`（`contract`/`api`/`real-chrome`）；`.github/workflows/external-algorithm-publish.yml`；**`tests/hardware/test_vendor_conversion.py` 需要 `XJALGO_VENDOR_TARGET` / `XJALGO_SOPHON_HARDWARE_TEST=1` 才运行，没有任何 workflow 设置这些变量或显式执行它**（`tests/hardware/test_vendor_conversion.py:14-31`），整仓 `pytest` job 只会把它收集为 skip |
| 真实硬件状态 | **HARDWARE_PENDING**。代码内没有 BM1684/BM1684X/BM1688 板端加载/推理路径；`hardware_verified` 恒为 False（`deployment_worker.py:963`）；RKNN 板验代码路径完整但本仓库/本机没有真实板卡证据；Ascend 只有编译，**未实现** Runtime/板端验证；TensorRT 只有编译。`accuracy_verified=false`（`conversion_management_service.py:1148`） |
| 缺口 | **G3**：ONNX↔BMODEL 对照依赖可选的本机 Sophon 模拟器（`numeric_consistency.py:404-425`），SDK 不在场时 `bmodel_numeric_status=unavailable` 仍是常态；本轮 L5 已把这个"常态"判为不可正式交付（见 §7），但真实文件比较仍 HARDWARE_PENDING。**G6**：RKNN/TensorRT/Ascend 没有任何目标级数值对照实现，L5 的数值证据只覆盖 PT/ONNX。 |

---

## L5 交付准入

| 项 | 内容 |
|---|---|
| 输入 | `request.json`、`result.json`、不可变 `evidence/<verification_id>.json`、`jobs/<job_id>/job.json`、`manifest.json`、真实产物字节（PT/ONNX/目标产物/样本图）、ModelArtifact 行 |
| 输出 | `delivery-quality-eligibility-v1`（eligible/code/reasons/failure_codes/identity/binding/sample/projection/bmodel…）；`delivery-quality-preflight-v1`（`formal_activation_eligible`、`delivery_presentation`、`attachment_delivery_allowed`、`hardware_acceptance`）；`job.json` 的 `numeric_status`/`publication_status`/`numeric_validation` |
| 权威 Owner | 准入：`numeric_consistency.py:1679 assert_delivery_quality_eligibility`；摘要投影：`:1380 project_numeric_status`；交付判定：`platform_core/model_artifacts.py:198 delivery_artifact_quality_preflight`（`:294` formal、`:316` attachment）；外部发布只读投影：`platform_core/external_algorithm_publish.py:4191 artifact_delivery_quality_projection`；转换任务投影：`conversion_management_service.py:1532 _conversion_delivery_quality_projection` |
| 验证方法 | 只读、可重算：证据文件可读 + `content_digest`/`identity_digest`/`verification_id` 重算一致；8 个身份字段齐全并与当前 job/manifest/产物字节逐项相等；样本集摘要与当前图片一致；冻结摘要 `status=completed`、`verdict/raw_verdict/detection_status=consistent`、张量与检测 `within_tolerance=true`、`sample_count≥1`、无 rejection、标签非 `conflict/mismatch`、`deployment_preprocessing_aligned=true`；job 摘要绑定同一 verification_id/content_digest；**（本轮新增）BMODEL 交付物必须有 ONNX↔BMODEL 数值与检测 `consistent`**；`delivery_artifact_quality_preflight` 另要求模型字节 SHA 匹配、`manifest_integrity_status=digest_verified`、`conversion_identity_verified=true`、`runtime_verified=true` 才给正式激活（`model_artifacts.py:224-296`） |
| 实际错误码 | `EVIDENCE_DIRECTORY_INVALID`、`EVIDENCE_REQUEST_UNREADABLE`、`EVIDENCE_RESULT_UNAVAILABLE`、`EVIDENCE_BINDING_MISSING`、`EVIDENCE_ID_INVALID`、`EVIDENCE_REF_UNSAFE/UNREADABLE`、`EVIDENCE_SCHEMA_UNSUPPORTED`、`EVIDENCE_ID_MISMATCH`、`EVIDENCE_DIGEST_MISMATCH`、`EVIDENCE_RESULT_MISMATCH`、`IDENTITY_INCOMPLETE`、`IDENTITY_DIGEST_MISMATCH`、`STALE_VERIFICATION_RESULT`、`EVIDENCE_IDENTITY_UNVERIFIED`、`IDENTITY_EXPECTATION_MISMATCH`、`EVIDENCE_SAMPLE_SET_CHANGED`、`VERDICT_STATUS_UNAVAILABLE`、`VERDICT_UNEXPLAINABLE`、`NUMERIC_VERDICT_NOT_ELIGIBLE`、`RAW_VERDICT_NOT_ELIGIBLE`、`DETECTION_VERDICT_NOT_ELIGIBLE`、`TENSOR_TOLERANCE_UNAVAILABLE`、`DETECTION_TOLERANCE_UNAVAILABLE`、`BMODEL_EVIDENCE_NOT_ELIGIBLE`（新增）、`SAMPLE_COUNT_UNAVAILABLE`、`VERDICT_REJECTED`、`LABEL_IDENTITY_CONFLICT`、`PREPROCESSING_ALIGNMENT_UNVERIFIED`、`PROJECTION_BINDING_MISMATCH`、`PROJECTION_IDENTITY_MISMATCH`、`PROJECTION_VERDICT_MISMATCH`、`PROJECTION_INCOMPLETE`（`numeric_consistency.py:1736-1938`）；preflight 侧 `MODEL_BYTES_MISSING`、`MODEL_SHA_MISMATCH`、`CONVERSION_IDENTITY_UNVERIFIED`、`MANIFEST_DIGEST_UNVERIFIED`、`NUMERIC_EVIDENCE_MISSING`、`NUMERIC_STATUS_WITHOUT_EVIDENCE`、`RUNTIME_VERIFICATION_UNAVAILABLE`、`ELIGIBILITY_CHECK_FAILED`、`PROJECTION_BINDING_MISMATCH/DIGEST_MISMATCH`（`model_artifacts.py:233-291`）；写入侧 `STALE_VERIFICATION_RESULT`、`VERIFICATION_EVIDENCE_CONFLICT`（`numeric_consistency.py:747-748`） |
| 证据位置 | 证据文件按内容寻址不可变（`numeric_consistency.py:1248-1287`）；`job.json.numeric_validation{verification_id,content_digest,evidence_ref,identity,parameters,sample_set,summary}`；ModelArtifact `metadata.numeric_validation`（`model_artifacts.py:79-137`） |
| 恢复 / 重试 | 证据先落盘再写摘要（`run_verification_directory`，`:1539-1629`）；写投影失败只重试投影；身份变化 → `stale`，拒绝覆盖并保留旧摘要（`:1423-1433`）；同身份同内容幂等 `already_projected` |
| CI 覆盖 | `.github/workflows/external-algorithm-publish.yml` 的 `contract`（`tests/unit/test_model_artifacts.py`、发布/交付投影）；`.github/workflows/remote-conversion-runtime.yml` 的 `control-plane`（`tests/unit/test_conversion_numeric_consistency.py`、`tests/api/test_conversion_numeric_validation.py`）；`.github/workflows/v42.25-release-regression.yml` |
| 真实硬件 | 不产生硬件结论：`hardware_verified` 只读取既有证据，L5 从不设置它 |
| 缺口 | **G1**（标签身份 unknown 放行）；**G6**（RKNN/TRT/OM 无目标级数值对照）；**G10**（`model_artifacts.py:286-291` 在存在 `numeric_evidence.reasons` 时不会把它们并入 artifact 级 `reasons`，正式激活仍被 `numeric_eligible` 挡住，但 artifact 行 `code` 可能为空——展示层缺口，不是放行）。 |

---

## 6. 缺口清单（GAP，不是合同）

| 编号 | 缺口 | 代码证据 | 现状 |
|---|---|---|---|
| G1 | 类别顺序/标签集合只在 Sophon 转换冻结；其它转换的数值验证 `label_identity=unknown`，L5 仍判 eligible | `conversion_management_service.py:803`；`numeric_consistency.py:303-323,1905` | **未解决**（历史文档 42.24.523 已列为 P0 类别身份，需要独立补证流程；本轮未动，避免把历史证据静默作废） |
| G2 | BMODEL 交付物的 PT/ONNX 证据即可让 `assert_delivery_quality_eligibility` 返回 `eligible=true`，即使 BMODEL 从未比较 | `numeric_consistency.py:1679-1938`（修复前无 bmodel 判定） | **本轮已关闭**（§7） |
| G3 | ONNX↔BMODEL 比较依赖可选本机 Sophon 模拟器；不可用时 `unavailable` 是常态 | `numeric_consistency.py:404-425,670-691`；`deployment_worker.py:636-652` | 未解决；现在会阻止正式交付（fail closed），真实比较仍 HARDWARE_PENDING |
| G4 | `threshold_crossings` 只统计不门禁 | `numeric_consistency.py:194,299` | 有意设计（NMS 压制的无害跨越） |
| G5 | 只支持单输出 YOLO11 XYWH+类别分数；融合 NMS/多头/多输出一律不可比 | `numeric_consistency.py:133-143` | 明确未支持，不是通过 |
| G6 | RKNN/TensorRT/Ascend 没有目标级数值对照；L5 数值证据只覆盖 PT/ONNX | `numeric_consistency.py` 无 rknn/trt/om 比较；`deployment_worker.py:699-735,656-695` | 未实现；RKNN 正式激活依赖板端 `runtime_verified`，不是精度验收 |
| G7 | 真实 PT/ONNX 集成测试与新矩阵测试不在转换类 workflow 的显式清单中 | `remote-conversion-runtime.yml:236-269` 未列出 `tests/integration/test_real_pt_onnx_numeric.py`、`tests/unit/test_conversion_consistency_matrix.py`；仅整仓 `pytest` job 会收集（`pytest.ini:2 testpaths = tests`） | 需要 lead 决定是否把两者加入 `remote-conversion-runtime.yml` 的 `control-plane` 清单 |
| G8 | FP16 容忍度是全局归一化 MAE+余弦，`max_abs_error` 不门禁 | `numeric_consistency.py:69-98` | 有意设计，L3 兜底 |
| G9 | `result.json` 在运行中可重写（进度），只有 evidence 文件不可变 | `numeric_consistency.py:1289-1295,1558-1565` | 准入只读 evidence，不读可变 result |
| G10 | artifact 级 `reasons` 可能不含 numeric 拒绝原因（`code` 为空） | `model_artifacts.py:286-291` | 展示层缺口 |

---

## 7. 本轮关闭的缺口（D2）

**缺口**：BMODEL 转换（`target=sophon`，`bmodel_expected=true`）的交付准入只看 PT↔ONNX。证据文件其实已经记录了 ONNX↔BMODEL 的数值与检测结论（`bmodel_numeric_status`/`bmodel_detection_status`），但 `assert_delivery_quality_eligibility` 从未读取它们，因此：

- BMODEL 从未比较（模拟器不可用）→ 仍 `eligible=true`；
- ONNX↔BMODEL 检测已不同 → 仍 `eligible=true`。

**RED 证据（修复前）**：新增测试在未改生产代码时失败于
`assert verdict["eligible"] is False` → `assert True is False`，即当时返回 `eligible=True`。

**修复（最小）**：`platform_core/deployment/numeric_consistency.py`

- 新稳定码 `BMODEL_EVIDENCE_NOT_ELIGIBLE = "BMODEL_EVIDENCE_NOT_ELIGIBLE"`（`:33`）。
- `assert_delivery_quality_eligibility` 依据**已冻结**的 `parameters.bmodel_expected` 或身份 `target_artifact_kind ∈ {sophon,bmodel}` 判定"BMODEL 交付物"，并要求 `bmodel.numeric_status == "consistent"` 且 `bmodel.detection_status == "consistent"`；否则记入 `failure_codes` 并拒绝（`:1858-1903`）。
- 返回体新增 `bmodel_required` 与 `bmodel{numeric_status,detection_status,error}`，便于 UI/报告显示真实原因（`:1725,1862-1875`）。

**未改变**：`verify_images` 的比较逻辑、容忍度、协议字符串、`numeric_status` 投影、证据格式；失败时证据、`result.json`、PT/ONNX 指标与产物仍可读/可下载（只是不宣称正式交付）。**恢复路径**：在具备官方 Sophon 离线模型运行器的节点重跑数值验证，得到 `bmodel_numeric_status=consistent` 即可。

**边界**：`hardware_verified` 仍恒为 False；本轮只关闭"软件数值证据"缺口，不涉及任何真实 BMODEL/RKNN/Ascend 板端验证。

**测试**：`tests/unit/test_conversion_consistency_matrix.py`

- 负例 1：BMODEL 未比较 → `eligible=false`、`code=BMODEL_EVIDENCE_NOT_ELIGIBLE`，且此时 `job.numeric_status` 仍是 `consistent`（证明拒绝来自证据门禁而非可变摘要）。
- 负例 2：BMODEL 张量一致但检测不同 → 同样拒绝。
- 正例：BMODEL 数值+检测都一致且身份绑定到 BMODEL SHA → `eligible=true`。
- 回归：ONNX 交付物（`bmodel_expected=false`）行为不变，仍 `eligible=true`。

---

## 8. HARDWARE_PENDING 边界（不得宣称已验证）

- BM1684 / BM1684X / BM1688：只有 TPU-MLIR 编译与**合成张量**官方数值对照；没有板端加载、真实图片、现场前后处理/NMS/输出解码证据。`hardware_verified=false`，`model_validation_status=incomplete`。
- RK3568 / RK3576：编译阶段码与板端验收**记录校验**代码完整；本仓库没有真实板卡执行证据，`tests/hardware/test_vendor_conversion.py` 需显式授权且无 workflow 执行。
- Ascend 310P/910：只有 ATC 编译，**未实现** Runtime/板端验证。
- TensorRT：只有 `trtexec` 编译，未接入本矩阵的数值/硬件层。
- 任何 CI 绿、ONNX Checker 通过、ONNX Runtime CPU 推理通过、合成输入官方对照通过，都**不等于**真实硬件通过或算法准确率验收。

---

## 9. 取证与复现

- 本轮矩阵只读代码 + 定向单测；未接触生产数据、GPU、板卡、OSS。
- 已运行（本机 CPU，`-p no:cacheprovider`）：
  - `python -m pytest -q tests/unit/test_conversion_consistency_matrix.py` → **4 passed**
  - `python -m pytest -q tests/unit/test_conversion_numeric_consistency.py tests/unit/test_model_artifacts.py` → **145 passed**
  - `python -m pytest -q tests/unit/test_conversion_numeric_consistency.py tests/unit/test_conversion_tasks.py tests/api/test_conversion_numeric_validation.py` → **62 passed**
  - `python -m pytest -q tests/integration/test_real_pt_onnx_numeric.py -k delivery_eligible` → **1 passed**（真实 PT→ONNX→真实图片→证据→准入）
  - `python -m py_compile platform_core/deployment/numeric_consistency.py tests/unit/test_conversion_consistency_matrix.py` → OK；`git diff --check` → 0
- 未运行：任何厂商 SDK、真实 BMODEL/RKNN/OM 设备、生产环境；这些仍为 NOT VERIFIED。
