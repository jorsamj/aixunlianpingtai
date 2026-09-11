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


# main.mjs: make semantic UI state persistence part of the final navigation owner.
path = 'static/main.mjs'
text = read(path)
text = replace_once(
    text,
    "import {installNavigationStability} from './modules/navigation-stability.js?v=422506';\n",
    "import {installNavigationStability} from './modules/navigation-stability.js?v=422507';\nimport {persistUiState} from './modules/ui-state.js?v=422500';\n",
    'bump navigation stability and import UI state persistence',
)
text = replace_once(
    text,
    "installNavigationStability({\n  getState: () => state,\n  notify,\n  requestScope: pageRequestScope,\n  pollRegistry,\n});\n",
    "installNavigationStability({\n  getState: () => state,\n  notify,\n  requestScope: pageRequestScope,\n  pollRegistry,\n  persistNavigationState: currentState => persistUiState(currentState),\n});\n",
    'wire final navigation persistence',
)
write(path, text)

# index.html: cache-bust main module because its imports changed.
path = 'static/index.html'
text = read(path)
text = replace_once(
    text,
    '/static/main.mjs?v=42.25.53',
    '/static/main.mjs?v=42.25.54',
    'bump main module cache',
)
write(path, text)

# Clean an accidental no-op assertion introduced while extending the browser test.
path = 'tests/browser/navigation-stability.spec.mjs'
text = read(path)
text = replace_once(
    text,
    "  const delayedUrl2 = delayedUrl;\n  expect(delayedUrl2).toContain('/api/');\n",
    '',
    'remove redundant delayedUrl2 assertion',
)
write(path, text)

print('wired final navigation persistence and bumped main cache')
