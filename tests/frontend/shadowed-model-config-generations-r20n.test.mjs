import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('R20n retires shadowed model-config generations while preserving final M4 ownership', () => {
  for (const marker of [
    "window.saveModelConfigV35=async function(id='')",
    "window.saveModelConfig426=async function(id='')",
    "window.saveModelConfig427=async function(id='')",
    'saveModelConfigV35(',
    'saveModelConfig426(',
    'saveModelConfig427(',
  ]) {
    assert.equal(app.includes(marker), false, `retired Model Config generation must stay absent: ${marker}`);
  }

  const openOwners = app.match(/window\.openModelConfigModalV35=function\(id=''\)/g) || [];
  assert.equal(openOwners.length, 1, 'only the live M4 openModelConfigModalV35 function owner may remain');
  assert.match(app, /window\.saveVisionModelM4=async function\(id=''\)/, 'final M4 save owner must remain');
  assert.match(app, /onclick=\"saveVisionModelM4\('/, 'live M4 modal must still submit through saveVisionModelM4');
  assert.match(app, /window\.__m4OpenModelConfig=window\.openModelConfigModalV35;/, 'M4 capture must remain');
  assert.match(app, /if\(window\.__m4OpenModelConfig\)window\.openModelConfigModalV35=window\.__m4OpenModelConfig;/, 'M4 final activation must remain');

  const start = app.indexOf("window.saveVisionModelM4=async function(id='')");
  const owner = app.slice(start, start + 6500);
  assert.match(owner, /NavigationStability\?\.action\?\.\(state\.page\)/, 'final M4 save must keep the action fence');
  assert.doesNotMatch(owner, /await loadAll\(\)|await loadRelated\(\)/, 'final M4 save must remain local-state-only');
});
