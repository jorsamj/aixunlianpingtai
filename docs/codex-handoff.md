# Codex / 人工接管交接记录

## 当前状态

- 工作分支：`feat/windows-p0`
- 稳定主分支：`main`
- Codex WIP 接管起点：`f42313f`
- 当前版本：`42.22.4`
- 当前阶段：**停止继续加新功能，等待真实环境验收**
- 合并要求：在 Windows 前端、后端回归、Playwright、真实对象存储验证完成前，不合并 `main`。

## 不得回退的产品约束

1. 训练素材是一个统一素材池，不恢复“训练数据集分组”作为训练合同。
2. 训练任务按精确素材 ID 工作，保留 `train_image_ids` / `test_image_ids` 合同。
3. 标签是业务筛选维度；Local/OSS/S3/Remote 只是物理存储位置。
4. 外部试验/评测素材推理时，Ground Truth 只能隐藏用于评分，不能喂给模型。
5. Windows 开发与 NVIDIA Linux 生产都必须支持，禁止写死 Windows 路径或 Windows-only 命令。
6. 已有素材、标注、算法版本不能因升级被清空、移动或重新编号。

## v42.22.x 已完成主体

- Local / 阿里云 OSS / S3-MinIO / Remote Material Server 存储 Provider。
- `StorageManager` 统一解析本地和远程素材。
- Secret 与普通配置分离；前端编辑存储源留空密钥不会清掉原密钥。
- OSS 配置 Prefix 后的分页 marker 已修复。
- 外部已有素材扫描只建索引，不把整个源复制到本地。
- `MaterialRepository` 使用 SQLite + WAL，支持来源、状态、标签 OR、游标分页。
- 老 `images.json` 可迁移，素材 ID 保持不变。
- 外部历史素材即使 `stored_name=""`，读取时也生成稳定 `<image_id>.<ext>` 工作文件名；`object_key` 不变。
- SHA256 内容缓存与 Training Worker 的远程素材 materialize 已接入。
- 外部素材默认删除索引，不默认删源文件；批量删除源文件要求 `delete_source=true` + `confirmation=DELETE_SOURCE`。

## v42.22.3：主素材页性能收口

新增：
- `static/material-pagination-bootstrap.js`
- `static/modules/material-pagination-runtime.js`
- `tests/frontend/material-pagination-runtime.test.mjs`

实现：
- 普通页面/素材页面不再刷新即把全部素材塞进浏览器。
- 数据集页默认 48 张一页，使用 `/api/v61/projects/{id}/materials` cursor pagination。
- 搜索、来源、处理状态、标签 OR、已标注/未标注改为服务端筛选。
- “清洗当前素材 / 当前素材无需清洗”通过 `/materials/ids` 分页只读取 ID。
- 分页模式的摘要用服务端 total；总标注框没有 aggregate API 时明确显示“当前页标注框”。
- 为保证正确性，训练、自动标注/清洗、质量中心、测试发布、部署测试、自动迭代暂时仍进入 full material mode，避免这些旧流程只看到第一页。

## v42.22.3：`mutate()` 写放大止血

`MaterialRepository.mutate()` 已从：

- 读取全表
- DELETE 全表
- 全量重写

改成：

- callback 仍读取全表以兼容旧调用；
- 只写真正变化/新增的 rows；
- 只删除真正删除的 IDs；
- 无变化不 bump revision。

这显著降低 WAL 写放大，但 legacy callback 仍可能全表读取，不能宣称所有百万行热路径已经完成 set-based 改造。

## v42.22.4：超大 ID 与扫描进度收口

新增：
- `platform_core/material_repository_batch.py`
- `tests/unit/test_material_repository_batch.py`
- `static/modules/storage-import-progress.js`
- `tests/frontend/storage-import-progress.test.mjs`

### 大 ID 防护

`MaterialRepository` 的大批量 ID 操作安装 500 ID/批保护：

- `get_many()`：分块 SELECT；
- `remove()`：单事务、分块 SELECT/DELETE；
- legacy `mutate()`：大量删除时分块 DELETE。

目的：避免 1 万 / 10 万 ID 选择时生成超大 `IN (?, ?, ...)` 并撞 SQLite variable limit。

新增测试覆盖：
- 2200 ID `get_many`；
- 1800 ID `remove`；
- 1300 条 legacy mutate 删除。

### 对象存储扫描进度

扫描对象总数未知时，不再显示不可证明的 0% / 37% 等百分比。

运行中展示 Worker 真实返回内容，例如：

`SCANNING · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg`

- QUEUED：显示“已进入扫描队列”；
- FINALIZING：显示“正在整理扫描结果”；
- 关闭弹窗只停止浏览器轮询，不停止 durable worker task；
- 成功后同时展示 scanned/importable/duplicates/failed。

## 仍未完成 / 不得误报完成

### 1. 真实 Windows 浏览器回归

用户本机此前无法连接 `github.com:443`，因此 42.22.2+ 尚未拉到本地执行。

必须验证：
- 素材页刷新不再全量加载；
- 未处理/已处理、搜索、标签 OR、来源、标注状态筛选；
- 上一页/下一页；
- 当前筛选批量清洗/无需清洗；
- 上传和标注保存后的当前页刷新；
- 从数据页进入训练后完整素材池恢复；
- 训练全选/反选和 exact image ID 不受分页影响；
- 自动标注、质量、测试发布、部署测试不只看到第一页；
- 对象存储扫描期间不再出现假百分比。

