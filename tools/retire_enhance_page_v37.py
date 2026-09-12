from pathlib import Path

APP = Path('static/app.js')
INDEX = Path('static/index.html')
TEST = Path('tests/frontend/post-render-normalization-owner.test.mjs')

app = APP.read_text(encoding='utf-8')
index = INDEX.read_text(encoding='utf-8')

old_enhance = """  function enhancePageV37(){
    const view=document.getElementById('view');if(!view)return;
    view.querySelectorAll('table.table').forEach(table=>{if(!table.parentElement.classList.contains('table-wrap')){const wrap=document.createElement('div');wrap.className='table-wrap';table.parentNode.insertBefore(wrap,table);wrap.appendChild(table)}});
    view.querySelectorAll('.panel').forEach(panel=>{const title=panel.querySelector('.panel-title')?.textContent?.trim();if(title==='使用建议')panel.remove()});
    document.querySelectorAll('.modal-body table.table').forEach(table=>{if(!table.parentElement.classList.contains('table-wrap')){const wrap=document.createElement('div');wrap.className='table-wrap';table.parentNode.insertBefore(wrap,table);wrap.appendChild(table)}});
  }
"""
if app.count(old_enhance) != 1:
    raise SystemExit(f'expected one enhancePageV37 implementation, found {app.count(old_enhance)}')

old_render = "  render=function(){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};baseRenderV37();requestAnimationFrame(enhancePageV37)};"
new_render = "  render=function(){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};baseRenderV37()};"
if app.count(old_render) != 1:
    raise SystemExit(f'expected one baseRenderV37 enhance callback, found {app.count(old_render)}')

old_modal = "  modal=function(title,body,wide){baseModalV37(title,body,wide);requestAnimationFrame(()=>{enhancePageV37();const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})};"
new_modal = "  modal=function(title,body,wide){baseModalV37(title,body,wide);requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})};"
if app.count(old_modal) != 1:
    raise SystemExit(f'expected one baseModalV37 enhance callback, found {app.count(old_modal)}')

cleanup_anchor = """  function cleanup(root){
    if(!root||!root.querySelectorAll)return;
    window.beautifyFileInputs426?.(root);
"""
if app.count(cleanup_anchor) != 1:
    raise SystemExit(f'expected one cleanup owner anchor, found {app.count(cleanup_anchor)}')

cleanup_tables = """  function cleanup(root){
    if(!root||!root.querySelectorAll)return;
    window.beautifyFileInputs426?.(root);
    const wrapTable=table=>{if(!table.parentElement?.classList.contains('table-wrap')){const wrap=document.createElement('div');wrap.className='table-wrap';table.parentNode?.insertBefore(wrap,table);wrap.appendChild(table)}};
    if(root.matches?.('table.table'))wrapTable(root);
    root.querySelectorAll('table.table').forEach(wrapTable);
"""

app = app.replace(old_enhance, '', 1)
app = app.replace(old_render, new_render, 1)
app = app.replace(old_modal, new_modal, 1)
app = app.replace(cleanup_anchor, cleanup_tables, 1)

if 'enhancePageV37' in app:
    raise SystemExit('enhancePageV37 remains after semantic migration')
if 'requestAnimationFrame(enhancePageV37)' in app:
    raise SystemExit('old page enhancement RAF remains')
if 'const baseRenderV37=render;' not in app or new_render not in app:
    raise SystemExit('baseRenderV37 versionInfo semantic owner was removed accidentally')
if 'const baseModalV37=modal;' not in app or new_modal not in app:
    raise SystemExit('baseModalV37 autofocus semantic owner was removed accidentally')
if "root.querySelectorAll('table.table').forEach(wrapTable);" not in app:
    raise SystemExit('cleanup table normalization owner missing')
if "['接入方式','系统原则','一条主流程','快速入口','使用建议'].includes(t)" not in app:
    raise SystemExit('cleanup 使用建议 removal semantic missing')

old_cache = '/static/app.js?v=42.25.68'
new_cache = '/static/app.js?v=42.25.69'
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

test('V37 wrappers retain only still-live non-normalization semantics', () => {
  assert.equal(app.includes('const baseRenderV37=render;'), true);
  assert.equal(app.includes("render=function(){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};baseRenderV37()};"), true);
  assert.equal(app.includes('const baseModalV37=modal;'), true);
  assert.equal(app.includes("requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})"), true);
});
""", encoding='utf-8')

APP.write_text(app, encoding='utf-8')
INDEX.write_text(index, encoding='utf-8')
print('retired enhancePageV37; cleanup now owns table/post-render normalization')
