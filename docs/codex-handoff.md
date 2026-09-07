# Codex / 人工接管交接记录

## 当前分支

- 工作分支：`feat/windows-p0`
- 稳定主分支：`main`
- 本轮接管起点：`f42313f`（Codex 在额度耗尽前保存的 WIP）
- 当前版本：`42.22.2`

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
- 当前版本统一为 `42.22.2`。
- `app.js` / `main.mjs` / `styles.css` 查询版本同步更新。
- `storage.js` module cache key 更新为 `422202`，避免浏览器继续使用修复前的存储配置逻辑。

## 已知未完成 / 不得误报为完成

### P0：主素材页面仍未真正使用服务端分页

虽然已经有：
- `GET /api/v61/projects/{project_id}/materials`
- `GET /api/v61/projects/{project_id}/materials/ids`
- SQLite cursor pagination

但旧主页面仍通过 `/api/projects/{project_id}/images` 一次读取全部素材到 `state.images`。

因此当前不能宣称整个系统已经支持 10 万 / 50 万 / 100 万素材规模。需要把素材列表、训练选择器、筛选与“全选”逐步切换到服务端分页/ID 查询。

> 这个改动影响现有页面状态模型和训练选择器，不能用临时 monkey patch 草率切换；应作为下一轮独立性能收口任务完成并做浏览器回归。

### P0：`MaterialRepository.mutate()` 仍是全表兼容事务

旧代码仍有多处调用 `mutate()`；其实现会读取全表并重写全部 rows。大规模素材下必须逐步改成 set-based `patch/upsert/remove`，不能继续依赖全表 mutate。

### P0：存储扫描没有可证明的真实总百分比

对象存储 list API 在流式扫描前通常不知道总对象数。当前已改为显示真实扫描计数，但前端仍可能同时显示旧 `progress` 百分比。

不要伪造百分比。后续应将扫描 UI 改为“已扫描 N 个 / 可导入 M 张”的 indeterminate 进度，只有能确定总数时才显示百分比。

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

人工接管后的修改尚未在用户 Windows 环境执行完整回归。当前用户网络无法连接 `github.com:443`，所以本地 worktree 暂时也尚未拉取 `42.22.2`。

当前状态必须写作：

- 代码已提交到 `feat/windows-p0`：是
- 静态审查：已完成本轮重点项
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
4. 先运行与本轮相关的定向测试：
   - `tests/unit/test_material_repository.py`
   - `tests/api/test_material_storage_deletion.py`
   - storage frontend tests
   - storage provider unit tests
   - storage import worker integration tests
   - storage source Playwright
5. 若定向测试通过，再跑完整前端测试和 Playwright。
6. 最后再跑全量后端回归。
7. 只修真实失败，不重构无关模块。
8. 不恢复 dataset grouping，不恢复训练按 dataset 展开。
9. 完成后报告：失败原因、修改文件、测试命令、结果、commit SHA。

## 合并 main 的门槛

至少满足：

- 编辑存储源不会丢凭据；
- Local / OSS / S3 / Remote 的连接错误真实可见；
- 外部索引导入不复制源文件；
- 历史外部素材即使没有 stored_name 也可被旧导出/构建链路安全命名；
- 本地 + 外部素材可混合进入 Training Worker；
- SHA mismatch 阻止训练；
- 外部删除默认只删索引；
- 批量源文件删除有强二次确认；
- 前端单测通过；
- Playwright 核心流程通过；
- 现有标注/清洗/训练回归通过；
- 不再把“存在测试代码但未执行”写成“已验证”。
