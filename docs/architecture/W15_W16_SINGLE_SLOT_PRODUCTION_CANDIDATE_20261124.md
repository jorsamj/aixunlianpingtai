# W15/W16 单槽生产候选与离线交付收口（2026-11-24 / N6 轮）

> 状态标签：`SINGLE_SLOT_CANDIDATE_EVIDENCE_RECORDED` /
> `REAL_GPU_UAT_NOT_VERIFIED` / `REAL_HARDWARE_INFERENCE_NOT_VERIFIED` /
> `PRODUCTION_DUAL_SLOT_DISABLED` / `A800_PREFLIGHT_REQUIRED` /
> `A800_PRODUCTION_UPGRADE_NOT_EXECUTED` / `OFFLINE_INSTALL_NOT_VERIFIED` /
> `REAL_SYSTEMD_HOST_NOT_EXECUTED` / `CANDIDATE_CI_PENDING`
>
> 本文件只记录可在隔离环境复现的证据与明确未验证边界。**未对 A800、4070、任何生产服务、
> 生产数据库/素材/GT/模型执行任何操作；未升级、未部署、未启用双槽；未执行真实 systemd、
> 真实断网安装；本轮未做任何 Git 写操作（无 commit/push/tag）。**

## 1. 候选身份（N6.3）

```text
CANDIDATE_CODE_SHA_40HEX = "bee265a488983d4dc206d0f901d6f169af9e9f15"
```

> 该行为唯一候选代码 SHA 占位：**由主代理在本轮全部代码提交完成后替换为远端实际 40 位
> SHA；未替换前不得作为生产候选身份，也不得把本文档其余证据当作可部署候选。**
> 占位值不是 40 位十六进制，工具会 fail-closed 拒绝（见 §5 的 N6.1 测试）；不得用
> “当前 HEAD / 最终 SHA / CI 全绿”代替这个准确 SHA。

| 项 | 值 |
|---|---|
| 唯一开发分支 | `feature/external-algorithm-publishing` |
| **代码候选 SHA（40 位）** | 见上方 `CANDIDATE_CODE_SHA_40HEX`（=`bee265a488983d4dc206d0f901d6f169af9e9f15`，已推送远端） |
| VERSION.txt | `42.24.592`（本轮未修改） |
| 运行时 build_id | 部署时必须等于代码候选 SHA：`MC_BUILD_REVISION=<候选SHA>`，或 Git worktree HEAD 恰为该 SHA；证据以 `/api/health` 的 build/version 与本地 `resolve_build_identity` 一致为准 |
| 前端构建身份 | `static/vue-catalog/offline-assets.json` 与 `static/vue-app/offline-assets.json` 的 receipt（`sha`=候选SHA、`build_origin=github-actions`、逐资源 sha256/bytes）；`UI_BUILD_VERSION=42.25.0-dev` 仅为内部 UI 构建元数据，**不是产品版本**。本机开发 checkout 的 receipt 为 `local-check`/`sha=null` 且缺 app receipt，属未验证；生产候选必须以候选 SHA 的 CI artifact receipt 为准 |
| Python 依赖身份 | `requirements*.txt` 内容摘要 + 已安装关键发行版版本指纹（见 §2.1）；不提供 wheelhouse 哈希清单 |
| CI 事实 | **CI_PENDING**：`bee265a488983d4dc206d0f901d6f169af9e9f15` 推送后单次查询（2026-11-24 16:20 +08）24 个 workflow 已触发、0 completed；未完成前不称验收通过，接受状态以该 SHA 的实际 Actions 结果为准 |
| 双槽开关 | 生产默认关闭（见 §3.2） |
| 生产升级工具 | `tools/production_upgrade.py`（预检 + 受控备份 + 数据库/应用/协调回滚） |

候选定义：准确 40 位代码 SHA（占位替换后）+ VERSION + 前端构建身份 + 对应准确 SHA CI
+ 本文件验证边界。本文档、单槽绿色测试与 CI 均不等同生产部署安全。

## 2. 本轮 N6.1 剩余安全边界（隔离实现并测试）

### 2.1 备份/回滚绑定前端构建身份与 Python 依赖指纹

