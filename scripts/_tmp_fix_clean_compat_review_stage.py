from pathlib import Path

path = Path('app.py')
text = path.read_text(encoding='utf-8')
old = "        'stage': body.get('phase'),\n"
new = "        'stage': 'review' if status == 'awaiting_confirmation' else body.get('phase'),\n"
if text.count(old) != 1:
    raise SystemExit(f'clean compatibility stage mapping: expected one match, got {text.count(old)}')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
