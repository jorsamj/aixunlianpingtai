# 列表操作菜单与导航简化验收（2026-10-16）

## 本轮推送后专项核验（优先于下方首次本地报告）

视觉收口补充：Grid 变窄后状态 Tab 曾被 flex 压成逐字换行。先补 Chrome 失败断言，再仅对 <=760px 的状态按钮设置 flex-shrink:0 / white-space:nowrap；状态栏自身横向滚动，页面和桌面列宽不变。最终 styles 缓存为42.25.387，正式 VERSION 与 app/main 不变。后续 CI 以最后提交 SHA 为准。

14db6a2b 首次 CI 的 ZIP Ubuntu contract 失败日志已读取：新增 Python 步骤只安装 pytest，但 platform_core 包初始化会导入 AnnotationRepository/FileLock，测试收集报 ModuleNotFoundError:filelock；Windows contract 及 backend-persistence、real-chrome-refresh 实际成功。补齐同一步骤的 filelock 依赖，不绕过 package 初始化、不改产品代码或测试断言。最终 SHA 必须重新验收。

- 3be8881710443cc615bca046c42dd2d85e6cfe39 已按用户授权普通快进推送；精确 SHA 的 push/pull_request 合计 40 个实际工作流、112 个 Job，全部 completed/success，无失败/取消/跳过。旧工作流名与未触发项不能重复计为通过。
- 再次扫描全部实际静态入口：算法列表、训练任务使用 entity-more；素材、清洗、AI 任务、算法版本和质量列表是直接操作按钮，不存在另一套未升级的 92px 菜单，不新增无意义入口。现有 Chrome 算法版本删除、素材分页、AI 轮询、质量导航与训练报告回归均保留。
- 375px 原训练 Grid 内容实际 1044px / 351px，宽表格撑大子项。仅设置训练页 minmax(0,1fr)、子项 min-width:0 与表格滚动包装 border-box。修复后 main=375/375、训练页=351/351、表格容器=347/1040，只有表格内部横向滚动；桌面三视口列宽不变。四视口菜单均完整、可点击，真实鼠标采样 18.7–26.5ms。
- ZIP 日志不是无害删除提示：atomic_write_json 共享 job.json.tmp，双写屏障能确定复现临时文件身份碰撞；替换失败还会残留临时文件。改为 UUID 独立同目录 staging、独占创建、关闭流后原子替换，finally 仅清理本次创建的文件。保持原 JSON、文件权限/umask 和同文件系统替换，不改 Task/Annotation/删除语义。
- 仅独立 staging 仍在真实 Windows 四写入线程压测复现 WinError 5；增加仅针对 winerror 5/32/33 的最多四次替换，等待总上限 30ms。持续占用仍抛出，非 Windows 权限错误不重试。没有静默吞错或无限重试。
- 最终 Windows 压测五轮、四线程合计 4000 次写入：0 错误、0 残留 temp，最终 JSON 有效；原子写入 7 个用例重复五次通过，覆盖独立 staging、临时占用、持续锁失败、保留旧文件和资源清理。
- 原 v19 部分写入测试夹具改为阻断新 staging 的实际 JSON 写入流，而非匹配已退役固定 .tmp 文件；原进度 12.3→13.4 / 3600→4500 的所有读一致性断言保留。
- 本地最终回归：Node24 972/972、Python 75/75、真实 Chrome 44/44。Python 覆盖 ZIP multipart/原子持久化/取消回滚、标注与普通上传清洗；Chrome 包含 3/5/10 ZIP、恢复/项目隔离、菜单与四视口，无上述 Windows 错误日志。仍有 FastAPI/httpx 弃用警告，不伪称零警告。
- 样式缓存单独升级 42.25.386，app/main 保持 42.25.385，VERSION=42.24.356。既有 ZIP Workflow 增加 Ubuntu/Windows 原子写入实际步骤，并让共享 annotations.py 修改触发 ZIP 与 Material Upload Cleaning Performance；不新建工作流。
- 后续修复提交需以自己的最终远端 SHA 验收 CI，不能沿用 3be88817 的成功结果。最终远端统计见交付时的独立 CI 快照；未部署、未合并 main、未操作生产数据。

