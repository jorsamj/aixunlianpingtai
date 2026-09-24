import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const serviceNodes = readFileSync(new URL('../../static/modules/service-node-runtime.js', import.meta.url), 'utf8');
const agents = readFileSync(new URL('../../AGENTS.md', import.meta.url), 'utf8');

function finalRenderNavBlock() {
  const start = app.lastIndexOf('renderNav=function(){');
  const end = app.indexOf('window.renderLabelManagement414=', start);
  assert.ok(start >= 0 && end > start, 'final renderNav owner must exist');
  return app.slice(start, end);
}

test('formal renderNav owns training resources and service nodes inside advanced navigation', () => {
  const block = finalRenderNavBlock();
  assert.match(block, /\{title:'算法生成',items:\['算法列表','训练任务'\]\}/);
  assert.match(block, /\{title:'高级功能',items:\[[^\]]*'训练资源'[^\]]*'服务节点'[^\]]*\]\}/);
  assert.equal((block.match(/'训练资源'/g) || []).length, 1);
  assert.equal((block.match(/'服务节点'/g) || []).length, 1);
  const toggleStart = app.indexOf('window.toggleAdvanced427=function()');
  const toggleEnd = app.indexOf('};', toggleStart);
  assert.doesNotMatch(app.slice(toggleStart, toggleEnd), /setPage|state\.page\s*=/);
});

test('training resource breadcrumb follows its formal advanced navigation group', () => {
  const start = app.indexOf('const TOP_CRUMB413=Object.freeze({');
  const end = app.indexOf('});', start);
  const block = app.slice(start, end);
  assert.match(block, /'训练资源':'高级功能'/);
});

test('ServiceNodeRuntime owns page business only and never injects navigation DOM', () => {
  assert.doesNotMatch(serviceNodes, /decorateNavigation|data-service-node-nav|serviceNodeNav|navObserver/);
  assert.doesNotMatch(serviceNodes, /getElementById\(['"]nav['"]\)/);
  assert.match(serviceNodes, /registerPageOwner\?\.\(PAGE, \(\) => render\(\)\)/);
});

test('repository records the permanent one-owner one-truth anti-nesting constraint', () => {
  assert.match(agents, /一个能力一个 final owner/);
  assert.match(agents, /一份状态一个 canonical truth/);
  assert.match(agents, /normalize\s*\/\s*redirect\s*\/\s*delegate/);
  assert.match(agents, /Page\s*→\s*Surface\s*→\s*Content/);
});
