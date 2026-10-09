import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const index = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const formalVersion = fs.readFileSync(new URL('../../VERSION.txt', import.meta.url), 'utf8').trim();

test('visible version marker waits for backend formal version truth', () => {
  assert.equal(index.includes('<span id="versionBadge" class="version-badge">v—</span>'), true);
  assert.equal(index.includes(`<span id="versionBadge" class="version-badge">v${formalVersion}</span>`), false);
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

test('canonical chrome reads formal version from bootstrap state only', () => {
  assert.equal(app.includes("const V413='42.24.0'"), false);
  assert.equal(app.includes("const V414='42.24.0'"), false);
  assert.match(app, /state\.versionInfo=\{version:String\(s\.platform_version\|\|''\)\.trim\(\)\|\|'—'/);

  const topStart = app.indexOf('renderTop=function renderTopCanonical413()');
  const topEnd = app.indexOf('\n})();', topStart);
  assert.ok(topStart >= 0 && topEnd > topStart);
  assert.match(app.slice(topStart, topEnd), /state\.versionInfo\?\.version/);

  const navStart = app.indexOf('const icon414=');
  const navEnd = app.indexOf('window.renderLabelManagement414=', navStart);
  assert.ok(navStart >= 0 && navEnd > navStart);
  assert.match(app.slice(navStart, navEnd), /state\.versionInfo\?\.version/);
});

test('entry bundles use cache-bust markers independently from formal release truth', () => {
  assert.match(index, /\/static\/app\.js\?v=\d+(?:\.\d+)*/);
  assert.match(index, /\/static\/main\.mjs\?v=\d+(?:\.\d+)*/);
  assert.match(index, /\/static\/styles\.css\?v=\d+(?:\.\d+)*/);
  assert.equal(index.includes('/static/modules/storage-cache-runtime.js?v=422540'), true);
  assert.match(main, /\.\/modules\/model-artifact-runtime\.js\?v=\d+/);
  assert.match(main, /\.\/modules\/training-task-runtime\.js\?v=\d+/);
  assert.match(main, /\.\/modules\/training-create-hydration\.js\?v=\d+/);
  assert.equal(main.includes("./modules/training-submit.js?v=422597"), true);
  assert.equal(main.includes("./modules/auto-label-poll-runtime.js?v=422503"), true);
  assert.equal(index.includes('/static/modules/training-task-visibility-runtime.js'), false);
  assert.equal(main.includes("./modules/training-task-visibility-runtime.js?v=422607"), true);
  assert.equal(main.includes("./modules/material-pagination-runtime.js?v=422608"), true);
  assert.equal(main.includes("./modules/material-batches.js?v=422403"), true);
  assert.equal(index.includes('/static/zip-import-bootstrap.mjs?v=422616'), true);
  assert.equal(index.includes('/static/training-checkpoint-resume-bootstrap.mjs?v=422541'), true);
  assert.equal(index.includes('<span id="versionBadge" class="version-badge">v—</span>'), true);
});

test('formal platform version is not re-embedded into visible static chrome', () => {
  assert.equal(app.includes(`'${formalVersion}'`), false);
  assert.equal(index.includes(`v${formalVersion}</span>`), false);
});

test('negative sample runtime is cache-busted with canonical owner retirement', () => {
  assert.equal(main.includes("./modules/negative-samples.js?v=422544"), true);
});

test('training material picker canonical confirm asset is current', () => {
  assert.equal(main.includes("./modules/training-material-picker-runtime.js?v=422603"), true);
});
