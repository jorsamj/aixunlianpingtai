import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

const legacyStartupTimers = [
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},80);",
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},100);",
  "setTimeout(()=>{if(state?.project){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};render()}},120);",
];

test('legacy v35/v36/v37 startup render timers cannot return', () => {
  for (const timer of legacyStartupTimers) assert.equal(app.includes(timer), false);
});

test('startup dispatch remains owned by the final __clInit path', () => {
  assert.equal(app.includes('queueMicrotask(()=>{if(window.__clInit)window.__clInit()});'), true);
  assert.equal(app.includes('window.__clInit=function(){if(window.__v53InitPromise)return window.__v53InitPromise;'), true);
});

test('bounded startup cleanup timer cannot return after final render ownership', () => {
  assert.equal(app.includes("setTimeout(()=>{renderTop();cleanup(document);},100);"), false);
  assert.equal(app.includes('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});'), true);
  assert.equal(app.split("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))").length - 1, 1);
  assert.equal(app.includes("if(modalBody)modalObserver.observe(modalBody,{childList:true,subtree:true});"), true);
});