- `backup.json` 新增 **`frontend_build`**：逐 receipt 记录 `receipt_sha256/bytes/
  receipt_code_sha/build_origin/asset_count/assets_digest`；worktree 模式下逐个资源复核
  `sha256+bytes`，资源被重建但 receipt 未更新（或 receipt 缺失/越界/非法字段）记为
  `invalid`，不冒充干净；读取 `UI_BUILD_VERSION`；生成稳定 `identity` 摘要；
  `matches_code_sha` 用候选/previous SHA 对比 receipt `sha`；全部不可得时显式
  `unavailable`（含原因），不猜测。
- `backup.json` 新增 **`python_dependencies`**：记录每个 `requirements*.txt` 的
  sha256/bytes 汇总摘要，以及 `importlib.metadata` 中关键发行版已安装版本；状态
  `ok/partial/unavailable`。本工具**从不 pip install/upgrade**。
- 协调回滚结果新增 **`application_identity_binding`**（dry-run 也输出）：
  - `frontend_build.matches_recorded`：备份时前端构建 vs 部署机当前构建；
  - `frontend_build.restorable_by_git=false`：前端构建目录被 `.gitignore` 忽略，
    **Git checkout 不能恢复**，需按目标 SHA 的构建另行恢复；
  - `receipt_sha_matches_target_code`：当前部署前端构建的 receipt SHA 与回滚目标代码 SHA
    对比；`recorded_receipt_sha_matches_backup_code`：备份绑定时的自洽性；
  - `python_dependencies.installed_matches/requirements_match/changed_packages`。
  - 显式风险码（不静默）：`FRONTEND_BUILD_CHANGED_SINCE_BACKUP`、
    `FRONTEND_BUILD_BOUND_TO_DIFFERENT_CODE_SHA`、
    `FRONTEND_BUILD_BOUND_TO_DIFFERENT_BACKUP_CODE_SHA`、
    `PYTHON_DEPENDENCY_VERSION_DRIFT`、`PYTHON_REQUIREMENTS_CHANGED_SINCE_BACKUP`、
    `*_IDENTITY_UNAVAILABLE`；在 `identity_risks` 与 stderr `APPLICATION_IDENTITY_RISK`
    同时给出。
- 边界：身份不一致是**显式风险字段**（不自动阻断应急回滚），工具不会修改前端构建、
  Python 包或 requirements；`write_silence=unverified` 保持不变，仍不宣称跨库业务一致或灾备。

### 2.2 systemd 配置差异检测（只读，不自动改）

- `capture_systemd_configuration()`：`systemctl show` 读取 `FragmentPath`、`DropInPaths`、
  `EnvironmentFiles`，对 unit/drop-in/env 文件做 sha256/大小/符号链接目标记录；
  `Environment=` **只记录摘要与键数，绝不落原文**（可能含密钥）。
- `--apply` 升级在停服前取快照，启动并校验 Worker 后再次快照并比较；差异输出
  `SYSTEMD_CONFIGURATION_RISK`（风险码 `SYSTEMD_CONFIGURATION_CHANGED_DURING_UPGRADE`）；
  失败路径也尝试对比并输出 `SYSTEMD_CONFIGURATION_RISK_ON_FAILURE`。全程只读，
  **不自动修改任何 unit/drop-in/env 文件**；同一配置不受影响时明确打印 unchanged。

### 2.3 停服前/停服后活动任务复核（fail-closed）

- 保留原有 `require_idle_tasks`：升级前、停服后合并代码前各检查一次；回滚前/停服后各一次。
- 新增 `require_post_stop_idle()`：停服后二次只读探测 active tasks、未释放
  `execution_resource_holds`、agent 心跳（TTL）、worker build marker；发现正证据即
  `POST_STOP_ACTIVITY_BLOCK_UPGRADE` / `POST_STOP_ACTIVITY_BLOCK_ROLLBACK` 失败关闭，
  升级未切码时恢复旧服务、回滚保持 stopped，**不自动 force**。
- 只有显式 `--force-idle` 才记录 `forced=true` + `forced_reasons`，且
  `write_silence` 仍 `unverified`；不把强制当一致性证明。

### 2.4 回滚后 detached HEAD 与后续升级

- 协调回滚按设计以非破坏性 `git checkout --detach <目标SHA>` 留在 detached HEAD；
  结果输出 `detached_head=true`、`branch_restore_required=true`、
  `branch_restore_command="git -C <repo> switch feature/external-algorithm-publishing"`。
