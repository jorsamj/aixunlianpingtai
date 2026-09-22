import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const index = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');

test('visible version marker starts at the formal release version', () => {
  assert.equal(index.includes('<span id="versionBadge" class="version-badge">v42.24.0</span>'), true);
  assert.equal(index.includes('<span id="versionBadge" class="version-badge">v42.25.0-dev</span>'), false);
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
  const delayed = /setTimeout\(\(\)=>\{const v=document\.getElementById\('versionBadge'\);if\(v\)v\.textContent=/g;
  assert.equal((app.match(delayed) || []).length, 0);
  assert.equal(app.includes('baseRender417'), false);
  assert.equal(app.includes('[120,600,1600].forEach'), false);
});

test('canonical chrome owners keep the formal badge and footer values', () => {
  assert.match(app, /const V413='42\.24\.0'/);
  assert.match(app, /renderTop=function renderTopCanonical413\(\)/);
  const topStart = app.indexOf('renderTop=function renderTopCanonical413()');
  const topEnd = app.indexOf('\n})();', topStart);
  assert.ok(topStart >= 0 && topEnd > topStart);
  assert.match(app.slice(topStart, topEnd), /v\.textContent='v'\+V413/);

  assert.match(app, /const V414='42\.24\.0'/);
  const navStart = app.indexOf('const icon414=');
  const navEnd = app.indexOf('window.renderLabelManagement414=', navStart);
  assert.ok(navStart >= 0 && navEnd > navStart);
  assert.match(app.slice(navStart, navEnd), /<b>v\$\{V414\}<\/b>/);
});


test('entry bundles advance cache-bust markers without changing the formal release badge', () => {
  assert.equal(index.includes('/static/app.js?v=42.25.192'), true);
  assert.equal(index.includes('/static/main.mjs?v=42.25.192'), true);
  assert.equal(index.includes('/static/modules/storage-cache-runtime.js?v=422540'), true);
  assert.equal(main.includes("./modules/model-artifact-runtime.js?v=65005"), true);
  assert.equal(main.includes("./modules/training-task-runtime.js?v=422548"), true);
  assert.equal(main.includes("./modules/auto-label-poll-runtime.js?v=422503"), true);
  assert.equal(index.includes('/static/modules/training-task-visibility-runtime.js?v=422546'), true);
  assert.equal(main.includes("./modules/material-pagination-runtime.js?v=422212"), true);
  assert.equal(index.includes('/static/zip-import-bootstrap.mjs?v=422542'), true);
  assert.equal(index.includes('/static/training-checkpoint-resume-bootstrap.mjs?v=422541'), true);
  assert.equal(index.includes('<span id="versionBadge" class="version-badge">v42.24.0</span>'), true);
});


test('negative sample runtime is cache-busted with canonical owner retirement', () => {
  assert.equal(main.includes("./modules/negative-samples.js?v=422544"), true);
});


test('training material picker canonical confirm asset is current', () => {
  assert.equal(main.includes("./modules/training-material-picker-runtime.js?v=422547"), true);
});
