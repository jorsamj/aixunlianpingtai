# AI 开发接续入口

畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## HEAD 与阶段

执行基线 / 最近已推送代码：`e639bb12585a79556b7a5fd703205368720265c3`。当前开发 M0–M1，尚未推送本批；最终准确 HEAD 以 `git rev-parse HEAD` 及远端同分支核验，不能把本文基线冒充最终交付 SHA。原三份未提交 Payload 设计保留，不混入提交。

目标是逐步完整替换旧前端，不长期双写。当前 FastAPI 模块化单体 + SQLite + 各原 Repository + ArtifactStore + Worker/Agent/Supervisor 已有成熟执行安全。新目标为现有 frontend 工程双构建：库模式继续服务旧视图，独立 `/app/` 使用 Vue Root / Hash Router / Pinia / Element Plus；新应用不加载 app.js，不移入旧表单，不创建第二 API/任务 Owner。

## 本批实现与限制

M0 已建立[功能/API矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)，单独列开发与验收状态。M1 正在实现独立 Shell + 原生算法卡片、筛选/分页、详情/版本、本地创建/基本编辑。训练、转换、交付等暂由显式整页交接原完整 Owner，不宣称原生完成。不得因此减少原菜单、字段、默认值或权限。

新 SPA 源码 `frontend/src/app/`；原库 `frontend/src/main.ts` 不迁走。后端仅新增 `/app` 静态挂载。旧系统仅通过显式 allowlist 消费交接参数，先核验 canonical 项目与算法/版本；不把 localStorage 当项目权威。旧系统生产仍是原默认单项目合同，不能借本轮交接改变它。

## 当前验证与 CI

开发中，本批 CI 尚未触发。类型检查和双构建已运行；具体最终结果在本批实现结束时更新，不能以临时输出宣称 M1 验收通过。旧 service-nodes 首项本地单次通过，无法稳定复现旧 CI 的标题缺失，未放宽断言或 timeout；记录待观察，不反复重试阻塞 M1。

## 下一步与禁止事项

完成 M1 的真实同源 API / Shell 导航与算法读写、旧系统交接、离线闭包和 SHA 核验，更新矩阵/本入口/功能台账后小提交推送，仅查最终 SHA CI 一次。M1 结束停止跨领域开发，等待 GPT 审查底座；下一阶段才能迁移训练全流程。

保留唯一数据 Owner、既有训练/GT/Task/Lease/Payload/模型/发布安全；普通 UI 不过度封装、防御、测试。不得操作 A800/4070/生产数据、改 VERSION、强推、merge main、Release。业务需求/默认值/权限变更先确认。自动化通过不等于生产或硬件验收。

## 必需文档

- [当前技术架构及历史实施](../TECH_FOUNDATION_P2_20261117.md)
- [功能/API矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)
- [功能保留台账](EXISTING_FEATURE_PRESERVATION.md)
- [旧前端 Owner 地图](../FRONTEND_OWNER_MAP_V42_25.md)
- [第三方组件合同](../FRONTEND_THIRD_PARTY_REUSE_POLICY.md)
- [Payload 连续交付与已知边界](P2B_4A_2B_CONTINUOUS_DELIVERY_20261118.md)
