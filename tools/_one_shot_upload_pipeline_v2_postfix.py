from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

storage = ROOT / 'static/modules/storage-import-progress.js'
text = storage.read_text(encoding='utf-8')
if text.count('const POLL_DELAY = 800;') != 1:
    raise SystemExit('generated 800ms poll marker missing')
text = text.replace('const POLL_DELAY = 800;', 'const POLL_DELAY = 1200;', 1)
if text.count('  const parts = [stageLabel];') != 1:
    raise SystemExit('generated translated progress marker missing')
text = text.replace('  const parts = [stageLabel];', '  const parts = [stage];', 1)
storage.write_text(text, encoding='utf-8')

# The page already loads main.mjs v42.25.102 on the current baseline; keep the
# existing wiring contract exact instead of asserting the obsolete 42.25.99 value.
test_path = ROOT / 'tests/frontend/material-upload-runtime.test.mjs'
test_text = test_path.read_text(encoding='utf-8')
if test_text.count('main\\.mjs\\?v=42\\.25\\.99') != 1:
    raise SystemExit('stale main.mjs version assertion marker missing')
test_path.write_text(test_text.replace('main\\.mjs\\?v=42\\.25\\.99', 'main\\.mjs\\?v=42\\.25\\.102', 1), encoding='utf-8')

print('upload pipeline v2 post-fix applied')
