"""Optional analysis configuration. Never imports the external analysis engine."""
from __future__ import annotations

import json
from pathlib import Path


def audit_configuration(data_dir):
    path = Path(data_dir) / "smart_material_audit.json"
    value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(value, dict) or not isinstance(value.get("enabled", False), bool):
        raise ValueError("smart_material_audit.enabled must be a boolean")
    return {"enabled": value.get("enabled", False),
            "python": str(value.get("python") or ""),
            "max_images": min(2000, max(2, int(value.get("max_images", 1000)))),
            "timeout_seconds": min(3600, max(10, int(value.get("timeout_seconds", 600))))}


def require_enabled(data_dir):
    config = audit_configuration(data_dir)
    if not config["enabled"]:
        raise ValueError("SMART_AUDIT_DISABLED: 智能素材分析未启用")
    if not config["python"] or not Path(config["python"]).is_file():
        raise ValueError("SMART_AUDIT_ENVIRONMENT_UNAVAILABLE: 未配置独立分析环境")
    return config
