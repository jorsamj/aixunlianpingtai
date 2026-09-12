from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/post-render-normalization-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

base_old = "function modal(title,body,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;$('#modal .modal-card').classList.toggle('wide',!!wide);$('#modal').classList.remove('hidden')}"
base_new = "function modal(title,body,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;$('#modal .modal-card').classList.toggle('wide',!!wide);$('#modal').classList.remove('hidden');requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})}"
if app.count(base_old) != 1:
    raise SystemExit(f'expected one base modal definition, found {app.count(base_old)}')

v37_old = """  const baseModalV37=modal;
  modal=function(title,body,wide){baseModalV37(title,body,wide);requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})};
  window.modal=modal;
"""
if app.count(v37_old) != 1:
    raise SystemExit(f'expected one baseModalV37 wrapper, found {app.count(v37_old)}')

later_capture = 'const oldModal424=modal, oldClose424=closeModal;'
later_delegate = 'oldModal424(title,body,wide); return baseModal;'
if app.count(later_capture) != 1 or app.count(later_delegate) != 1:
    raise SystemExit('later v42.4 modal delegation contract changed')

app = app.replace(base_old, base_new, 1)
app = app.replace(v37_old, '', 1)

if 'baseModalV37' in app:
    raise SystemExit('baseModalV37 remains after migration')
if app.count("requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})") != 1:
    raise SystemExit('expected exactly one base-modal autofocus callback after migration')
if later_capture not in app or later_delegate not in app:
    raise SystemExit('later v42.4 modal owner was changed accidentally')

old_cache = '/static/app.js?v=42.25.70'
new_cache = '/static/app.js?v=42.25.71'
if index.count(old_cache) != 1:
    raise SystemExit(f'expected one {old_cache}, found {index.count(old_cache)}')
index = index.replace(old_cache, new_cache, 1)

TEST.write_text("""import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const autofocus = "requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})";

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

test('base modal owns autofocus without a V37 compatibility wrapper', () => {
  assert.equal(app.includes('const baseModalV37=modal;'), false);
  assert.equal(app.includes('baseModalV37('), false);
  assert.equal(app.split(autofocus).length - 1, 1);
  assert.equal(app.includes("function modal(title,body,wide=false){$('#modalTitle').textContent=title;$('#modalBody').innerHTML=body;"), true);
  assert.equal(app.includes('const oldModal424=modal, oldClose424=closeModal;'), true);
  assert.equal(app.includes('oldModal424(title,body,wide); return baseModal;'), true);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('migrated base modal autofocus into canonical base modal and retired baseModalV37')
