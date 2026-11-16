# A800 现有平台｜上线候选版本冻结与只读现场准入（2026-11-16）

> **A800 尚未授权部署，现场状态尚未核实。** 此文只冻结已通过 CI 的原平台/原 Runner 候选，明确只读检查及真正的生产实施前提。不能据此开启新 Supervisor，不能将 CI 全绿视为 A800 GPU/CUDA 现场验收。

## 1. 唯一代码候选与证据

- GitHub 仓库：`jorsamj/aixunlianpingtai`；唯一开发分支 `feature/external-algorithm-publishing`。
- **冻结 A 轨道现有平台候选完整 SHA：`06d35355a802c4056111636a58d2c9b549efd74b`**。
- 已逐一从 GitHub Actions 精确查询此 SHA 产生的 **23/23 completed SUCCESS**，含原平台的训练、素材、AI 标注、任务与节点、Node Agent、GPU Runtime、Portable Deployment、前端浏览器、真实 Ubuntu CPU/systemd 等工作流。请以 <https://github.com/jorsamj/aixunlianpingtai/commit/06d35355a802c4056111636a58d2c9b549efd74b/checks> 再次核对。
- 当时远端 HEAD 为 `45c27075114513fc005668446709e28620130e5d`；GitHub compare 表明从冻结候选到该 HEAD **只前进一个提交**，且仅修改 `docs/P0_01C_2D2D2C03_STOP_RECOVERY_DEPLOY_GATE_20261116.md`。该 HEAD 有 `[skip ci]`，所以 **不要把 HEAD 无 CI 错误解释为 0 项测试通过，也不要自动用浮动 HEAD 做部署目标**。
- **本冻结准入仅属于 A 轨道现有 Web/API/Worker/legacy Runner，不包含 root Supervisor PT 转换的生产启用**。使用已验证 SHA 并不会自动关闭新增功能；实施前必须独立确认现有生产开关原状及所有实验/CI-only 模块不可从生产调用。

## 2. A800 实机只读核查（仅查、不执行部署）

历史路径参考：代码 `/data/platform/aixunlianpingtai`、业务数据 `/data/platform-data`、Web `http://127.0.0.1:8010/api/health`。这些是历史值，**必须先在现场验证，不可据此假定运行状态**。

下列命令不会进行 `git fetch/pull/checkout`，不会启动训练，不会停止任何进程，不会写入报告文件，不会修改生产业务数据库。请在 A800 上由有权限的运维账户执行；若未安装 Python 或某一服务名称不同，记录实际情况，不要为通过检查而修改服务：

```bash
printf '\n===== TIME / HOST =====\n'
date -Is
hostname
printf '\n===== CODE / WORKTREE (NO FETCH) =====\n'
if test -d /data/platform/aixunlianpingtai/.git; then
  git -C /data/platform/aixunlianpingtai rev-parse HEAD
  git -C /data/platform/aixunlianpingtai branch --show-current
  printf 'tracked/untracked change count: '
  git -C /data/platform/aixunlianpingtai status --porcelain | wc -l
else
  echo 'CODE_REPO_NOT_FOUND_OR_NOT_A_GIT_WORKTREE'
fi
printf '\n===== DISK / GPU =====\n'
df -h / /data/platform-data
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader
printf '\n===== SERVICES =====\n'
systemctl is-active changlian-web.service changlian-worker.service || true
systemctl list-units --type=service --state=running --no-pager | grep -Ei 'changlian|training|worker' || true
printf '\n===== WEB HEALTH =====\n'
python3 - <<'PY'
import json
import urllib.request
url = 'http://127.0.0.1:8010/api/health'
try:
    with urllib.request.urlopen(url, timeout=5) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        print('HEALTH_UNEXPECTED_RESPONSE')
    else:
        print('ok:', data.get('ok'), 'version:', data.get('version'))
except Exception as exc:
    print('HEALTH_UNVERIFIED:', type(exc).__name__)
PY
printf '\n===== CENTRAL TASKS / GPU RESERVATIONS (READ ONLY) =====\n'
python3 - <<'PY'
import sqlite3
from pathlib import Path
path = Path('/data/platform-data/task_runtime/tasks.sqlite3')
if not path.is_file():
    print('TASK_DB_NOT_FOUND: CANNOT PROVE IDLE')
    raise SystemExit(0)
try:
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',
                         uri=True, timeout=3) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA busy_timeout=3000')
        print('task_status_counts:')
        for status, count in db.execute(
            'SELECT status,COUNT(*) FROM tasks GROUP BY status ORDER BY status'
        ):
            print('  ', status if status is not None else '(NULL)', count)
        terminal = ('SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED',
                    'BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE')
        placeholders = ','.join('?' for _ in terminal)
        count = db.execute(
            'SELECT COUNT(*) FROM tasks WHERE status IS NULL OR '
            f'status NOT IN ({placeholders})', terminal
        ).fetchone()[0]
        print('nonterminal_tasks:', count)
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if 'gpu_reservations' in tables:
            print('gpu_reservations:', db.execute(
                'SELECT COUNT(*) FROM gpu_reservations'
            ).fetchone()[0])
        else:
            print('gpu_reservations: TABLE_NOT_FOUND')
except (sqlite3.Error, OSError) as exc:
    print('READ_ONLY_TASK_STATE_UNVERIFIED:', type(exc).__name__)
PY
```

