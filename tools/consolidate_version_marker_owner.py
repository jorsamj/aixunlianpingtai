from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


app_path = Path('static/app.js')
app = app_path.read_text(encoding='utf-8')

# Retire historical startup-only writers that repeatedly overwrite the visible
# version badge after the final renderTop owner has already rendered it.
legacy_version_timer = re.compile(
    r"\s*setTimeout\(\(\)=>\{const v=document\.getElementById\('versionBadge'\);if\(v\)v\.textContent=(?:'v42\.24\.0'|'v'\+V(?:39|42|422|423|424|425|427|428|429|410|411))\},(?:50|100|120|150|180)\);"
)
matches = legacy_version_timer.findall(app)
if len(matches) != 12:
    raise SystemExit(f'legacy visible version timers: expected 12 matches, found {len(matches)}')
app = legacy_version_timer.sub('', app)

base_render_417 = "  const baseRender417=render;\n  render=function(){const result=baseRender417?.(),badge=document.getElementById('versionBadge'),footer=document.querySelector('.nav-footer b');if(badge)badge.textContent='v42.24.0';if(footer)footer.textContent='v42.24.0';return result};\n  [120,600,1600].forEach(delay=>setTimeout(()=>{const badge=document.getElementById('versionBadge'),footer=document.querySelector('.nav-footer b');if(badge)badge.textContent='v42.24.0';if(footer)footer.textContent='v42.24.0'},delay));\n"
app = replace_once(app, base_render_417, '', 'baseRender417 visible version correction owner')

if 'baseRender417' in app:
    raise SystemExit('baseRender417 remains after retirement')
if "[120,600,1600].forEach" in app:
    raise SystemExit('baseRender417 delayed correction timers remain')
if legacy_version_timer.search(app):
    raise SystemExit('legacy visible version timer remains')
if re.search(r"setTimeout\(\(\)=>\{const v=document\.getElementById\('versionBadge'\);if\(v\)v\.textContent=", app):
    raise SystemExit('unclassified delayed visible version timer remains')

# Keep the final element-specific owners. Both resolve to formal VERSION 42.24.0.
if "const V426='42.24.0';" not in app:
    raise SystemExit('V426 formal version constant is missing')
if "const nav426=renderNav;renderNav=function(){nav426();const e=document.querySelector('.nav-footer b');if(e)e.textContent='v'+V426};" not in app:
    raise SystemExit('nav426 final footer version owner is missing')
if "const V412='42.24.0';" not in app:
    raise SystemExit('V412 formal version constant is missing')
if "const top412=renderTop;renderTop=function(){top412();const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V412;" not in app:
    raise SystemExit('top412 final badge version owner is missing')

app_path.write_text(app, encoding='utf-8')

main_path = Path('static/main.mjs')
main = main_path.read_text(encoding='utf-8')
legacy_main_owner = """function applyBuildVersion() {
  const badge = document.getElementById('versionBadge');
  if (badge) badge.textContent = `v${UI_BUILD_VERSION}`;
  const footer = document.querySelector('.nav-footer b');
  if (footer) footer.textContent = `v${UI_BUILD_VERSION}`;
  document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;
}

applyBuildVersion();
for (const delay of [80, 500, 1800, 3600, 8000]) setTimeout(applyBuildVersion, delay);"""
main = replace_once(
    main,
    legacy_main_owner,
    "document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;",
    'main.mjs build metadata / visible version mixed owner',
)
if "document.getElementById('versionBadge')" in main:
    raise SystemExit('main.mjs still writes visible versionBadge')
if "document.querySelector('.nav-footer b')" in main:
    raise SystemExit('main.mjs still writes visible nav footer version')
if 'applyBuildVersion' in main:
    raise SystemExit('legacy applyBuildVersion owner remains')
if 'setTimeout(applyBuildVersion' in main:
    raise SystemExit('legacy delayed main.mjs version writer remains')
if "const UI_BUILD_VERSION = '42.25.0-dev';" not in main:
    raise SystemExit('internal UI build metadata constant must remain')
if 'document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;' not in main:
    raise SystemExit('internal UI build metadata marker is missing')
main_path.write_text(main, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(
    index,
    '<span id="versionBadge" class="version-badge">v42.25.0-dev</span>',
    '<span id="versionBadge" class="version-badge">v42.24.0</span>',
    'static visible version marker',
)
index = replace_once(index, '/static/app.js?v=42.25.65', '/static/app.js?v=42.25.66', 'app cache bump')
index = replace_once(index, '/static/main.mjs?v=42.25.68', '/static/main.mjs?v=42.25.69', 'main cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/version-marker-owner.test.mjs')
if test_path.exists():
    raise SystemExit('version marker owner guard test already exists')
test_path.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const index = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');

test('visible version marker starts at the formal release version', () => {
  assert.equal(index.includes('<span id=\"versionBadge\" class=\"version-badge\">v42.24.0</span>'), true);
  assert.equal(index.includes('<span id=\"versionBadge\" class=\"version-badge\">v42.25.0-dev</span>'), false);
});

test('main runtime owns build metadata but never visible version markers', () => {
  assert.equal(main.includes("const UI_BUILD_VERSION = '42.25.0-dev';"), true);
  assert.equal(main.includes('document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;'), true);
  assert.equal(main.includes("document.getElementById('versionBadge')"), false);
  assert.equal(main.includes("document.querySelector('.nav-footer b')"), false);
  assert.equal(main.includes('applyBuildVersion'), false);
  assert.equal(main.includes('setTimeout(applyBuildVersion'), false);
});

test('legacy delayed visible version writers cannot return', () => {
  const delayed = /setTimeout\\(\\(\\)=>\\{const v=document\\.getElementById\\('versionBadge'\\);if\\(v\\)v\\.textContent=/g;
  assert.equal((app.match(delayed) || []).length, 0);
  assert.equal(app.includes('baseRender417'), false);
  assert.equal(app.includes('[120,600,1600].forEach'), false);
});

test('final classic owners keep formal badge and footer values', () => {
  assert.equal(app.includes("const V426='42.24.0';"), true);
  assert.equal(app.includes("const nav426=renderNav;renderNav=function(){nav426();const e=document.querySelector('.nav-footer b');if(e)e.textContent='v'+V426};"), true);
  assert.equal(app.includes("const V412='42.24.0';"), true);
  assert.equal(app.includes("const top412=renderTop;renderTop=function(){top412();const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V412;"), true);
});
""", encoding='utf-8')

workflow_path = Path('.github/workflows/frontend-runtime-stabilization.yml')
workflow = workflow_path.read_text(encoding='utf-8')
needle = "      - name: Frontend unit tests\n        run: node --test tests/frontend/*.test.mjs\n"
guard = """      - name: Formal version marker owner guard
        run: |
          node --test tests/frontend/version-marker-owner.test.mjs
          if grep -F -n 'baseRender417' static/app.js; then
            echo 'retired baseRender417 version correction owner was reintroduced' >&2
            exit 1
          fi
          if grep -F -n 'applyBuildVersion' static/main.mjs; then
            echo 'main.mjs visible build-version writer was reintroduced' >&2
            exit 1
          fi
      - name: Frontend unit tests
        run: node --test tests/frontend/*.test.mjs
"""
workflow = replace_once(workflow, needle, guard, 'main CI version marker guard insertion')
workflow_path.write_text(workflow, encoding='utf-8')

print('consolidated visible version marker ownership')
