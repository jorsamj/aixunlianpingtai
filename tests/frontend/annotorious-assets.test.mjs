import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';

test('official Annotorious artifacts, licenses and pinned dependency inventory rebuild offline',()=>{
 const manifest=JSON.parse(readFileSync('static/vendor/annotorious/manifest.json','utf8'));
 assert.equal(manifest.version,'3.9.5');assert.equal(manifest.license,'BSD-3-Clause');
 assert.equal(manifest.embedded_svelte.version,'4.2.20');
 const result=spawnSync(process.execPath,['tools/vendor_annotorious.mjs','--check'],{encoding:'utf8'});
 assert.equal(result.status,0,result.stdout+result.stderr);
 assert.equal(JSON.parse(readFileSync('package.json','utf8')).dependencies['@annotorious/annotorious'],'3.9.5');
 assert.ok(manifest.dependencies.every(row=>row.license&&row.notice_sha256));
});