- `--target` 升级预检：detached HEAD 时拒绝
  `DETACHED_HEAD_UPGRADE_BLOCKED` 并打印上述精确命令；**工具绝不自动切分支/合并/重置**。
  运维显式恢复分支后，dry-run 预检恢复允许（测试覆盖允许路径且不执行 merge）。

### 2.5 部分恢复/失败状态与“回滚后再次升级”语义

- 保留结构化失败诊断：`partial_restore`（restored/already_restored/failed/
  not_attempted）、`safety_backup_dir/manifest_sha256`、`services=stopped`、
  `post_stop_activity`、`identity_risks`、`application_sha`、幂等重试说明；CLI 输出
  `PARTIAL_RESTORE` JSON + `DEPLOYMENT_REFUSED`，退出码 1，不做第二次自动回滚。
- 新增测试覆盖：部分恢复失败后 HEAD 已停在目标 SHA（detached）→ 再次 `--target`
  升级被拒绝（含恢复分支命令）；显式恢复分支后 dry-run 允许；协调回滚成功后同样拒绝
  直到恢复分支。
- `write_silence=unverified` 与 `disaster_recovery=false` 原样保留，不新增一致性声明。

## 3. 单槽候选基线

### 3.1 已验证功能（隔离/测试证据）

| 能力 | 证据 | 边界 |
|---|---|---|
| 原有本地训练/远程单槽训练/单槽转换 | `tests/integration/test_training_task_worker.py`、`test_node_agent_training_runtime.py`、W9 转换/数值/Manifest 测试 | 未在真实 20k 素材/GPU 上跑 |
| 历史任务与 DB schema | schema-6/7 fixture 迁移、`v42.25-release-regression.yml` 套件 | 生产历史库未拷贝验证 |
| 单槽默认、双槽关闭 | §3.2 不变量测试 | 生产节点配置未核对 |
| 生产升级工具（预检/备份/回滚） | `tests/unit/test_production_upgrade.py`、`test_production_upgrade_rollback_m10.py`、`test_production_upgrade_n61_safety.py`、`test_deployment_upgrade_safety.py` | 仅隔离 mock/临时 Git+SQLite；真实 systemd 未执行 |
| N6.1 身份绑定/systemd diff/停服复核/detached 预检 | 本轮新增 10 项 N6.1 测试（见 §5） | 真实主机未执行 |
| 前端离线资源与精确 SHA 打包 | `tests/frontend/vue-offline-chunks.test.mjs`（2/2）、合成端到端（§4.3） | 真实 CI artifact 与断网机未验证 |

### 3.2 默认关闭功能（生产口径）

| 项 | 生产默认 | 证据 |
|---|---|---|
| Agent 执行槽 | 1（`DSH_AGENT_EXECUTION_SLOTS=2` 本地 opt-in） | `test_dual_slot_execution_is_explicit_opt_in_and_defaults_to_one_slot` |
| 中央双槽授权 | 无（节点能力默认空列表） | `service_nodes.py` 默认 allowed/reported |
| 双槽故障语义 | 缺 Hold 一律拒绝释放 | `_dual_hold_verified()` + 原始槽位合同测试 |
| 单槽远程 finish | 无中央停证（既有边界） | 双槽才有 Hold/Stop Proof 合同 |

### 3.3 数据库迁移、备份范围与回滚条件

- **数据库迁移**：控制面 SQLite schema 版本由代码声明；协调回滚前按目标代码声明的
  schema 与备份库实际 schema/关键表列做 fail-closed 兼容评估（不兼容/未知/不可读一律
  `BACKUP_SCHEMA_INCOMPATIBLE` 拒绝）；**本轮未在生产库执行迁移**。服务启动可能重建
  WAL/checkpoint，故回滚后启动前后各做一次 SHA256/quick_check（启动后差异仅告警不伪称一致）。
- **备份范围**：仅控制面 SQLite（`task_runtime/tasks.sqlite3`、`storage/storage_sources.sqlite3`、
  `model_artifacts/artifacts.sqlite3`、`external_algorithm_publish/publications.sqlite3`、
  `projects/<project_id>/*.sqlite3` 顶层文件）；素材/媒体原文件、模型权重、训练产物/
  checkpoint、项目其他业务文件**明确排除**；`write_silence=unverified`、
  `cross_database_atomic=false`、`disaster_recovery=false`。
