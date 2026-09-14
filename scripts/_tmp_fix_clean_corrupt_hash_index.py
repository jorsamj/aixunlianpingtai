from pathlib import Path

path = Path('platform_core/cleaning_batches.py')
text = path.read_text(encoding='utf-8')
old = '''        if result["status"] == "succeeded":
            index.remember(image_id, result["metrics"], near_indexed)
'''
new = '''        metrics = result.get("metrics") or {}
        if result["status"] == "succeeded" and metrics.get("sha256") is not None and metrics.get("dhash") is not None:
            index.remember(image_id, metrics, near_indexed)
'''
if text.count(old) != 1:
    raise SystemExit(f'corrupt hash-index guard: expected one match, got {text.count(old)}')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