## 范围与事实

- 本地基线：85dfb0f5c0417841be4f8e6b7c35c0a0e1f53467。
- 工作树：C:/Users/jorsam/.codex/worktrees/training-failure-diagnostics/畅联云算法训练_v42.14.0；实际本地分支 codex/training-failure-diagnostics。后续获准推送的目标仍是 feature/external-algorithm-publishing。
- VERSION.txt 保持 42.24.356；入口 app/main/styles 缓存键 42.25.385，实际修改的算法/训练列表模块和共享菜单模块为 4226385。
- git fetch 本轮连接重置，不能把缓存的 origin SHA 当作新鲜远端核验。没有 push、merge、Release 或部署。

## 根因与修复

实际常规行菜单只有算法列表和训练任务列表两处 entity-more；素材、AI、清洗、质量等使用直接按钮，不添加不存在的菜单。

旧实现是原生 details + 相对容器内绝对定位，没有共享交互 Owner。Chrome 基线菜单宽 92px、操作项 30px，字号实测已有 14px（未复现低于 14px）。布局没有视口翻转与滚动边界处理，绝对浮层受容器裁切规则约束。原生打开状态改变 innerHTML，训练进度补丁将它误判为业务动作变化，实测进度更新会替换已打开 summary。

本地并未复现 >100ms 的菜单延迟，也未发现打开菜单等待业务 API；因此不虚构慢请求根因或数量级性能提升。

共享 RowActionMenuRuntime 仅负责既有动作的展示：一个活动菜单、事件委托、原生 Popover 顶层（非遮罩）、一次定位和 rAF 合并滚动/resize。每次打开只读取当前记录的少量原始按钮，不扫描或重绘整表、不请求 API、不计算筛选，不建立第二套业务 Owner。操作通过原始 button.click() 执行；disabled、确认、API、删除范围和任务状态合同保留。关闭即移除命中/焦点能力，短淡出不会拦截页面。

菜单为 240px / 14px / 44px 操作项，SVG 线性图标、危险操作独立红色，进入 140ms transform+opacity、退出 80ms，支持 reduced-motion。支持单开、切换、外部关闭、Esc/Tab/方向键、焦点恢复和 ARIA；下方优先、底部翻转、左右边界约束。训练补丁比较上次生成的动作 HTML，而不是带 ARIA 状态的现场 DOM；动作权限/状态改变仍替换节点并关闭失效菜单。

侧栏 nav-project 整块、对应 CSS、nav-project-v 更新、顶部重复 projectBadge 已移除。state.project、Project ID、API 项目上下文未改。刷新、导航重绘、折叠/展开和隔离项目 ID 已验证。

## Chrome Performance 对照

同一 Windows 设备、真实 Chrome、1200 条算法记录、原有分页。可比较的数值为同步 click 到两个 rAF 后可见采样的保守上界，并非精确 compositor 首帧时间。自然帧相位会产生几毫秒波动，不据此宣称性能大幅提升。

| 视口 | 修改前 ms | 修改后最终 Node24 运行 ms |
| --- | ---: | ---: |
| 1920×1080 | 22.4 | 18.5 |
| 1440×900 | 22.3 | 22.3 |
| 1366×768 | 22.5 | 24.5 |
| 375×812 | 22.2 | 18.0 |

另用真实鼠标 pointerup 到两个 rAF 采样：23.3 / 25.8 / 22.9 / 23.5ms。全部 <100ms。打开菜单 API=0，原卡片身份保留。1200 条训练任务经原 TrainingTaskRuntime 实际 GET 刷新后，进度更新、原 summary 和打开菜单均保留；状态变为 stopping 时及时关闭。

