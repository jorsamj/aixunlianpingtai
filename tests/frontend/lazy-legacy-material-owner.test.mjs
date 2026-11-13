import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
const legacy=readFileSync(new URL('../../static/modules/legacy-material-compatibility.js',import.meta.url),'utf8');
const html=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');

test('compatibility migration stays out of the startup static import graph',()=>{
  assert.doesNotMatch(main,/^import\s+\{renderLegacyMaterialCompatibility\}\s+from\s+['"]\.\/modules\/legacy-material-compatibility\.js/m);
  assert.match(main,/return import\('\.\/modules\/legacy-material-compatibility\.js\?v=20261023fullscan'\)/);
  assert.equal((main.match(/legacy-material-compatibility\.js\?v=/g)||[]).length,1);
  assert.match(legacy,/export function renderLegacyMaterialCompatibility\(/);
});

test('lazy owner checks navigation, project and render generation before touching view',()=>{
  const start=main.indexOf('function renderLegacyCompatibilityOnDemand(){');
  const end=main.indexOf('\nconst unregisterLegacyMaterialCompatibility',start);
  assert.ok(start>=0&&end>start);
  const code=main.slice(start,end);
  assert.match(code,/navigationStabilityRuntime\.action\('旧素材兼容迁移'\)/);
  assert.match(code,/sequence === legacyCompatibilityRenderSequence/);
  assert.match(code,/owner\.isCurrent\(\)/);
  assert.match(code,/String\(state\.project\?\.id \|\| ''\) === projectId/);
  assert.match(code,/if\(!current\(\)\)return false/);
  assert.match(code,/module\.renderLegacyMaterialCompatibility\(\{projectId:\(\)=>state\.project\?\.id,notify\}\)/);
  assert.match(code,/if\(legacyCompatibilityModule\)return renderLoaded\(legacyCompatibilityModule\)/);
});

test('main entry keeps the numeric same-version cache contract',()=>{
  for(const name of ['styles.css','app.js','main.mjs'])assert.ok(html.includes('/static/'+name+'?v=42.25.601'));
});
