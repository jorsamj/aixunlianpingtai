> 2026-11-17 P1S–P1Z新授权：从P1S接续，历史“完成后停止”由新授权取代。P1S新增Vue三步展示，原Draft/Label/Picker/Submit子树单一DOM归属，opt-in vue_training_create=1，旧默认及回退保留。当前代码/隔离验收与准确SHA CI状态见[专项](PRODUCTIZATION_P1S_20261117.md)。

# 前端第三方组件长期复用规范

核对日期：2026-11-17。适用于渐进式 Vue 展示接入与原生页面维护。本规范要求优先复用仓库已经落地的第三方组件、适配器和业务 Owner；没有授权的版本升级、引擎替换和业务重构不属于展示接入。

## 1. 已核对的组件与唯一接入位置

以下版本来自根 `package.json`、对应 vendor manifest 或 ECharts README，不能凭最新 npm 版本推测现场版本。

| 能力 | 仓库锁定版本 | 现有接入 Owner / 证据 |
| --- | --- | --- |
| 图片框编辑 | `@annotorious/annotorious` 3.9.5，BSD-3-Clause | `static/modules/annotorious-editor.js` 的 `loadAnnotorious`、`createAnnotoriousEditor`；几何转换唯一复用 `annotation-geometry-adapter.js`；`static/vendor/annotorious/manifest.json` |
| 上传选择与展示 | 官方预构建 `uppy` 6.0.5，MIT；根依赖另锁定 `@uppy/core` 6.3.0、`@uppy/dashboard` 6.0.2、`@uppy/locales` 5.3.1 | `static/modules/uppy-zip-adapter.js`，`static/vendor/uppy/manifest.json`；原导入会话、ZIP 任务及服务端持久导入 Owner 保持 |
| 只读素材平移缩放 | `@panzoom/panzoom` 4.6.2，MIT | `static/modules/material-presentation.js`，`static/vendor/material-presentation/manifest.json` |
| 浮层定位 | `@floating-ui/dom` 1.8.0，MIT | `material-presentation.js` 的 `computePosition/autoUpdate/offset/flip/shift` |
| 图标 | `lucide` 1.70.0 | `material-presentation.js` 已按图标导入本地模块；许可证见同目录 manifest 与 `lucide-LICENSE` |
| 报告图表 | Apache ECharts 6.1.0，Apache-2.0 | `static/modules/reports.js` 按需加载；`static/vendor/echarts/README.md`、LICENSE、NOTICE |

Vue 壳当前另在 `frontend/package.json` 锁定 Vue 3.5.45、Element Plus 2.14.8。壳的存在不改变上述插件的唯一装载入口；不得为 Vue 再安装、打包第二份 Annotorious/Uppy 或其插件，也不得引入 CDN、在线字体或在线资源依赖。

## 2. 标注编辑必须复用原引擎与几何适配

可编辑框操作必须使用 Annotorious 3.9.5，经 `createAnnotoriousEditor` 接入。禁止用另一套 SVG/canvas/pointer 实现替代画框、拖动、缩放框、框选、坐标映射、撤销重做等编辑 kernel。禁止在 Vue 组件中直接访问插件内部状态、复制几何转换或绕过原适配器调用内部 annotator。

现有 `annotorious-editor.js` 已实现与该编辑器绑定的 viewport pan/zoom、缩放中心、fit、指针捕获及 resize 生命周期；本轮必须保留。不得以“优先第三方”为由给编辑器叠加另一层 Panzoom、重复变换坐标，或新建自研 viewport/kernel。需要优化时先在原 adapter 定位真实缺陷，再做小范围修复。

只读 overlay 与可编辑 kernel 分开：列表缩略图、结果预览可以用现有只读框投影和 `MaterialPreview` 呈现，有界框预览应标识其截断性质；预览框不是完整编辑数据，不能拿预览数组覆盖正式框。需要编辑时加载原编辑 Owner 的完整候选/正式 GT 数据，再进入原 Annotorious adapter。

