from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: cache marker mismatch for {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    Path("static/main.mjs"),
    "./modules/training-task-runtime.js?v=422505",
    "./modules/training-task-runtime.js?v=422519",
)
replace_once(
    Path("static/index.html"),
    "/static/main.mjs?v=42.25.94",
    "/static/main.mjs?v=42.25.95",
)
