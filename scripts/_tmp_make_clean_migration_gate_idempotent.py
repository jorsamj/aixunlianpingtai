from pathlib import Path

path = Path('scripts/_tmp_migrate_clean_execution_truth.py')
text = path.read_text(encoding='utf-8')
marker = '# 3) Make the new API behavior a permanent release contract.\n'
if marker not in text:
    raise SystemExit('clean migration release-gate marker missing')
# The permanent release gate is already committed through the connector because
# GITHUB_TOKEN cannot write workflow files. Keep this migration product-only.
text = text.split(marker, 1)[0].rstrip() + '\n'
path.write_text(text, encoding='utf-8')
