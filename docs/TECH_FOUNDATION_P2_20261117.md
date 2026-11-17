> **当前保护约束**：P2A/P2B 代码保留；P1Z 菜单替代已按用户确认局部修复，工作台与业务试点开关独立，原正式菜单/Owner 不替换。[当前功能保留台账与审批规则](architecture/EXISTING_FEATURE_PRESERVATION.md) 优先于历史工作台描述；本轮完成后停止。

# P2 技术底座实施与回退

起点：远端/本地 5e9ae26548c07bbff91b37d703d2bf4a8be0b446，唯一 feature/external-algorithm-publishing，工作区干净。

## P2A 独立提交

- frontend/src/main.ts：18 个页面改为函数式动态 import，加载前后检查原 context.signal；仅原 Owner 驱动挂载/卸载。移除每次挂载只包含 `/` 的冗余内存 Router，直接挂载页面；不接管旧 hash 或建立第二导航。
- frontend/vite.config.ts：保留稳定主 JS/CSS 和本地 base，动态 Chunk 采用内容哈希，生成 manifest.json。共享 Vue/Element/组件由 Rollup 复用，第三方原插件不复制。
- tools/verify_vue_offline.mjs：检查 manifest 闭包、动态业务页及全部资源；生成逐文件 SHA256/准确 CI SHA 清单。构建脚本和既有 CI 使用同一校验。
- tools/package_vue_offline.py：同 SHA git archive + 已校验官方 artifact 的整个 Vue 目录组合，不限于两个入口文件；原 vendor/LICENSE/NOTICE/map 原样保留。
- 仅补充按需加载/离线闭包的定向测试，既有 CI 执行 Node、类型构建、Chrome 与隔离真实入口；本地只必要快速构建。

## P2B 独立提交

- platform_core/deployment/catalog_api.py：沿用已有 APIRouter 工厂模式，迁出七条 v39 catalog 路由，复用 ModelArtifactRepository 和 compute_platform_catalog；不反向 import app。
- app.py 仅注入可调用 Provider / 原资源函数并 include_router，保持全局 Session middleware、异常映射、原 URL/HTTP status/revision/operation_id/引用保护。
- 既有 API 测试改为调用真实注册端点，保留所有业务断言；增加独立工厂 HTTP 合同及鉴权/observe_only 的必要覆盖，接入原 Remote Conversion CI。

## 状态边界

Pinia 仅保存字典展示/筛选/加载态和本次操作待核回执，原 API Adapter 仍调用 context.get/post 等原 api 通道；表单临时状态留在组件，页面读取缓存受项目身份、revision、取消约束。算法版本、GT、任务执行、冻结选择、发布回执均不成为 Pinia 持久业务真相。后续跨页面真实路由出现后再评估统一 Vue Shell，本轮不强制建立。

## 后续文档与验证

P2C/P2D 独立源码依据文档：只做数据 Owner/迁移门槛和异构能力证据分层；不加数据库依赖、不迁移 Schema、不检测硬件。

本轮不修改 VERSION、默认入口、生产环境、训练/GT/Worker/Agent/Supervisor/租约或发布写入逻辑。准确新 SHA CI 和产物状态以交付记录为准，不借用起点 CI。

回退按相反顺序 git revert P2B 提交、P2A 提交；离线包必须整包恢复同 SHA 源码与全部 Vue 资源，不混用 Chunk。无数据库迁移，无数据回滚步骤。

## 实际变更与验证边界

P2A 独立提交 3a4d76e；一次本地 vue-tsc/Vite 构建成功，30 个 manifest 闭包文件，18 个业务页动态入口。稳定入口约 0.73 KB、共享 main runtime 650.86 KB，工作台业务 Chunk 13.63 KB；原单 JS 1041.657 KB，CSS 163.751 KB 不变。首屏还需共享依赖，不能只用入口 0.73 KB 宣称整体性能；生产 P95 未测。

P2B 七个函数 AST 在仅替换注入依赖后与原函数完全一致；没有修改算法/素材/GT/候选/模型/发布/Task Repository。既有测试从 app 全局函数转为原注册 Router.endpoint，断言保留。补实际 HTTP 401/200/422 与独立 Router 路径集合检查；TestClient 不启动 lifespan，SDK 通过替身保持隔离。

后续 Router 顺序：第二批 v12 算法管理、v62 训练任务只读、v44 报告只读；第三批素材查询、AI 读取、模型资产及转换历史。优先现有模块工厂，尚未新增 platform_api 或 application/domain 空目录，不创建无意义转发 Service。

离线组合（不构建）命令：

```text
python tools/package_vue_offline.py --sha <准确SHA> --artifact <该SHA制品ZIP> --metadata <官方artifact元数据JSON> --output <新交付ZIP>
```

工具先核 workflow_run.head_sha、制品名称、官方摘要、ZIP CRC、CI 构建来源和每个 Chunk SHA/大小，拒绝其他 SHA、本地构建和缺失文件；git archive 同 SHA 源码包含原 vendor/LICENSE/NOTICE/map，附完整 Vue 目录和元数据。既有 Frontend Runtime CI 继续上传整个 static/vue-catalog（manifest 非隐藏文件）；不新建重复 workflow。新构建必须整个目录同 SHA 交付，并完整刷新页面后使用；不在正在打开的旧页面混装新 Chunk。

准确最终提交的 Frontend Runtime/Remote Conversion CI、官方制品下载与完整包校验推送后填写，不将本地构建等同于 CI/现场离线安装。
