from pathlib import Path

path = Path(__file__).resolve().parents[1] / "platform_core" / "external_algorithm_platform.py"
text = path.read_text(encoding="utf-8")
old = '            "base_url": client.base_url,\n'
new = '            "base_url": normalize_base_url(payload.base_url if payload is not None else self.repository.config().get("base_url")),\n'
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected one base_url result binding, found {count}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched connectivity result base_url source")
