from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/post-render-normalization-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

old = """  const baseRenderV37=render;
  render=function(){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};baseRenderV37()};

"""
if app.count(old) != 1:
    raise SystemExit(f'expected one baseRenderV37 wrapper, found {app.count(old)}')

later_owner = """  const V42='42.24.0';"""
later_write = """    state.versionInfo={...(state.versionInfo||{}),version:V42};"""
if app.count(later_owner) != 1 or app.count(later_write) != 1:
    raise SystemExit('later V42 versionInfo owner contract changed')

modal_owner = "const baseModalV37=modal;"
modal_focus = "requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})"
if app.count(modal_owner) != 1 or app.count(modal_focus) != 1:
    raise SystemExit('baseModalV37 autofocus owner changed; refusing unrelated migration')

app = app.replace(old, '', 1)

if 'const baseRenderV37=render;' in app or 'baseRenderV37()' in app:
    raise SystemExit('baseRenderV37 remains after retirement')
if later_owner not in app or later_write not in app:
    raise SystemExit('later V42 versionInfo owner missing after retirement')
if modal_owner not in app or modal_focus not in app:
    raise SystemExit('baseModalV37 autofocus owner was changed accidentally')

old_cache = '/static/app.js?v=42.25.69'
new_cache = '/static/app.js?v=42.25.70'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one {old_cache}, found {index.count(old_cache)}')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('enhancePageV37 compatibility helper cannot return', () => {
  assert.equal(app.includes('function enhancePageV37'), false);
  assert.equal(app.includes('requestAnimationFrame(enhancePageV37)'), false);
  assert.equal(app.includes('enhancePageV37();const first='), false);
});

test('cleanup owns table wrapping and 使用建议 cleanup semantics', () => {
  assert.equal(app.includes("if(root.matches?.('table.table'))wrapTable(root);"), true);
  assert.equal(app.includes("root.querySelectorAll('table.table').forEach(wrapTable);"), true);
  assert.equal(app.includes("['接入方式','系统原则','一条主流程','快速入口','使用建议'].includes(t)"), true);
});

test('baseRenderV37 duplicate versionInfo wrapper cannot return', () => {
  assert.equal(app.includes('const baseRenderV37=render;'), false);
  assert.equal(app.includes('baseRenderV37()'), false);
  assert.equal(app.includes("const V42='42.24.0';"), true);
  assert.equal(app.includes('state.versionInfo={...(state.versionInfo||{}),version:V42};'), true);
});

test('baseModalV37 retains autofocus until separately migrated', () => {
  assert.equal(app.includes('const baseModalV37=modal;'), true);
  assert.equal(app.includes("requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})"), true);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('retired duplicate baseRenderV37 versionInfo wrapper; later V42 owner remains')
