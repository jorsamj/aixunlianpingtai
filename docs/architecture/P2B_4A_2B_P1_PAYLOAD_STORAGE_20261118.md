# P2B-4A-2B-P1：不可变 Payload 存储基础能力

日期：2026-11-18。基线：`a3afdc0a18661e0b77a33555f846f231e58180c8`。VERSION保持42.24.592。

## 交付范围

新增基础能力，不接入正式任务生产/执行。TaskRepository、Scheduler、训练/部署创建与发布入口、Claim、API、数据库Schema、前端、CI与VERSION没有修改。现有业务继续使用原路径；本阶段**没有解决全部生产路径的stale Payload风险**。

- `task_runtime/payload_publications.py`：确定性JSON、独立hash验证、无覆盖文件发布、业务意图身份及不可变收据。
- `task_runtime/artifacts.py`：三个受控接口、保留区隔离、删除前完整检查；没有版本/收据/暂存目录的legacy删除行为保留。
- `task_runtime/worker.py`：Fenced统一入口；准备前、版本link前、收据link前及返回前检查执行权，读取前后也检查。旧checkpoint/result/log仍使用原接口。
- `tests/unit/task_runtime/test_artifact_fencing.py`：保留原有fencing测试，新增P1定向回归，纳入现有Release Regression已执行的测试入口；不修改工作流或既有断言。

三份原有未提交的2A/2B架构设计文档留在工作区，不混入P1提交。本说明记录本轮审批对原设计的修正；不会拿早期设计中“整行Claim比较”作为后续默认合同。

## 接口与数据合同

```python
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity

identity = PayloadPublicationIdentity(
    task_id="training-parent", project_id="project-1", kind="TRAINING",
    phase="training.ready", expected_ref="payload.json", expected_parent_attempt=0,
    intent={"request_id": "accepted-request", "target": "local"},
)
prepared = store.prepare_payload_publication(identity, payload,
    activation={"stage": "queued", "required_capabilities": ["training.runtime"]})
verified = store.read_payload_version(identity.task_id, prepared.version.payload_ref)
receipt = store.read_payload_publication_receipt(identity.task_id,
    prepared.operation_id, identity=identity)
```

`store`是现有ArtifactStore实例；示例不写Task数据库。`PreparedPayloadPublication`只是完整文件提案，绝不表示Task已发布/READY或可领取。

确定性序列化为UTF-8、无BOM、sort_keys、固定separators、禁止NaN/Infinity和非字符串object key。identity在构造时序列化并脱离调用者的可变dict；读取结果以不可变bytes保存，data/metadata属性每次解析新对象。

operation_id = SHA256(canonical identity)，identity包含protocol、task_id、project_id、parent_kind、phase、expected_payload_ref、父attempt与固定intent。phase为create/training.freeze/training.ready/deployment.ready，强制phase/kind匹配；create只接受空expected_ref。子执行代数、token、Worker随机身份和当前时间不由基础接口自动注入op。调用方仍负责提供稳定业务intent，不能用随机intent规避冲突。

版本ref：`payload-versions/v1/<operation_id>/sha256-<digest>.json`；DEPLOYMENT_TEST前缀为`scenario/`。SHA256绑定实际字节，未来进程只凭ref即可独立验证，不依赖原descriptor或收据。验证不回退payload.json。

收据ref：`payload-publications/v1/<operation_id>.json`，部署同样保留scenario前缀。收据绑定完整identity、op、new_ref、digest、size及activation。允许的activation字段仅resource_key/required_capabilities/stage，且只允许READY阶段提议。读取重算op、验证身份/前缀/ref/op/digest/size/字段和实际版本；提供expected identity时还作完整身份比较。收据是固定提案证据，**不是当前Task真相，也不是执行授权**。

## 文件发布、冲突及恢复

私有`.payload-staging-v1`文件独占创建→完整写入→flush/fsync→读回验证→同文件系统os.link无覆盖发布→适用平台目录同步。关闭写句柄后才link；不使用覆盖replace，也不直接在最终名上边写边暴露。

先版本，后收据；同op同字节和相同activation幂等验证返回，不改已有mtime。不同Payload或不同activation使收据竞争报PUBLICATION_OPERATION_CONFLICT，保留胜者，可能留下孤立版本，不删除、不随机换op。P2再处理合法恢复与业务重新规划，P1不擅自选择另一个提案。

版本写失败不产生半成品最终名；版本完成而收据失败仅留孤立版本。重启重试验证已有文件后可完成同次提案。进程在版本完成后直接退出的回归验证了“有版本、无收据”；基础接口不会把它变成Task引用。所有Task数据库提交、父子关联与CAS均未实施。

异常有结构化`code`：非法身份/JSON/activation/ref、缺失版本、摘要或大小不符、收据非法、冲突、不支持后端、IO错误、保留策略。失败不访问Task数据库、不修改任务状态。同步失败可能已产生完整但未确认成功的文件，原op可重试并重新同步；不宣称OS IO错误一定意味着零文件副作用。

## 路径与删除保护

保留名称：payload-versions、payload-publications、.payload-staging-v1。普通artifact_path/atomic_write_json/append_log及Fenced旧入口拒绝保留区，包括解析后的别名路径。版本接口拒绝不安全路径、Windows保留组件、符号链接及reparse point。删除先检查普通/场景保留根，再执行任何删除；命中则ARTIFACT_RETENTION_REQUIRED，整个目录保留，没有部分删除后再抛异常。

这是受控应用内协议。root或普通父目录Path仍可由同权限代码自行拼接文件名；Python访问控制不能阻止任意同OS账号写者。未批准跨模块文件锁，也不把chmod或只读属性当强隔离。正式接入仍须覆盖写入口并排空旧发布者。

