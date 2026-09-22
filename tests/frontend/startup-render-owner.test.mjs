import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const styles = fs.readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');

const legacyStartupTimers = [
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},80);",
  "setTimeout(()=>{ if(state?.project){ state.versionInfo={...(state.versionInfo||{}),version:'42.24.0'}; render(); }},100);",
  "setTimeout(()=>{if(state?.project){state.versionInfo={...(state.versionInfo||{}),version:V37_VERSION};render()}},120);",
];

test('legacy v35/v36/v37 startup render timers cannot return', () => {
  for (const timer of legacyStartupTimers) assert.equal(app.includes(timer), false);
});

test('startup dispatch is deferred until canonical page owners and render bridge are installed', () => {
  assert.equal(app.includes('queueMicrotask(()=>{if(window.__clInit)window.__clInit()});'), false);
  assert.equal(app.includes('window.__clStartupDeferredToCanonicalRouter=true;'), true);
  assert.equal(app.includes('window.__clInit=function(){if(window.__v53InitPromise)return window.__v53InitPromise;'), true);
  const bridge = main.indexOf('window.render = function canonicalRenderBridge()');
  const startup = main.indexOf('const canonicalStartupPromise = window.__clInit?.();');
  assert.ok(bridge >= 0 && startup > bridge, 'canonical render bridge must exist before startup begins');
});

test('bounded startup cleanup timer cannot return after final render ownership', () => {
  assert.equal(app.includes("setTimeout(()=>{renderTop();cleanup(document);},100);"), false);
  assert.equal(app.includes('window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});'), true);
  assert.equal(app.includes("window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))"), false);
  assert.match(main, /PostRenderNormalizationRuntime\?\.apply\?\./);
  assert.equal(app.includes('new MutationObserver'), false);
  assert.equal(app.includes('window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});'), true);
});


test('v42 dashboard renderer only calls helpers from its own scope', () => {
  const start = app.indexOf('function renderDashboardBody42()');
  const end = app.indexOf('window.renderHomeDashboard=renderHomeDashboard', start);
  assert.ok(start >= 0 && end > start);
  const block = app.slice(start, end);
  assert.match(block, /fmtHours42\(jobDuration42\(j\)\)/);
  assert.match(block, /fmtHours42\(d\.totalSeconds\)/);
  assert.match(block, /fmtHours42\(d\.avgSeconds\)/);
  assert.doesNotMatch(block, /fmtHours422|jobDuration422/);
});


test('startup progress patches one stable boot card instead of rebuilding the whole view', () => {
  const start = app.indexOf('function boot(st)');
  const end = app.indexOf('function apply(s)', start);
  assert.ok(start >= 0 && end > start);
  const block = app.slice(start, end);

  assert.match(block, /function paintBoot\(view,st\)/);
  assert.match(block, /data-boot-card="1"/);
  assert.match(block, /data-boot-progress-bar/);
  assert.match(block, /bar\.style\.transform=/);
  assert.match(block, /paintBoot\(view,st\)/);
  assert.doesNotMatch(block, /if\(view\)view\.innerHTML=boot\(st\)/);
  assert.match(styles, /\.boot413-progress>i>em\{[^}]*width:100%[^}]*transform-origin:left center[^}]*transition:transform/);
  assert.doesNotMatch(styles, /\.boot413-progress>i>em\{[^}]*transition:width/);
});


test('canonical startup adopts the already-running page extras request instead of issuing a duplicate refresh', () => {
  assert.match(main, /function adoptPageExtrasInflight\(page, promise\)/);
  assert.match(main, /pageExtrasInflight\.set\(page, task\)/);
  assert.match(main, /pageExtrasLoadedAt\.set\(page, Date\.now\(\)\)/);
  const start = main.indexOf('const canonicalStartupPromise = window.__clInit?.();');
  const end = main.indexOf('document.documentElement.dataset.uiBuild', start);
  assert.ok(start >= 0 && end > start);
  const block = main.slice(start, end);
  const adopt = block.indexOf('adoptPageExtrasInflight(startupPage, state.__extras412);');
  const refresh = block.indexOf('refreshCurrentPageOwner(startupPage);');
  assert.ok(adopt >= 0 && refresh > adopt);
});


test('normal startup does not repaint the canonical page after app bootstrap already painted it', () => {
  assert.match(app, /state\.uiReady=true;render\(\);state\.__startupCanonicalPainted=true/);
  const start = main.indexOf('const canonicalStartupPromise = window.__clInit?.();');
  const end = main.indexOf('document.documentElement.dataset.uiBuild', start);
  assert.ok(start >= 0 && end > start);
  const block = main.slice(start, end);
  assert.match(block, /if \(!state\.__startupCanonicalPainted && navigationStabilityRuntime\.hasPageOwner\(startupPage\)\)/);
  assert.match(block, /source: 'startup-owner'/);
});
