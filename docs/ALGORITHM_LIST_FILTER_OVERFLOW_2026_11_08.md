# 算法列表筛选栏越界｜2026-11-08

## 现象与代码定位

新版本「算法列表」筛选控件在部分桌面窗口或品目筛选展开后横向越出屏幕。前端唯一 Owner 为 `static/modules/algorithm-list-runtime.js`。布局根因是原 `.algorithm-filter-primary`、`.algorithm-filter-secondary` 固定最小轨道宽度，以及旧版 `@media(max-width:1280px)` 将品目浮层从右对齐改为左对齐，同时浮层存在 `min-width:560px`。浏览器断点未反映左侧导航占据的真实页面宽度。

## 本次定向修复

- 将算法列表 Grid 的根轨道设为 `minmax(0,1fr)`，筛选栏及控件可按实际父宽度收缩。
- 筛选容器使用 CSS `container-type:inline-size`；其实际宽度低于 780px 时搜索/筛选分行、次级筛选两列；低于 520px 时单列。不改变其他页面的媒体规则。
- 桌面品目浮层恢复向右对齐；窄容器内改为相对于本筛选 Surface 两侧各留 11px，移除固定 560px 最小宽度，并限制可滚动高度。
- 小屏三级品目只显示当前可操作列；按下一级切换 `.is-current`，避免初始状态呈现空列。
- 入口 `styles.css`、`main.mjs` 以及模块导入更新缓存版本标识，避免浏览器沿用旧筛选布局。

## 验证记录

- `node --test tests/frontend/algorithm-list-runtime.test.mjs`：20/20 通过。
- 可运行的完整前端测试（排除本地缺失的 Uppy/Annotorious/ZIP 依赖）：1437/1437 通过。
- `node --check`、`git diff --check`：通过。
- 新增真实 Chrome 布局测试至 `tests/browser/algorithm-list-performance.spec.mjs`，覆盖 1920/1366/1100/1024/900/768/600/390px 与品目展开、窄屏下钻、勾选；当前本地容器未安装 Playwright/Chrome，**实际浏览器结果与准确提交 SHA 的 GitHub Actions 尚待核验**。

## 边界

仅修改前端布局、品目可视列与测试，不变更数据查询、训练、GT、API、模型或生产环境；不合并 `main`、不创建 release、禁止 force push。真机分辨率、缩放比、不同浏览器及生产缓存是否完全恢复，需要发布后现场 UAT。