- **回滚条件（三种独立语义）**：
  1. 数据库恢复：`--rollback [--apply --acknowledge-data-restore]`，仅替换 manifest 记录
     的数据库，`application_rollback=not_requested`，不删除备份后新建库；
  2. 应用回滚：协调回滚 `--rollback-application-to <40hex>`，目标必须是备份
     previous_sha 或其后代祖先，非破坏性 detached checkout，不 reset/clean/stash；
  3. 协调回滚：先验证备份/schema/身份绑定 → 停服 → 停服后活动复核 → checkout+
     恢复权限+数据库 → 启动校验；任一步失败保持 stopped、不自动二次回滚，输出结构化
     诊断与 pre-rollback 安全快照位置。
- **升级前置**：分支正确且**非 detached HEAD**、worktree 干净、无活跃任务、服务
  active、目标 SHA 为当前 HEAD 后代且位于远端分支、备份已创建并 verify（或显式
  `--acknowledge-no-data-backup`）、停服后活动复核通过（或显式 `--force-idle`）。

### 3.4 现场 UAT 与已知风险

- 现场 UAT 顺序见 §8；A800/4070 只读预检前不得 `--apply`。
- 已知风险：真实 systemd/Linux 主机未跑；A800 现场状态未核实；前端构建输出不由 Git
  恢复；Python 依赖升级不由回滚恢复（仅风险提示）；systemd 配置漂移只报告不修复；
  `--force-idle/--force/--acknowledge-*` 均为显式例外，不产生一致性声明；素材/权重/
  产物不在快照范围，必须现场已有独立备份。

## 4. N6.2 离线安装事实清单与阻断

### 4.1 已有能力（全仓定位结论）

| 能力 | 现有实现/证据 | 状态 |
|---|---|---|
| 前端静态资源离线校验 | `tools/verify_vue_offline.mjs`（manifest 闭包/动态页/不安全路径/空资源）与 `tools/verify_vue_app_offline.mjs`（SPA 入口、仅本地资源、拒绝远程运行时依赖、receipt sha/build_origin） | 已有（隔离验证 2/2） |
| 精确 SHA 源码+同 SHA CI 前端资源打包 | `tools/package_vue_offline.py`：40hex SHA、artifact name/digest、receipt `sha`/`build_origin=github-actions`、逐资源 sha256/bytes、ZIP CRC、source ZIP comment=SHA、拒绝重建、输出证明 JSON | 已有（合成端到端 PASS） |
| 离线打包文档 | `docs/PRODUCTIZATION_P0_P1_CLOSEOUT_20261116.md`「正式离线打包必须包含忽略的构建目录」；CI artifact `vue-catalog-preview-<SHA>` | 已有 |
| 板端 Agent systemd 安装 | `tools/install_rockchip_agent.sh`：Linux/root、预装 Python/RKNNLite、doctor fail-closed、0600 EnvironmentFile、unit 生成；自身不联网安装依赖 | 已有（未在目标板执行） |
| Python 依赖版本记录 | `requirements.txt`（19 行：3 个 `==`、16 个范围）、`requirements-dev.txt`、`remote_web_requirements.txt`；optional FiftyOne 哈希锁 `optional-dependencies/fiftyone-windows-py312.lock.txt`（仅可选 sidecar，含 `--no-index --find-links --require-hashes` 指引） | 部分（主依赖无锁无 wheelhouse） |
| 升级/健康检查 | `tools/production_upgrade.py`、`/api/health` | 已有（隔离） |

### 4.2 缺失能力（准确阻断，不得宣称离线安装完成）

- 无 `install_offline.sh`/`wheelhouse`/`pip download` 打包脚本（全仓搜索无此类脚本，`wheelhouse` 不存在）；
- 无主 Web/Worker 的 systemd unit 安装脚本（仓库内无 `.service` 文件；生产依赖既有现场安装）；
- 无 Python wheels（主依赖）及哈希清单、无系统库/驱动清单、无模型权重/字体离线包；
- 无离线启动编排、断网 health check、安装后验证脚本；
- 依赖版本不可复现：主 requirements 19 行中仅 3 个精确 pin，16 个为范围；`remote_web_requirements.txt` 0 pin；
- 本机工作区 `static/vue-catalog/offline-assets.json` 为 `local-check`/`sha=null` 且缺
  `static/vue-app/offline-assets.json`，说明本地构建 receipt **不是**候选身份；生产候选必须
  使用候选 SHA 的 CI artifact（`vue-catalog-preview-<SHA>`）再经 `package_vue_offline.py` 校验；
