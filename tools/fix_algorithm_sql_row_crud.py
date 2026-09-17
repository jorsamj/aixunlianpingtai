from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "platform_core" / "algorithm_sql_store.py"
text = TARGET.read_text(encoding="utf-8")
old = '''                    merged = dict(current)\n                    merged.update(master)\n                    if changed:\n'''
new = '''                    merged = dict(current)\n                    merged.update(master)\n                    # external master data must never rewrite the platform's stable algorithm id\n                    merged["id"] = algorithm_id\n                    if changed:\n'''
if old not in text:
    raise SystemExit("external sync merge block not found")
TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
print("external sync stable algorithm id guard applied")
