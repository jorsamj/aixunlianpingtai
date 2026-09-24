import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

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

test('version truth no longer depends on a render wrapper', () => {
  assert.equal(app.includes('const baseRenderV37=render;'), false);
  assert.equal(app.includes('baseRenderV37()'), false);
  assert.equal(app.includes('state.versionInfo={...(state.versionInfo||{}),version:V42};'), false);
  assert.match(app, /state\.versionInfo=\{version:V413,name:'畅联云算法训练'\}/);
});

test('base modal owns autofocus without a V37 compatibility wrapper', () => {
  assert.equal(app.includes('const baseModalV37=modal;'), false);
  assert.equal(app.includes('baseModalV37('), false);
  assert.equal(app.split(autofocus).length - 1, 1);
  assert.equal(app.includes("function modalBase(title,body,wide=false){$('#modalTitle').textContent=title;window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
  assert.equal(app.includes('const oldModal424=modal, oldClose424=closeModal;'), false);
  assert.equal(app.includes('modalBase(title,body,wide); return baseModal;'), true);
  assert.match(app, /modal=function modalStackCanonical424\(title,body,wide=false\)/);
});

test('canonical router owns page normalization without legacy view observer or render wrapper', () => {
  assert.equal(app.includes('const baseRender=render;'), false);
  assert.equal(app.includes("requestAnimationFrame(()=>cleanup(document.getElementById('view')))"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.split('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});').length - 1, 1);
  assert.equal(app.includes("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))"), false);
  assert.match(main, /function applyPostRenderNormalization\(page\)/);
  assert.match(main, /PostRenderNormalizationRuntime\?\.apply\?\.\(document\.getElementById\('view'\)\)/);
  assert.doesNotMatch(app, /\brender\s*=\s*function\b/);
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
});