仅分享以上输出中非敏感的版本/计数信息，不上传访问密钥、Node Token、环境变量、原始日志和用户素材；如命令没有数据库权限，记为 **UNKNOWN/BLOCK**，不要自行更改数据库权限。

### 现场核查怎么判

1. 服务器程序目录、真实当前 SHA、服务名称与 Web 健康必须核实；不能只看部署脚本默认目录。
2. `nonterminal_tasks` **必须为 0** 才能使用现有 `tools/production_upgrade.py` 的升级前空闲检查；`QUEUED`、`RUNNING`、`CANCEL_REQUESTED`、`AWAITING_CONFIRMATION`、`UNKNOWN`、空状态及其他未知状态均阻塞。**不得为上线而强制清空/取消任务**。
3. `gpu_reservations` 不等于 0 或 GPU 有占用时必须明确其来源；不能单靠 `nonterminal_tasks=0` 断言 GPU 计算已停止，尤其不能把远程 Agent 离线视为释放证据。
4. 磁盘与历史基线存在高占用风险：先确认是否有足够快照空间，优先使用独立备份存储；**不可在备份未验证前删除训练副本或大量素材来换取空间**。
5. 不能因 root Supervisor CI 通过而设置 `supervisor-required`、切换正式 MODEL_CONVERSION 执行路径或启用自动解除远程 STOP HOLD。

## 3. 生产升级工具的已核实边界和关键风险

- 仓库已有 `tools/production_upgrade.py`，面向 **Git worktree + systemd 的特定安装形态**，预期 `changlian-web.service`、`changlian-worker.service`、本机 8010。需先证实现场匹配，**不要在未知现场直接调用 `--apply`**。
- 此工具所谓非 `--apply` dry-run 仍执行 `git fetch`，会修改本机 `FETCH_HEAD` 与部分 Git 元数据，因此**不属于本节严格只读检查**，暂不建议先运行它。
- `--apply` 会停止正式 Worker 和 Web、`git merge --ff-only` 切换代码及校验健康；它**不执行数据库/素材备份，不负责数据库迁移的恢复**。
- 发生代码已切换后的异常时，它会停止两服务并交给运维人工评估，不会假装旧代码一定兼容可能已迁移的新数据库。必须先有一份**核实可恢复**的数据库+配置+素材/权重快照、独立空间、旧代码 SHA、服务配置备份及明确回滚负责人。
- `--acknowledge-no-data-backup` 只是危险状态下的显式确认，**绝不等同于完成备份**；现场未核实一致性快照前不得使用。
- `docs/A800_RC_ACCEPTANCE.md` 包含历史错误分支 `refactor/frontend-runtime-stabilization` 及旧环境预期，**不得照搬其 git/deploy 步骤**；19 项现场业务验收见 `docs/A800_FIELD_ACCEPTANCE.md`，目前仍为 **NOT VERIFIED**。

## 4. 决策与下一步

| 准入项 | 事实 | 当前结论 |
| --- | --- | --- |
| 准确业务候选 SHA | `06d35355...` | **已冻结** |
| 该 SHA 所有 GitHub Actions | 23/23 completed success | **PASS** |
| A800 实机 Web/Worker/数据目录/版本/CPU/GPU | 尚无新的现场输出 | **UNKNOWN / BLOCK** |
| 是否存在排队、运行中、取消中或远程隔离任务 | 尚无新的现场输出 | **UNKNOWN / BLOCK** |
| 实际磁盘和一致性备份恢复点 | 未提供现场证据 | **UNKNOWN / BLOCK** |
| 旧制品、服务配置、数据库迁移兼容和人工回滚 | 待确认 | **BLOCK** |
| A800 独立场景验收（19 项） | 文件仍 NOT VERIFIED | **PENDING** |
| 新 Supervisor root STOP / 自动恢复 | 没有生产可信回执与中央恢复闭环 | **NO-GO** |
| 生产停机、备份、部署授权 | 未取得 | **NOT AUTHORIZED** |

**建议：**现在仅进入 A800 只读现场核查和备份方案准备。确认全部安全项后再单独确定候选 SHA、窗口、影响和回滚，并由用户明确批准正式升级。原 Runner 不接管，实验 Supervisor 不启用。不得将未执行的生产步骤标成完成。
