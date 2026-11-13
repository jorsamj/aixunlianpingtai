# 13C-04D｜质量中心场景实测按需加载

基线：`5b75a4a8d441ce4ff5f9353e60658beab1833738`（唯一长期分支 `feature/external-algorithm-publishing`）。

## 根因与范围
13C-04C Chrome 隔离样本初始载入 104 个 JS，约 3.18MB 解码脚本；`app.js` 首屏 V8 已执行字符比 6.6%。这只能证明首屏装载结构值得优化，不证明生产 P95 已达标。代码审计确认 `quality-detection-workbench.js` 约 105KB，本来在 `main.mjs` 同步导入，但只有质量中心的场景算法实测标签用到。

本轮仅把该模块的静态导入替换为 `lazy-quality-detection-workbench.js` 的动态导入，并保持 `window.renderQualityDetectionBench64` 和 `window.QualityDetectionWorkbenchRuntime` 的原兼容接口。原评测 API、推理任务、GT 和批次的单一 Owner 不变。

## 安全边界
- 只有首次打开“场景算法实测”时才下载实测模块，其他标签不加载
- 重复打开仅复用；离开页面、切换项目和切标签后，迟到的 import 不能重绘旧页面
- 加载失败保留当前质量中心标签导航，显示重试入口；首次真实网络失败可以换唯一动态 import 查询参数手动重试
- 正式的训练提交、素材选择、数据库与 Worker 不动
- 入口 app/main/styles 缓存版本三者一致；专用懒加载器固定版本号避免热更新缓存混淆

## 验收
- Node 测试覆盖冷启动不加载、双重挂载单飞、离开后作废、失败可重试
- Chrome 测试覆盖首次打开、再次进入缓存以及延迟响应不会覆盖训练任务页
- 前端全量单测、相应 Chrome 测试及准确 SHA 的 CI 通过后才算完成
- 性能只按相同隔离 Chrome 测试环境对比，暂不宣称生产提速
