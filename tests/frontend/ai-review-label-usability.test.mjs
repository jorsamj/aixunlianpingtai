import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function reviewBlock() {
  const start = app.indexOf('function ensureReviewShell()');
  const end = app.indexOf('/* Explicit canonical-label creation used by import/rescan/ZIP/AI confirmation.', start);
  assert.ok(start >= 0 && end > start);
  return app.slice(start, end);
}

test('AI review uses searchable platform-label inputs instead of long mapping selects', () => {
  const source = reviewBlock();
  assert.match(source, /id="ai60PlatformLabelOptions"/);
  assert.match(source, /class="input ai60-label-combobox"/);
  assert.match(source, /list="ai60PlatformLabelOptions"/);
  assert.match(source, /updateAiLabelMappingFromInput60/);
  assert.match(source, /resolveAiReviewLabel60/);

  const mappingStart = source.indexOf('function renderAiLabelMapping60()');
  const mappingEnd = source.indexOf('window.renderAiLabelMapping60=renderAiLabelMapping60;', mappingStart);
  const mapping = source.slice(mappingStart, mappingEnd);
  assert.doesNotMatch(mapping, /<select class="select" onchange="updateAiLabelMapping60/);
});

test('AI review can filter mapping rows and explicitly map all source labels', () => {
  const source = reviewBlock();
  assert.match(source, /placeholder="筛选来源标签"/);
  assert.match(source, /window\.filterAiMappingRows60=query=>/);
  assert.match(source, /id="ai60MapAllTarget"/);
  assert.match(source, /window\.applyAiMappingAll60=\(\)=>/);
  assert.match(source, /review\.labelMapping\.set\(source,String\(label\.code\)\)/);
});

test('checked AI candidate images can have all candidate boxes unified to one formal label', () => {
  const source = reviewBlock();
  assert.match(source, /批量人工统一标签/);
  assert.match(source, /id="ai60BulkTarget"/);
  assert.match(source, /window\.applyAiBulkLabel60=\(\)=>/);
  assert.match(source, /review\.decisions\.get\(String\(item\.image_id\)\)===true/);
  assert.match(source, /review\.edits\.set\(id,next\)/);
  assert.match(source, /label:String\(label\.code\)/);
  assert.match(source, /class_id:label\.class_id\?\?box\.class_id/);
  assert.match(source, /所选图片没有候选框/);
});

test('accept-all still sends explicitly edited candidate boxes to the authoritative decisions endpoint', () => {
  const source = reviewBlock();
  const start = source.indexOf('window.completeAiReview60=async mode=>');
  const end = source.indexOf('window.confirmAiLabel427=', start);
  const complete = source.slice(start, end);
  assert.match(complete, /mode==='accept'/);
  assert.match(complete, /\[\.\.\.review\.edits\]\.map\(\(\[image_id,boxes\]\)=>\(\{image_id,accepted:true,boxes\}\)\)/);
  assert.match(complete, /commit:true,label_mapping/);
  assert.match(complete, /\/decisions/);
});

test('AI mapping renderer skips rebuild when labels and mapping signature are unchanged', () => {
  const source = reviewBlock();
  assert.match(source, /box\.dataset\.signature===signature/);
  assert.match(source, /datalist\.dataset\.signature!==signature/);
});
