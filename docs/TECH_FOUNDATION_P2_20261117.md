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
