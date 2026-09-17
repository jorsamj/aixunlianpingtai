import test from 'node:test';
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
  assert.equal(app.includes("function modal(title,body,wide=false){$('#modalTitle').textContent=title;window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
  assert.equal(app.includes('const oldModal424=modal, oldClose424=closeModal;'), true);
  assert.equal(app.includes('oldModal424(title,body,wide); return baseModal;'), true);
});

test('final render owns page normalization without legacy view observer or RAF wrapper', () => {
  assert.equal(app.includes('const baseRender=render;'), false);
  assert.equal(app.includes("requestAnimationFrame(()=>cleanup(document.getElementById('view')))"), false);
  assert.equal(app.includes("observer.observe(view,{childList:true,subtree:true})"), false);
  assert.equal(app.split('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});').length - 1, 1);
  assert.equal(app.split("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))").length - 1, 1);
  assert.equal(app.includes("render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61()}else finalRender();window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))};"), true);
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
});
