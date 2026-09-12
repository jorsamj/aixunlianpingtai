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

test('final classic owners keep formal badge and footer values', () => {
  assert.equal(app.includes("const V426='42.24.0';"), true);
  assert.equal(app.includes("const nav426=renderNav;renderNav=function(){nav426();const e=document.querySelector('.nav-footer b');if(e)e.textContent='v'+V426};"), true);
  assert.equal(app.includes("const V412='42.24.0';"), true);
  assert.equal(app.includes("const top412=renderTop;renderTop=function(){top412();const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V412;"), true);
});
