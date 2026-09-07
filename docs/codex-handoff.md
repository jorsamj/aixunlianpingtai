# Codex / 人工接管交接记录

## 当前分支

- 工作分支：`feat/windows-p0`
- 稳定主分支：`main`
- 本轮接管起点：`f42313f`（Codex 在额度耗尽前保存的 WIP）
- 当前版本：`42.22.3`

> 在前端、真实对象存储和回归测试完成前，不要直接合并 `main`。

## 产品约束（不得回退）

1. 训练素材是统一素材池，不恢复“训练数据集分组”概念。
2. 训练任务只接受 `train_image_ids` / `test_image_ids` 精确素材 ID。
3. 标签是筛选维度，存储来源只是物理位置，两者不能混为一体。
4. `dataset_id=default` 如仍存在，只允许作为历史存储兼容字段，不得参与训练素材展开。
5. 外部试验/评测素材推理时不能把 Ground Truth 标注喂给模型；标注只能由评测器隐藏使用。
6. Windows 开发、NVIDIA Linux 生产必须同时支持；禁止写死 Windows 路径或 Windows-only shell。
7. 已存在素材、标注、算法版本不得因升级被移动、清空或重新编号。

## v42.22.x 已实现的主体

- `StorageManager` / `StorageProvider` 统一存储抽象。
- 本地、阿里云 OSS、S3/MinIO、远程素材服务器 Provider。
- `StorageSourceRepository` + SQLite 存储源配置。
- Secret 与普通配置分离，数据库不保存明文密钥。
- `MaterialRepository` SQLite 素材索引、来源筛选、标签 OR 筛选、游标分页。
- 老 `images.json` 自动迁移到 SQLite，保持素材 ID。
- 外部已有素材扫描后“只建索引，不复制整个源文件”。
- `data/cache/materials/<sha256>` 内容寻址缓存与 SHA256 校验。
- Training Worker 已通过 `StorageManager.materialize()` 取得本地/远程素材。
- 训练协议拒绝 `train_dataset_ids` / `test_dataset_ids` legacy fallback。
- 外部素材默认删除平台索引，不默认删除源文件。

## 2026-09-07 人工接管后已修复

### 1. 编辑存储源误删原密钥

修复文件：
- `static/modules/storage.js`
- `tests/frontend/storage-source-ui.test.mjs`

修复内容：
- 编辑已配置 OSS/S3/Remote 时，如果密钥输入框留空，前端不再发送 `credentials: {}`。
- 因此后端不会把“留空”误解释为“清除原凭据”。
- OSS/S3 更换凭据时，Access Key 与 Secret 必须成对填写，禁止保存半套凭据。

### 2. OSS 配置 Prefix 后分页 marker 错位

修复文件：
- `platform_core/storage/oss.py`
- `tests/unit/storage/test_optional_providers.py`

修复内容：
- 对外 cursor 继续使用公共 object key。
- 调用 OSS SDK 的 marker 时重新补回配置 Prefix。
- 避免大量对象翻页时重复、错位或卡住。

### 3. 存储导入结果字段与现有前端不一致

修复文件：
- `platform_core/storage/import_tasks.py`
- `tests/integration/test_storage_import_worker.py`

修复内容：
- canonical 字段继续保留 `scanned_files` / `importable_images`。
- 临时兼容 v42.22 初版前端读取的 `scanned` / `importable`，避免真实扫描成功却显示 0。
- 扫描期间 `current_item` 展示真实“已扫描 / 可导入 / 重复 / 失败 / 当前对象”计数。
- 最终写结果前进入 `FINALIZING`，成功任务由 Scheduler 收口到 100%。

### 4. 外部素材 `stored_name` 为空导致旧链路无法生成目标文件名

修复文件：
- `platform_core/storage/import_tasks.py`
- `platform_core/material_repository.py`
- `tests/unit/test_material_repository.py`

修复内容：
- 新导入外部素材仍然不复制进 `project/uploads`，但索引生成稳定逻辑文件名 `<image_id>.<ext>`。
- 对历史数据库中仍然存在 `stored_name=""` 的外部素材，`MaterialRepository` 读取时会兼容生成 `<image_id>.<ext>`。
- `object_key` 完全保持原值，不改变 OSS/S3/远程服务器的物理来源。
- 使用 `image_id` 作为工作文件名，避免不同目录/不同存储源中同名 `camera.jpg` 在导出/训练目录里碰撞。

### 5. 外部素材批量源文件删除二次确认

现状：后端已经要求外部素材批量删除源文件必须同时提交：
- `delete_source=true`
- `confirmation=DELETE_SOURCE`

补充文件：
- `tests/api/test_material_storage_deletion.py`

新增回归约束：
- 没有 confirmation 时必须返回 409；
- 索引和源文件都必须继续存在；
- 明确 confirmation 后才允许真正删除外部源文件和平台索引。

### 6. 本地验收产物误提交风险

修复文件：
- `.gitignore`

新增忽略：
- `.acceptance-data/`
- `.task-check-data/`
- `/yolo11n.pt`

