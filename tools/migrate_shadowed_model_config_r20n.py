from __future__ import annotations

import argparse
from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/shadowed-model-config-generations-r20n.test.mjs')

OPEN_MARKER = "window.openModelConfigModalV35=function(id='')"
SAVE_MARKERS = (
    "window.saveModelConfigV35=async function(id='')",
    "window.saveModelConfig426=async function(id='')",
    "window.saveModelConfig427=async function(id='')",
)
DEAD_CALLS = ('saveModelConfigV35(', 'saveModelConfig426(', 'saveModelConfig427(')


def function_statement(text: str, start: int) -> tuple[int, int, str]:
    brace = text.find('{', start)
    if brace < 0:
        raise SystemExit(f'function brace not found near offset {start}')
    depth = 0
    i = brace
    quote: str | None = None
    line_comment = False
    block_comment = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ''
        if line_comment:
            if ch == '\n':
                line_comment = False
            i += 1
            continue
        if block_comment:
            if ch == '*' and nxt == '/':
                block_comment = False
                i += 2
                continue
            i += 1
            continue
        if quote:
            if ch == '\\':
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == '/' and nxt == '/':
            line_comment = True
            i += 2
            continue
        if ch == '/' and nxt == '*':
            block_comment = True
            i += 2
            continue
        if ch in ("'", '"', '`'):
            quote = ch
            i += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                while end < len(text) and text[end] in ' \t':
                    end += 1
                if end < len(text) and text[end] == ';':
                    end += 1
                if end < len(text) and text[end] == '\r':
                    end += 1
                if end < len(text) and text[end] == '\n':
                    end += 1
                line_start = text.rfind('\n', 0, start) + 1
                return line_start, end, text[line_start:end]
        i += 1
    raise SystemExit(f'unclosed function assignment near offset {start}')


def all_positions(text: str, marker: str) -> list[int]:
    out: list[int] = []
    pos = 0
    while True:
        pos = text.find(marker, pos)
        if pos < 0:
            return out
        out.append(pos)
        pos += len(marker)


def preflight(app: str, index: str) -> list[tuple[int, int, str]]:
    if Path('VERSION.txt').read_text(encoding='utf-8').strip() != '42.24.0':
        raise SystemExit('formal VERSION.txt drifted from 42.24.0')
    if '/static/app.js?v=42.25.92' not in index:
        raise SystemExit('expected pre-R20n app cache 42.25.92 not found')

    for marker in SAVE_MARKERS:
        if app.count(marker) != 1:
            raise SystemExit(f'expected exactly one dead save owner before R20n: {marker}')

    open_statements = [function_statement(app, p) for p in all_positions(app, OPEN_MARKER)]
    dead_opens = [row for row in open_statements if any(call in row[2] for call in DEAD_CALLS)]
    if len(dead_opens) != 3:
        raise SystemExit(f'expected exactly three shadowed Model Config modal generations, found {len(dead_opens)}')

    if "window.saveVisionModelM4=async function(id='')" not in app:
        raise SystemExit('final M4 save owner missing')
    if "window.__m4OpenModelConfig=window.openModelConfigModalV35;" not in app:
        raise SystemExit('M4 model-config capture missing')
    if "if(window.__m4OpenModelConfig)window.openModelConfigModalV35=window.__m4OpenModelConfig;" not in app:
        raise SystemExit('M4 final activation restore missing')

    m4_opens = [row for row in open_statements if 'saveVisionModelM4(' in row[2]]
    if len(m4_opens) != 1:
        raise SystemExit(f'expected exactly one live M4 Model Config modal owner, found {len(m4_opens)}')

    removals = dead_opens[:]
    for marker in SAVE_MARKERS:
        removals.append(function_statement(app, app.index(marker)))
    return removals


def build_test() -> str:
    return """import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('R20n retires shadowed model-config generations while preserving final M4 ownership', () => {
  for (const marker of [
    "window.saveModelConfigV35=async function(id='')",
    "window.saveModelConfig426=async function(id='')",
    "window.saveModelConfig427=async function(id='')",
    'saveModelConfigV35(',
    'saveModelConfig426(',
    'saveModelConfig427(',
  ]) {
    assert.equal(app.includes(marker), false, `retired Model Config generation must stay absent: ${marker}`);
  }

  const openOwners = app.match(/window\\.openModelConfigModalV35=function\\(id=''\\)/g) || [];
  assert.equal(openOwners.length, 1, 'only the live M4 openModelConfigModalV35 function owner may remain');
  assert.match(app, /window\\.saveVisionModelM4=async function\\(id=''\\)/, 'final M4 save owner must remain');
  assert.match(app, /onclick=\\"saveVisionModelM4\\('/, 'live M4 modal must still submit through saveVisionModelM4');
  assert.match(app, /window\\.__m4OpenModelConfig=window\\.openModelConfigModalV35;/, 'M4 capture must remain');
  assert.match(app, /if\\(window\\.__m4OpenModelConfig\\)window\\.openModelConfigModalV35=window\\.__m4OpenModelConfig;/, 'M4 final activation must remain');

  const start = app.indexOf("window.saveVisionModelM4=async function(id='')");
  const owner = app.slice(start, start + 6500);
  assert.match(owner, /NavigationStability\\?\\.action\\?\\.\\(state\\.page\\)/, 'final M4 save must keep the action fence');
  assert.doesNotMatch(owner, /await loadAll\\(\\)|await loadRelated\\(\\)/, 'final M4 save must remain local-state-only');
});
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()

    app = APP.read_text(encoding='utf-8')
    index = INDEX.read_text(encoding='utf-8')
    removals = preflight(app, index)
    print(f'R20n preflight: {len(removals)} dead statements proven shadowed; final M4 owner preserved')
    if args.check_only:
        return

    for start, end, _ in sorted(removals, key=lambda row: row[0], reverse=True):
        app = app[:start] + app[end:]

    for marker in SAVE_MARKERS:
        if marker in app:
            raise SystemExit(f'dead save owner survived R20n: {marker}')
    for call in DEAD_CALLS:
        if call in app:
            raise SystemExit(f'dead Model Config call survived R20n: {call}')
    if app.count(OPEN_MARKER) != 1:
        raise SystemExit(f'expected exactly one function-form openModelConfigModalV35 after R20n, found {app.count(OPEN_MARKER)}')
    if 'saveVisionModelM4(' not in app:
        raise SystemExit('final M4 modal/save path was damaged')

    old_cache = '/static/app.js?v=42.25.92'
    new_cache = '/static/app.js?v=42.25.93'
    if index.count(old_cache) != 1:
        raise SystemExit('expected exactly one app cache marker to bump')
    index = index.replace(old_cache, new_cache, 1)
    if 'id="versionBadge" class="version-badge">v42.24.0</span>' not in index:
        raise SystemExit('visible formal version badge drifted')

    APP.write_text(app, encoding='utf-8')
    INDEX.write_text(index, encoding='utf-8')
    TEST.write_text(build_test(), encoding='utf-8')
    print('R20n migration applied: shadowed Model Config generations retired; app cache 42.25.93')


if __name__ == '__main__':
    main()
