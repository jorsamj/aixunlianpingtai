from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly one match, got {count}')
    target.write_text(text.replace(old, new, 1), encoding='utf-8')


replace_once(
    'platform_core/zip_multipart.py',
    """    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:\n        current = now or _utc_now()\n        removed = 0\n        released = 0\n        with self.lock:\n            for meta_path in list(self.root.glob('*/upload.json')):\n                try:\n                    meta = json.loads(meta_path.read_text(encoding='utf-8'))\n                except (OSError, json.JSONDecodeError):\n                    continue\n                if not isinstance(meta, dict) or not self._expired(meta, meta_path, now=current):\n                    continue\n                released += self._remove_upload_dir(meta_path.parent)\n                removed += 1\n        return {'removed_uploads': removed, 'released_bytes': released}\n\n""",
    """    def _cleanup_expired_locked(self, current: datetime) -> dict[str, int]:\n        removed = 0\n        released = 0\n        for meta_path in list(self.root.glob('*/upload.json')):\n            try:\n                meta = json.loads(meta_path.read_text(encoding='utf-8'))\n            except (OSError, json.JSONDecodeError):\n                continue\n            if not isinstance(meta, dict) or not self._expired(meta, meta_path, now=current):\n                continue\n            released += self._remove_upload_dir(meta_path.parent)\n            removed += 1\n        return {'removed_uploads': removed, 'released_bytes': released}\n\n    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:\n        current = now or _utc_now()\n        with self.lock:\n            return self._cleanup_expired_locked(current)\n\n    def cleanup_expired_if_due(\n        self, *, interval_seconds: int = 60, now: datetime | None = None\n    ) -> dict[str, int]:\n        current = now or _utc_now()\n        interval = max(10, min(3600, int(interval_seconds or 60)))\n        marker = self.root / '.gc.json'\n        with self.lock:\n            last_run = None\n            if marker.is_file():\n                try:\n                    body = json.loads(marker.read_text(encoding='utf-8'))\n                    last_run = _parse_iso(body.get('last_run_at')) if isinstance(body, dict) else None\n                except (OSError, json.JSONDecodeError):\n                    last_run = None\n            if last_run is not None and (current - last_run).total_seconds() < interval:\n                return {'removed_uploads': 0, 'released_bytes': 0, 'skipped': 1}\n            result = self._cleanup_expired_locked(current)\n            _atomic_json(marker, {\n                'last_run_at': _iso(current),\n                'removed_uploads': result['removed_uploads'],\n                'released_bytes': result['released_bytes'],\n            })\n            return {**result, 'skipped': 0}\n\n""",
)

replace_once(
    'app.py',
    """@app.get(\"/api/v19/projects/{project_id}/import/jobs\")\ndef v19_list_import_jobs(project_id: str):\n    get_project(project_id)\n    jobs = []\n""",
    """@app.get(\"/api/v19/projects/{project_id}/import/jobs\")\ndef v19_list_import_jobs(project_id: str):\n    get_project(project_id)\n    _v19_multipart_repository(project_id).cleanup_expired_if_due(interval_seconds=60)\n    jobs = []\n""",
)

replace_once(
    'static/modules/external-algorithm-platform.js',
    """    const last = c.lastSync;\n    const cache = c.cache || {};\n    return `<section class=\"label414-shell\" data-external-platform-page=\"1\">\n""",
    """    const last = c.lastSync;\n    const cache = c.cache || {};\n    const credential = c.credentials || {};\n    const credentialBackendText = ({\n      environment: '环境变量',\n      keyring: '系统密钥环',\n      encrypted_file: '服务器加密文件',\n      memory: '内存',\n      unavailable: '不可用',\n    })[String(credential.backend || '')] || '待检测';\n    const credentialManaged = credential.backend === 'environment';\n    const credentialStatusText = credential.configured\n      ? `已配置（${escapeHtml(credential.masked || 'AccessKey 已保存')}）`\n      : credential.available === false ? '安全存储不可用' : '未配置';\n    const credentialHelpText = credential.available === false\n      ? '服务器没有可用的安全 Secret 后端。请配置系统 SecretService，或设置 MC_SECRET_MASTER_KEY 启用服务器加密文件。'\n      : credentialManaged\n        ? `当前凭据由 ${escapeHtml(credential.environment_name || '环境变量')} 管理，只读；页面不会覆盖。`\n        : 'AccessSecret 仅提交给后端安全存储，页面不会读取已保存的明文 Secret。';\n    return `<section class=\"label414-shell\" data-external-platform-page=\"1\">\n""",
)

