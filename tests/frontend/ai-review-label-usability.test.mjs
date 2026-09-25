import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');

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


test('AI review is a dedicated human-review workbench with explicit per-image accept and reject', () => {
  const source = reviewBlock();
  assert.match(source, /AI标注审核工作台/);
  assert.match(source, /ai-review-workbench-modal/);
  assert.match(source, /data-ai66-filter="empty"/);
  assert.match(source, /window\.setAiDecision60/);
  assert.match(source, />采用<\/button>/);
  assert.match(source, />拒绝<\/button>/);
  assert.match(source, /AI判断无目标/);
  assert.match(source, /已人工修改/);
});

test('AI review confirmation follows durable commit to terminal and invalidates material truth', () => {
  const source = reviewBlock();
  const start = source.indexOf('window.completeAiReview60=async mode=>');
  const end = source.indexOf('window.confirmAiLabel427=', start);
  const complete = source.slice(start, end);
  assert.match(complete, /waitForTaskTerminal/);
  assert.match(complete, /ai-review-commit:/);
  assert.match(complete, /MaterialPaginationRuntime61\?\.invalidate/);
  assert.match(complete, /AI审核结果已写入正式标注/);
});


test('AI candidate editing is visual-first rather than coordinate-first', () => {
  const source = reviewBlock();
  const start = source.indexOf('function ensureCandidateEditorShell60');
  const end = source.indexOf('window.completeAiReview60=async mode=>', start);
  const editor = source.slice(start, end);
  assert.match(editor, /VISUAL BOX EDITOR/);
  assert.match(editor, /pointerdown/);
  assert.match(editor, /pointermove/);
  assert.match(editor, /pointerup/);
  assert.match(editor, /data-h="nw"/);
  assert.match(editor, /空白处拖拽新建/);
  assert.match(editor, /ai_candidate_reviewed/);
  assert.match(editor, /高级坐标/);
});

test('AI review exposes low-confidence filtering', () => {
  const source = reviewBlock();
  assert.match(source, /data-ai66-filter="low"/);
  assert.match(source, /Number\(box\.confidence\)<\.6/);
});

test('AI review keeps mapping bounded and candidate actions readable without sticky overlays', () => {
  assert.match(styles, /\.ai66-label-tools\{[^}]*max-height:min\(34vh,320px\)[^}]*overflow:auto/s);
  assert.match(styles, /\.ai66-candidate-card>footer \.btn\{min-height:32px;font-size:12px\}/);
  assert.match(styles, /\.ai66-review-footer\{position:relative!important/);
});

test('AI review KPI separates total truth from current-page decisions', () => {
  const source = reviewBlock();
  assert.match(source, /id="ai66Total"/);
  assert.match(source, /id="ai66Accepted"/);
  assert.match(source, /id="ai66Rejected"/);
  assert.match(source, /id="ai66Boxes"/);
  assert.match(source, /本页无目标/);
  assert.match(source, /本页失败/);
  assert.match(source, /review\.decisions\.get\(String\(item\.image_id\)\)===false/);
  assert.match(source, /reduce\(\(sum,item\)=>sum\+\(item\.status==='failed'\?0:\(item\.boxes\|\|\[\]\)\.length\),0\)/);
});


test('AI candidate overlay labels stay inside the visible image stage', () => {
  assert.match(styles, /\.ai66-candidate-card \.data412-box em\{[^}]*left:2px;top:2px[^}]*max-width:180px[^}]*text-overflow:ellipsis/s);
});