- **发现隐式联网**（不在本轮允许修改清单，仅报告，未改）：`start_remote_deploy_server.sh`
  （无条件 `pip install ...`）、`start_remote_deploy_server.bat`（`pip install -r
  remote_web_requirements.txt`）、`tools/install_ultralytics_to_lab.bat`（显式 PyPI 镜像）；
  这些脚本不能用于断网安装；
- Windows 本机无法完成 Linux 断网安装与 true systemd 验证：`OFFLINE_INSTALL_NOT_VERIFIED` 保留。

### 4.3 本轮隔离验证（真实执行，非生产）

1. `python -m py_compile tools/package_vue_offline.py`：exit 0。
2. `node --test tests/frontend/vue-offline-chunks.test.mjs`：**2 passed / 0 failed**
   （闭包校验、路径逃逸/空资源/缺失依赖拒绝；精确 SHA 双构建打包、mismatch 拒绝）。
3. 合成端到端：临时 Git 仓库（真实 commit）+ 构造同 SHA `github-actions` artifact +
   metadata → `package()` 输出 delivery ZIP；校验 comment=SHA、包含 `VERSION.txt`/vendor/
   两套前端资源/交付元数据、`proof.rebuilt=false`、`crc=PASS`；负例：receipt SHA 不匹配、
   `local-check` 本地重建均 `ValueError` 拒绝（**PASS**）。
4. 缺依赖显式阻断：`pip install --no-index --find-links <空目录> --no-deps fastapi`
   → `No matching distribution found`，exit 1（无 wheelhouse 时不会隐式联网）。
5. 离线脚本静态扫描：三份 `*offline*` 脚本无 `pip/curl/wget/urllib/npm install` 网络调用；
   `verify_vue_app_offline.mjs` 仅有“拒绝远程运行时依赖”的正则字面量。
- **未执行/未验证**：真实 Linux 断网安装、真实 CI artifact 下载、`npm ci/build` 断网构建、
  wheelhouse 生成与 `--require-hashes` 安装、主 Web/Worker systemd 安装、断网启动与健康检查。

### 4.4 目标机断网验证的最小步骤（待授权执行）

1. 联网同发行版机：`pip download -r requirements.txt -d wheelhouse` 并生成哈希清单；
   同时准备系统库/模型/字体与 `git archive <候选SHA>` + 该 SHA 的 CI 前端 artifact。
2. 用 `tools/package_vue_offline.py` 生成“源码+前端资源”ZIP（需与 CI artifact/metadata 同 SHA）。
3. 目标机断网：`pip install --no-index --find-links wheelhouse --require-hashes -r requirements.txt`；
   解压源码与前端资源；安装/核对 systemd unit 与环境文件；启动 Web/Worker；
   `/api/health` 返回 ok 且 build/version 与候选 SHA/VERSION 一致；`--target` dry-run 预检通过。
4. 全程记录每一步缺失项；未完成前保持 `OFFLINE_INSTALL_NOT_VERIFIED`。

## 5. 可复现命令（隔离环境）

```bash
# 原有升级工具验收（本轮真实执行：42 passed, 1 skipped）
python -m pytest -q tests/unit/test_production_upgrade.py \
  tests/unit/test_production_upgrade_rollback_m10.py tests/unit/test_deployment_upgrade_safety.py
# N6.1 新增边界测试（本轮真实执行：10 passed；含候选 SHA 占位不得通过 40-hex
# fail-closed 门、替换为真实 40-hex 后该门接受的断言）
python -m pytest -q tests/unit/test_production_upgrade_n61_safety.py
python -m py_compile tools/production_upgrade.py
python tools/production_upgrade.py --help
# 离线前端资源/打包（本轮真实执行：2 passed；package 需在候选 SHA checkout 根目录执行）
node --test tests/frontend/vue-offline-chunks.test.mjs
python -m py_compile tools/package_vue_offline.py
# 单槽/恢复/双槽合同、真实 HTTP E2E、Linux SIGKILL（在准确 Linux CI 上按原命令执行）
python tools/production_upgrade.py --target <候选SHA>            # 默认 dry-run；detached 会拒绝
python tools/production_upgrade.py --backup-only --backup-dir /data/backups/pre --target <候选SHA>
python tools/production_upgrade.py --rollback --backup-dir /data/backups/pre   # dry-run 校验
```