### 2. 高频 legacy `mutate()` 仍有全表读取

目前已经消除“全表重写”和“大 ID SQL 参数”风险，但 `app.py` 中部分旧 callback 仍会读取全表，例如 split、自动划分、清洗确认、AI/导入决策、训练补充素材。

这些应在真实回归稳定后逐个改成 set-based `patch / remove / upsert`。不要在无法完整回归时对巨大 `app.py` 做整文件盲改。

### 3. 专用工作流仍有 full material mode

训练/自动标注/质量/测试发布/部署测试/自动迭代目前优先保证正确性，仍会加载完整素材池。

后续如确实需要百万规模，应把这些选择器继续改成服务端分页 + `/materials/ids`，而不是牺牲 exact image ID 正确性。

### 4. 真实 MinIO / OSS 未验证

仓库有真实 MinIO 验收代码，但环境变量未配置时会 SKIP。测试存在不等于真实验证通过。

必须实测上传、预览、cache miss/hit、混合训练、索引删除、显式源删除。

### 5. NVIDIA Linux 尚未验收

- Headless Linux Keyring/SecretStore 需要实测保存、重启、读取和脱敏。
- 启动器策略测试证明 Linux 分支不会调用 `_run_install`，也不会访问 CPU PyTorch index；这只是 mock/subprocess-policy 证据，不是 NVIDIA 机器启动验收。
- 真实 NVIDIA CUDA 启动：未验证

## NVIDIA Launcher Safety Plan：本轮回归证据

- `python -m py_compile launcher.py`：通过。
- `python -m pytest tests/unit/test_launcher_torch_policy.py tests/unit/test_launcher_workers.py -q --basetemp .pytest-task3-targeted-basetemp -p no:cacheprovider`：`29 passed, 5 warnings in 0.22s`。其中 Linux policy tests 覆盖所有 Linux 路径：`_run_install` 调用数为零，且从不使用 CPU index；该结论仅限策略测试。
- 同一组测试还覆盖 Windows pinned CPU bootstrap 及安装后 probe；均通过。此轮未以脚本入口执行 `launcher.py`，没有调用 pip，也没有改变本机 Torch。
- 第一次以正常 Windows 权限运行 `python -m pytest -q`：`1 failed, 354 passed, 4 skipped, 20 warnings in 179.82s`。唯一失败是 `tests/api/test_storage_upload.py::test_upload_to_selected_storage_source_enters_unified_pool`：清洗任务在 10 秒阈值后仍为 `running`。可复跑诊断命令为 `python -m pytest tests/api/test_storage_upload.py::test_upload_to_selected_storage_source_enters_unified_pool -q`；连续单独执行 3 次均通过，耗时分别为 `0.62s`、`0.56s`、`0.55s`。未复现确定性前序依赖或根因，也没有因此改代码。
- 第二次相同正常 Windows 权限 `python -m pytest -q`：`355 passed, 4 skipped, 20 warnings in 69.09s`（exit 0）。第一次的暂态超时仍是回归观察项，不能表述为“已修复”。
- 受限会话使用默认 Windows Temp 时，pytest 枚举 `%LOCALAPPDATA%\\Temp\\pytest-of-<user>` 报 `PermissionError [WinError 5]`。强制工作树 D: `--basetemp` 后，既有 `test_legacy_dataset_delete_refuses_remote_materials` 以 `Path.replace()` 在 C:/D: 跨卷报 `WinError 17`。两者均为测试环境诊断，不计为产品失败。
- 本轮未连接 Ubuntu 或 A800/NVIDIA 主机；不能把上述单测或 Windows 回归当成真实 Linux/CUDA 启动验证。真实 NVIDIA CUDA 启动：未验证

## 测试状态

Codex 额度耗尽前报告过：`318 passed, 4 skipped`，但那是人工接管前的版本，不能覆盖 42.22.1~42.22.4。

当前必须写成：

- 代码提交到 `feat/windows-p0`：是
- 静态审查：已做
- NVIDIA Launcher 定向测试：`29 passed`（策略测试；非真机 CUDA）
- 42.22.4 前端单测：待执行
- Playwright：待执行
- 全量后端回归：第二轮 `355 passed, 4 skipped, 20 warnings`；第一次曾出现一次未复现的清洗任务 10 秒超时，仍待后续观察
- 真实 MinIO：待执行
- 真实 OSS：待执行
- NVIDIA Linux / CUDA 启动：未验证

GitHub 当前没有 CI status，不能把“测试代码已写”表述成“已经通过”。

## 网络恢复后的验收顺序

1. `git checkout feat/windows-p0`
2. `git pull --ff-only origin feat/windows-p0`
3. 确认 `VERSION.txt = 42.22.4`
4. 先跑定向测试：
   - `tests/unit/test_material_repository.py`
   - `tests/unit/test_material_repository_batch.py`
   - `tests/api/test_material_storage_deletion.py`
   - `tests/unit/storage/test_optional_providers.py`
   - `tests/integration/test_storage_import_worker.py`
   - frontend storage/pagination/progress tests
5. 再跑 Playwright 素材库、存储源、训练选择主流程。
6. 通过后再跑全量后端回归。
7. 只修真实失败，不重新设计已稳定模块。
8. 真实 MinIO/OSS环境没有配置时必须报告 `SKIPPED / NOT VERIFIED`。
9. 全部完成后才讨论合并 `main`。
