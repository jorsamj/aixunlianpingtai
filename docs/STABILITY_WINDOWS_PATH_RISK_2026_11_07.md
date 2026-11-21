# Windows 长路径风险复核

基线为 `42.24.561` / `fc38666004168104c1d9ed1356d690fb46218561`，对应任务书第八节。测试在本机隔离目录执行。Windows NT 10.0.26300、CPython 3.12.7 x64，读取 `LongPathsEnabled` 的结果为 `0`。

## 同一发布用例的长短路径对照

用例为 `tests/unit/test_external_algorithm_publish.py::test_automatic_weight_replacement_keeps_id_and_reads_back_without_manual_selection[sophon-bm1684x]`。它使用测试字节、内存凭据、畅联客户端替身和 URL 探测替身，实际运行本地存储 Provider、SQLite 资产仓储和发布状态逻辑。三个运行使用同一用例、断言和代码。

| 临时目录 | 用例根长度 | 转换源路径长度 | 本地发布目标长度 | 结果 |
| --- | ---: | ---: | ---: | --- |
| Windows 默认 pytest 临时根，C: | 95 | 148 | 273 | 1 失败，`WinError 3` |
| 受控短根，D:，`--basetemp` 13 字符 | 45 | 98 | 223 | 1 通过 |
| 受控长根，D:，`--basetemp` 63 字符 | 95 | 148 | 273 | 1 失败，`WinError 3` |

长度是完整路径字符串的字符数。D: 上增加 50 字符即可得到相同失败，因而盘符差异不足以解释结果。默认失败和短目录通过也与上一轮的[架构整改记录](ARCHITECTURE_EVIDENCE_SCOPED_2026_11_07.md)相符。本次运行仅重测该代表用例。

通过只读查询两次 D: 测试留下的 SQLite，定位到长根下 Sophon 资产为 `FAILED`，原始权重为 `UPLOADED`，版本发布为 `PARTIAL`。Sophon 的 `storage_error` 记录了从同目录 `.part-<32 位随机串>.tmp` 到 `cba06b…-model.bmodel` 的 `WinError 3`，对应 `LocalStorageProvider._atomic_copy` 的 `os.replace`。源模型已存在，临时文件路径为 238 字符，最终目标为 273 字符。短根下原始权重和两份转换资产均为 `UPLOADED`，版本发布为 `PUBLISHED`。原用例继续验证新转换产物替换同一远端权重身份、回读确认及再次发布幂等。

复现入口如下。第二次执行向同一个命令增加 `--basetemp <新建的隔离短根>`，第三次使用同一盘符下较深的独立根。每次用一个未使用过的目录，pytest 会管理该目录。

```powershell
$env:PYTHONPATH = '.'
$env:PYTHONDONTWRITEBYTECODE = '1'
$case = 'tests/unit/test_external_algorithm_publish.py::test_automatic_weight_replacement_keeps_id_and_reads_back_without_manual_selection[sophon-bm1684x]'
python -m pytest -p no:cacheprovider -q --tb=short --confcutdir=tests/unit $case
```

## 实际业务路径与恢复边界

| 环节 | 实际路径与处理 | 本次证据 |
| --- | --- | --- |
| Windows 数据根 | `runtime_paths.resolve_data_dir` 优先取 `MC_TRAIN_DATA_DIR` 或 `MC_DATA_DIR`。缺省候选包括 `%LOCALAPPDATA%\XJAlgo\data`、旧用户目录及程序目录下的 `data`。 | 代码核对，现场目录深度待核验。 |
| 转换工作区 | `app.py` 的 `deploy_root` 和 `_deploy_job_dir` 使用 `<data>/projects/<project>/deployment/jobs/<job>`，源文件复制到 `source/<原文件名>`。任务记录、执行日志、校准和输出继续使用任务目录。Agent 回传落在 `<project>/deploy/jobs/<task>/artifacts`。发布按项目、算法、版本匹配已完成任务，任务同名时优先 Agent 根。 | 样本的转换源路径未触发报错。未运行转换器或 Agent。 |
| 本地发布 | `StorageProviderFactory` 的无显式根 `default_local` 使用项目目录。资产仓储用 `<prefix>/projects/<project>/algorithms/<algorithm>/versions/<version>/<target>/<chip>/<64 位 SHA256>-<文件名>` 构成对象键。Sophon 的目标部分为 `conversions/sophon/<chip>`。`build_artifact_object_key` 生成安全文件名并保留内容身份，完整绝对路径还取决于存储根深度、ID 和文件名。 | 同一个真实本地 Provider 已复现最终替换失败。S3/OSS 对象键不映射到该本地目标路径，源文件读取仍依赖本地工作区。 |
| 临时文件与恢复 | 本地写入在同目录创建 `.part`、刷盘、替换，`finally` 清理临时文件。资产失败落库并保留错误，发布保留 `PARTIAL`。资产重试从同一资产记录和源文件重新进入 `ensure_uploaded`，仍受版本栅栏约束。发布已有重试间隔和身份回读逻辑。 | 长目录保留原始权重的成功状态与转换失败证据。短目录通过独立运行验证，未在长目录失败库上执行迁移或恢复。 |

## 风险分类与本轮决策

- **测试环境问题已证实。** pytest 的用例目录叠加了本地发布的固定层级和哈希文件名。保持原断言，通过受控短 `--basetemp` 完成这组 Windows 本地回归。
- **业务路径存在同一条件性风险。** 报错来自产品使用的本地 Provider，而不是测试专用文件写入。Windows 部署选择较深的本地存储根、较长的 ID 或文件名时，可能达到同样的路径长度并出现部分发布。现有证据可以确认机制，现场根目录、Windows 策略、转换器和服务进程兼容性仍为 **NOT VERIFIED（待现场验收）**。
- **保留风险报告。** 本轮只改变复测使用的临时目录。本地深路径持续存在时，直接重试仍会访问同一目标。现场排查应先记录脱敏的源路径、目标路径和长度，并核对失败阶段及原资产状态。若需更改配置或迁移已有文件，须单独核验历史绝对路径、对象键与重试回读的一致性。