## 6. 明确未验证（不得宣称通过）

- `CANDIDATE_CI_PENDING`：§1 代码候选 SHA 已回填为 `bee265a488983d4dc206d0f901d6f169af9e9f15`；该 SHA 的 GitHub Actions 尚未全部完成（单次查询时 0 completed），在获得必要 CI 证据前不得称生产候选验收通过；
  工具对占位值 fail-closed（`TARGET_SHA_REQUIRED`/`PREVIOUS_SHA_REQUIRED`，有测试断言）；
  CI 事实 UNKNOWN（未联网查询）。
- `REAL_GPU_UAT_NOT_VERIFIED`：真实双卡 UAT 未执行（`W7B_GPU_UAT_CHECKLIST_20261123.md` 保持未执行）。
- `REAL_HARDWARE_INFERENCE_NOT_VERIFIED`：RKNN/BMODEL/TensorRT 等板端推理未执行。
- `A800_PREFLIGHT_REQUIRED`、`A800_PRODUCTION_UPGRADE_NOT_EXECUTED`：未接触 A800/4070/生产。
- `REAL_SYSTEMD_HOST_NOT_EXECUTED`：真实 systemd unit/env 差异检测、停服复核、升级/回滚
  本机未执行（仅在隔离临时文件/模拟 systemctl 下验证）。
- `OFFLINE_INSTALL_NOT_VERIFIED`：真实 Linux 断网安装、wheelhouse/系统库/模型/字体、
  断网启动与健康检查均未验证。
- 真实 20 万级素材、长稳、P95 性能：未在生产数据/主机测量。
- 真实 Linux POSIX SIGKILL 全链路：以准确 SHA 的 GitHub Actions Linux job 实跑结果为准。

## 7. 建议的现场 UAT 顺序（需单独授权，本轮不执行）

1. 目标机只读预检：确认分支、非 detached、worktree 干净、服务名/8010 健康与路径匹配；
   `tools/production_upgrade.py --target <候选SHA>`（dry-run）。
2. `--backup-only --backup-dir <安全路径>` 并 `verify_data_backup` 通过；确认
   `backup.json.frontend_build/python_dependencies` 为 ok 或明确 unavailable。
3. 单槽基线：本地训练、远程单槽训练、单槽转换各 1 个任务；检查任务/报告/Hold/日志。
4. 升级作业窗口：`--apply --backup-dir ...`；检查输出中 `POST-STOP IDLE PROBE`、
   `SYSTEMD_CONFIGURATION`（变更即风险，先人工确认配置来源）、Web/Worker 状态。
5. 如需回滚：先 `--rollback ...`（dry-run）核对 `application_identity_binding.identity_risks`
   与数据库/schema 诊断，再 `--apply --acknowledge-data-restore`；
   协调回滚后按输出的 `branch_restore_command` 显式恢复分支，再执行后续升级。
6. 前端构建若与回滚目标 SHA 不一致，按该 SHA 的 CI artifact 单独恢复
   `static/vue-catalog|vue-app`（Git 不恢复）；Python 依赖漂移同理需单独还原环境。
7. 双槽仅在独立授权节点按 W7-B 清单验证；验证前生产保持关闭。

### 历史记录（上一轮 M11/M13-A/M14-A，保留不重写）

- 候选代码 SHA（上一轮）: `3d17cc74`；文档提交随后。CI 事实（`39a1d0f1`/`fe0e964c`）：
  Node Agent Executor PR run 45331930879 success，Linux job 138234917704 的 POSIX
  crash-window 与 Real Node Agent OS SIGKILL recovery 两个 step 均 success ⇒
  `AGENT_SIGKILL_RESTART_E2E_PASS`；同 SHA push run Windows contract 失败根因已由
  `d803afea` 修复。
- M11：`/app` 新增 AI 任务列表/转换记录/服务节点三个只读原生页；旧入口、菜单、算法库
  卡片、素材标注台入口保持不变；vue-tsc、vite app build、Node 合同、Playwright 本地验证。
- M13-A：真实请求可触发 `TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE`；显式负样本必须能
  归属目标算法，否则 fail-closed。
- M14-A：取消未证明进程停止时进入 `cancelling_unverified` 诊断并退避重试，不释放 GPU/lease。
