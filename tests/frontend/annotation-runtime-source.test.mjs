import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('the final AI annotation override uses the persistent v60 task API', () => {
  const marker = source.lastIndexOf('Persistent v60 AI annotation UI');
  assert.ok(marker > 0);
  const finalLayer = source.slice(marker);
  assert.match(finalLayer, /\/api\/v60\/projects\/\$\{pid\(\)\}\/annotation-tasks/);
  assert.doesNotMatch(finalLayer, /\/api\/v47\/projects\/.*ai-label-tasks/);
  assert.match(finalLayer, /createTaskPoller/);
  assert.match(finalLayer, /completeAiReview60/);
  assert.match(finalLayer, /editAiCandidate60/);
});

test('the stable annotation layer is after all legacy renderer overrides', () => {
  assert.ok(source.lastIndexOf('Stable single-instance manual/batch annotation workbench') > source.lastIndexOf('renderAnnotator=function'));
  assert.ok(source.lastIndexOf('/api/v60/projects/${pid()}/annotation-tasks') > source.lastIndexOf('/api/v47/projects/${pid()}/ai-label-tasks'));
});


test('manual annotation shell paints before authoritative hydration and prefetches adjacent work', () => {
  const marker = source.lastIndexOf('Stable single-instance manual/batch annotation workbench');
  const end = source.indexOf('Persistent v60 AI annotation UI', marker);
  assert.ok(marker > 0 && end > marker);
  const stable = source.slice(marker, end);
  assert.match(stable, /beforeLoad:\(id,\{cached\}=\{\}\)=>\{if\(!cached\)prepareAnnotationShell420\(id\)\}/);
  assert.match(stable, /state\.annotationHydrating420=true/);
  assert.match(stable, /正在读取标注…/);
  assert.match(stable, /data-ann420-edit="1"/);
  assert.match(stable, /stage\.classList\.toggle\('disabled',locked/);
  assert.match(stable, /Promise\.all\(\[apiRequestAnnotation420\(id\),labelsPromise\]\)/);
  assert.match(stable, /prefetchAnnotationNeighbors420/);
  assert.match(stable, /annotationWorkbench\?\.prefetch/);
  assert.match(stable, /preload\(image\.url\)/);
  assert.match(stable, /annotationWorkbench\?\.remember/);
  assert.match(stable, /saveAnnotationCanonical420/);
  assert.match(stable, /saveAnnotationCore420/);
  assert.equal((stable.match(/annotationWorkbench\?\.open\(ids\[at\+1\]\)/g) || []).length, 1);
  assert.match(source, /const locked=!!state\.annotationHydrating420\|\|!!state\.annotationLoadError420/);
  assert.match(source, /if\(!locked&&e\.key==='Delete'\)deleteActiveBox\(\)/);
  assert.match(source, /if\(!locked\)saveAnn\(false\)/);
});


test('manual annotation hot path paints only the active box until pointerup commit', () => {
  const start = source.lastIndexOf('Pointer based annotation editing is the canonical interaction owner.');
  const end = source.indexOf('// ---------- image upload with actual browser upload progress / ETA ----------', start);
  assert.ok(start > 0 && end > start);
  const interaction = source.slice(start, end);
  const moveStart = interaction.indexOf("st.addEventListener('pointermove'");
  const finishStart = interaction.indexOf('const finish=', moveStart);
  const move = interaction.slice(moveStart, finishStart);
  assert.match(interaction, /state\.annPointerAbort\?\.abort/);
  assert.match(interaction, /new AbortController\(\)/);
  assert.match(interaction, /requestAnimationFrame/);
  assert.match(move, /scheduleActivePaint\(\)/);
  assert.doesNotMatch(move, /markDirty\(\)/);
  assert.doesNotMatch(move, /drawBoxes\(\)/);
  assert.doesNotMatch(interaction, /window\.addEventListener\(['"]mouse(?:move|up)/);
  assert.match(interaction, /if\(created\|\|\(mode!=='draw'&&changed\)\)markDirty\(\)/);
});

test('manual annotation uses a dedicated near-fullscreen workbench with complete label and object panels', () => {
  const marker = source.lastIndexOf('Stable single-instance manual/batch annotation workbench');
  const end = source.indexOf('Persistent v60 AI annotation UI', marker);
  const stable = source.slice(marker, end);
  assert.match(stable, /annotation-workbench-modal/);
  assert.match(stable, /id="annLabels"/);
  assert.match(stable, /id="annBoxes"/);
  assert.match(stable, /ann420-toolbar-primary/);
  assert.match(stable, /ann420-toolbar-nav/);
  assert.match(stable, /ann420-toolbar-edit/);
  assert.match(stable, /materialAnnotationStatus420/);
});


test('formal material status distinguishes manual, AI-confirmed, mixed, and confirmed-empty truth', () => {
  const marker = source.lastIndexOf('Stable single-instance manual/batch annotation workbench');
  const end = source.indexOf('Persistent v60 AI annotation UI', marker);
  const stable = source.slice(marker, end);
  assert.match(stable, /materialAnnotationStatusV66/);
  assert.match(stable, /AI已确认/);
  assert.match(stable, /混合标注/);
  assert.match(stable, /人工标注/);
  assert.match(stable, /已确认无目标/);
  assert.match(stable, /annotation_origin/);
});


test('material detail exposes durable annotation status, provenance, and update time', () => {
  assert.match(source, /annotationOriginLabelV66/);
  assert.match(source, /annotationUpdatedTextV66/);
  assert.match(source, /标注来源/);
  assert.match(source, /最后标注/);
  assert.match(source, /AI审核确认 \+ 人工编辑/);
  assert.match(source, /annotation_summary_at/);
});


test('dataset cards show transient AI review truth without treating it as formal annotation', () => {
  assert.match(source, /annotation-material-states\?image_ids=/);
  assert.match(source, /AI待审核/);
  assert.match(source, /AI正在入库/);
  assert.match(source, /AI候选失败/);
  assert.match(source, /state\.aiMaterialStates60/);
  assert.match(source, /state\.data412Tab==='processed'.*refreshAiMaterialStates60/s);
  assert.match(source, /标注来源/);
  assert.match(source, /AI任务/);
});


test('material card patching prefers stable material id over filename', () => {
  assert.match(source, /data-material-id=/);
  assert.match(source, /CSS\.escape\(materialId\)/);
  assert.match(source, /const cards=.*\.data412-card,.data429-card/s);
});


test('material card incremental patch uses the same v66 annotation status owner', () => {
  assert.match(source, /meta\[1\]\.textContent=window\.materialAnnotationStatusV66\?\.\(image\)\|\|materialAnnotationStatus420\(image\)/);
});


test('pending AI material exposes direct review action and locks duplicate commit', () => {
  assert.match(source, /annotationMaterialActionV66/);
  assert.match(source, /审核AI结果/);
  assert.match(source, /AI正在入库/);
  assert.match(source, /查看AI任务/);
  assert.match(source, /reviewAiLabel427/);
  assert.match(source, /showAiTask60/);
  assert.match(source, /aiMaterialStates60\?\.\[String\(x\.id\)\]\?\.state/);
});
