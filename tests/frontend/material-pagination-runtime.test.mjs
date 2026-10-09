import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  buildMaterialQuery,
  requiresFullMaterialPool,
} from '../../static/modules/material-pagination-runtime.js';


test('material paging query keeps filters on the server', () => {
  const params = buildMaterialQuery({
    limit: 48,
    cursor: 'next-token',
    query: 'fire',
    sourceId: 'oss-a',
    processingStatus: 'processed',
    labels: ['fire', 'smoke'],
    annotated: 'marked',
  });
  assert.equal(params.get('limit'), '48');
  assert.equal(params.get('cursor'), 'next-token');
  assert.equal(params.get('query'), 'fire');
  assert.deepEqual(params.getAll('storage_source_id'), ['oss-a']);
  assert.equal(params.get('processing_status'), 'processed');
  assert.deepEqual(params.getAll('label'), ['fire', 'smoke']);
  assert.equal(params.get('annotated'), 'true');
});

test('material paging query supports a true numbered page contract', () => {
  const params = buildMaterialQuery({page: 50, pageSize: 20, query: 'helmet'});
  assert.equal(params.get('page'), '50');
  assert.equal(params.get('page_size'), '20');
  assert.equal(params.has('cursor'), false);
  assert.equal(params.get('query'), 'helmet');
});

