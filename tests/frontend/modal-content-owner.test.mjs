import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('base modal content replacement is explicit and observer-free', () => {
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
  assert.equal(app.includes("window.ModalContentRuntime.replace($('#modalBody'),body);"), true);
  assert.equal(app.includes("if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);"), true);
});

test('known post-open base modal refresh paths use ModalContentRuntime', () => {
  assert.equal(app.includes("loadImportJobs().then(()=>window.ModalContentRuntime.replace(document.getElementById('modalBody'),renderImportJobsPanel()))"), true);
  assert.equal(app.includes("if(!$('#modal').classList.contains('hidden'))window.ModalContentRuntime.replace($('#modalBody'),renderImportJobsPanel());"), true);
  assert.equal(app.includes("document.getElementById('modalBody').innerHTML="), false);
});

test('modal-like preview and review rewrites route through one content replacement owner', () => {
  assert.equal(app.includes('if(body)body.innerHTML=previewBody426()'), false);
  assert.equal(app.includes('if(body&&list[i])body.innerHTML=previewHtml411(list[i],list,i)'), false);
  assert.equal(app.includes('if(body)body.innerHTML=reviewHtml412()'), false);
  assert.equal(app.includes('if(body)body.innerHTML=importReview414Html()'), false);
  assert.equal(app.split('window.ModalContentRuntime.replace(body,reviewHtml412())').length - 1, 3);
  assert.equal(app.split('window.ModalContentRuntime.replace(body,importReview414Html())').length - 1, 4);
});
