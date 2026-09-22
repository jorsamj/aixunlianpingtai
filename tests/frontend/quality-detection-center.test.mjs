import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const navigation = readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');

test('collapsed product navigation has only overview, algorithm generation and data center groups', () => {
  const start = app.lastIndexOf('const icon414=');
  const end = app.indexOf('\n\n  window.renderLabelManagement414', start);
  assert.ok(start >= 0 && end > start);
  const nav = app.slice(start, end);
  assert.match(nav, /title:'总览'/);
  assert.match(nav, /title:'算法生成'/);
  assert.match(nav, /title:'数据中心'/);
  assert.doesNotMatch(nav, /title:'测试评测'/);
  assert.doesNotMatch(nav, /title:'部署中心'/);
  assert.match(nav, /if\(state\.v427Advanced\)groups\.push/);
});

test('retired test routes normalize into quality center and are no longer canonical main owners', () => {
  assert.match(navigation, /requested === '测试发布' \|\| requested === '检测台'\) return '质量中心'/);
  assert.doesNotMatch(main, /\['测试发布', 'renderTest'\]/);
  assert.doesNotMatch(main, /\['检测台', 'renderDetectBench'\]/);
  assert.doesNotMatch(main, /PAGE_EXTRAS_OWNERS = new Set\([^\n]+测试发布/);
  assert.doesNotMatch(main, /PAGE_EXTRAS_OWNERS = new Set\([^\n]+检测台/);
});

test('quality center owns a model-detection tab instead of a standalone test section', () => {
  assert.match(app, /window\.setQualityCenterTab411=async function\(tab\)/);
  assert.match(app, /模型检测/);
  assert.match(app, /window\.loadPageExtras413\?\.\('质量中心'\)/);
  assert.match(app, /window\.renderDetectBench\?\.\(\)/);
});

test('quality detection supports original and algorithm-version models on both sides', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  assert.ok(start >= 0);
  const source = app.slice(start);
  assert.match(source, /source==='builtin'/);
  assert.match(source, /source==='algorithm_version'/);
  assert.match(source, /modelBrowser64\('A'/);
  assert.match(source, /modelBrowser64\('B'/);
  assert.match(source, /搜索算法、版本或模型/);
  assert.match(source, /原始 \/ 基础模型/);
  assert.match(source, /算法版本/);
});

test('quality detection accepts single, multi and folder image input and runs real inference tasks', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /id="benchFiles64" type="file" accept="image\/\*" multiple/);
  assert.match(source, /id="benchFolder64" type="file" accept="image\/\*" multiple webkitdirectory directory/);
  assert.match(source, /window\.runBenchBatch64=async function/);
  assert.match(source, /await window\.benchPredictOne\('benchModelA'/);
  assert.match(source, /await window\.benchPredictOne\('benchModelB'/);
  assert.match(app, /\/api\/v61\/projects\/\$\{pid\(\)\}\/deployment-tests/);
  assert.match(app, /ownerPages:\['质量中心'\]/);
});

test('batch detection exposes result details and human correctness review states', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /本次检测结果/);
  assert.match(source, /openBenchResult64/);
  assert.match(source, /正确/);
  assert.match(source, /漏检/);
  assert.match(source, /误检/);
  assert.match(source, /框不准/);
  assert.match(source, /类别错误/);
});


test('quality detection persists batch identity and restores recent server-side results', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(app, /form\.append\('detection_batch_id'/);
  assert.match(app, /form\.append\('detection_item_index'/);
  assert.match(app, /form\.append\('detection_side'/);
  assert.match(source, /window\.loadDetectionBatches64=async function/);
  assert.match(source, /\/api\/v64\/projects\/\$\{pid\(\)\}\/detection-batches\?limit=12/);
  assert.match(source, /window\.openDetectionBatch64=async function/);
  assert.match(source, /batchFromDurable64/);
  assert.match(source, /最近检测批次/);
});

test('human detection review is saved through the durable review endpoint', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /window\.markBenchReview64=async function/);
  assert.match(source, /detection-batches\/\$\{encodeURIComponent\(row\.batchId\)\}\/items\/\$\{Number\(row\.itemIndex\?\?index\)\}\/review/);
  assert.match(source, /已保存：/);
});

test('algorithm-version selector groups versions by their owning algorithm', () => {
  const start = app.lastIndexOf('v64: quality-center model detection workbench');
  const source = app.slice(start);
  assert.match(source, /return `算法 · \$\{algorithm\?\.name/);
  assert.match(source, /state\.algorithms/);
});
