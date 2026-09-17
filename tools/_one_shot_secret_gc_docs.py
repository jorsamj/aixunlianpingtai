from pathlib import Path
import re


def replace_between(path: str, start_pattern: str, end_pattern: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding='utf-8')
    pattern = re.compile(start_pattern + r'.*?(?=' + end_pattern + r')', re.S)
    updated, count = pattern.subn(replacement.rstrip() + '\n\n', text, count=1)
    if count != 1:
        raise SystemExit(f'{path}: expected one section replacement, got {count}')
    target.write_text(updated, encoding='utf-8')


handoff = 'docs/PROJECT_HANDOFF_CURRENT.md'
replace_between(
    handoff,
    r'## P1 — Headless Linux Secret 持久化\n',
    r'## P1 — Multipart session GC\n',
    '''## CLOSED — Headless Linux Secret 持久化

状态：**CLOSED（代码与永久合同完成；真实生产主机仍需部署验收）**。

当前 SecretStore 已形成三层安全策略，禁止明文 JSON 回退：

```text
1. 环境变量只读注入（优先）
   MC_CHANGLIAN_ACCESS_KEY
   MC_CHANGLIAN_ACCESS_SECRET

2. 系统 Keyring
   Windows Credential Locker / Linux SecretService 等可用 backend

3. Headless Linux 加密文件 fallback
   MC_SECRET_MASTER_KEY
   → Fernet 加密
   → <data_dir>/secure/secrets.enc.json
```

`MC_SECRET_MASTER_KEY` 是服务器主密钥，必须由部署环境/Secret Manager 注入，不能写进仓库、普通 JSON 或前端。

配置页面会明确显示当前凭据后端：

```text
环境变量 / 系统密钥环 / 服务器加密文件 / 不可用
```

如果安全 backend 不可用，真实 Secret 写入继续 fail-closed，不会降级为明文保存。

相关主文件：

```text
platform_core/secrets.py
static/modules/external-algorithm-platform.js
requirements.txt
```

永久测试覆盖环境变量优先级、加密文件 round-trip、密文不包含明文 Secret、backend public state 和无 backend 安全降级。'''
)

replace_between(
    handoff,
    r'## P1 — Multipart session GC\n',
    r'## P1 — 真实 500 张 ZIP benchmark\n',
    '''## CLOSED — Multipart session TTL / GC

状态：**CLOSED**。

未完成 ZIP multipart session 现在包含：

```text
created_at
updated_at
expires_at
```

当前项目策略：

```text
默认 TTL：24 小时
每成功写入一个 part：刷新 updated_at / expires_at
completed session：不参与过期 GC
```

右下角 UploadTaskCenter 会轮询 v19 导入任务列表；该服务端入口会调用：

```text
cleanup_expired_if_due(interval_seconds=60)
```

因此正常使用平台时最多每 60 秒尝试一次 GC，而不是每次页面轮询都扫描磁盘。GC 记录：

```text
removed_uploads
released_bytes
last_run_at
```

新建/恢复 multipart session 时也会执行过期清理兜底。'''
)

bug = 'docs/BUG_AUDIT_2026-09-17.md'
replace_between(
    bug,
    r'### OPEN-01 — Headless Linux 新畅联 Secret 的安全持久化方案未最终定型\n',
    r'---\n\n### OPEN-02 — 未完成 multipart session 缺少过期清理 / GC\n',
    '''### CLOSED-04 — Headless Linux 新畅联 Secret 安全持久化

**级别：P1**
**状态：CLOSED（代码/合同完成，生产主机仍需部署验收）**

现在 `platform_core/secrets.py` 支持：

```text
环境变量只读注入
→ 系统 Keyring
→ MC_SECRET_MASTER_KEY + Fernet 加密文件 fallback
```

新畅联可使用：

```text
MC_CHANGLIAN_ACCESS_KEY
MC_CHANGLIAN_ACCESS_SECRET
```

做部署侧只读注入；需要从页面保存时，Headless Linux 可以配置 `MC_SECRET_MASTER_KEY`，Secret 密文保存在运行数据目录的 `secure/secrets.enc.json`，不会回退到明文业务 JSON。

配置页面会显示 backend 来源；安全 backend 不可用时继续 fail-closed。

`cryptography` 已加入正式依赖，永久测试覆盖密文不可出现 AccessSecret 明文。'''
)

replace_between(
    bug,
    r'### OPEN-02 — 未完成 multipart session 缺少过期清理 / GC\n',
    r'---\n\n### OPEN-03 — 上传任务中心仍有独立 1\.5 秒 project-switch interval\n',
    '''### CLOSED-05 — Multipart session TTL / GC

**级别：P1/P2**
**状态：CLOSED**

当前实现：

```text
默认 TTL = 24 小时
created_at / updated_at / expires_at
part 成功写入后自动续期
completed 上传不参与过期清理
```

`ZipMultipartRepository.cleanup_expired()` 会删除过期未完成 session，并返回 `removed_uploads / released_bytes`。

`cleanup_expired_if_due(interval_seconds=60)` 使用 GC marker 做节流。右下角上传任务中心轮询的 v19 job list 服务端入口会触发该方法，因此平台正常运行时最多每 60 秒执行一次过期扫描；创建/恢复上传时仍有兜底清理。

这一策略参考 resumable upload 的 expiration 设计，但 24 小时是本平台当前产品策略，不是协议强制值。'''
)

print('handoff and bug audit updated for Secret/GC closure')