test('dataset final owner delegates numbered navigation to shared pagination', () => {
  const runtime = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  assert.match(runtime, /PlatformCore\?\.pagination\?\.mountPagination/);
  assert.match(runtime, /onPageChange: targetPage => loadMaterialPage61/);
  assert.doesNotMatch(runtime, /pager\.innerHTML = `<button class="btn mini"/);
});


test('canonical pages do not hydrate the complete material pool during navigation', () => {
  assert.equal(requiresFullMaterialPool('数据集'), false);
  assert.equal(requiresFullMaterialPool('算法列表'), false);
  assert.equal(requiresFullMaterialPool('训练任务'), false);
  assert.equal(requiresFullMaterialPool('质量中心'), false);
  assert.equal(requiresFullMaterialPool('自动标注'), false);
  assert.equal(requiresFullMaterialPool('自动标注及清洗'), false);
  assert.equal(requiresFullMaterialPool('自动迭代'), false);

  const picker = fs.readFileSync(new URL('../../static/modules/training-material-picker-runtime.js', import.meta.url), 'utf8');
  const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(picker, /fullPoolHydration: false/);
  assert.doesNotMatch(main, /FULL_MATERIAL_PAGES\.(?:add|delete)\(/);
  assert.match(app, /await window\.MaterialPaginationRuntime61\?\.ensureFullPool\?\.\(\)/);
});


test('pagination bootstrap is loaded before the legacy app bundle', () => {
  const html = fs.readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
  const bootstrap = html.indexOf('material-pagination-bootstrap.js');
  const app = html.indexOf('/static/app.js');
  assert.ok(bootstrap >= 0);
  assert.ok(app > bootstrap);

  const bootstrapSource = fs.readFileSync(new URL('../../static/material-pagination-bootstrap.js', import.meta.url), 'utf8');
  assert.match(bootstrapSource, /\/api\/v61\/projects\/\$\{projectId\}\/materials/);
  assert.match(bootstrapSource, /state\.mode !== 'paged'/);
});


test('dataset cache and full-pool switching are owned by final named navigation hooks', () => {
  const runtime = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

  assert.match(runtime, /function beforeNavigate61\(page\)/);
  assert.match(runtime, /function afterNavigate61\(page, navigation\)/);
  assert.match(runtime, /const action = window\.NavigationStability\?\.action\?\.\(target\)/);
  assert.match(runtime, /action\?\.commit/);
  assert.doesNotMatch(runtime, /await window\.refreshCurrentPage413\?\.\(\)/);
  assert.match(runtime, /beforeNavigate: beforeNavigate61/);
  assert.match(runtime, /afterNavigate: afterNavigate61/);
  assert.doesNotMatch(runtime, /materialAwareSetPage/);
  assert.doesNotMatch(runtime, /window\.setPage\s*=/);

  const start = main.indexOf('performNavigation: page => {');
  const end = main.indexOf('\n  },', start);
  assert.ok(start >= 0 && end > start);
  const owner = main.slice(start, end);
  const before = owner.indexOf('MaterialPaginationRuntime61?.beforeNavigate?.(page)');
  const stateMutation = owner.indexOf('state.page = page');
  const taskCenter = owner.indexOf('uploadTaskCenterRuntime.switchProject?.()');
  const render = owner.indexOf('render()');
  const after = owner.indexOf('MaterialPaginationRuntime61?.afterNavigate?.(page, materialNavigation)');
  assert.ok(before >= 0 && before < stateMutation);
  assert.ok(stateMutation < taskCenter && taskCenter < render && render < after);
});

test('identical material page loads are single-flight instead of issuing duplicate GETs', () => {
  const runtime = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  assert.match(runtime, /let pageLoadFlight = null/);
  assert.match(runtime, /let pageLoadFlightKey = ''/);
  assert.match(runtime, /if \(pageLoadFlight && pageLoadFlightKey === flightKey\) return pageLoadFlight/);
  assert.match(runtime, /JSON\.stringify\(\[projectId\(\), filterSignature61\(\), requestedPage, transport\.pageSize \|\| 48\]\)/);
});

test('explicit full material hydration is lazy, cached and single-flight', () => {
  const runtime = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  assert.match(runtime, /const FULL_MATERIAL_REVISIT_REUSE_MS = 10 \* 1000/);
  assert.match(runtime, /let fullPoolFlight = null/);
  assert.match(runtime, /if \(fullPoolFlight && fullPoolFlightProjectId === pid\) return fullPoolFlight/);
  assert.match(runtime, /async function ensureFullPool61\(\{force = false\} = \{\}\)/);
  assert.match(runtime, /if \(!force && snapshot\?\.fresh\) return snapshot\.items\.slice\(\)/);
  assert.match(runtime, /const rows = await loadFullPool61\(\)/);
  assert.match(runtime, /ensureFullPool: ensureFullPool61/);
  assert.match(runtime, /invalidateFullPool61\(\);\r?\n    const result = await loadMaterialPage61/);
});


test('page renders cannot overwrite the current UI version with 42.22.0', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /badge\.textContent='v42\.22\.0'/);
  assert.doesNotMatch(source, /footer\.textContent='v42\.22\.0'/);
});


test('upload cleaning decisions retain the complete current upload batch', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /recentUploadedMaterials61=\[\.\.\.uploaded\]/);
  assert.doesNotMatch(source, /recentUploadedMaterials61=.*\.slice\(0,500\)/);
});

test('unprocessed bulk operation uses the server-frozen FILTERED scope instead of the current 48 rows', () => {
  const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const runtime = fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  assert.match(app, /if\(ids===null\)\{/);
  assert.match(app, /scope:'FILTERED'/);
  assert.match(runtime, /annotated: value\.processingStatus === 'unprocessed' \? false/);
  assert.doesNotMatch(app, /const candidates=state\.images\|\|\[\];all=/);
});

test('cross-page cleaning, no-clean decision and batch annotation consume selected IDs without current-page intersection', () => {
  const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const annotationAction = app.match(/window\.openBatchAnnotation417=function\(\)\{[^\n]+/)?.[0] || '';
  const cleanAction = app.match(/window\.openSelectedClean417=function\(\)\{[^\n]+/)?.[0] || '';
  const readyAction = app.match(/window\.openSelectedReady417=function\(\)\{[^\n]+/)?.[0] || '';
  assert.match(annotationAction, /state\.annotationQueue414=ids/);
  assert.doesNotMatch(annotationAction, /state\.images/);
  assert.match(cleanAction, /scope:'SELECTED',imageIds:ids/);
  assert.match(readyAction, /scope:'SELECTED',imageIds:ids/);
  assert.match(app, /const detail=await apiRequestAnnotation420\(key\)/);
  assert.match(app, /offPageImages420\.set/);
});


test('label remap invalidation drops the stored paginated material card snapshot',()=>{
  const runtime=fs.readFileSync(new URL('../../static/modules/material-pagination-runtime.js',import.meta.url),'utf8');
  const invalidator=runtime.slice(runtime.indexOf('    invalidate() {'),runtime.indexOf('    patch: patchPagedDataset61'));
  assert.match(invalidator,/state\.materialPageCache61 = null/);
  assert.match(invalidator,/state\.images = \[\]/);
  assert.match(invalidator,/invalidateFullPool61\(\)/);
});