### 7. Playwright 健康状态断言与后端状态值不一致

修复文件：
- `tests/browser/storage-source.spec.mjs`

修复内容：
- 当前后端正式状态值是 `AVAILABLE / UNAVAILABLE`，浏览器测试不再错误期待 `HEALTHY`。

### 8. 浏览器静态缓存版本未同步

修复文件：
- `VERSION.txt`
- `static/index.html`
- `static/main.mjs`

修复内容：
- 当前版本统一为 `42.22.3`。
- `app.js` / `main.mjs` / `styles.css` 查询版本同步更新。
- `storage.js` module cache key 已更新，避免浏览器继续使用修复前逻辑。

### 9. 主素材页面接入服务端分页（v42.22.3）

新增/修改：
- `static/material-pagination-bootstrap.js`
- `static/modules/material-pagination-runtime.js`
- `static/main.mjs`
- `static/index.html`
- `tests/frontend/material-pagination-runtime.test.mjs`

实现原则：
- 不直接重写已经叠加很多版本逻辑的 `static/app.js`，通过独立分页运行时收口风险。
- Bootstrap 在 `app.js` 之前安装 fetch 兼容层；普通页面初次 `loadRelated()` 对旧 `/api/projects/{id}/images` 请求只取 v61 当前页，默认 48 张，避免刷新就加载全部素材。
- “数据集”页面使用 `/api/v61/projects/{id}/materials` cursor pagination。
- 搜索、来源、处理状态、标签 OR、标注状态都传给服务端筛选，不再只筛当前浏览器内存中的全量数组。
- 未处理状态在 Repository 层统一覆盖 `unprocessed / pending_decision / cleaning`。
- 上一页/下一页使用 cursor stack，不使用高 offset 扫描。
- “清洗当前素材 / 当前素材无需清洗”使用 `/materials/ids` 分页只读取 image_id，再提交批量任务，不把几十万条完整素材元数据拉到浏览器。
- 训练任务、自动标注/清洗、质量中心、测试发布、部署测试、自动迭代暂时保留 full material mode，进入这些旧工作流时重新加载完整素材池，优先保证训练/评测正确性，避免只看到第一页。
- 普通页面的摘要数量由服务端 total 补正；总标注框尚无独立 aggregate API，因此分页模式明确显示“当前页标注框”，不伪装成全库框数量。

当前状态：
- 代码已实现并提交。
- 纯函数/静态加载顺序测试已补。
- 尚未在用户 Windows 浏览器和 Playwright 中真实执行，因此不能标记“验收通过”。

### 10. `MaterialRepository.mutate()` 去掉全表重写（v42.22.3）

修改：
- `platform_core/material_repository.py`
- `tests/unit/test_material_repository.py`

以前兼容 `mutate()` 每次都会：
1. 读取全表；
2. 执行旧 callback；
3. `DELETE FROM materials`；
4. 全量重新 INSERT；
5. 重建所有 label rows。

现在：
- 为兼容旧 callback，仍会读取全表；
- callback 完成后对比变更前/后的 normalized payload；
- 只 DELETE 真正删除的 ID；
- 只 `_write_row()` 真正新增/改变的素材；
- 没有变化时不 bump revision；
- 不再每次清空并重建整个 materials 表。

这显著降低了旧功能的小批量操作写放大和 WAL 压力，但它仍不是百万行热路径的最终方案。

## 已知未完成 / 不得误报为完成

### P0：服务端分页已接入，但仍需真实浏览器回归

v42.22.3 已经实现主素材页面的服务端 cursor pagination，但在合并前必须真实验证：
- 页面刷新不再请求全量 `/images` 数据；
- 未处理/已处理切换；
- 标签 OR 筛选；
- 名称搜索；
- 来源筛选；
- 已标注/未标注；
- 上一页/下一页；
- 当前筛选批量清洗/无需清洗；
- 上传后当前页刷新；
- 标注保存后当前页刷新；
- 从数据页进入训练任务后完整素材池恢复；
- 训练全选/反选/精确 image_id 行为不受分页影响；
- 自动标注、质量中心、测试发布/部署测试不只看到第一页。

在 Playwright/Windows 实测前，不得写成“10万/50万/100万素材页面已验收”。

### P0：继续把高频旧 `mutate()` 调用改成 set-based API

`mutate()` 已不再全表 DELETE+重建，但 legacy callback 仍然需要先读取全表。

后续应优先把这些高频操作迁移成 `patch / upsert / remove`：
- 单张/批量 split 更新；
- 自动划分；
- 清洗确认/无需清洗；
- AI/导入决策后的素材状态 patch；
- 训练补充素材 split 更新。

复杂的历史“数据集物理删除恢复事务”先保留兼容流程，不在没有完整回归时强拆。

### P0：存储扫描没有可证明的真实总百分比

对象存储 list API 在流式扫描前通常不知道总对象数。当前已改为显示真实扫描计数，但前端仍可能同时显示旧 `progress` 百分比。

