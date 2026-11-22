# W3 训练选材性能治理（200k 隔离测量，2026-11-22）

> 合成 SQLite 夹具，200,000 素材、正式 GT、预生成标签分布；不是生产分布，也不是 A800/4070 实测。
> 未改训练参数、模型、冻结快照、正式 GT 或旧选材页面。

## 1. 调用链审计

| 层 | 入口/实现 | 事实 |
|---|---|---|
| API browse | `POST /api/v61/projects/{pid}/training-materials/browse`（`_gt_material_filter_page`） | 精确/延迟 total、page 或 cursor、标签 GT EXISTS、usage/负样本过滤 |
| API role | `POST .../role-page`（`_role_material_page`） | Vue 使用 `defer_role_counts=True, count_mode=deferred`；旧调用可不传 |
| 角色索引 | `_cached_role_index`（lru_cache 8） | 冷路径读取全部 processed 行 payload + GT，200k 成本高 |
| GT/usage | `AnnotationRepository` + `TrainingMaterialUsage` ATTACH | 同一 SQLite 读事务；revision 校验 |
| 前端 | `training-material-picker-runtime.js` / `TrainingMaterials.vue` | Vue 默认发 `defer_role_counts:true, count_mode:deferred`；旧工作台仍可能走精确 count |

## 2. 200k 测量（当前优化后，单次隔离运行）

| 场景 | 结果（两次隔离运行范围） |
|---|---:|
| role deferred 首页 | 10.32–22.90 ms |
| role deferred 第 2 页 | 17.77–54.07 ms |
| role legacy 冷索引（`defer_role_counts=False`） | 11,298–11,630 ms |
| GT 深页（page=2000, 60/页） | 68.39–93.22 ms |
| 标签过滤 deferred 首页（fire） | 9.27–15.40 ms |
| 标签过滤 exact 首页（fire） | **305.26–364.98 ms** |

优化前同夹具：标签过滤 exact **1,225.80 ms**，deferred 14.84 ms；role legacy 11,630 ms。
优化后 exact 降低约 **70–75%**；deferred 不受影响。EXPLAIN QUERY PLAN 使用
`ix_annotation_label_references_code`。

说明：

- 数据为合成：每 5 行 fire/smoke、每 2 行 smoke、其余 person；每 11 行 confirmed_empty；不是生产 GT 分布。
- 未测 RSS、查询次数、前端网络/渲染、20 万真实使用历史。
- role legacy 冷路径仍约 11s；Vue 不使用该路径，旧 API 调用方保留原语义。

## 3. 已实施优化

问题：精确 count 使用
`SELECT COUNT(*) FROM materials m WHERE ... EXISTS (annotation_label_references ... label_code IN ...)`，
200k 下对每个候选做相关 EXISTS。

修复：对 `label_mode=any` 的精确 count，从正式 GT 标签索引出发：

```sql
SELECT COUNT(*) FROM annotation_gt.annotation_label_references gt
JOIN materials m ON m.id = gt.image_id
WHERE gt.annotation_state='annotated' AND gt.box_count>0
  AND gt.label_code IN (...)
  AND <material status/query/source/usage filters>
```

- 单标签：`COUNT(*)`（PK 为 `(image_id,label_code)`，无重复）。
- 多标签 any：`COUNT(DISTINCT gt.image_id)`。
- `label_mode=all`、无标签 `require_ground_truth`、非 exact 路径继续原 SQL。
- 缓存 key 加入 `from_sql/count_expr`，不跨查询类型串用。
- 页面 SQL、排序、cursor、revision 校验、usage/负样本过滤完全不变。

### 结果等价

- 12k 正式 GT 多标签/深页测试通过：`filtered.total` 与独立 SQL 参考一致，页面 ID 顺序一致。
- 现有 `test_training_material_picker_history_sql.py` 的 15 项通过；2 项 Windows URI ATTACH 环境失败（既有问题，见未验证）。
- `test_training_picker_workbench_scale.py::test_twelve_thousand...` 通过；trace 断言已更新为接受新的索引 count SQL，未删除业务断言。

## 4. 未修改

- 未改 `page` 到 cursor 的 API/旧页面协议。
- 未改冻结快照、selection_id、excluded_image_ids、Train/Val/Test 约束。
- 未改 role legacy 索引缓存或全表 payload 分类。
- 未改训练参数/模型/GT。

## 5. 未验证

- 生产 20 万/百万真实 GT、历史使用、负样本分布：`NOT_VERIFIED`。
- 前端请求数量/渲染 P95、RSS、精确 SQL 次数：`NOT_VERIFIED`。
- role legacy 冷路径优化：未做；旧调用方仍可能等待约 11s（合成 200k）。
- 多标签 `label_mode=all` exact count 仍走原路径，未优化。
- 真实 NAS/OSS/GPU：未访问。