正式素材标注仍由原 AnnotationRepository/保存 Owner 管理；AI 候选、草稿、采用、正式入库仍由原 CandidateStore、原 v60 审核路由和正式 GT 提交 Owner 管理。Vue 只提供展示与受控动作，不新建候选仓库、并行写服务、资格状态机或第二份 GT 真相。

## 3. 薄 Vue 包装层必须满足的生命周期

1. 按项目、任务、图片与编辑会话捕获身份；每次异步资源加载、图片加载、接口返回后复核身份、AbortSignal、宿主连接状态。先前会话迟到的 Promise 不得挂载到新图片；若迟到返回 editor 实例，立即 `destroy()`。
2. mounted/图片就绪后调用原 adapter；项目切换、任务切换、换图与 unmount 时取消请求，移除订阅并 `destroy()`，使 observer、官方事件、键盘/指针/wheel 监听与 pointer capture 得到释放。清理必须幂等。
3. 用户输入不通过重建整个宿主来同步；复用原 `sync`、选择、模式、可见性、类别过滤接口，保留编辑中的 DOM、焦点、滚动与视口。只读或保存中状态通过原锁定接口控制。
4. 类别过滤/隐藏框只是显示投影。完整框集由原 Owner 保存；不得把插件当前可见 annotations 当成全部框集。原 adapter 的 `flush()` 会将可见编辑合并回完整框数组并保留隐藏框，这一行为必须保全。
5. 正式保存或候选草稿保存前先调用原 `flush()`，再由同一会话的原 Owner 读取完整框集、验证错误状态、执行原保存合同。不能因 `flush()` 无变化返回 false 就误判保存失败，也不能在转换报错后继续发送旧数组。
6. `autoSave:true` 仅是 Annotorious 的生命周期事件策略，不是服务端保存成功。只有原 API 持久回执及必要 GET 核验才能显示已保存/已正式入库；草稿 revision 与正式 GT version 不可混用。沿用 request_id、CAS、源 SHA、未知回执停止与恢复规则。

## 4. 离线 vendor 与依赖治理

- 沿用本地 `static/vendor` 资源和原加载器；构建后的 Vue 包不得再包含一份相同编辑/上传插件。依赖缺失时先检查既有 vendor 和原适配器，不能直接添加替代库。
- 保留 manifest、精确版本、许可证清单、source map、文件字节数和 SHA256；已有 map 原样保留。Annotorious manifest 已记录唯一 first-history guard patch、上游 hash 与实际产物 hash，并注明未改上游 map 的偏移限制，不得把它误报为纯原版文件或重新生成另一份无审计产物。
- 复用 `npm run verify:annotorious`、`verify:uppy`、`verify:material-presentation` 对应原工具。只有更改相应 vendor 时才运行其更新命令；普通 Vue 接入不得顺带升级或重拷全部依赖。
- ECharts 保留现有 `reports.js` 按需加载和 resize/dispose；不得为相同报告另加图表库。Floating UI 的 autoUpdate 清理和 Panzoom 实例销毁仍由原 presentation Owner 管理；图标使用既有本地资源。

## 5. 验证与修改范围

验证必须覆盖实际本地插件的 Chrome 关键路径，不能仅以 mock adapter、静态源码断言或截图证明可编辑行为：画框、选框、拖动/调框、类别修改、隐藏类别后保存仍保全隐藏框、viewport pan/zoom、保存前 flush、关闭/换图后的迟到初始化清理，以及原 API 草稿回读。正式 GT 写路径只在隔离临时数据且本轮已授权时验证。

只运行与当前改动直接相关的构建、adapter 用例和真实插件浏览器用例；有失败则定位原 Owner。不得借本规范大范围删除遗留实现、批量替换页面、升级版本、修改模型/Worker/生产数据或执行生产部署。保留已存在的原页面入口与回退；交付证据明确区分本地隔离验证、准确提交 CI 与现场验收。
