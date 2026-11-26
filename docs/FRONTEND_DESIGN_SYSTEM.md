# 畅联云前端设计规范

独立 Vue 应用通过 `frontend/src/app/style.css` 提供主题与 Element Plus 公共覆盖。继续使用本地字体和已有组件。交互设计参考键盘焦点、状态反馈及主题组织方式。 [Arco Design Vue](https://arco.design/vue/en-US/docs/pro/start) · [Semi Design](https://semi.design/zh-CN/)

|主题变量|值及用途|
|---|---|
|`--workspace-ink` / `--workspace-muted` / `--workspace-subtle`|`#171717` / `#52525B` / `#686872`，正文、说明和辅助文本|
|`--workspace-surface` / `--workspace-page` / `--workspace-hover`|`#FFFFFF` / `#F7F8FA` / `#F1F2F4`，内容、页面和交互背景|
|`--workspace-line` / `--workspace-accent`|`#E4E4E7` / `#242424`，分隔线和重点动作|
|`--workspace-radius` / `--workspace-gutter`|`8px` / `16–24px`，内容边角和页面留白|

- 页标题约 20–24px，区块标题 16px，正文 14px，辅助文字 12–13px。默认控件使用 Element Plus，普通控件圆角 6px，弹窗圆角 12px。键盘焦点有明确描边。
- 侧栏保留现有菜单和顺序。页头分开项目上下文和会话操作。表格强调行分隔和悬停，状态色用于业务结果。
- 弹窗区分标题、可滚动正文与操作栏。审核入库按范围、执行、完成或待核验展示，进度仅显示已核验的服务端数量。结果未知沿原请求查询。
- AI 审核在桌面保留三栏，紧凑视口以侧边检查面板容纳同一套操作。缩略图保持完整图像比例，原图放大和标注框继续使用既有组件。素材库优先展示图片、状态及人工标注。算法库保持卡片并分组呈现版本、训练和指标。
- 训练表单按原业务分组，报告复用 ECharts。具体阈值、请求、证据和旧入口交接状态见功能矩阵。

## 视觉证据

现有 Frontend Runtime Stabilization 流程会留存审核三档桌面截图，以及素材库、算法库、人工标注、训练表单和审核入库确认截图。当前代码的实际渲染核对状态为 `VISUAL_PENDING`。截图产生后需逐项确认图像、操作可达性、滚动及键盘焦点。