底部翻转、顶层命中、窄屏边界、缩小视口/滚动后锚点不可见关闭、分页、Enter/Space/Tab/Esc/方向键、reduced-motion 均有断言。原删除取消确认不发请求，确认后快速双击仅发一次 DELETE；外部算法编辑/删除仍 disabled；训练停止取消确认不发 POST。现有算法 CRUD、版本删除、训练暂停/批量删除等原测试保留业务断言。

## 测试结果

- Node.js 24.19.0：与 CI 相同的 node --test tests/frontend/*.test.mjs，972 passed / 0 failed。
- 同一 Node24 启动真实 Chrome，8 个相关 spec：44 passed / 0 failed（1.7m）。包括菜单新用例 3 条，以及算法列表、训练任务、训练质量报告、ZIP 恢复、企业导航、素材分页和 AI 轮询。
- app/main/菜单/训练列表语法检查、git diff --check 通过。
- 新 Chrome 用例加入现有 Frontend Runtime Stabilization；现有缓存/导航断言同步到新的真实合同，没有删测试或放宽业务保护。
- npm test 在系统 Node20 也通过；Node24 必须使用 CI 的显式文件 glob，目录参数 node --test tests/frontend 不在 Node24 中解析为整套测试，不修改与本轮无关的脚本。

一次组合运行曾把前置 ZIP 用例留下的正常库存轮询计入菜单 API=0 断言。夹具改用真实创建的空隔离项目，保留严格零请求断言；未关闭产品轮询或白名单隐藏请求。

## 可复核证据

证据目录：C:/Users/jorsam/.codex/visualizations/2026/10/16/row-menus。

- before/results：修改前原截图、Playwright Trace；before-menu-performance.json 与 before-chrome-performance.json 为从原 Trace 无修改提取的附件。
- final：最终 Node24 的 Playwright Trace、算法四视口 after-*.png、底部 bottom-*.png、训练四视口 training-*.png。
- after-menu-performance.json / after-chrome-performance.json：最终运行原附件。Chrome Performance JSON 可导入 DevTools Performance。
- 浏览器测试生成并覆盖的四张旧企业列表截图已额外归档，然后恢复为 HEAD 原内容，不混入本次提交。

## 边界与观察项

- 未运行 GitHub Actions、Linux、生产真实数据或服务器验收；不据本地结果宣称远端 CI/生产通过。
- 最终 44 个断言均通过，但 ZIP 10 文件测试期间服务端曾打印一次 Windows WinError 5：app.py:v19_create_multipart_upload → v19_write_job → annotations.atomic_write_json 的 job.json.tmp replace。相关后端文件相对基线无修改；这是仍需独立排查的文件锁/并发写入观察项，未在本轮归因或修改后端，不能宣称 ZIP 后端无风险。
- 窄屏训练页面仍有既有整页横向溢出表现；本轮验证菜单在真实滚动后的定位/命中，不扩大到整页布局重构。完整训练页面移动端视觉不是本轮“全平台通过”结论。
- 现代 Chrome 的原生 Popover 已实测；旧版不支持 Popover 的浏览器未验收。
- 本轮仅本地开发与验收完成，推送仍等待用户授权；任何推送前须重新 fetch 并核验提交关系。

## 修改文件

生产前端：static/app.js、static/index.html、static/main.mjs、static/styles.css、static/modules/algorithm-list-runtime.js、static/modules/training-task-visibility-runtime.js、static/modules/row-action-menu.js。

测试：tests/browser/row-action-menu.spec.mjs、algorithm-list-performance.spec.mjs、training-quality-reports.spec.mjs、zip-import-refresh-recovery.spec.mjs；tests/frontend/row-action-menu.test.mjs、cache-first-page-loading.test.mjs、training-task-visibility-runtime.test.mjs、version-marker-owner.test.mjs。

已有 CI：.github/workflows/frontend-runtime-stabilization.yml（纳入实际 Chrome 用例）、training-task-visibility.yml（精确缓存键同步）。

交接文档：本报告、AGENTS.md 和四份当前 owner/handoff 权威文档。
