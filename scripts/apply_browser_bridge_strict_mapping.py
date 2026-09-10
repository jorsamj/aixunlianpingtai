from __future__ import annotations

"""Fail-closed patch for legacy-browser YOLO label mapping.

The high-scale compatibility bridge may automatically resume only when every
external class maps uniquely to an existing active stable label. Unknown or
ambiguous classes must use the explicit durable import mapping UI; silently
creating project labels would reintroduce historical schema pollution.
"""

from pathlib import Path


TARGET = Path(__file__).resolve().parents[1] / "platform_core" / "storage" / "browser_v19_bridge.py"

OLD = '''    suggestions = mapping_suggestions(store.external_classes(), labels)
    occupied = {str(row.get("code") or "") for row in labels}
    actions: dict[str, dict[str, Any]] = {}
    for row in suggestions:
        class_id = int(row["class_id"])
        key = str(class_id)
        target_id = str(row.get("suggested_target_label_id") or "")
        if target_id:
            actions[key] = {"action": "map", "target_label_id": target_id}
            continue
        code = _safe_code(str(row.get("name") or ""), class_id, occupied)
        occupied.add(code)
        actions[key] = {
            "action": "create",
            "code": code,
            "display_name": str(row.get("name") or code),
        }
    confirm_import(
        store,
        artifacts,
        task_id,
        object_keys=_selection_keys(target_prefix, selected_paths),
        class_actions=actions,
        accept_quality_report=True,
        labels=labels,
        create_label=lambda spec: _create_label(meta_path, spec),
    )
'''

NEW = '''    suggestions = mapping_suggestions(store.external_classes(), labels)
    actions: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for row in suggestions:
        class_id = int(row["class_id"])
        key = str(class_id)
        target_id = str(row.get("suggested_target_label_id") or "")
        if target_id:
            actions[key] = {"action": "map", "target_label_id": target_id}
            continue
        unresolved.append(f"{class_id}:{str(row.get('name') or '')}")
    if unresolved:
        raise ValueError(
            "YOLO 外部标签无法唯一映射到现有平台标签："
            + ", ".join(unresolved[:20])
            + "。请使用服务器素材导入的标签映射确认页处理后再导入；系统不会自动创建标签。"
        )
    confirm_import(
        store,
        artifacts,
        task_id,
        object_keys=_selection_keys(target_prefix, selected_paths),
        class_actions=actions,
        accept_quality_report=True,
        labels=labels,
        create_label=lambda spec: _create_label(meta_path, spec),
    )
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text:
        print("strict browser YOLO label mapping already installed")
        return 0
    if text.count(OLD) != 1:
        raise SystemExit(f"refusing to patch mapping: expected one block, found {text.count(OLD)}")
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8", newline="\n")
    print("patched browser YOLO mapping to fail closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
