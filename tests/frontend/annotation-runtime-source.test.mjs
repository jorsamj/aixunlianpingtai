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
  assert.match(stable, /beforeLoad:id=>prepareAnnotationShell420\(id\)/);
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
