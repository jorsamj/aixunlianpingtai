# Windows P0 闭环实施路线图

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保护历史数据的前提下，按四个可独立验收的里程碑完成 Windows 本机视觉算法生产闭环。

**Architecture:** 新业务逻辑进入可测试的 `platform_core/` 与 `static/modules/`，现有 `app.py` 路由逐步改为调用唯一服务实现，现有 `app.js` 逐步移除受影响业务的 override。每个里程碑先建立失败测试，再做最小实现和端到端验证。

**Tech Stack:** Python 3.10-3.12、FastAPI、Pydantic、pytest、原生 ES Modules、Node test runner、Playwright、Ultralytics、OpenCV、ONNX、厂商 SDK。

---

## 执行顺序

1. [稳定基础与交互审计](./2026-08-28-m1-stability-foundation.md)
2. [标签、素材、上传、清洗与人工标注](./2026-08-28-m2-data-annotation-workflow.md)
3. [算法资产、迭代训练、数据质量与双层报告](./2026-08-28-m3-training-quality-reports.md)
4. [本地/在线模型自动标注与真实模型转换](./2026-08-28-m4-model-adapters-conversion.md)

## 里程碑门禁

- M1 未通过：不得修改历史数据或开始业务功能迁移。
- M2 未通过：不得宣称数据可训练。
- M3 未通过：不得进入服务器部署。
- M4 未通过：不得宣称自动标注或目标硬件转换可用。
- Windows 全链路通过后，另建 NVIDIA Linux/CUDA 实机部署计划。

## 全局完成命令

```powershell
python -m pytest tests -v
npm test
npx playwright test
python smoke_test_training.py
```

预期：全部命令退出码为 0；最小训练产物包含可加载权重、真实指标、算法版本和报告。

