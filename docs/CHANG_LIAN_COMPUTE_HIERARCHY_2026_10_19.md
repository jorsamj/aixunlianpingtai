# 新畅联算力环境父子分类与芯片字典（2026-10-19）

## 唯一数据所有权

- 外部算力环境主数据：`ExternalPlatformRepository.cache().compute_platforms`，从 `listAll?showChildren=true` 完整同步。字段 `computePlatformId / computePlatformName / computePlatformCode / parentId / delFlag` 保留远端身份。
- 本地芯片建议字典：`platform_core/compute_platform_catalog.py::CHIP_BINDING_DICTIONARY`，仅代表可配置的本地识别码，不代表转换引擎已验证支持。
- 外部发布映射：沿用 `ExternalPublicationRepository.config().target_mappings`。不创建新配置数据库或第二个客户端。

## 配置模型

单个 target 保留旧字段 `compute_platform_id`（父级 / 默认环境 ID）、`chip_code`（仅旧配置兼容）、`enabled`，新增 `chip_mappings`（本地型号 → 外部子节点 ID）。

示例（远端 ID 仅为说明）：

```json
{
  "rockchip": {
    "compute_platform_id": "100",
    "chip_mappings": {"RK3568": "101", "RK3576": "102"},
    "enabled": true
  }
}
```

调用新增权重接口时：实际 RK3568 产物携带 `computePlatformId=101`、`chipCode=RK3568`；不能从父子名称反推芯片。original/ONNX 等无具体芯片的目标继续采用它们单独配置的环境 ID。

## 安全与兼容约束

1. 主数据缺 ID、重复 ID、父节点缺失、自身引用或循环 → 同步失败，不以不完整树覆盖已有完整树。
2. 删除节点、失效父级、跨父分类绑定、空芯片或重复归一化芯片编号 → 不允许建立映射。
3. 父级下存在子分类，或者旧配置直接选择子分类时，RKNN 必须显式绑定本地芯片；无子分类的历史扁平配置继续兼容。
4. 未映射的新芯片只影响该转换产物的发布；已完成的 original 仍按既有独立映射发布。
5. 对应产物已有远端 weightId 后，新增的芯片细分映射不得自动将它改挂到另一远端 computePlatformId；需要人工核对并通过单独迁移流程处理。
6. `chip_mappings` 仅改变新畅联交付身份，不修改训练 Snapshot、模型版本、真实转换芯片、原始权重或源文件哈希。
7. 前端只从服务端领取芯片建议字典和最新远端主数据，已失效的历史 ID 仍会标明、不能静默换成某个同名节点。

## 验收入口

- Python：`tests/unit/test_external_algorithm_publish.py` 和 `tests/unit/test_external_algorithm_platform.py`
- Node：`tests/frontend/external-algorithm-publish.test.mjs`
- Chrome：External Algorithm Publish / External Algorithm Platform / Frontend Runtime Stabilization
- GitHub Actions：对应工作流及 Algorithm SQL Store 以最终 SHA 验收。

生产真实远端 ID 的含义、`computePlatformId` 在新增权重接口中是否允许填写子节点，需要由新畅联负责人确认并在受控环境验收。此文档不授权生产发布。