replace_once(
    'static/modules/external-algorithm-platform.js',
    """            <div class=\"field\"><label>AccessKey</label><input id=\"externalAccessKey\" class=\"input\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"${escapeHtml(c.credentials?.masked || '请输入 AccessKey')}\"></div>\n            <div class=\"field\"><label>AccessSecret</label><div class=\"row\"><input id=\"externalAccessSecret\" type=\"password\" class=\"input\" autocomplete=\"new-password\" spellcheck=\"false\" placeholder=\"${c.credentials?.configured ? '已配置，留空表示继续使用原 Secret' : '请输入 AccessSecret'}\"><button type=\"button\" class=\"btn\" id=\"externalSecretToggle\">显示</button></div></div>\n            <div class=\"field full\"><div class=\"subline\">凭据状态：${c.credentials?.configured ? `已配置（${escapeHtml(c.credentials?.masked || 'AccessKey 已保存')}）` : '未配置'}。AccessSecret 仅提交给后端保存，页面不会读取已保存的明文 Secret。</div></div>\n""",
    """            <div class=\"field\"><label>AccessKey</label><input id=\"externalAccessKey\" class=\"input\" autocomplete=\"off\" spellcheck=\"false\" ${credentialManaged ? 'disabled' : ''} placeholder=\"${escapeHtml(credentialManaged ? '由环境变量管理' : (credential.masked || '请输入 AccessKey'))}\"></div>\n            <div class=\"field\"><label>AccessSecret</label><div class=\"row\"><input id=\"externalAccessSecret\" type=\"password\" class=\"input\" autocomplete=\"new-password\" spellcheck=\"false\" ${credentialManaged ? 'disabled' : ''} placeholder=\"${credentialManaged ? '由环境变量管理' : (credential.configured ? '已配置，留空表示继续使用原 Secret' : '请输入 AccessSecret')}\"><button type=\"button\" class=\"btn\" id=\"externalSecretToggle\" ${credentialManaged ? 'disabled' : ''}>显示</button></div></div>\n            <div class=\"field full\"><div class=\"subline\">凭据状态：${credentialStatusText} · 存储后端：${escapeHtml(credentialBackendText)}。${credentialHelpText}</div>${credential.available === false ? '<div class=\"alert warn\" style=\"margin-top:10px\">当前只能查看公开配置，保存 AccessKey / AccessSecret 会失败关闭（fail-closed），不会降级成明文 JSON。</div>' : ''}</div>\n""",
)

replace_once(
    'tests/frontend/external-algorithm-platform.test.mjs',
    """      credentials: {configured: true, masked: 'ak-****1234'},\n""",
    """      credentials: {configured: true, masked: 'ak-****1234', available: true, backend: 'encrypted_file', writable: true},\n""",
)

replace_once(
    'tests/frontend/external-algorithm-platform.test.mjs',
    """  assert.equal(external.credentials.configured, true);\n""",
    """  assert.equal(external.credentials.configured, true);\n  assert.equal(external.credentials.backend, 'encrypted_file');\n  assert.equal(external.credentials.writable, true);\n""",
)

replace_once(
    'tests/frontend/external-algorithm-platform.test.mjs',
    """  assert.match(source, /id=\"externalConnectionResult\"/);\n});\n""",
    """  assert.match(source, /id=\"externalConnectionResult\"/);\n  assert.match(source, /credentialBackendText/);\n  assert.match(source, /MC_SECRET_MASTER_KEY/);\n  assert.match(source, /安全存储不可用/);\n});\n""",
)

print('one-shot secret/GC wiring patch applied')
