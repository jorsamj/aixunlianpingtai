from __future__ import annotations

from pathlib import Path

MARKER = "<!-- V42.25_STORAGE_INDEX_CANCEL_CLOSURE_20260913 -->"
DOCS = (
    Path("docs/TECH_DEBT_CLOSURE_V42_25.md"),
    Path("docs/CODEX_CURRENT_STATE.md"),
    Path("docs/frontend-legacy-audit.md"),
    Path("docs/FRONTEND_OWNER_MAP_V42_25.md"),
)

BLOCK = f"""

{MARKER}
## 2026-09-13 Storage indexing cancellation fencing — CLOSED

- 真实缺口：素材导入确认后的 indexing 以批次处理；取消在 preflight 查询期间成为 durable truth 时，旧 Worker 仍可能继续 `materials.upsert_many(...)` / annotation / candidate outcome 写入，形成“任务最终 CANCELLED，但业务数据已继续提交”。
- 永久合同：`tests/integration/test_storage_index_cancel_fencing.py` 走真实 `scan -> AWAITING_CONFIRMATION -> confirm -> indexing`，在 material preflight 返回时注入 `CANCEL_REQUESTED`，要求最终 `CANCELLED`、material count 保持 0、candidate 保持未 indexed、不得发布 final result。
- RED/GREEN：`34755117132`；产品修复 `fe951e32aa2d7b840bfd9c975d500d0f0d200c9d`；永久化 `f9b11e691dd2e9daf0d6da2d3ef4f14c0b6d0909`。
- 修复边界：confirmation/ID assignment/preflight 后及 material、annotation、candidate outcome、mark-indexed 等不可逆写入前均重新读取 cancellation durable truth；不改变扫描、SHA 去重、YOLO label mapping 与确认语义。
- cleaned-head 正式门：Release Regression `34755481707` PASS；Navigation Action Fencing + Real Chrome `34755481732` PASS；Frontend Runtime + Real Chrome `34755481693` PASS（33 browser tests PASS）。accepted HEAD：`6cf54ac3b98a97a8be4c60a46d008e2a6bb499a1`。
- Release gate 同步关闭测试路径漂移：conversion / training resource contract 指回真实测试路径，并新增永久 path-integrity guard，workflow 中所有显式 `tests/*.py` 路径必须真实存在后才允许进入 pytest。
- 正式版本边界不变：`VERSION.txt = 42.24.0`；未 merge main、未 tag、未 release；A800 / genuine 10k acceptance 继续 defer。
"""


def main() -> None:
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        if MARKER in text:
            continue
        path.write_text(text.rstrip() + BLOCK + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