P1只保护新命名空间；普通legacy删除及业务删除API未改。正式切换前必须解决保留异常与用户删除API、空间释放之间的兼容，不能直接把目前保留所有文件认定为最终产品方案。无自动GC。

## 字节上限依据

app.py:8272–8281对显式train_image_ids/test_image_ids各限制50,000；两个UUID列表的JSON约3.9MB。定向回归实际构造并发布这一级别的请求。选择默认**64MiB**作为工程余量，Payload和收据各有独立可配置上限：ArtifactStore(max_payload_bytes=..., max_receipt_bytes=...)，读取最多limit+1字节，越界明确拒绝，不截断。

冻结selection引用展开未沿用该显式列表限制，源码不能证明所有未来请求都小于64MiB。P2接入必须按实际请求规模配置上限并处理错误；本轮不会影响旧入口，也不把默认值宣称为现行业务全域上限。小Payload上限不限制其元数据收据；两个限制在落盘前分别检查。

## 平台边界与实际验证

- Windows：仅接受GetVolumePathName/GetDriveType/GetVolumeInformation确认的本地固定NTFS卷。内部文件操作使用扩展路径，支持本机未启用普通长路径时的完整op+digest路径。实际验证无覆盖硬链接、同op幂等、跨进程竞争/崩溃与重启。符号链接创建因本机权限限制跳过；未把跳过算通过。
- Linux：只接受从/proc/self/mountinfo识别的ext2/ext3/ext4/xfs/btrfs/tmpfs/overlay；网络/未知后端明确拒绝。文件fsync后同步最终目录及父链到根目录父目录；失败明确返回，不降级覆盖。tmpfs仅进程级，overlay依赖底层存储，不提供额外掉电保证。
- os.link失败（跨设备/不支持等）明确拒绝，写入/同步等失败报IO错误。Windows网络盘、FAT/exFAT、未审查ReFS、Mac等不在首版支持范围。
- 未实施文件+SQLite跨域掉电事务，Windows没有假装支持可移植目录fsync。普通测试、进程退出测试、WSL测试均不是掉电耐久性实验。

Linux实际烟测：本机WSL Ubuntu-22.04/Python3.10.12，将本次models/artifacts/payload_publications三个原样源码复制到WSL临时本地目录（隔离无关包初始化），执行同字节摘要/read/retry/conflict、真实symlink别名/逃逸、保留检查与目录fsync，全部通过；临时目录自动清理。WSL未安装pytest，因此没有声称Linux整套pytest通过。其余Linux文件系统类型仅实现准入识别，未逐一实测。Ubuntu GitHub CI结果另外按准确新SHA报告。

## 定向验证记录

```powershell
python -m pytest -q --tb=short --confcutdir=tests/unit tests/unit/task_runtime/test_artifact_fencing.py tests/unit/task_runtime/test_artifacts.py
python -m py_compile platform_core/task_runtime/artifacts.py platform_core/task_runtime/payload_publications.py platform_core/task_runtime/worker.py tests/unit/task_runtime/test_artifact_fencing.py
git diff --check
```

Windows：35 passed、1 skipped；skip为符号链接创建权限。编译/最终Diff检查结果以提交前实际输出为准。覆盖确定性字节、跨进程独立读取、并发竞争、同op冲突、版本/收据link失败、文件写失败、fsync失败、进程在版本后退出、重启恢复、大小限制与真实请求量级、保留区、Fenced失效和删除完整性。

序列化/hash/fsync测试替身期间，另一个SQLite连接实际取得BEGIN IMMEDIATE；存储实现本身无sqlite引用。此证明基础层不持Task writer，不证明尚未实现的Repository发布事务正确。

新增用例放在既有`test_artifact_fencing.py`，已有`.github/workflows/v42.25-release-regression.yml`的Runtime, resource and conversion contracts会执行它；未手动重跑其他工作流。按AGENTS.md异步验收规则，推送后仅查询准确SHA的实际CI状态，不循环轮询；运行中不得认定通过。

## 必须保留的后续问题

A. 正式Test读取：已核实`train_worker.py:1535–1538`、`checkpoint_validation_worker.py:261–262`调用assert_frozen_formal_test。P2/P3必须建立原执行Payload ref/attempt的可信持久锚点，并保护对应snapshot/freeze历史证据，不能只替换training_material_usage.py中的路径。本轮没有改上述调用者。

B. Claim快照：后续采用语义化字段（Payload身份、状态、task/project/kind、attempt、priority/rank、resource/capabilities及真正参与Admission的stage等），**不默认比较整个Task行**。展示进度和无关metadata不自动使Claim失败。本轮未修改claim_next，也未启用Candidate Pipeline。

C. 删除保留：正式接入前必须确定用户删除任务语义、目录清理、版本保留、删除Task后的审计、空间回收与同task_id重建；P1只做防误删保护，不修改业务删除API，不自动GC。正式接入不得使原删除功能失效。

其余：TaskRepository引用CAS/父子fencing事务尚未实施；训练/部署写入口未迁移；非Payload证据不因本协议自动不可变；无旧任务迁移、无生产部署。本轮完成后等待独立复核，不进入P2。

## 协作与交付状态

主模型负责协议实现、定向测试、实际Diff与安全边界复核、Git交付；gpt-6.1-sol只读搜集Payload规模/现有CI入口并复核存储Diff，指出收据/Payload上限耦合问题，主模型独立确认后拆分限制并补回归。未委派提交、推送或架构决策，避免重复全仓审计。

本地验证、提交推送、准确SHA的CI与专项最终验收分别报告。CI尚未完成时P1保持未验收，不能正式关闭整个P2B-4A-2B。
