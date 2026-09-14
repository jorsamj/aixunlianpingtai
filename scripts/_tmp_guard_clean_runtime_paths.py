from pathlib import Path

path = Path('.github/workflows/v42.25-release-regression.yml')
text = path.read_text(encoding='utf-8')
if '      - platform_core/cleaning_batches.py\n' not in text:
    anchor = '      - platform_core/annotation_task_service.py\n'
    if text.count(anchor) != 1:
        raise SystemExit('release cleaning_batches trigger anchor mismatch')
    text = text.replace(anchor, anchor + '      - platform_core/cleaning_batches.py\n', 1)
path.write_text(text, encoding='utf-8')
