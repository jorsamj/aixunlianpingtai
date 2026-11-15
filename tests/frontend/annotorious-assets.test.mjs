import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';

test('official Annotorious artifacts, licenses and pinned dependency inventory rebuild offline',()=>{
 const manifest=JSON.parse(readFileSync('static/vendor/annotorious/manifest.json','utf8'));
 assert.equal(manifest.version,'3.9.5');assert.equal(manifest.license,'BSD-3-Clause');
 assert.equal(manifest.embedded_svelte.version,'4.2.20');
 assert.equal(manifest.patches?.['annotorious.js']?.upstream_sha256,
   '66a2ac758870234b7102b5e6ad93082c4f8bb23d0d47b296df7e032f2c92a1c5');
 assert.equal(manifest.files['annotorious.js'].sha256,
   '9bdfd34307d3e70bf50f4a1e338ad29018b20c562704756d14b3575ca24088f9');
 assert.equal(manifest.files['annotorious.js'].bytes,116848);
 assert.match(readFileSync('static/modules/annotorious-editor.js','utf8'),
   /annotorious\.js\?v=3\.9\.5-history1/);
 const result=spawnSync(process.execPath,['tools/vendor_annotorious.mjs','--check'],{encoding:'utf8'});
 assert.equal(result.status,0,result.stdout+result.stderr);
 assert.equal(JSON.parse(readFileSync('package.json','utf8')).dependencies['@annotorious/annotorious'],'3.9.5');
 assert.ok(manifest.dependencies.every(row=>row.license&&row.notice_sha256));
});