不要伪造百分比。后续应将扫描 UI 改为“已扫描 N 个 / 可导入 M 张”的 indeterminate 进度，只有能确定总数时才显示百分比。

### P1：专用工作流仍采用 full material mode

为了不破坏现有训练/自动标注/质量/发布逻辑，v42.22.3 在这些页面仍会加载完整素材池。

下一阶段可逐步将：
- 训练素材选择器；
- AI 标注选择器；
- 质量中心；
- 发布/部署测试素材选择；

改成服务端分页 + `/materials/ids` 的 exact image-id 合同。完成前不要为了“全站零全量读取”牺牲任务正确性。

### P1：真实 MinIO / OSS 尚未在本机证明执行

仓库已有真实 MinIO 验收测试，但通过环境变量控制，默认会跳过。不要把“测试代码存在”写成“真实 MinIO 已通过”。

需要真实环境执行后记录：
- Endpoint
- 测试时间
- 上传/预览/缓存 miss/hit/混合训练/删除语义结果
- 失败日志（如有）

真实阿里云 OSS 也需要单独执行。

### P1：Linux NVIDIA Headless SecretStore 尚未验证

当前生产凭据主要依赖系统 Keyring。API 单测大量使用 `MemorySecretStore`，不能证明无桌面 Linux 一定存在可用 keyring backend。

NVIDIA Linux 上必须实测：
1. 保存 OSS/S3 凭据；
2. 服务重启；
3. 凭据仍可读取；
4. 普通 SQLite/JSON/API 永不返回明文；
5. 无 keyring backend 时给出明确解决方案，不可假成功。

### P1：Linux NVIDIA 启动器仍需单独处理

`launcher.py` 目前仍固定安装 CPU PyTorch 组合，不能直接作为新 NVIDIA Linux 服务器的 GPU 安装器使用。

不要在 NVIDIA 生产机上未经修改直接执行该 CPU bootstrap。应提供独立 Linux/NVIDIA 安装或检测流程。

### P2：大文件上传仍经 FastAPI 中转

OSS/S3 Provider 已支持 presigned URL，但当前浏览器图片上传仍通过 API 服务中转。普通图片可用，但大规模/大文件建议后续切到短时签名直传或 multipart/resumable 方案。

### P2：素材缓存尚无容量/LRU治理

SHA256 cache 已可复用，但正式生产前需要：
- 最大容量
- LRU/TTL 清理
- 磁盘水位保护
- 正在被任务引用的缓存文件禁止误删

## 测试状态

Codex 在额度耗尽前报告：
- 后端全量回归：318 passed，4 skipped
- 没有失败

但这只是 Codex 当时本机输出，GitHub 当前没有对应 CI status，不能视为独立验证。

人工接管后的修改尚未在用户 Windows 环境执行完整回归。当前用户网络无法连接 `github.com:443`，所以本地 worktree 暂时也尚未拉取 `42.22.3`。

当前状态必须写作：

- 代码已提交到 `feat/windows-p0`：是
- 静态审查：已完成本轮重点项
- MaterialRepository differential mutate：已实现，待本机测试
- 主素材服务端分页：已实现，待浏览器/Playwright 回归
- 后端全量回归（人工接管后）：待执行
- 前端单测（人工接管后）：待执行
- Playwright（人工接管后）：待执行
- 真实 MinIO：待执行
- 真实 OSS：待执行
- NVIDIA Linux：待执行

## Codex 恢复额度后的最省额度执行方式

不要重新分析整个项目。直接：

1. `git checkout feat/windows-p0`
2. `git pull`
3. 阅读本文件。
4. 先运行定向测试：
   - `tests/unit/test_material_repository.py`
   - `tests/api/test_material_storage_deletion.py`
   - `tests/frontend/material-pagination-runtime.test.mjs`
   - `tests/frontend/storage-source-ui.test.mjs`
   - storage provider unit tests
   - storage import worker integration tests
5. 再运行素材分页相关 Playwright：刷新、筛选、翻页、批量动作、进入训练页面恢复完整素材池。
6. 若定向测试通过，再跑完整前端测试和 Playwright。
7. 最后再跑全量后端回归。
8. 只修真实失败，不重构无关模块。
9. 不恢复 dataset grouping，不恢复训练按 dataset 展开。
10. 完成后报告：失败原因、修改文件、测试命令、结果、commit SHA。

## 合并 main 的门槛

至少满足：

- 编辑存储源不会丢凭据；
- Local / OSS / S3 / Remote 的连接错误真实可见；
- 外部索引导入不复制源文件；
- 历史外部素材即使没有 stored_name 也可被旧导出/构建链路安全命名；
- 主素材页面 server-side paging 真实浏览器回归通过；
- 训练/自动标注/质量/发布工作流不会因为分页只看到第一页；
- 本地 + 外部素材可混合进入 Training Worker；
- SHA mismatch 阻止训练；
- 外部删除默认只删索引；
- 批量源文件删除有强二次确认；
- 前端单测通过；
- Playwright 核心流程通过；
- 现有标注/清洗/训练回归通过；
- 不再把“存在测试代码但未执行”写成“已验证”。
