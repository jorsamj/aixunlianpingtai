# 畅联云算法训练平台｜2026-11-16 双轨部署准入与现场只读核查

> **状态：DEPLOYMENT NOT AUTHORIZED / NO PRODUCTION ACCESS.** 本文件只提供准入合同与只读核查，不能证明 A800 或双4070 当前版本可直接部署。所有生产操作必须单独取得用户明确授权。本文件不是实施记录。

## 0. 唯一正确的 GitHub 开发分支

- 仓库：`jorsamj/aixunlianpingtai`。
- 唯一允许开发、提交与推送的分支：`feature/external-algorithm-publishing`。**禁止按历史 RC 手册直接切换旧 `refactor/frontend-runtime-stabilization` 分支**，禁止合并/强推 main 或创建 Release。
- 每次部署前重新从远端取得完整 SHA，冻结后不随分支后续 HEAD 漂移；必须以**该 SHA 自身** CI 和部署实测作准入，不准引用其他 SHA 的“全绿”。
- 上一轮已验收 2C-03A 功能 SHA `09a042d535aa0520acea4d3c0d7892c037163dda`（23/23），**该版本号不等于平台所有业务发布功能的已验收版本**；不要误把 2C-03A 合同通过当成可直接生产上线的证据。
- 当前 2C-03C 中央签名停止、OS journal 及真实停止联调**仍未生产验收**，禁止启用 Supervisor PT 转换。

## 1. 两条完全独立的发布轨道

| 轨道 | 范围 | 准入 | 禁止 |
| --- | --- | --- | --- |
| A：现有稳定平台与既有 Runner | 前端、API、原任务调度、训练、标注、素材、原 `AgentConversionRunner` 等既有能力 | 指定候选 SHA 本身 CI 全绿，现场备份/回滚、真实功能验收、任务安全窗口、用户授权 | 不启用 `supervisor-required`，不宣称新系统可信 StopReceipt/远程失联恢复完成 |
| B：新 Supervisor 受保护 PT→ONNX | 中央 STOP 签名、root-owned journal、受保护执行、真实可信 StopReceipt、中央恢复/资源释放、原 Runner 上传/发布 | 独立完成 2C-03C/StopReceipt/central CAS、systemd249、完整 Runner 接管和负面/现场验收后再单独授权 | 不得把原 CI PoC、固定官方 `yolo11n.pt` 导出或内存 CAS 演示当成生产部署授权 |

> A 轨道可以先行准备；不能因 B 未完成而一概阻塞业务，但 A 自身的生产准入、候选版本与回滚仍必须独立确认。

## 2. 现场只读核查清单（无停机、无训练、无数据库写入）

以下仅供经授权的运维人员在**对应服务器本地**执行；不要向第三方发送秘钥、原始素材或日志中的敏感数据。

### 2.1 A800 只读核查

已知历史业务数据目录：`/data/platform-data`，**不保证现时部署版本、运行状态和端口仍与历史一致**。

```bash
date -Is
uname -a
df -h / /data/platform-data
sudo systemctl list-units --type=service --state=running --no-pager | grep -Ei 'changlian|worker|training' || true
sudo systemctl list-unit-files --no-pager | grep -Ei 'changlian|worker|training' || true
sudo ss -ltnp | head -60
sudo test -d /data/platform-data && sudo du -sh /data/platform-data
```

先按真实现场的 service/容器配置定位 Web、Worker、数据、代码 SHA 和日志位置，再进行**只读**健康检查。不要假定运行单位名称、端口或旧入口仍有效。**禁止在只读阶段停止 Worker、清理缓存、执行 SQLite 写入或提交测试训练**。

### 2.2 双 RTX4070 现场只读核查

历史目录：程序 `/opt/changlian-4070`、业务数据 `/var/lib/changlian-4070/data`、本机 Web 健康入口 `http://127.0.0.1:18010/api/health`。仅为上一次已知基线，需现场重新核查。

```bash
date -Is
df -h / /var/lib/changlian-4070/data
curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18010/api/health
nvidia-smi --query-gpu=index,name,memory.total,memory.used --format=csv,noheader
sudo systemctl list-units --type=service --state=running --no-pager | grep -Ei 'changlian|worker|agent|wevis|model' || true
sudo test -d /var/lib/changlian-4070/data && sudo du -sh /var/lib/changlian-4070/data
```

如现场路径、实际用户账户（历史要求普通 Worker 为 `changlian4070`）、模型网关或运行版本不匹配，停止部署流程并先做差异审计。WeVisOne 和训练共享双 GPU，任何重新部署、切换模型、转换 Worker 启停前必须确认无冲突任务。

