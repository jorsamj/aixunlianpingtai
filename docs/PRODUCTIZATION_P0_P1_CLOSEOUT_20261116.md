# P0/P1 精准收尾验收记录（2026-11-16）

范围仅入口缓存合同、厂商/芯片预览状态、相关验收证据及离线静态资源包含方式。基线与远端 HEAD 均核对为 `9cb7bcf037631d8ef8cb5c2edea0a8268495cf89`，唯一分支 `feature/external-algorithm-publishing`。VERSION.txt 保持 42.24.592；不改训练/GT/标注/Task/Worker/Agent/Supervisor/数据库，不部署或重启服务，不进入 P2/P3/P4。

## 原失败与修复

旧 [Frontend Runtime CI](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43886152476) 的 frontend 1669 项中 8 失败。三个入口 `styles.css` / `app.js` / `main.mjs` 共同构成按顺序加载的应用壳，测试合同要求同一数字缓存标识；显示版本由后端 bootstrap 决定，与入口缓存标识独立。之前仅 main 更新 607，而另两项仍 606，导致相等合同与精确期望同时失败。

将另两入口统一到 **42.25.607**，保持 main 不回退。仅同步受影响的精确测试期望；未删除测试、放宽断言或修改其他模块缓存。原八文件：

- ai-review-immersive-workbench.test.mjs
- lazy-advanced-evaluation-owner.test.mjs
- lazy-changlian-data-browser-owner.test.mjs
- lazy-legacy-material-owner.test.mjs
- lazy-quality-detection-workbench-owner.test.mjs
- modal-style-scope-13b.test.mjs
- navigation-presentation-owner.test.mjs
- version-marker-owner.test.mjs

原八文件修复前复现 **32 passed / 8 failed**；修复后连同受影响的 training-resource-cards-extraction 共 **44/44**。其中 ai-review 的缓存期望随原入口读取，无须修改；version-marker 的相等断言原样保留。未改 training-material-picker 等独立模块缓存。

## 后端状态语义

列表 capability 与详情 resource 均显示 `status_label || status || 未核验`。后端统一词汇来自 `platform_core/compute_platform_catalog.py`，Vue 不复制状态标签字典，不用 sdk_ready/ready 布尔值覆盖详细状态，不从模板推断安装、兼容性或准入。颜色仅依据后端 status；转换准入业务未改。

新增一项定向 Chrome 场景覆盖待配置、待检测、检测中、过期、失败、不兼容、未适配、资源不可用、可转换（均设置 sdk_ready/ready=false 以检验标签优先级），及无 label 时显示原 status。已有场景覆盖无证据的“未核验”。测试发现长表格下抽屉关闭按钮被表格遮挡，补入现有 ElDrawer 必需的 `el-overlay.css`，未增加新导航或弹窗实现。

## 实测证据与边界

- Node22：`vue-tsc --noEmit && vite build` 成功；JS 675.32 kB / gzip190.50，CSS95.20 kB / gzip13.65。
- `frontend` 的 Playwright 三项定向测试 **3/3**；包含返回、取消、重入、查询、详情、状态语义。静态服务器日志证实两制品均 HTTP200。
- 本地真实 FastAPI + 原 static/index.html/app.js/main.mjs/NavigationStability 冒烟通过：原本地登录、刷新复用、原部署资源→厂商与芯片字典→只读预览、返回取消请求、Vue卸载、原新增厂商弹窗、登出失效；两制品200，pageerror=[]。
- 该真实入口测试使用全新系统临时数据目录、127.0.0.1:8028、uvicorn lifespan=off，手动运行原核心 bootstrap；仅在测试进程将本机资源函数替换为原只读摘要，并禁止SDK检测函数。未启动调度/恢复后台生命周期、未连接生产、未运行SDK命令。完整管理仅验证页面及新增弹窗可访问，没有提交CRUD写操作。
- 本地证据：`test-results/vue-catalog/real-entry.json`、`real-entry.png`、`catalog-1366.png`、`catalog-768.png`（忽略目录，不入源码Git）。本地一次性冒烟没有冒充CI自动化用例。
- 真实入口第一次检查显示完整字典是原高级分区，须点击“厂商与芯片字典”后进入；返回会记住 catalog 分区。未新建导航。真实入口验证覆盖这一行为。

旧CI的 Vue build / Chrome步骤被单测失败跳过；upload步骤虽然success，其日志明确“未找到文件，不上传制品”。本批将缺失制品行为由 ignore 改 error，必须依据新提交的 frontend build/Chrome/upload日志和Artifacts API实际条目判定成功。准确SHA CI需在推送后检查，不能借用旧提交的绿色浏览器分片。

## 正式离线打包必须包含忽略的构建目录

`git archive` / 源码ZIP本身不包含被忽略的 `static/vue-catalog/`。可联网构建机先执行 npm ci/build，再按准确SHA的 `vue-catalog-preview-<SHA>` CI artifact 提供已构建资源。artifact内保留 `static/vue-catalog/` 与 `test-results/vue-catalog/` 两个路径；解压后将前者放回同一SHA源码根，截图不是运行依赖。不要将整个artifact误解压到 static/vue-catalog 造成重复目录。

在项目根执行以下步骤生成“源码+Vue静态资源”ZIP（输出放上级目录，先确保输出文件名为本次全新文件）：

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
git archive --format=zip --output=../changlian-source-with-vue.zip HEAD
python -c "from pathlib import Path; from zipfile import ZipFile; p=Path('static/vue-catalog'); required=[p/'catalog-preview.js',p/'catalog-preview.css']; assert all(x.is_file() and x.stat().st_size for x in required); z=ZipFile('../changlian-source-with-vue.zip','a'); [z.write(x,x.as_posix()) for x in p.rglob('*') if x.is_file()]; z.close(); z=ZipFile('../changlian-source-with-vue.zip'); assert all(x.as_posix() in z.namelist() for x in required); print('Vue assets included'); z.close()"
```

部署机沿用原应用静态目录 `/static` 服务，预览运行不需要 Node/npm/CDN。以上仅明确源码包加入Vue资源的方法，不能替代原离线 Python依赖/系统库/容器打包和目标机验收。尚未验证真实离线目标机部署、断网安装、生产数据、真实SDK、A800/4070、ARM64或异构硬件；不得宣称完整离线交付已完成。

架构约束保留 linux/amd64、linux/arm64、NVIDIA CUDA、华为昇腾扩展可能性，本批不实现硬件适配。P0/P1代码验收须以新SHA CI和真实上传制品核验为条件；离线现场交付单独待验。本轮结束不自动启动后续专项。
