from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


# 1) app.js: remove the two historical setupPagePolling shells and make every
# remaining call site hand polling lifecycle directly to PollRegistry.
path = 'static/app.js'
text = read(path)
if 'setupPagePolling' not in text:
    raise SystemExit('static/app.js: expected historical setupPagePolling shells before migration')

text = replace_once(
    text,
    "function setupPagePolling(){window.PollRegistryRuntime?.replaceTrainingJobTimer?.();}\n",
    '',
    'remove first setupPagePolling shell',
)
text = replace_once(
    text,
    "  setupPagePolling=function(){window.PollRegistryRuntime?.replaceTrainingJobTimer?.();};\n",
    '',
    'remove second setupPagePolling shell',
)

# Historical render generations used either a guarded call or a direct call.
text = text.replace(
    "if(typeof setupPagePolling==='function') setupPagePolling();",
    "window.PollRegistryRuntime?.replaceTrainingJobTimer?.();",
)
text = text.replace(
    'setupPagePolling();',
    'window.PollRegistryRuntime?.replaceTrainingJobTimer?.();',
)
text = text.replace(
    'setupPagePolling()',
    'window.PollRegistryRuntime?.replaceTrainingJobTimer?.()',
)

if 'setupPagePolling' in text:
    raise SystemExit('static/app.js: setupPagePolling remains after migration')
if text.count('window.PollRegistryRuntime?.replaceTrainingJobTimer?.()') < 3:
    raise SystemExit('static/app.js: expected direct training polling handoffs after shell retirement')
write(path, text)


# 2) Permanent CI: setupPagePolling itself becomes a forbidden active token.
path = '.github/workflows/frontend-runtime-stabilization.yml'
text = read(path)
old = """          if grep -Fq 'setupPagePolling' static/app.js; then\n            if ! grep -Fq 'window.PollRegistryRuntime?.replaceTrainingJobTimer?.();' static/app.js; then\n              echo 'remaining setupPagePolling entrypoints must hand lifecycle explicitly to PollRegistry' >&2\n              exit 1\n            fi\n          fi\n"""
new = """          if grep -F -n 'setupPagePolling' static/app.js; then\n            echo 'retired setupPagePolling shell was reintroduced into active app.js' >&2\n            exit 1\n          fi\n"""
text = replace_once(text, old, new, 'tighten Training PollRegistry permanent guard')
write(path, text)


# 3) Cache-bust the changed classic app only.
path = 'static/index.html'
text = read(path)
text = replace_once(
    text,
    '/static/app.js?v=42.25.48',
    '/static/app.js?v=42.25.49',
    'bump app.js cache',
)
write(path, text)

print('retired setupPagePolling shells and tightened permanent guard')