### 2.3 中央任务/租约保护准入

- 记录真实任务表中非终态任务**数量及种类**（只读/脱敏），至少包括 RUNNING、CANCEL_REQUESTED、AWAITING_CONFIRMATION、转换排队和清理中的任务。**发现运行中的长训练，不允许以“可中断”假定推进部署**。
- 核对中央 API、Worker/Agent、服务节点报告的版本；原任务 attempt、lease、resource_key 与 Worker 能力必须一致。
- 当远程停止证据为 UNKNOWN/HOLD 时，**不能因 Agent 超时释放 GPU 或再次调度相同任务**。若生产已有类似异常，优先维持隔离待核实。

## 3. A 轨道部署前硬门槛（逐项全部为 PASS）

1. **候选 SHA**：以远端指定分支完整 SHA 冻结，与制品 SHA、部署机版本一一对应。确认候选版本确实包含要交付的业务修复，且没有启用 2C-03 尚未验收的生产开关。
2. **CI**：该**候选 SHA 本身**工作流全部完成且成功，特别包括训练、素材选择、节点调度、数据持久化、API 和前端浏览器回归。失败或未完成＝BLOCK。
3. **备份**：由运维按正式标准对程序/配置、数据库及素材数据制定快照及验证恢复点；特别注意 A800 数据容量压力，不能仅凭 `cp` 执行巨量无容量保证的备份。先确认备份可读且数据恢复路径已演练。
4. **任务安全窗口**：已确认部署窗口不会中断训练、转换、标注或正在上传的成果；必要的停机动作由用户单独授权。
5. **冒烟与 UI**：只针对独立验收项目，核查登录、算法列表、素材分页与跨页选取、训练任务创建/取消状态、报告、AI 标注审核、版本下载和原转换链路。不在正式业务数据上擅自运行测试。
6. **一键回退合同**：记录旧制品和完整 SHA、原服务配置、数据兼容性以及回滚命令的负责人。数据库迁移必须先核查向前/向后兼容；**不能保证退回旧程序必然能读新数据库**。
7. **用户明确批准**：批准的目标服务器、窗口、候选 SHA、停机影响、回滚条件必须全部明确，再操作 A800/4070。

## 4. B 轨道 Supervisor 上线前硬门槛（暂全为 BLOCK/PENDING）

- 2C-03C 原中央 STOP 签名授权 + root journal 一次性 CAS + 真实 Ubuntu24.04 systemd 停止观察，CI 全绿及崩溃/双并发/租约轮换反例。
- Root-only 独立 StopReceipt 签发和中央独立验签：证明不是 Agent 同进程可伪造签名，challenge/nonce/原任务 attempt/lease 和原 cgroup 全绑定；不可从已消失的 unit 或伪造布尔值宣称死亡。
- 中央原任务 DB 真正一次性恢复/释放 GPU 资源的 CAS；UNKNOWN 必须 HOLD；恢复和取消状态与原任务状态保持一致。
- Ubuntu22.04/systemd249 的**真实受保护 PT 执行/停止**替代 `ExitType=cgroup` 的受证实语义；两种系统版本都覆盖后代进程与异常终止。
- 原 AgentConversionRunner 的源文件 SHA/size 检查、训练权重可信来源、标准日志/取消、结果 prepare/upload/confirm/finalize/finish、失联/晚到栅栏和生产灰度回滚全部贯通。
- 全仓该 HEAD CI 全绿后，才能申请正式生产部署审批。

## 5. 现有现场验收文档对照与历史注意事项

- `docs/A800_FIELD_ACCEPTANCE.md` 有 19 项现场业务验收清单，当前文件明确仍标注 NOT VERIFIED，不能因其中有表格就当作实际 PASS。
- `docs/4070_AI_INFERENCE_FIELD_ACCEPTANCE.md` 有 24 项双 GPU/AI 审核验收，历史仍标注 NOT VERIFIED。
- `docs/A800_RC_ACCEPTANCE.md` 是旧 `v42.25` RC 手册，内含过时分支名；其 read-only 思路可以参考，但必须依据当前唯一开发分支和实际系统接口**重审命令**。
- 新 Supervisor 的详细进度及安全限制见 `docs/P0_01C_2D2D2C03_STOP_RECOVERY_DEPLOY_GATE_20261116.md`。

**发布建议：**先完成 A 的指定 SHA CI/现场只读预检/回滚演练再申请部署；B 的 root Supervisor 必须等独立可信停止与恢复闭环，严禁生产试错。
