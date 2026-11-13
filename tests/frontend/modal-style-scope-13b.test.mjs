import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const report=readFileSync(new URL('../../static/algorithm-report-modal.css',import.meta.url),'utf8');
const shared=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
const index=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');

test('shared scroll fallback remains in the existing global stylesheet',()=>{
  assert.match(shared,/\.modal:not\(\.import350-minimized\)\{align-items:safe center;overflow-y:auto;overscroll-behavior:contain\}/);
  assert.match(shared,/\.modal:not\(\.import350-minimized\)>\.modal-card>\.modal-body\{min-height:0;overscroll-behavior:contain\}/);
  assert.match(shared,/\.modal\.import350-minimized\{[^}]*display:block/);
  assert.match(shared,/\.modal\.import350-minimized \.modal-body\{display:none!important\}/);
});

test('algorithm report stylesheet cannot install unscoped modal layout rules',()=>{
  assert.doesNotMatch(report,/(?:^|\n)\s*\.modal:not\(\.hidden\)(?:\{|>\.modal-card)/);
  for(const marker of ['data-algorithm-report','data-algorithm-report-loading']){
    const scope='.modal:not(.hidden):has(['+marker+'])';
    assert.ok(report.includes(scope+'{') || report.includes(scope+','));
    assert.ok(report.includes(scope+'>.modal-card'));
    assert.ok(report.includes(scope+'>.modal-card>.modal-head'));
    assert.ok(report.includes(scope+'>.modal-card>.modal-body'));
  }
  assert.match(report,/height:86dvh/);
  assert.match(report,/scrollbar-gutter:stable/);
});

test('only algorithm report asset receives a new cache marker',()=>{
  assert.match(index,/\/static\/algorithm-report-modal\.css\?v=20261113-modal-scope1/);
  assert.match(index,/\/static\/app\.js\?v=42\.25\.598/);
  assert.match(index,/\/static\/main\.mjs\?v=42\.25\.598/);
  assert.match(index,/\/static\/styles\.css\?v=42\.25\.598/);
});
